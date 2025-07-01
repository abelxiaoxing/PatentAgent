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
                # Unset proxy if it's not provided, to avoid using old env vars
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
            config = {"response_mime_type": "application/json"} if json_mode else {}
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


# --- 新的工作流与UI章节映射 ---
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
        "workflow_keys": ["drawings"],
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
    return st.session_state[f"{key}_versions"][active_index]

def is_stale(ui_key: str) -> bool:
    """检查某个UI章节是否因其依赖项更新而过时。"""
    timestamps = st.session_state.data_timestamps
    if ui_key not in timestamps:
        return False 
    
    section_time = timestamps[ui_key]
    for dep in UI_SECTION_CONFIG[ui_key]["dependencies"]:
        if dep in timestamps and timestamps[dep] > section_time:
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

def generate_all_drawings(llm_client: LLMClient, invention_solution_detail: str):
    """统一生成所有附图：先构思，然后为每个构思生成代码。"""
    if not invention_solution_detail:
        st.warning("无法生成附图，因为“技术解决方案”内容为空。")
        return

    # 1. Generate ideas
    ideas_prompt = prompts.PROMPT_MERMAID_IDEAS.format(invention_solution_detail=invention_solution_detail)
    try:
        ideas_response_str = llm_client.call([{"role": "user", "content": ideas_prompt}], json_mode=True)
        ideas = json.loads(ideas_response_str.strip())
        if not isinstance(ideas, list):
            st.error(f"附图构思返回格式错误，期望列表但得到: {ideas_response_str}")
            return
    except (json.JSONDecodeError, KeyError) as e:
        st.error(f"无法解析附图构思列表: {ideas_response_str}")
        return

    # 2. Generate code for each idea
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
        
        drawings.append({
            "title": idea_title,
            "description": idea_desc,
            "code": code.strip()
        })
        progress_bar.progress((i + 1) / len(ideas), text=f"已生成附图: {idea_title}")
    
    # 3. Save to session state
    st.session_state.drawings_versions.append(drawings)
    st.session_state.drawings_active_index = len(st.session_state.drawings_versions) - 1
    st.session_state.data_timestamps['drawings'] = time.time()

def generate_ui_section(llm_client: LLMClient, ui_key: str):
    """为单个UI章节执行其背后的完整微任务流，并组装最终内容。"""
    if ui_key == "drawings": 
        return

    brief = st.session_state.structured_brief
    workflow_keys = UI_SECTION_CONFIG[ui_key]["workflow_keys"]

    for micro_key in workflow_keys:
        step_config = WORKFLOW_CONFIG[micro_key]
        
        format_args = {**brief}
        for dep in step_config["dependencies"]:
            format_args[dep] = get_active_content(dep) or brief.get(dep)

        if "key_components_or_steps" in step_config["dependencies"]:
            format_args["key_components_or_steps"] = "\n".join(brief.get('key_components_or_steps', []))
        if micro_key == "invention_effects":
            solution_points = get_active_content("solution_points") or []
            format_args["solution_points_str"] = "\n".join([f"{i+1}. {p}" for i, p in enumerate(solution_points)])

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

    final_content = ""
    if ui_key == "title":
        final_content = get_active_content("title_options")
    elif ui_key == "background":
        context = get_active_content("background_context")
        problem = get_active_content("background_problem")
        final_content = f"## 2.1 对最接近发明的同类现有技术状况加以分析说明\n{context}\n\n## 2.2 实事求是地指出现有技术存在的问题，尽可能分析存在的原因。\n{problem}"
    elif ui_key == "invention":
        purpose = get_active_content("invention_purpose")
        solution_detail = get_active_content("invention_solution_detail")
        effects = get_active_content("invention_effects")
        final_content = f"## 3.1 发明目的\n{purpose}\n\n## 3.2 技术解决方案\n{solution_detail}\n\n## 3.3 技术效果\n{effects}"
    elif ui_key == "implementation":
        details = get_active_content("implementation_details") or []
        final_content = "\n\n".join([f"{i+1}. {detail}" for i, detail in enumerate(details)])

    if ui_key == "title":
        st.session_state.title_versions.extend(final_content)
        st.session_state.title_active_index = len(st.session_state.title_versions) - 1
    else:
        st.session_state[f"{ui_key}_versions"].append(final_content)
        st.session_state[f"{ui_key}_active_index"] = len(st.session_state[f"{ui_key}_versions"]) - 1
    
    st.session_state.data_timestamps[ui_key] = time.time()

