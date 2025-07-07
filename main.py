import streamlit as st
import openai
import httpx
import os
import json
from pathlib import Path
from typing import List, Dict, Any
from google import genai
from dotenv import load_dotenv, find_dotenv, set_key
import time
import streamlit.components.v1 as components
import prompts


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
        "openai": {
            "api_base": os.getenv("OPENAI_API_BASE", "https://api.mistral.ai/v1"),
            "api_key": os.getenv("OPENAI_API_KEY", ""),
            "model": os.getenv("OPENAI_MODEL", "mistral-medium-latest"),
            "proxy_url": os.getenv("OPENAI_PROXY_URL", ""),
        },
        "google": {
            "api_key": os.getenv("GOOGLE_API_KEY", ""),
            "model": os.getenv("GOOGLE_MODEL", "gemini-2.5-flash"),
            "proxy_url": os.getenv("GOOGLE_PROXY_URL", ""),
        },
    }

def save_config(cfg: dict):
    """将配置保存到 .env 文件。"""
    set_key(env_file, "PROVIDER", cfg.get("provider", "openai"))
    if "openai" in cfg:
        set_key(env_file, "OPENAI_API_KEY", cfg["openai"].get("api_key", ""))
        set_key(env_file, "OPENAI_API_BASE", cfg["openai"].get("api_base", ""))
        set_key(env_file, "OPENAI_MODEL", cfg["openai"].get("model", ""))
        set_key(env_file, "OPENAI_PROXY_URL", cfg["openai"].get("proxy_url", ""))
    if "google" in cfg:
        set_key(env_file, "GOOGLE_API_KEY", cfg["google"].get("api_key", ""))
        set_key(env_file, "GOOGLE_MODEL", cfg["google"].get("model", ""))
        set_key(env_file, "GOOGLE_PROXY_URL", cfg["google"].get("proxy_url", ""))

class LLMClient:
    """一个统一的、简化的LLM客户端，支持OpenAI兼容接口和Google Gemini，并统一处理代理。"""
    def __init__(self, config: dict):
        self.full_config = config
        self.provider = config.get("provider", "openai")
        provider_cfg = config.get(self.provider, {})
        
        proxy_url = provider_cfg.get("proxy_url")
        self.model = provider_cfg.get("model")
        api_key = provider_cfg.get("api_key")

        if self.provider == "google":
            if proxy_url:
                os.environ["HTTP_PROXY"] = proxy_url
                os.environ["HTTPS_PROXY"] = proxy_url
            else:
                if "HTTP_PROXY" in os.environ:
                    del os.environ["HTTP_PROXY"]
                if "HTTPS_PROXY" in os.environ:
                    del os.environ["HTTPS_PROXY"]
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
            generation_config_params = {}
            generation_config_params["temperature"] = 0.1
            generation_config_params["top_p"] = 0.1
            if json_mode:
                generation_config_params["response_mime_type"] = "application/json"
            config = genai.types.GenerateContentConfig(**generation_config_params)
            # config = {"response_mime_type": "application/json"} if json_mode else {}
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
                temperature=0.1,
                top_p=0.1,
                messages=messages,
                **extra_params,
            )
            return response.choices[0].message.content


# --- 工作流与UI章节映射 ---
UI_SECTION_ORDER = ["title", "background", "invention", "drawings", "implementation"]
UI_SECTION_CONFIG = {
    "title": {
        "label": "发明名称",
        "workflow_keys": ["title_options"],
        "dependencies": ["structured_brief"],
    },
    "background": {
        "label": "背景技术",
        "workflow_keys": ["background_problem", "background_context"],
        "dependencies": ["structured_brief"],
    },
    "invention": {
        "label": "发明内容",
        "workflow_keys": ["invention_purpose", "solution_points", "invention_solution_detail", "invention_effects"],
        "dependencies": ["background", "structured_brief"],
    },
    "drawings": {
        "label": "附图",
        "workflow_keys": [], # Drawings are handled by a dedicated function
        "dependencies": ["invention"],
    },
    "implementation": {
        "label": "具体实施方式",
        "workflow_keys": ["implementation_details"],
        "dependencies": ["invention", "structured_brief"],
    },
}

