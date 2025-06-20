import streamlit as st
import openai
import httpx
import os
import json
from pathlib import Path
from typing import List, Dict, Any
from google import genai
from dotenv import load_dotenv, find_dotenv, set_key
from pydantic import BaseModel
import re
import time

def extract_json_from_string(text: str) -> dict | None:
    """使用正则表达式从可能包含前后缀文本的字符串中提取第一个有效的JSON对象。"""
    match = re.search(r'\{.*\}', text, re.DOTALL)
    return json.loads(match.group(0))

class Recipe(BaseModel):
    recipe_name: str
    ingredients: list[str]

# 加载 .env 文件中的环境变量
env_file = find_dotenv()
if not env_file:
    env_file = Path(".env")
    env_file.touch()
load_dotenv(env_file)

def load_config() -> dict:
    """加载配置，支持 openai兼容格式 / google 分节嵌套结构。"""
    return {
        "provider": os.getenv("PROVIDER", "openai"),
        "proxy_url": os.getenv("PROXY_URL", ""),
        "openai": {
            "api_base": os.getenv("OPENAI_API_BASE", "https://api.mistral.ai/v1"),
            "api_key": os.getenv("OPENAI_API_KEY", ""),
            "model": os.getenv("OPENAI_MODEL", "mistral-medium-latest"),
        },
        "google": {
            "api_key": os.getenv("GOOGLE_API_KEY", ""),
            "model": os.getenv("GOOGLE_MODEL", "gemini-2.5-flash"),
        },
    }

def save_config(cfg: dict):
    """将配置保存到 .env 文件。"""
    set_key(env_file, "PROVIDER", cfg.get("provider", "openai"))
    set_key(env_file, "PROXY_URL", cfg.get("proxy_url", ""))
    if "openai" in cfg:
        set_key(env_file, "OPENAI_API_KEY", cfg["openai"].get("api_key", ""))
        set_key(env_file, "OPENAI_API_BASE", cfg["openai"].get("api_base", ""))
        set_key(env_file, "OPENAI_MODEL", cfg["openai"].get("model", ""))
    if "google" in cfg:
        set_key(env_file, "GOOGLE_API_KEY", cfg["google"].get("api_key", ""))
        set_key(env_file, "GOOGLE_MODEL", cfg["google"].get("model", ""))

class LLMClient:
    """一个统一的、简化的LLM客户端，支持OpenAI兼容接口和Google Gemini，并统一处理代理。"""
    def __init__(self, config: dict):
        self.full_config = config
        self.provider = config.get("provider", "openai")
        proxy_url = config.get("proxy_url")
        provider_cfg = config.get(self.provider)
        self.model = provider_cfg.get("model")
        api_key = provider_cfg.get("api_key")

        if self.provider == "google":
            if proxy_url:
                os.environ["HTTP_PROXY"] = proxy_url
                os.environ["HTTPS_PROXY"] = proxy_url
            self.client = genai.Client(api_key=api_key)
        else:  # openai 兼容
            http_client = httpx.Client(proxy=proxy_url or None)
            self.client = openai.OpenAI(
                api_key=api_key,
                base_url=provider_cfg.get("api_base", ""),
                http_client=http_client,
            )

    def call(self, messages: List[Dict], json_mode: bool = False) -> str:
        """根据提供商调用相应的LLM API"""
        if self.provider == "google":
            config = {
                "response_mime_type": "application/json",
                "response_schema": Recipe,
            } if json_mode else {}
            
            response = self.client.models.generate_content(
                model=self.model, 
                config=config,
                contents=messages[0]["content"],
            )
            return response.text
        else: # openai 兼容
            extra_params = {"response_format": {"type": "json_object"}} if json_mode else {}
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                **extra_params,
            )
            return response.choices[0].message.content

# --- Prompt 模板 ---
ROLE_INSTRUCTION = "你是一位资深的专利代理师，擅长撰写结构清晰、逻辑严谨的专利申请文件。"

