import streamlit as st
import openai
import httpx
import os
import json
from pathlib import Path
from typing import List, Dict
from google import genai
from dotenv import load_dotenv, find_dotenv, set_key
from pydantic import BaseModel
import re

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

# --- 配置管理 (与原版相同) ---
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
    "任务描述：请仔细阅读并分析以下技术交底材料，将其拆解并提炼成一个结构化的JSON对象。请确保JSON格式正确无误。\n"
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
    "任务描述：请根据以下核心创新点和技术方案，提炼出符合中国专利命名规范且不超过25个汉字的发明名称。要求简洁明了并准确反映技术内容。请只返回发明名称本身，不要添加任何多余内容。\n\n"
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
    for key in ["title", "background", "invention", "implementation"]:
        if key not in st.session_state:
            st.session_state[key] = ""

def main():
    st.set_page_config(page_title="专利撰写助手", layout="wide", page_icon="📝")
    st.title("📝 智能专利申请书撰写助手")

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
                    is_json_mode = st.session_state.config["provider"] == "openai"
                    response_str = llm_client.call([{"role": "user", "content": prompt}], json_mode=is_json_mode)
                    st.session_state.structured_brief = extract_json_from_string(response_str)
                    st.session_state.stage = "review_brief"
                    st.rerun()
                except (json.JSONDecodeError, KeyError) as e:
                    st.error(f"无法解析模型返回的核心要素，请检查模型输出或尝试调整输入。错误: {e}\n模型原始返回: \n{response_str}")
        else:
            st.warning("请输入您的技术构思。")

    # --- 阶段二：审核并确认核心要素 ---
    if st.session_state.stage == "review_brief":
        st.header("Step 2️⃣: 审核并确认核心要素")
        st.info("请检查并可编辑由AI提炼的发明核心信息，这将作为后续所有章节撰写的基础。")
        
        brief = st.session_state.structured_brief
        brief['problem_statement'] = st.text_area("1. 待解决的技术问题", value=brief.get('problem_statement', ''), height=100)
        brief['core_inventive_concept'] = st.text_area("2. 核心创新点", value=brief.get('core_inventive_concept', ''), height=100)
        brief['technical_solution_summary'] = st.text_area("3. 技术方案概述", value=brief.get('technical_solution_summary', ''), height=100)
        
        key_steps_list = brief.get('key_components_or_steps', [])
        key_steps_str = "\n".join(key_steps_list) if isinstance(key_steps_list, list) else key_steps_list
        edited_steps_str = st.text_area("4. 关键组件/步骤清单", value=key_steps_str, height=100)
        brief['key_components_or_steps'] = [line.strip() for line in edited_steps_str.split('\n') if line.strip()]
        brief['achieved_effects'] = st.text_area("5. 有益效果", value=brief.get('achieved_effects', ''), height=100)

        col1, col2 = st.columns(2)
        if col1.button("✅ 确认核心要素，开始撰写", type="primary"):
            st.session_state.structured_brief = brief
            st.session_state.stage = "writing"
            st.rerun()
        if col2.button("返回重新输入"):
            st.session_state.stage = "input"
            st.rerun()

    # --- 阶段三：分步生成与撰写 ---
    if st.session_state.stage == "writing":
        st.header("Step 3️⃣: 逐章生成与编辑专利草稿")
        brief = st.session_state.structured_brief

        # 动态生成各个部分
        sections = {
            "title": ("发明名称", PROMPT_TITLE, {"core_inventive_concept": brief['core_inventive_concept'], "technical_solution_summary": brief['technical_solution_summary']}),
            "background": ("背景技术", PROMPT_BACKGROUND, {"title": st.session_state.title, "problem_statement": brief['problem_statement']}),
            "invention": ("发明内容", PROMPT_INVENTION_CONTENT, {"title": st.session_state.title, "background": st.session_state.background, **brief}),
            "implementation": ("具体实施方式", PROMPT_IMPLEMENTATION, {"title": st.session_state.title, "invention_content": st.session_state.invention, "key_components_or_steps": "\n".join(brief['key_components_or_steps'])})
        }

        # 按照顺序检查并生成
        for key, (label, prompt_template, format_args) in sections.items():
            with st.expander(f"**{label}**", expanded=not st.session_state[key]):
                if not st.session_state[key]:
                    # 只有前置条件满足时，才显示生成按钮
                    if all(val for k, val in format_args.items() if k in st.session_state and isinstance(st.session_state[k], str)):
                        if st.button(f"✍️ 生成{label}", key=f"btn_{key}"):
                            with st.spinner(f"正在调用{label}代理..."):
                                prompt = prompt_template.format(**format_args)
                                response = llm_client.call([{"role": "user", "content": prompt}])
                                st.session_state[key] = response.strip()
                                st.rerun()
                    else:
                        st.info(f"请先生成前置章节（如：发明名称）以继续。")
                
                # 显示已生成的内容供编辑
                if st.session_state[key]:
                    if key == 'title':
                        st.session_state[key] = st.text_input(label, value=st.session_state[key], key=f"edit_{key}")
                    else:
                        st.session_state[key] = st.text_area(label, value=st.session_state[key], height=300, key=f"edit_{key}")

        # --- 阶段四：预览与下载 ---
        if all(st.session_state[key] for key in sections):
            st.header("Step 4️⃣: 预览与下载")
            st.markdown("---")
            full_text = (
                f"# 一、发明名称\n{st.session_state.title}\n\n"
                f"{st.session_state.background}\n\n"
                f"{st.session_state.invention}\n\n"
                f"{st.session_state.implementation}"
            )
            st.subheader("完整草稿预览")
            st.markdown(full_text)
            st.download_button("📄 下载完整草稿 (.md)", full_text, file_name=f"{st.session_state.title}_patent_draft.md")

if __name__ == "__main__":
    main()