WORKFLOW_CONFIG = {
    "title_options": {"prompt": prompts.PROMPT_TITLE, "json_mode": True, "dependencies": ["core_inventive_concept", "technical_solution_summary"]},
    "background_problem": {"prompt": prompts.PROMPT_BACKGROUND_PROBLEM, "json_mode": False, "dependencies": ["problem_statement"]},
    "background_context": {"prompt": prompts.PROMPT_BACKGROUND_CONTEXT, "json_mode": False, "dependencies": ["background_problem"]},
    "invention_purpose": {"prompt": prompts.PROMPT_INVENTION_PURPOSE, "json_mode": False, "dependencies": ["background_problem"]},
    "solution_points": {"prompt": prompts.PROMPT_INVENTION_SOLUTION_POINTS, "json_mode": True, "dependencies": ["technical_solution_summary", "key_components_or_steps"]},
    "invention_solution_detail": {"prompt": prompts.PROMPT_INVENTION_SOLUTION_DETAIL, "json_mode": False, "dependencies": ["core_inventive_concept", "technical_solution_summary", "key_components_or_steps"]},
    "invention_effects": {"prompt": prompts.PROMPT_INVENTION_EFFECTS, "json_mode": False, "dependencies": ["solution_points", "achieved_effects"]},
    "implementation_details": {"prompt": prompts.PROMPT_IMPLEMENTATION_POINT, "json_mode": False, "dependencies": ["solution_points"]},
}

# --- 状态管理与依赖检查 ---
def get_active_content(key: str) -> Any:
    """获取某个部分当前激活版本的内容。"""
    if f"{key}_versions" not in st.session_state or not st.session_state[f"{key}_versions"]:
        return None
    active_index = st.session_state.get(f"{key}_active_index", 0)
    version_data = st.session_state[f"{key}_versions"][active_index]
    
    # Handle old string-based versions for backward compatibility
    if isinstance(version_data, str):
        return version_data
    # Handle new dictionary-based versions
    if isinstance(version_data, dict):
        return version_data.get("active_content")
    # Handle lists (like for drawings)
    if isinstance(version_data, list):
        return version_data
    return None

def is_stale(ui_key: str) -> bool:
    """检查某个UI章节是否因其依赖项更新而过时。"""
    timestamps = st.session_state.data_timestamps
    if ui_key not in timestamps:
        return False 
    
    section_time = timestamps[ui_key]
    for dep in UI_SECTION_CONFIG[ui_key]["dependencies"]:
        # Need to handle the case where the dependency itself is complex
        dep_timestamp = timestamps.get(dep)
        if dep_timestamp and dep_timestamp > section_time:
            return True
    if 'structured_brief' in UI_SECTION_CONFIG[ui_key]['dependencies']:
        if 'structured_brief' in timestamps and timestamps['structured_brief'] > section_time:
            return True
    return False

# --- 核心工作流与UI渲染 ---
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
    if "globally_refined_draft" not in st.session_state:
        st.session_state.globally_refined_draft = {}
    if "refined_version_available" not in st.session_state:
        st.session_state.refined_version_available = False


    all_keys = list(UI_SECTION_CONFIG.keys()) + list(WORKFLOW_CONFIG.keys())
    for key in all_keys:
        if f"{key}_versions" not in st.session_state:
            st.session_state[f"{key}_versions"] = []
        if f"{key}_active_index" not in st.session_state:
            st.session_state[f"{key}_active_index"] = 0

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
        p_cfg["api_key"] = st.text_input("API Key", value=p_cfg.get("api_key", ""), type="password", key=f'{config["provider"]}_api_key')

        if config["provider"] == "openai":
            p_cfg["api_base"] = st.text_input("API 基础地址", value=p_cfg.get("api_base", ""), key="openai_api_base")
            p_cfg["model"] = st.text_input("模型名称", value=p_cfg.get("model", ""), key="openai_model")
            p_cfg["proxy_url"] = st.text_input(
                "代理 URL (可选)", value=p_cfg.get("proxy_url", ""),
                placeholder="http://127.0.0.1:7890", key="openai_proxy_url"
            )
        else: # google
            p_cfg["model"] = st.text_input("模型名称", value=p_cfg.get("model", ""), key="google_model")
            p_cfg["proxy_url"] = st.text_input(
                "代理 URL (可选)", value=p_cfg.get("proxy_url", ""),
                placeholder="http://127.0.0.1:7890", key="google_proxy_url"
            )

        if st.button("保存配置"):
            save_config(config)
            st.success("配置已保存！")
            if 'llm_client' in st.session_state:
                del st.session_state.llm_client
            st.rerun()