def main():
    st.set_page_config(page_title="智能专利撰写助手 v3", layout="wide", page_icon="📝")
    st.title("📝 智能专利申请书撰写助手 v3")
    st.caption("附图流程已升级：一键生成初稿时将自动构思并生成全套附图。")

    initialize_session_state()
    config = st.session_state.config
    render_sidebar(config)

    active_provider = st.session_state.config["provider"]
    if not st.session_state.config.get(active_provider, {}).get("api_key"):
        st.warning("请在左侧边栏配置并保存您的 API Key。")
        st.stop()

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
        key_steps_list = brief.get('key_components_or_steps', [])
        if isinstance(key_steps_list, list) and key_steps_list and isinstance(key_steps_list[0], dict):
            key_steps_str = "\n".join([f"{item.get('name', '')}: {item.get('function', '')}" for item in key_steps_list])
        elif isinstance(key_steps_list, list):
            key_steps_str = "\n".join(key_steps_list)
        else:
            key_steps_str = str(key_steps_list)
        edited_steps_str = st.text_area("关键组件/步骤清单", value=key_steps_str, on_change=update_brief_timestamp)
        brief['key_components_or_steps'] = [line.strip() for line in edited_steps_str.split('\n') if line.strip()]
        brief['achieved_effects'] = st.text_area("有益效果", value=brief.get('achieved_effects', ''), on_change=update_brief_timestamp)

        col1, col2, col3 = st.columns([2,2,1])
        if col1.button("🚀 一键生成初稿", type="primary"):
            with st.status("正在为您生成完整专利初稿...", expanded=True) as status:
                # Generate text sections first
                for key in UI_SECTION_ORDER:
                    if key == 'drawings': 
                        continue
                    status.update(label=f"正在生成: {UI_SECTION_CONFIG[key]['label']}...")
                    generate_ui_section(llm_client, key)
                
                # Then, generate all drawings based on the invention content
                status.update(label="正在构思并生成全套附图...")
                invention_solution_detail = get_active_content("invention_solution_detail")
                if invention_solution_detail:
                    generate_all_drawings(llm_client, invention_solution_detail)
                
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
                # --- 特殊处理附图章节 ---
                if key == 'drawings':
                    invention_solution_detail = get_active_content("invention_solution_detail")
                    if not invention_solution_detail:
                        st.info("请先生成“发明内容”章节中的“技术解决方案”。")
                        continue

                    if st.button("💡 (重新)构思并生成所有附图"):
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
                                            active_drawings[i]["code"] = new_code.strip()
                                            
                                            st.session_state.drawings_versions.append(active_drawings)
                                            st.session_state.drawings_active_index = len(st.session_state.drawings_versions) - 1
                                            st.session_state.data_timestamps['drawings'] = time.time()
                                            st.rerun()

                                st.markdown(f"**构思说明:** *{drawing.get('description', '无')}*")
                                
                                drawing_key = f"mermaid_{i}"
                                safe_title = "".join(c for c in drawing.get('title', '') if c.isalnum() or c in (' ', '_')).rstrip()
                                
                                escaped_code = drawing["code"].replace("`", "\\`")

                                html_component = f'''
                                    <div id="mermaid-view-{drawing_key}">
                                        <div id="mermaid-output-{drawing_key}" style="background-color: white; padding: 1rem; border-radius: 0.5rem;"></div>
                                    </div>
                                    <button id="download-btn-{drawing_key}" style="margin-top: 10px; padding: 5px 10px; border-radius: 5px; border: 1px solid #ccc; cursor: pointer;">📥 下载 PNG</button>
                                    <script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
                                    <script>
                                    (function() {{
                                        const drawingKey = "{drawing_key}";
                                        const pngFileName = "{safe_title or f'drawing_{i}'}.png";
                                        const code = `{escaped_code}`.trim();
                                        
                                        const outputDiv = document.getElementById(`mermaid-output-${{drawingKey}}`);
                                        const downloadBtn = document.getElementById(`download-btn-${{drawingKey}}`);

                                        const renderDiagram = async () => {{
                                            try {{
                                                // 将主题从 'base' 修改为 'neutral' 以实现黑白风格
                                                mermaid.initialize({{ startOnLoad: false, theme: 'neutral' }}); 
                                                const {{ svg }} = await mermaid.render(`mermaid-svg-${{drawingKey}}`, code);
                                                outputDiv.innerHTML = svg;
                                            }} catch (e) {{
                                                outputDiv.innerHTML = `<pre style="color: red;">Error rendering diagram:\n${{e.message}}</pre>`;
                                                console.error("Mermaid render error:", e);
                                            }}
                                        }};

                                        const downloadPNG = async () => {{
                                            try {{
                                                const svgElement = outputDiv.querySelector('svg');
                                                if (!svgElement) {{ alert("Diagram not rendered yet."); return; }}
                                                
                                                // 确保下载的PNG背景是白色
                                                svgElement.style.backgroundColor = 'white';

                                                const svgData = new XMLSerializer().serializeToString(svgElement);
                                                const img = new Image();
                                                const canvas = document.createElement('canvas');
                                                const ctx = canvas.getContext('2d');

                                                img.onload = function() {{
                                                    const scale = 2; 
                                                    // 使用 SVG 的 viewBox 属性来获取准确尺寸，避免 getBoundingClientRect 的问题
                                                    const viewBox = svgElement.viewBox.baseVal;
                                                    const width = viewBox.width;
                                                    const height = viewBox.height;
                                                    
                                                    canvas.width = width * scale;
                                                    canvas.height = height * scale;
                                                    
                                                    // 绘制白色背景
                                                    ctx.fillStyle = 'white';
                                                    ctx.fillRect(0, 0, canvas.width, canvas.height);
                                                    
                                                    // 绘制图像
                                                    ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
                                                    
                                                    const pngFile = canvas.toDataURL('image/png');
                                                    const downloadLink = document.createElement('a');
                                                    downloadLink.download = pngFileName;
                                                    downloadLink.href = pngFile;
                                                    document.body.appendChild(downloadLink);
                                                    downloadLink.click();
                                                    document.body.removeChild(downloadLink);
                                                }};
                                                img.src = `data:image/svg+xml;base64,${{btoa(unescape(encodeURIComponent(svgData)))}}`;
                                            }} catch (e) {{
                                                console.error("Download failed:", e);
                                                alert(`Failed to generate PNG: ${{e.message}}`);
                                            }}
                                        }};

                                        if (code) {{
                                            renderDiagram();
                                            downloadBtn.addEventListener('click', downloadPNG);
                                        }}
                                    }})();
                                    </script>
                                '''
                                components.html(html_component, height=450, scrolling=True)
                                
                                edited_code = st.text_area("编辑Mermaid代码:", value=drawing["code"], key=f"edit_code_{i}", height=150)
                                if edited_code != drawing["code"]:
                                    active_drawings = json.loads(json.dumps(get_active_content("drawings")))
                                    active_drawings[i]["code"] = edited_code
                                    st.session_state.drawings_versions.append(active_drawings)
                                    st.session_state.drawings_active_index = len(st.session_state.drawings_versions) - 1
                                    st.session_state.data_timestamps['drawings'] = time.time()
                                    st.rerun()
                    continue
                
                # --- 常规章节处理 ---
                col1, col2 = st.columns([3, 1])
                with col1:
                    deps_met = all(get_active_content(dep) or (dep == 'structured_brief' and st.session_state.structured_brief) for dep in config["dependencies"])
                    if deps_met:
                        if st.button(f"🔄 重新生成 {label}" if versions else f"✍️ 生成 {label}", key=f"btn_{key}"):
                            with st.spinner(f"正在调用 {label} 代理..."):
                                generate_ui_section(llm_client, key)
                                st.session_state.just_generated_key = key
                                st.rerun()
                    else:
                        st.info(f"请先生成前置章节。")

                with col2:
                    if len(versions) > 1:
                        active_idx = st.session_state.get(f"{key}_active_index", 0)
                        new_idx = st.selectbox(f"选择版本 (共{len(versions)}个)", range(len(versions)), index=active_idx, format_func=lambda x: f"版本 {x+1}", key=f"select_{key}")
                        if new_idx != active_idx:
                            st.session_state[f"{key}_active_index"] = new_idx
                            st.rerun()

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
    if st.session_state.stage == "writing" and all(get_active_content(key) for key in ["title", "background", "invention", "implementation"]):
        st.header("Step 4️⃣: 预览与下载")
        st.markdown("---")
        
        title = get_active_content('title')
        
        # 构建附图章节
        drawings_text = ""
        drawings = get_active_content("drawings")
        if drawings:
            for i, drawing in enumerate(drawings):
                drawings_text += f"## 附图{i+1}：{drawing['title']}\n"
                drawings_text += f"```mermaid\n{drawing['code']}\n```\n\n"

        full_text = (
            f"# 一、发明名称\n{title}\n\n"
            f"# 二、现有技术（背景技术）\n{get_active_content('background')}\n\n"
            f"# 三、发明内容\n{get_active_content('invention')}\n\n"
            f"# 四、附图\n{drawings_text if drawings_text else '（本申请无附图）'}\n\n"
            f"# 五、具体实施方式\n{get_active_content('implementation')}"
        )
        st.subheader("完整草稿预览")
        st.markdown(full_text.replace('\n', '\n\n'))
        st.download_button("📄 下载完整草稿 (.md)", full_text, file_name=f"{title}_patent_draft.md")

if __name__ == "__main__":
    main()