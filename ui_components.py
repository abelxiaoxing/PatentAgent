import streamlit as st
import streamlit.components.v1 as components
import json
from config import save_config

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

@st.cache_data
def load_mermaid_script():
    """加载并缓存Mermaid JS脚本文件。"""
    try:
        with open("mermaid_script.js", "r") as f:
            return f.read()
    except FileNotFoundError:
        st.error("错误：mermaid_script.js 文件未找到。")
        return ""

def render_mermaid_component(drawing_key: str, drawing: dict, height: int = 500):
    """
    渲染单个Mermaid图表组件。
    - 使用st.cache_data缓存外部JS文件内容。
    - 将Mermaid代码和元数据安全地嵌入HTML。
    - 确保Mermaid初始化和渲染在正确的时间执行。
    - 设置了固定的高度并允许滚动。
    """
    mermaid_script_content = load_mermaid_script()
    if not mermaid_script_content:
        st.error("Mermaid脚本未能加载，无法渲染附图。")
        return

    # 清理和准备数据
    code_to_render = clean_mermaid_code(drawing.get("code", "graph TD; A[无代码];"))
    safe_title = "".join(c for c in drawing.get('title', '') if c.isalnum() or c in (' ', '_')).rstrip()

    # 将Python变量安全地转换为JSON字符串，以便在JS中使用
    code_json = json.dumps(code_to_render)
    safe_title_json = json.dumps(safe_title)
    drawing_key_json = json.dumps(drawing_key)

    # 构建HTML组件
    # - 外部JS文件只注入一次。
    # - Mermaid库只加载一次。
    # - 每次组件重绘时，通过内联脚本调用渲染函数。
    html_content = f"""
    <div id="mermaid-container-{drawing_key}" style="height: {height-50}px; overflow: auto; border: 1px solid #eee; padding: 10px; border-radius: 5px;">
        <div id="mermaid-output-{drawing_key}" style="background-color: white; padding: 1rem; border-radius: 0.5rem;"></div>
    </div>
    <button id="download-btn-{drawing_key}" style="margin-top: 10px; padding: 5px 10px; border-radius: 5px; border: 1px solid #ccc; cursor: pointer;">📥 下载 PNG</button>

    <script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
    <script>
        // 确保Mermaid已初始化
        if (typeof mermaid !== 'undefined') {{
            mermaid.initialize({{ startOnLoad: false, theme: 'neutral' }});
        }}
        
        // 注入外部JS文件的功能
        {mermaid_script_content}
    </script>
    <script>
        // 使用try-catch确保即使一个图表失败，其他图表也能继续渲染
        try {{
            const code = {code_json};
            const safeTitle = {safe_title_json};
            const drawingKey = {drawing_key_json};

            // 延迟调用以确保DOM元素已准备好
            setTimeout(() => {{
                if (window.renderMermaid) {{
                    window.renderMermaid(drawingKey, safeTitle, code);
                }} else {{
                    console.error('renderMermaid function not found.');
                }}
            }}, 100);
        }} catch (e) {{
            console.error('Failed to parse mermaid diagram for key {drawing_key}:', e);
            const outputDiv = document.getElementById('mermaid-output-{drawing_key}');
            if(outputDiv) {{
                outputDiv.innerHTML = '<p style="color:red;">Failed to parse drawing data. See browser console for details.</p>';
            }}
        }}
    </script>
    """
    components.html(html_content, height=height, scrolling=True)