def clean_mermaid_code(code: str) -> str:
    """清理Mermaid代码字符串，移除可选的markdown代码块标识。"""
    cleaned_code = code.strip()
    if cleaned_code.startswith("```mermaid"):
        cleaned_code = cleaned_code[len("```mermaid"):].strip()
    if cleaned_code.endswith("```"):
        cleaned_code = cleaned_code[:-3].strip()
    return cleaned_code

def generate_all_drawings(llm_client: LLMClient, invention_solution_detail: str):
    """统一生成所有附图：先构思，然后为每个构思生成代码。"""
    if not invention_solution_detail:
        st.warning("无法生成附图，因为“发明内容”>“技术解决方案”内容为空。")
        return

    with st.spinner("正在为附图构思..."):
        ideas_prompt = prompts.PROMPT_MERMAID_IDEAS.format(invention_solution_detail=invention_solution_detail)
        ideas_response_str = llm_client.call([{"role": "user", "content": ideas_prompt}], json_mode=True)
        ideas = json.loads(ideas_response_str.strip())
        if not isinstance(ideas, list):
            st.error(f"附图构思返回格式错误，期望列表但得到: {ideas_response_str}")
            return

    drawings = []
    progress_bar = st.progress(0, text="正在生成附图代码...")
    for i, idea in enumerate(ideas):
        idea_title = idea.get('title', f'附图构思 {i+1}')
        idea_desc = idea.get('description', '')
        
        code_prompt = prompts.PROMPT_MERMAID_CODE.format(
            title=idea_title,
            description=idea_desc,
            invention_solution_detail=invention_solution_detail
        )
        code = llm_client.call([{"role": "user", "content": code_prompt}], json_mode=False)
        
        cleaned_code = clean_mermaid_code(code)

        drawings.append({
            "title": idea_title,
            "description": idea_desc,
            "code": cleaned_code
        })
        progress_bar.progress((i + 1) / len(ideas), text=f"已生成附图: {idea_title}")
    
    st.session_state.drawings_versions.append(drawings)
    st.session_state.drawings_active_index = len(st.session_state.drawings_versions) - 1
    st.session_state.data_timestamps['drawings'] = time.time()

@st.cache_data
def load_mermaid_script():
    """加载并缓存Mermaid JS脚本文件。"""
    try:
        with open("mermaid_script.js", "r") as f:
            return f.read()
    except FileNotFoundError:
        st.error("错误：mermaid_script.js 文件未找到。")
        return ""

def render_mermaid_component(drawing_key: str, drawing: dict, height: int = 450):
    """渲染单个Mermaid图表组件，使用外部JS文件。"""
    mermaid_script = load_mermaid_script()
    if not mermaid_script:
        return

    safe_title = "".join(c for c in drawing.get('title', '') if c.isalnum() or c in (' ', '_')).rstrip()
    
    # 将数据安全地转为JSON字符串
    code_json = json.dumps(drawing.get("code", ""))
    safe_title_json = json.dumps(safe_title)
    drawing_key_json = json.dumps(drawing_key)

    html_component = f'''
        <div id="mermaid-view-{drawing_key}">
            <div id="mermaid-output-{drawing_key}" style="background-color: white; padding: 1rem; border-radius: 0.5rem;"></div>
        </div>
        <button id="download-btn-{drawing_key}" style="margin-top: 10px; padding: 5px 10px; border-radius: 5px; border: 1px solid #ccc; cursor: pointer;">📥 下载 PNG</button>
        
        <script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
        <script>
            {mermaid_script}
        </script>
        <script>
            // 使用JSON.parse来安全地解码数据
            const code = JSON.parse({code_json});
            const safeTitle = JSON.parse({safe_title_json});
            const drawingKey = JSON.parse({drawing_key_json});
            
            // 调用全局渲染函数
            window.renderMermaid(drawingKey, safeTitle, code);
        </script>
    '''
    components.html(html_component, height=height, scrolling=True)