# 0. 分析代理
PROMPT_ANALYZE = (
    f"{ROLE_INSTRUCTION}\n"
    "任务描述：请仔细阅读并分析以下技术交底材料，将其拆解并提炼成一个结构化的JSON对象。\n"
    "**重要：请直接返回有效的JSON对象，不要包含任何解释性文字、前言或代码块标记。你的回答必须以 '{{' 开头，并以 '}}' 结尾。**\n"
    "JSON结构应包含以下字段：\n"
    "1. `problem_statement`: 该发明旨在解决的现有技术中的具体问题是什么？（1-2句话）\n"
    "2. `core_inventive_concept`: 本发明的核心创新点或最关键的技术特征是什么？（区别于现有技术的本质）\n"
    "3. `technical_solution_summary`: 为解决上述问题，本发明提出的技术方案概述，包括关键组件或步骤。\n"
    "4. `key_components_or_steps`: 列出实现该方案所需的主要物理组件或工艺步骤的清单（使用列表格式）。\n"
    "5. `achieved_effects`: 与现有技术相比，本发明能带来的具体、可量化的有益效果是什么？\n\n"
    "技术交底材料：\n{user_input}"
)

# 1. 发明名称代理
PROMPT_TITLE = (
    f"{ROLE_INSTRUCTION}\n"
    "任务描述：请根据以下核心创新点和技术方案，提炼出3个符合中国专利命名规范且不超过25个汉字的备选发明名称。要求简洁明了并准确反映技术内容。\n"
    "**重要：请直接返回一个包含3个名称字符串的JSON数组，不要包含任何其他解释。**\n"
    "示例输出: `[\"备选名称一\", \"备选名称二\", \"备选名称三\"]`\n\n"
    "核心创新点：{core_inventive_concept}\n"
    "技术方案概述：{technical_solution_summary}"
)

# 2. 背景技术代理
PROMPT_BACKGROUND = (
    f"{ROLE_INSTRUCTION}\n"
    "任务描述：请围绕以下“待解决的技术问题”，撰写“二、现有技术（背景技术）”章节。你需要分析与此问题最相关的现有技术状况，并实事求是地指出现有技术存在的问题及原因。请使用专业、客观的中文，并以 Markdown 格式返回。\n\n"
    "发明名称：{title}\n"
    "待解决的技术问题：{problem_statement}"
)

# 3. 发明内容代理
PROMPT_INVENTION_CONTENT = (
    f"{ROLE_INSTRUCTION}\n"
    "任务描述：请依据以下结构化的发明信息和已生成的背景技术，撰写“三、发明内容”章节。内容需严格对应，逻辑清晰。\n"
    "1. 发明目的：清晰回应背景技术中提出的问题（源自`problem_statement`）。\n"
    "2. 技术解决方案：基于`technical_solution_summary`和`key_components_or_steps`展开，清楚、完整地描述本发明的方案。\n"
    "3. 技术效果：具体、实事求是地描述本发明可达到的效果（源自`achieved_effects`）。\n"
    "请使用专业、严谨的中文，并以 Markdown 格式返回。\n\n"
    "发明名称：{title}\n"
    "背景技术章节（供参考）：\n{background}\n\n"
    "结构化发明信息：\n"
    "  - 待解决问题: {problem_statement}\n"
    "  - 技术方案概述: {technical_solution_summary}\n"
    "  - 关键组件/步骤: {key_components_or_steps}\n"
    "  - 有益效果: {achieved_effects}"
)

# 4. 具体实施方式代理
PROMPT_IMPLEMENTATION = (
    f"{ROLE_INSTRUCTION}\n"
    "任务描述：请将“发明内容”中阐述的技术方案具体化，撰写“四、具体实施方式”章节。请至少举出一个明确、可操作的具体实施例，可结合“关键组件/步骤清单”进行详细说明。请以 Markdown 格式返回。\n\n"
    "发明名称：{title}\n"
    "发明内容章节（作为蓝本）：\n{invention_content}\n\n"
    "关键组件/步骤清单（供参考）：\n{key_components_or_steps}"
)

