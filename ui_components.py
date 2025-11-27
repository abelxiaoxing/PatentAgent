import streamlit as st
import streamlit.components.v1 as components
import json
import time
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
            p_cfg["model"] = st.text_input("模型名称", value=p_cfg.get("model", ""), key="openai_model_name")
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

        # 1秒自动保存功能（内存中）
        if 'last_config_save_time' not in st.session_state:
            st.session_state.last_config_save_time = 0

        current_time = time.time()
        if current_time - st.session_state.last_config_save_time >= 1:
            # 自动保存到session_state中（内存中）
            st.session_state.config = config.copy()
            st.session_state.last_config_save_time = current_time

            # 更新LLM客户端配置
            if 'llm_client' in st.session_state:
                st.session_state.llm_client.update_config(config)

        if st.button("💾 永久保存配置", type="primary"):
            save_config(config)
            st.success("配置已永久保存到配置文件！")
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


def load_mermaid_script() -> str:
    """加载并缓存外部的Mermaid JS脚本文件内容。"""
    try:
        with open("mermaid_script.js", "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        # This will be visible in the browser's JS console
                return "console.error('FATAL: mermaid_script.js not found.');"

def render_mermaid_component(drawing_key: str, drawing: dict, height: int = 500):
    """
    使用统一的HTML组件渲染单个Mermaid图表。
    每个组件都在一个独立的iframe中加载自己的JS依赖项。
    """
    # 1. 加载自定义脚本内容
    mermaid_script_content = load_mermaid_script()

    # 2. 为每个组件准备完整的脚本集
    # 每次调用都必须包含这些脚本，因为每个组件都在一个独立的iframe中。
    script_tags = f"""
    <script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
    <script>{mermaid_script_content}</script>
    """

    # 3. 清理和准备数据
    code_to_render = clean_mermaid_code(drawing.get("code", "graph TD; A[无代码];"))
    safe_title = "".join(c for c in drawing.get('title', '') if c.isalnum() or c in (' ', '_')).rstrip()

    # 4. 将 Python 变量转换为 JSON 字符串以便安全嵌入
    code_json = json.dumps(code_to_render)
    safe_title_json = json.dumps(safe_title)
    drawing_key_json = json.dumps(drawing_key)

    # 5. 构建完整的 HTML 内容
    html_content = f"""
    {script_tags}
    <div style="position: relative; height: {height}px;">
        <div id="mermaid-container-{drawing_key}" style="height: 100%; overflow: auto; border: 1px solid #eee; padding: 10px; border-radius: 5px;">
            <div id="mermaid-error-{drawing_key}" style="color: red;"></div>
            <div id="mermaid-output-{drawing_key}" style="background-color: white; padding: 1rem; border-radius: 0.5rem;"></div>
        </div>
        <button id="download-btn-{drawing_key}" style="position: absolute; top: 15px; right: 15px; padding: 5px 10px; border-radius: 5px; border: 1px solid #ccc; cursor: pointer; z-index: 10;">📥 下载 PNG</button>
    </div>
    
    <script>
        // 使用 setTimeout 确保 Mermaid 库已初始化
        setTimeout(() => {{
            try {{
                if (window.renderMermaid) {{
                    window.renderMermaid({drawing_key_json}, {safe_title_json}, {code_json});
                }} else {{
                    const errorMsg = 'Mermaid render function (window.renderMermaid) not found.';
                    console.error(errorMsg);
                    const errorDiv = document.getElementById('mermaid-error-{drawing_key}');
                    if(errorDiv) {{
                        errorDiv.innerHTML = '<p>' + errorMsg + '</p>';
                    }}
                }}
            }} catch (e) {{
                const errorMsg = 'Error initializing Mermaid: ' + (e.message || e);
                console.error('Error initializing Mermaid render for key: ' + '{drawing_key}', e);
                const errorDiv = document.getElementById('mermaid-error-{drawing_key}');
                if(errorDiv) {{
                    errorDiv.innerHTML = '<p>' + errorMsg + '</p>';
                }}
            }}
        }}, 100);
    </script>
    """
    components.html(html_content, height=height, scrolling=True)