def build_format_args(dependencies: List[str]) -> Dict[str, Any]:
    """根据依赖项列表，构建用于格式化Prompt的字典。"""
    format_args = {**st.session_state.structured_brief}
    for dep in dependencies:
        dep_content = get_active_content(dep)
        if isinstance(dep_content, dict):
            format_args[dep] = dep_content.get('active_content') or st.session_state.structured_brief.get(dep)
        else:
            format_args[dep] = dep_content or st.session_state.structured_brief.get(dep)

    if "key_components_or_steps" in dependencies:
        format_args["key_components_or_steps"] = "\n".join(st.session_state.structured_brief.get('key_components_or_steps', []))
    
    if "solution_points" in dependencies:
        solution_points = get_active_content("solution_points") or []
        format_args["solution_points_str"] = "\n".join([f"{i+1}. {p}" for i, p in enumerate(solution_points)])

    return format_args

def generate_ui_section(llm_client: LLMClient, ui_key: str):
    """为单个UI章节执行生成、批判和精炼的完整流程。"""
    if ui_key == "drawings":
        invention_solution_detail = get_active_content("invention_solution_detail")
        generate_all_drawings(llm_client, invention_solution_detail)
        return

    # --- 步骤 1: 生成所有微观组件 ---
    workflow_keys = UI_SECTION_CONFIG[ui_key]["workflow_keys"]
    for micro_key in workflow_keys:
        step_config = WORKFLOW_CONFIG[micro_key]
        
        # 使用新的辅助函数构建参数
        format_args = build_format_args(step_config["dependencies"])

        # 特殊处理 implementation_details 的循环生成
        if micro_key == "implementation_details":
            points = get_active_content("solution_points") or []
            details = []
            for i, point in enumerate(points):
                point_prompt = step_config["prompt"].format(point=point)
                detail = llm_client.call([{"role": "user", "content": point_prompt}], json_mode=False)
                details.append(detail)
            st.session_state[f"{micro_key}_versions"].append(details)
            st.session_state[f"{micro_key}_active_index"] = len(st.session_state[f"{micro_key}_versions"]) - 1
            st.session_state.data_timestamps[micro_key] = time.time()
            continue

        prompt = step_config["prompt"].format(**format_args)
        response_str = llm_client.call([{"role": "user", "content": prompt}], json_mode=step_config["json_mode"])
        try:
            result = json.loads(response_str.strip()) if step_config["json_mode"] else response_str.strip()
        except json.JSONDecodeError:
            st.error(f"无法解析JSON，模型返回内容: {response_str}")
            return
        st.session_state[f"{micro_key}_versions"].append(result)
        st.session_state[f"{micro_key}_active_index"] = len(st.session_state[f"{micro_key}_versions"]) - 1
        st.session_state.data_timestamps[micro_key] = time.time()

    # --- 步骤 2: 组装初稿 (content_v1) ---
    content_v1 = ""
    if ui_key == "title":
        title_options = get_active_content("title_options") or []
        st.session_state.title_versions.extend(title_options)
        st.session_state.title_active_index = len(st.session_state.title_versions) - 1
        st.session_state.data_timestamps[ui_key] = time.time()
        return
    elif ui_key == "background":
        context = get_active_content("background_context") or ""
        problem = get_active_content("background_problem") or ""
        content_v1 = f"## 2.1 对最接近发明的同类现有技术状况加以分析说明\n{context}\n\n## 2.2 实事求是地指出现有技术存在的问题，尽可能分析存在的原因。\n{problem}"
    elif ui_key == "invention":
        purpose = get_active_content("invention_purpose") or ""
        solution_detail = get_active_content("invention_solution_detail") or ""
        effects = get_active_content("invention_effects") or ""
        content_v1 = f"## 3.1 发明目的\n{purpose}\n\n## 3.2 技术解决方案\n{solution_detail}\n\n## 3.3 技术效果\n{effects}"
    elif ui_key == "implementation":
        details = get_active_content("implementation_details") or []
        content_v1 = "\n".join([f"{i+1}. {detail}" for i, detail in enumerate(details)])

    if not content_v1.strip():
        st.warning(f"无法为 {UI_SECTION_CONFIG[ui_key]['label']} 生成初稿，依赖项内容为空。")
        return

    # --- 步骤 3: 内部批判 (Self-Criticism) ---
    active_content = content_v1
    critic_result = None
    with st.spinner(f"“批判家”正在审查 {UI_SECTION_CONFIG[ui_key]['label']}..."):
        critic_prompt = prompts.PROMPT_CRITIC_SECTION.format(
            section_content=content_v1,
            structured_brief=json.dumps(st.session_state.structured_brief, ensure_ascii=False, indent=2)
        )
        try:
            critic_response_str = llm_client.call([{"role": "user", "content": critic_prompt}], json_mode=True)
            critic_result = json.loads(critic_response_str.strip())
        except (json.JSONDecodeError, KeyError) as e:
            st.error(f"无法解析批判家返回的JSON: {e}\n原始返回: {critic_response_str}")

    # --- 步骤 4: 决策与迭代 ---
    if critic_result and not critic_result.get("passed", True):
        with st.spinner(f"根据批判家意见，正在自动精炼 {UI_SECTION_CONFIG[ui_key]['label']}..."):
            feedback_str = "\n".join(critic_result.get("feedback", ["无具体反馈。"]))
            refine_prompt = prompts.PROMPT_REFINE_SECTION.format(
                structured_brief=json.dumps(st.session_state.structured_brief, ensure_ascii=False, indent=2),
                content_v1=content_v1,
                feedback=feedback_str
            )
            try:
                content_v2 = llm_client.call([{"role": "user", "content": refine_prompt}], json_mode=False)
                active_content = content_v2.strip()
                st.success(f"{UI_SECTION_CONFIG[ui_key]['label']} 已自动精炼！")
            except Exception as e:
                st.error(f"自动精炼失败: {e}")
    elif critic_result:
        st.success(f"{UI_SECTION_CONFIG[ui_key]['label']} 初稿质量达标！")

    # --- 步骤 5: 保存最终版本 ---
    new_version = {
        "active_content": active_content,
        "initial_draft": content_v1,
        "critic_feedback": critic_result
    }
    st.session_state[f"{ui_key}_versions"].append(new_version)
    st.session_state[f"{ui_key}_active_index"] = len(st.session_state[f"{ui_key}_versions"]) - 1
    st.session_state.data_timestamps[ui_key] = time.time()