# --- 新增：工作流配置与依赖管理 ---
SECTION_ORDER = ["title", "background", "invention", "implementation"]
SECTION_CONFIG = {
    "title": {
        "label": "发明名称",
        "prompt": PROMPT_TITLE,
        "dependencies": ["structured_brief"],
        "json_mode": True,
    },
    "background": {
        "label": "背景技术",
        "prompt": PROMPT_BACKGROUND,
        "dependencies": ["title", "structured_brief"],
    },
    "invention": {
        "label": "发明内容",
        "prompt": PROMPT_INVENTION_CONTENT,
        "dependencies": ["title", "background", "structured_brief"],
    },
    "implementation": {
        "label": "具体实施方式",
        "prompt": PROMPT_IMPLEMENTATION,
        "dependencies": ["title", "invention", "structured_brief"],
    },
}

def is_stale(section_key: str) -> bool:
    """检查某个章节是否因其依赖项更新而过时。"""
    timestamps = st.session_state.data_timestamps
    if section_key not in timestamps:
        return False # 尚未生成，不算过时
    
    section_time = timestamps[section_key]
    for dep in SECTION_CONFIG[section_key]["dependencies"]:
        if dep in timestamps and timestamps[dep] > section_time:
            return True
    return False

def get_active_content(key: str) -> Any:
    """获取某个部分当前激活版本的内容。"""
    if f"{key}_versions" not in st.session_state or not st.session_state[f"{key}_versions"]:
        return None
    active_index = st.session_state.get(f"{key}_active_index", 0)
    return st.session_state[f"{key}_versions"][active_index]

# --- Streamlit 应用界面 ---
def render_sidebar(config: dict):
    """渲染侧边栏并返回更新后的配置字典。"""
    with st.sidebar:
        st.header("⚙️ API 配置")
        provider_map = {"OpenAI兼容": "openai", "Google": "google"}
        provider_keys = list(provider_map.keys())
        current_provider_key = next((key for key, value in provider_map.items() if value == config.get("provider")), "OpenAI兼容")
        
        selected_provider_display = st.radio(
            "模型提供商", options=provider_keys, 
            index=provider_keys.index(current_provider_key),
            horizontal=True
        )
        config["provider"] = provider_map[selected_provider_display]

        p_cfg = config[config["provider"]]
        p_cfg["api_key"] = st.text_input("API Key", value=p_cfg.get("api_key", ""), type="password", key=f"{config['provider']}_api_key")

        if config["provider"] == "openai":
            p_cfg["api_base"] = st.text_input("API 基础地址", value=p_cfg.get("api_base", ""), key="openai_api_base")
            p_cfg["model"] = st.text_input("模型名称", value=p_cfg.get("model", ""), key="openai_model")
        else:
            p_cfg["model"] = st.text_input("模型名称", value=p_cfg.get("model", ""), key="google_model")

        config["proxy_url"] = st.text_input(
            "代理 URL (可选)", value=config.get("proxy_url", ""), 
            placeholder="http://127.0.0.1:7890"
        )

        if st.button("保存配置"):
            save_config(config)
            st.success("配置已保存！")
            if 'llm_client' in st.session_state:
                del st.session_state.llm_client
            st.rerun()

def initialize_session_state():
    """初始化所有需要的会话状态变量。"""
    if "stage" not in st.session_state:
        st.session_state.stage = "input"
    if "config" not in st.session_state:
        st.session_state.config = load_config()
    if "user_input" not in st.session_state:
        st.session_state.user_input = ""
    if "structured_brief" not in st.session_state:
        st.session_state.structured_brief = {}
    if "data_timestamps" not in st.session_state:
        st.session_state.data_timestamps = {}

    # 为每个章节初始化版本列表和激活索引
    for key in SECTION_CONFIG:
        if f"{key}_versions" not in st.session_state:
            st.session_state[f"{key}_versions"] = []
        if f"{key}_active_index" not in st.session_state:
            st.session_state[f"{key}_active_index"] = 0