def run_global_refinement(llm_client: LLMClient):
    """迭代所有章节，并根据全局上下文和原始生成要求进行重构和润色。"""
    st.session_state.globally_refined_draft = {}
    initial_draft_content = {key: get_active_content(key) for key in UI_SECTION_ORDER}

    prompt_map = {
        "background": [prompts.PROMPT_BACKGROUND_CONTEXT, prompts.PROMPT_BACKGROUND_PROBLEM],
        "invention": [prompts.PROMPT_INVENTION_PURPOSE, prompts.PROMPT_INVENTION_SOLUTION_DETAIL, prompts.PROMPT_INVENTION_EFFECTS],
        "implementation": [prompts.PROMPT_IMPLEMENTATION_POINT]
    }

    with st.status("正在执行全局重构与润色...", expanded=True) as status:
        for target_key in UI_SECTION_ORDER:
            if target_key in ['drawings', 'title']:
                st.session_state.globally_refined_draft[target_key] = initial_draft_content.get(target_key)
                continue
            
            status.update(label=f"正在重构与润色: {UI_SECTION_CONFIG[target_key]['label']}...")
            
            global_context_parts = []
            for key, content in initial_draft_content.items():
                if key != target_key:
                    label = UI_SECTION_CONFIG[key]['label']
                    processed_content = ""
                    if key == 'title':
                        processed_content = content or ""
                    elif key == 'drawings' and isinstance(content, list):
                        processed_content = "附图列表:\n" + "\n".join([f"- {d.get('title')}: {d.get('description')}" for d in content])
                    elif isinstance(content, str):
                        processed_content = content
                    
                    if processed_content:
                        global_context_parts.append(f"--- {label} ---\n{processed_content}")
            
            global_context = "\n".join(global_context_parts)
            target_content = initial_draft_content.get(target_key, "")

            original_prompts = prompt_map.get(target_key, [])
            original_generation_prompt = "\n\n---\n\n".join(original_prompts)
            if not original_generation_prompt:
                 st.warning(f"未找到 {UI_SECTION_CONFIG[target_key]['label']} 的原始生成指令，将仅基于全局上下文进行润色。")

            refine_prompt = prompts.PROMPT_GLOBAL_RESTRUCTURE_AND_POLISH.format(
                global_context=global_context,
                target_section_name=UI_SECTION_CONFIG[target_key]['label'],
                target_section_content=target_content,
                original_generation_prompt=original_generation_prompt
            )
            
            try:
                refined_content = llm_client.call([{"role": "user", "content": refine_prompt}], json_mode=False)
                st.session_state.globally_refined_draft[target_key] = refined_content.strip()
            except Exception as e:
                st.error(f"全局重构章节 {UI_SECTION_CONFIG[target_key]['label']} 失败: {e}")
                st.session_state.globally_refined_draft[target_key] = target_content

        status.update(label="✅ 全局重构与润色完成！", state="complete")
    st.session_state.refined_version_available = True

def main():
    st.set_page_config(page_title="智能专利撰写助手 v4", layout="wide", page_icon="📝")
    st.title("📝 智能专利申请书撰写助手 v4")
    st.caption("新功能：生成时进行自我批判与修正，并支持全局回顾精炼。")

    initialize_session_state()
    config = st.session_state.config
    render_sidebar(config)

    active_provider = st.session_state.config["provider"]
    if not st.session_state.config.get(active_provider, {}).get("api_key"):
        st.warning("请在左侧边栏配置并保存您的 API Key。")
        st.stop()

    if 'llm_client' not in st.session_state or st.session_state.llm_client.full_config != st.session_state.config:
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
        if st.button("🔬 分析并提炼核心要素", type="primary"):
            if user_input:
                st.session_state.user_input = user_input
                prompt = prompts.PROMPT_ANALYZE.format(user_input=user_input)
                with st.spinner("正在调用分析代理，请稍候..."):
                    try:
                        response_str = llm_client.call([{"role": "user", "content": prompt}], json_mode=True)
                        st.session_state.structured_brief = json.loads(response_str.strip())
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
        def update_brief_timestamp():
            st.session_state.data_timestamps['structured_brief'] = time.time()

        brief['background_technology'] = st.text_area("背景技术", value=brief.get('background_technology', ''), on_change=update_brief_timestamp)
        brief['problem_statement'] = st.text_area("待解决的技术问题", value=brief.get('problem_statement', ''), on_change=update_brief_timestamp)
        brief['core_inventive_concept'] = st.text_area("核心创新点", value=brief.get('core_inventive_concept', ''), on_change=update_brief_timestamp)
        brief['technical_solution_summary'] = st.text_area("技术方案概述", value=brief.get('technical_solution_summary', ''), on_change=update_brief_timestamp)
        
        key_components = brief.get('key_components_or_steps', [])
        processed_steps = []
        if key_components and isinstance(key_components[0], dict):
            processed_steps = [str(list(item.values())[0]) for item in key_components if item and item.values()]
        else:
            processed_steps = [str(item) for item in key_components]
        key_steps_str = "\n".join(processed_steps)

        edited_steps_str = st.text_area("关键组件/步骤清单", value=key_steps_str, on_change=update_brief_timestamp)
        brief['key_components_or_steps'] = [line.strip() for line in edited_steps_str.split('\n') if line.strip()]
        brief['achieved_effects'] = st.text_area("有益效果", value=brief.get('achieved_effects', ''), on_change=update_brief_timestamp)

        col1, col2, col3 = st.columns([2,2,1])
        if col1.button("🚀 一键生成初稿", type="primary"):
            with st.status("正在为您生成完整专利初稿...", expanded=True) as status:
                for key in UI_SECTION_ORDER:
                    status.update(label=f"正在生成: {UI_SECTION_CONFIG[key]['label']}...")
                    generate_ui_section(llm_client, key)
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
        
        if st.button("⬅️ 返回修改核心要素"):
            st.session_state.stage = "review_brief"
            st.rerun()
        
        st.markdown("---")
        just_generated_key = st.session_state.pop('just_generated_key', None)

        for key in UI_SECTION_ORDER:
            config = UI_SECTION_CONFIG[key]
            label = config["label"]
            versions = st.session_state.get(f"{key}_versions", [])
            is_section_stale = is_stale(key)
            
            expander_label = f"**{label}**"
            if is_section_stale:
                expander_label += " ⚠️ (依赖项已更新，建议重新生成)"
            elif not versions:
                expander_label += " (待生成)"
            
            is_expanded = (not versions) or is_section_stale or (key == just_generated_key)
            with st.expander(expander_label, expanded=is_expanded):
                if key == 'drawings':
                    invention_content = get_active_content("invention")
                    if not invention_content:
                        st.info("请先生成“发明内容”章节。")
                        continue

                    invention_solution_detail = get_active_content("invention_solution_detail")

                    if st.button("💡 (重新)构思并生成所有附图", key="regen_all_drawings"):
                        with st.spinner("正在为您重新生成全套附图..."):
                            generate_all_drawings(llm_client, invention_solution_detail)
                            st.rerun()
                    
                    drawings = get_active_content("drawings")
                    if drawings:
                        st.caption("为保证独立性，可对单个附图重新生成，或在下方编辑代码。")
                        
                        for i, drawing in enumerate(drawings):
                            with st.container(border=True):
                                col1, col2 = st.columns([3, 1])
                                with col1:
                                    st.markdown(f"**附图 {i+1}: {drawing.get('title', '无标题')}**")
                                with col2:
                                    if st.button(f"🔄 重新生成此图", key=f"regen_drawing_{i}"):
                                        with st.spinner(f"正在重新生成附图: {drawing.get('title', '无标题')}..."):
                                            code_prompt = prompts.PROMPT_MERMAID_CODE.format(
                                                title=drawing.get('title', ''),
                                                description=drawing.get('description', ''),
                                                invention_solution_detail=invention_solution_detail
                                            )
                                            new_code = llm_client.call([{"role": "user", "content": code_prompt}], json_mode=False)
                                            
                                            active_drawings = json.loads(json.dumps(get_active_content("drawings")))
                                            active_drawings[i]["code"] = clean_mermaid_code(new_code)
                                            
                                            st.session_state.drawings_versions.append(active_drawings)
                                            st.session_state.drawings_active_index = len(st.session_state.drawings_versions) - 1
                                            st.session_state.data_timestamps['drawings'] = time.time()
                                            st.rerun()

                                st.markdown(f"**构思说明:** *{drawing.get('description', '无')}*")
                                
                                # 使用新的辅助函数渲染组件
                                drawing_key = f"mermaid_{i}"
                                render_mermaid_component(drawing_key, drawing)
                                
                                edited_code = st.text_area("编辑Mermaid代码:", value=drawing["code"], key=f"edit_code_{i}", height=150)
                                if edited_code != drawing["code"]:
                                    active_drawings = json.loads(json.dumps(get_active_content("drawings")))
                                    active_drawings[i]["code"] = edited_code
                                    st.session_state.drawings_versions.append(active_drawings)
                                    st.session_state.drawings_active_index = len(st.session_state.drawings_versions) - 1
                                    st.session_state.data_timestamps['drawings'] = time.time()
                                    st.rerun()
                    continue

                col1, col2 = st.columns([3, 1])
                with col1:
                    deps_met = all(
                        (st.session_state.get("structured_brief") if dep == "structured_brief" else get_active_content(dep))
                        for dep in config["dependencies"]
                    )
                    if deps_met:
                        if st.button(f"🔄 重新生成 {label}" if versions else f"✍️ 生成 {label}", key=f"btn_{key}"):
                            with st.spinner(f"正在执行 {label} 的生成/精炼流程..."):
                                generate_ui_section(llm_client, key)
                                st.session_state.just_generated_key = key
                                st.rerun()
                    else:
                        st.info(f"请先生成前置章节: {', '.join(config['dependencies'])}")

                active_idx = st.session_state.get(f"{key}_active_index", 0)
                if len(versions) > 1:
                    with col2:
                        version_labels = [f"版本 {i+1}" for i in range(len(versions))]
                        new_idx = st.selectbox(f"选择版本", version_labels, index=active_idx, key=f"select_{key}")
                        active_idx = version_labels.index(new_idx)
                        if active_idx != st.session_state.get(f"{key}_active_index", 0):
                            st.session_state[f"{key}_active_index"] = active_idx
                            st.rerun()

                if versions:
                    active_version_data = versions[active_idx]
                    active_content = get_active_content(key)

                    def create_new_version_from_edit(k, new_content):
                        if k == 'title':
                            st.session_state[f"{k}_versions"].append(new_content)
                        else:
                            new_version_obj = {"active_content": new_content, "initial_draft": new_content, "critic_feedback": None}
                            st.session_state[f"{k}_versions"].append(new_version_obj)
                        st.session_state[f"{k}_active_index"] = len(st.session_state[f"{k}_versions"]) - 1
                        st.session_state.data_timestamps[k] = time.time()

                    if isinstance(active_version_data, dict) and active_version_data.get("critic_feedback"):
                        feedback = active_version_data["critic_feedback"]
                        with st.container(border=True):
                            score = feedback.get('score', 'N/A')
                            passed = "✅ 通过" if feedback.get('passed') else "❌ 待改进"
                            st.markdown(f"**AI 批判家意见:** {passed} (得分: {score})")
                            if not feedback.get('passed') and feedback.get('feedback'):
                                for f in feedback['feedback']:
                                    st.caption(f" - {f}")
                                if active_version_data['active_content'] != active_version_data['initial_draft']:
                                    st.markdown("**初稿 (v1):**")
                                    st.text_area(
                                        label="v1 draft content",
                                        value=active_version_data['initial_draft'],
                                        height=200,
                                        disabled=True,
                                        key=f"v1_draft_{key}",
                                        label_visibility="collapsed"
                                    )
                    
                    if key == 'title':
                        edited_content = st.text_input("编辑区", value=active_content, key=f"edit_{key}")
                    else:
                        edited_content = st.text_area("编辑区", value=active_content, height=300, key=f"edit_{key}")
                    
                    if edited_content != active_content:
                        create_new_version_from_edit(key, edited_content)
                        st.rerun()

    # --- 阶段四：预览与下载 ---
    if st.session_state.stage == "writing" and all(get_active_content(key) for key in UI_SECTION_ORDER if key != 'drawings'):
        st.header("Step 4️⃣: 预览、精炼与下载")
        st.markdown("---")

        if st.button("✨ **全局重构与润色** ✨", type="primary", help="调用顶级专利总编AI，对所有章节进行深度重构、润色和细节补充，确保全文逻辑、深度和专业性达到最佳状态。"):
            run_global_refinement(llm_client)
            st.rerun()

        tabs = ["✍️ 初稿"]
        if st.session_state.get("refined_version_available"):
            tabs.append("✨ 全局重构润色版")
        
        selected_tab = st.radio("选择预览版本", tabs, horizontal=True)

        if selected_tab == "✍️ 初稿":
            draft_data = {key: get_active_content(key) for key in UI_SECTION_ORDER}
            st.subheader("初稿预览")
        else: # 全局精炼版
            draft_data = st.session_state.globally_refined_draft
            st.subheader("全局重构润色版预览")

        title = draft_data.get('title', '无标题')
        drawings_text = ""
        drawings = draft_data.get("drawings")
        if drawings and isinstance(drawings, list):
            for i, drawing in enumerate(drawings):
                drawings_text += f"## 附图{i+1}：{drawing.get('title', '')}\n"
                drawings_text += f"```mermaid\n{drawing.get('code', '')}\n```\n\n"

        full_text = (
            f"# 一、发明名称\n{title}\n\n"
            f"# 二、现有技术（背景技术）\n{draft_data.get('background', '')}\n\n"
            f"# 三、发明内容\n{draft_data.get('invention', '')}\n\n"
            f"# 四、附图说明\n{drawings_text if drawings_text else '（本申请无附图）'}\n\n"
            f"# 五、具体实施方式\n{draft_data.get('implementation', '')}"
        )
        st.subheader("完整草稿预览")
        st.markdown(full_text)
        st.download_button("📄 下载当前预览版本 (.md)", full_text, file_name=f"{title}_patent_draft.md")

if __name__ == "__main__":
    main()