def generate_section(llm_client: LLMClient, key: str):
    """生成指定章节内容的通用函数。"""
    config = SECTION_CONFIG[key]
    brief = st.session_state.structured_brief
    
    # 准备格式化参数
    format_args = {
        "structured_brief": brief,
        "title": get_active_content("title"),
        "background": get_active_content("background"),
        "invention": get_active_content("invention"),
        "implementation": get_active_content("implementation"),
        **brief, # 将摘要内容直接展开，方便prompt调用
        "key_components_or_steps": "\n".join(brief.get('key_components_or_steps', []))
    }
    
    prompt = config["prompt"].format(**format_args)
    is_json = config.get("json_mode", False)
    response_str = llm_client.call([{"role": "user", "content": prompt}], json_mode=is_json)

    # 处理响应并更新状态
    if key == "title":
        try:
            new_versions = json.loads(response_str)
            st.session_state.title_versions.extend(new_versions)
            st.session_state.title_active_index = len(st.session_state.title_versions) - 1
        except json.JSONDecodeError:
            st.session_state.title_versions.append(f"解析失败：{response_str}")
            st.session_state.title_active_index = len(st.session_state.title_versions) - 1
    else:
        st.session_state[f"{key}_versions"].append(response_str.strip())
        st.session_state[f"{key}_active_index"] = len(st.session_state[f"{key}_versions"]) - 1
    
    st.session_state.data_timestamps[key] = time.time()

def main():
    st.set_page_config(page_title="智能专利撰写助手", layout="wide", page_icon="📝")
    st.title("📝 智能专利申请书撰写助手")
    st.caption("引入了依赖感知、一键生成和版本控制功能")

    initialize_session_state()
    render_sidebar(st.session_state.config)

    active_provider = st.session_state.config["provider"]
    if not st.session_state.config.get(active_provider, {}).get("api_key"):
        st.warning("请在左侧边栏配置并保存您的 API Key。")
        st.stop()

    # 缓存LLM客户端实例
    if 'llm_client' not in st.session_state:
        st.session_state.llm_client = LLMClient(st.session_state.config)
    llm_client = st.session_state.llm_client

    # --- 阶段一：输入核心构思 ---
    if st.session_state.stage == "input":
        st.header("Step 1️⃣: 输入核心技术构思")
        user_input = st.text_area(
            "在此处粘贴您的技术交底、项目介绍、或任何描述发明的文字：",
            value=st.session_state.user_input,
            height=250,
            key="user_input_area"
        )
        if st.button("🔬 分析并提炼核心要素", type="primary", disabled=(st.session_state.stage != "input")):
            if user_input:
                st.session_state.user_input = user_input
                prompt = PROMPT_ANALYZE.format(user_input=user_input)
                with st.spinner("正在调用分析代理，请稍候..."):
                    try:
                        response_str = llm_client.call([{"role": "user", "content": prompt}], json_mode=False)
                        st.session_state.structured_brief = extract_json_from_string(response_str)
                        st.session_state.stage = "review_brief"
                        st.rerun()
                    except (json.JSONDecodeError, KeyError) as e:
                        st.error(f"无法解析模型返回的核心要素，请检查模型输出或尝试调整输入。错误: {e}\n模型原始返回: \n{response_str}")
            else:
                st.warning("请输入您的技术构思。")

    # --- 阶段二：审核并确认核心要素 ---
    if st.session_state.stage == "review_brief":
        st.header("Step 2️⃣: 审核核心要素并选择模式")
        st.info("请检查并编辑AI提炼的发明核心信息。您的修改将自动触发依赖更新提示。")
        
        brief = st.session_state.structured_brief
        # 使用 on_change 回调来更新时间戳
        def update_brief_timestamp():
            st.session_state.data_timestamps['structured_brief'] = time.time()

        brief['problem_statement'] = st.text_area("1. 待解决的技术问题", value=brief.get('problem_statement', ''), on_change=update_brief_timestamp)
        brief['core_inventive_concept'] = st.text_area("2. 核心创新点", value=brief.get('core_inventive_concept', ''), on_change=update_brief_timestamp)
        brief['technical_solution_summary'] = st.text_area("3. 技术方案概述", value=brief.get('technical_solution_summary', ''), on_change=update_brief_timestamp)
        key_steps_list = brief.get('key_components_or_steps', [])
        key_steps_str = "\n".join(key_steps_list) if isinstance(key_steps_list, list) else key_steps_list
        edited_steps_str = st.text_area("4. 关键组件/步骤清单", value=key_steps_str, on_change=update_brief_timestamp)
        brief['key_components_or_steps'] = [line.strip() for line in edited_steps_str.split('\n') if line.strip()]
        brief['achieved_effects'] = st.text_area("5. 有益效果", value=brief.get('achieved_effects', ''), on_change=update_brief_timestamp)

        col1, col2, col3 = st.columns([2,2,1])
        if col1.button("🚀 一键生成初稿", type="primary"):
            with st.status("正在为您生成完整专利初稿...", expanded=True) as status:
                for key in SECTION_ORDER:
                    status.update(label=f"正在生成: {SECTION_CONFIG[key]['label']}...")
                    generate_section(llm_client, key)
                status.update(label="✅ 所有章节生成完毕！", state="complete")
            st.session_state.stage = "writing"
            st.rerun()

        if col2.button("✍️ 进入分步精修模式"):
            st.session_state.stage = "writing"
            st.rerun()
        
        if col3.button("返回重新输入"):
            st.session_state.stage = "input"
            st.rerun()

    # --- 阶段三：分步生成与撰写 ---
    if st.session_state.stage == "writing":
        st.header("Step 3️⃣: 逐章生成与编辑专利草稿")
        
        for key in SECTION_ORDER:
            config = SECTION_CONFIG[key]
            label = config["label"]
            versions = st.session_state.get(f"{key}_versions", [])
            is_section_stale = is_stale(key)
            
            expander_label = f"**{label}**"
            if is_section_stale:
                expander_label += " ⚠️ (依赖项已更新，建议重新生成)"
            elif not versions:
                expander_label += " (待生成)"
            
            with st.expander(expander_label, expanded=not versions or is_section_stale):
                col1, col2 = st.columns([3, 1])
                
                with col1:
                    # 检查前置依赖是否都已生成
                    deps_met = all(get_active_content(dep) for dep in config["dependencies"] if dep != "structured_brief")
                    if deps_met:
                        if st.button(f"🔄 重新生成 {label}" if versions else f"✍️ 生成 {label}", key=f"btn_{key}"):
                            with st.spinner(f"正在调用 {label} 代理..."):
                                generate_section(llm_client, key)
                                st.rerun()
                    else:
                        st.info(f"请先生成前置章节。")

                with col2:
                    if len(versions) > 1:
                        # 版本选择器
                        active_idx = st.session_state.get(f"{key}_active_index", 0)
                        new_idx = st.selectbox(f"选择版本 (共{len(versions)}个)", range(len(versions)), index=active_idx, format_func=lambda x: f"版本 {x+1}", key=f"select_{key}")
                        if new_idx != active_idx:
                            st.session_state[f"{key}_active_index"] = new_idx
                            st.rerun()

                # 显示和编辑当前激活版本的内容
                if versions:
                    active_content = get_active_content(key)
                    
                    def create_new_version(k, new_content):
                        st.session_state[f"{k}_versions"].append(new_content)
                        st.session_state[f"{k}_active_index"] = len(st.session_state[f"{k}_versions"]) - 1
                        st.session_state.data_timestamps[k] = time.time()

                    if key == 'title':
                        edited_content = st.text_input("编辑区", value=active_content, key=f"edit_{key}")
                    else:
                        edited_content = st.text_area("编辑区", value=active_content, height=300, key=f"edit_{key}")
                    
                    if edited_content != active_content:
                        create_new_version(key, edited_content)
                        st.rerun()

    # --- 阶段四：预览与下载 ---
    if all(get_active_content(key) for key in SECTION_ORDER):
        st.header("Step 4️⃣: 预览与下载")
        st.markdown("---")
        
        title = get_active_content('title')
        full_text = (
            f"# 一、发明名称\n{title}\n\n"
            f"{get_active_content('background')}\n\n"
            f"{get_active_content('invention')}\n\n"
            f"{get_active_content('implementation')}"
        )
        st.subheader("完整草稿预览")
        st.markdown(full_text)
        st.download_button("📄 下载完整草稿 (.md)", full_text, file_name=f"{title}_patent_draft.md")

if __name__ == "__main__":
    main()