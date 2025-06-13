import streamlit as st
import openai
import httpx
import tomllib
import os
from pathlib import Path
from typing import List, Dict
from google import genai
from dotenv import load_dotenv, find_dotenv, set_key

# 加载 .env 文件中的环境变量
env_file = find_dotenv()
load_dotenv(env_file)

# --- 配置管理 ---
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
            "model": os.getenv("GOOGLE_MODEL", "gemini-2.5-flash-preview-04-17"),
        },
    }

def save_config(cfg: dict):
    """将配置保存到 .env 文件。"""
    global env_file
    if not env_file:
        env_file = Path(".env")
        env_file.touch() # 确保文件存在

    # 将配置字典中的值逐一写入 .env 文件
    set_key(env_file, "PROVIDER", cfg.get("provider", "openai"))
    set_key(env_file, "PROXY_URL", cfg.get("proxy_url", ""))
    
    if "openai" in cfg:
        set_key(env_file, "OPENAI_API_KEY", cfg["openai"].get("api_key", ""))
        set_key(env_file, "OPENAI_API_BASE", cfg["openai"].get("api_base", ""))
        set_key(env_file, "OPENAI_MODEL", cfg["openai"].get("model", ""))

    if "google" in cfg:
        set_key(env_file, "GOOGLE_API_KEY", cfg["google"].get("api_key", ""))
        set_key(env_file, "GOOGLE_MODEL", cfg["google"].get("model", ""))

# --- API 客户端 ---
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

    def call(self, messages: List[Dict], **kwargs) -> str:
        """根据提供商调用相应的LLM API。"""
        if self.provider == "google":
            prompt = messages[0]["content"]
            response = self.client.models.generate_content(model=self.model, contents=prompt)
            return response.text
        else:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                **kwargs
            )
            return response.choices[0].message.content

# --- Prompt 模板 ---
ROLE_INSTRUCTION = "你是一位资深的专利代理师，擅长撰写结构清晰、逻辑严谨的专利申请文件。"

# 1. 发明名称
PROMPT_TITLE = (
    f"{ROLE_INSTRUCTION}\n任务描述：请根据以下核心技术构思，提炼出符合中国专利命名规范且不超过25个汉字的发明名称，要求简洁明了并准确反映技术内容。请只返回发明名称本身，不要添加编号、标点或其他多余文字。\n\n核心技术构思：\n{{user_input}}"
)

# 2. 现有技术（背景技术）章节
PROMPT_BACKGROUND = (
    f"{ROLE_INSTRUCTION}\n任务描述：请撰写“二、现有技术（背景技术）”章节内容，包含：\n2.1 对最接近发明的同类现有技术状况加以分析说明（包括构造、各部件间的位置和连接关系、工艺过程等）；\n2.2 实事求是地指出现有技术存在的问题并分析原因。\n请使用专业、客观的中文，并以 Markdown 格式返回。\n\n发明名称：{{title}}\n核心技术构思：\n{{user_input}}"
)

# 3. 发明内容章节
PROMPT_INVENTION_CONTENT = (
    f"{ROLE_INSTRUCTION}\n任务描述：请依据以下信息撰写“三、发明内容”章节，其中包括：\n3.1 发明目的（对应2.2中的问题）；\n3.2 技术解决方案（清楚、完整、准确地描述本发明的方案并突出区别于现有技术的发明点）；\n3.3 技术效果（与3.1与3.2对应，具体、实事求是地描述本发明可达到的效果，最好给出数据）。\n请使用专业、严谨的中文，并以 Markdown 格式返回。\n\n发明名称：{{title}}\n背景技术：\n{{background}}\n核心技术构思：\n{{user_input}}"
)

# 4. 具体实施方式章节
PROMPT_IMPLEMENTATION = (
    f"{ROLE_INSTRUCTION}\n任务描述：请结合以下信息撰写“四、具体实施方式”章节，至少举出一个明确且可操作的具体实施例，必要时结合附图说明，并解释出现的英文缩写或特殊代号。请以 Markdown 格式返回。\n\n发明名称：{{title}}\n发明内容：\n{{invention_content}}\n核心技术构思：\n{{user_input}}"
)

# --- Streamlit 应用界面 ---
def render_sidebar(config: dict):
    """渲染侧边栏并返回更新后的配置字典。"""
    with st.sidebar:
        st.header("⚙️ API 配置")
        provider_map = {"OpenAI兼容": "openai", "Google": "google"}
        provider_display = "Google" if config.get("provider") == "google" else "OpenAI兼容"
        
        selected_provider = st.radio(
            "模型提供商", options=["OpenAI兼容", "Google"], 
            index=list(provider_map.keys()).index(provider_display),
            horizontal=True
        )

        config["provider"] = provider_map[selected_provider]

        p_cfg = config[config["provider"]]
        p_cfg["api_key"] = st.text_input("API Key", value=p_cfg.get("api_key", ""), type="password")

        if config["provider"] == "openai":
            p_cfg["api_base"] = st.text_input("API 基础地址", value=p_cfg.get("api_base", ""))
            p_cfg["model"] = st.text_input("模型名称", value=p_cfg.get("model", ""))
        else:
            p_cfg["model"] = st.text_input("模型名称", value=p_cfg.get("model", "gemini-2.5-flash-preview-04-17"))

        # 代理配置对所有提供商都可用
        config["proxy_url"] = st.text_input(
            "代理 URL (可选)", 
            value=config.get("proxy_url", ""), 
            placeholder="http://127.0.0.1:7890",
            help="为所有API请求设置代理。"
        )

        if st.button("保存配置"):
            save_config(config)
            st.success("配置已保存！")

def main():
    st.set_page_config(page_title="专利撰写助手", layout="wide", page_icon="📝")
    st.title("📝 发明专利申请书撰写助手")

    # 初始化配置与会话状态
    if "config" not in st.session_state:
        st.session_state.config = load_config()

    # 初始化流程相关的 session_state 变量
    required_session_keys = [
        "stage",         # 当前阶段
        "user_input",    # 核心技术构思
        "title",         # 发明名称
        "background",    # 背景技术
        "invention",     # 发明内容
        "implementation" # 具体实施方式
    ]
    for k in required_session_keys:
        if k not in st.session_state:
            st.session_state[k] = ""
    if not st.session_state.stage:
        st.session_state.stage = "input"

    # 侧边栏渲染
    render_sidebar(st.session_state.config)

    active_provider = st.session_state.config["provider"]
    if not st.session_state.config[active_provider].get("api_key"):
        st.warning("请在左侧边栏配置并保存您的 API Key。")
        st.stop()

    llm_client = LLMClient(st.session_state.config)

    # ----------------------------- 阶段一：输入核心构思 -----------------------------
    if st.session_state.stage == "input":
        user_input = st.text_area("请输入核心技术构思、发明点、项目介绍等：", height=300, key="user_input_area")
        if st.button("🎯 生成发明名称", type="primary") and user_input:
            # 调用 LLM 生成发明名称
            messages = [{"role": "user", "content": PROMPT_TITLE.format(user_input=user_input)}]
            with st.spinner("正在生成发明名称..."):
                title = llm_client.call(messages).strip()
            st.session_state.user_input = user_input
            st.session_state.title = title
            st.session_state.stage = "title"
            st.rerun()

    # ----------------------------- 阶段二：编辑/确认发明名称 -----------------------------
    if st.session_state.stage == "title":
        st.subheader("Step 2️⃣  请确认或修改发明名称：")
        edited_title = st.text_input("发明名称（≤25字）：", value=st.session_state.title, max_chars=25)
        col1, col2 = st.columns(2)
        if col1.button("✅ 确认并生成背景技术", type="primary"):
            st.session_state.title = edited_title
            # 生成背景技术
            messages = [{"role": "user", "content": PROMPT_BACKGROUND.format(title=edited_title, user_input=st.session_state.user_input)}]
            with st.spinner("正在生成背景技术章节..."):
                background = llm_client.call(messages)
            st.session_state.background = background
            st.session_state.stage = "background"
            st.rerun()
        if col2.button("返回上一步"):
            st.session_state.stage = "input"
            st.rerun()

    # ----------------------------- 阶段三：背景技术编辑/确认 -----------------------------
    if st.session_state.stage == "background":
        st.subheader("Step 3️⃣  请审阅并修改背景技术章节：")
        edited_background = st.text_area("二、现有技术（背景技术）：", value=st.session_state.background, height=500)
        col1, col2 = st.columns(2)
        if col1.button("✅ 确认并生成发明内容", type="primary"):
            st.session_state.background = edited_background
            # 生成发明内容
            messages = [{"role": "user", "content": PROMPT_INVENTION_CONTENT.format(title=st.session_state.title, background=edited_background, user_input=st.session_state.user_input)}]
            with st.spinner("正在生成发明内容章节..."):
                invention_content = llm_client.call(messages)
            st.session_state.invention = invention_content
            st.session_state.stage = "invention"
            st.rerun()
        if col2.button("返回上一步"):
            st.session_state.stage = "title"
            st.rerun()

    # ----------------------------- 阶段四：发明内容编辑/确认 -----------------------------
    if st.session_state.stage == "invention":
        st.subheader("Step 4️⃣  请审阅并修改发明内容章节：")
        edited_invention = st.text_area("三、发明内容：", value=st.session_state.invention, height=600)
        col1, col2 = st.columns(2)
        if col1.button("✅ 确认并生成具体实施方式", type="primary"):
            st.session_state.invention = edited_invention
            # 生成具体实施方式
            messages = [{"role": "user", "content": PROMPT_IMPLEMENTATION.format(title=st.session_state.title, invention_content=edited_invention, user_input=st.session_state.user_input)}]
            with st.spinner("正在生成具体实施方式章节..."):
                implementation = llm_client.call(messages)
            st.session_state.implementation = implementation
            st.session_state.stage = "implementation"
            st.rerun()
        if col2.button("返回上一步"):
            st.session_state.stage = "background"
            st.rerun()

    # ----------------------------- 阶段五：具体实施方式编辑/下载 -----------------------------
    if st.session_state.stage == "implementation":
        st.subheader("Step 5️⃣  请审阅并修改具体实施方式章节：")
        edited_implementation = st.text_area("四、具体实施方式：", value=st.session_state.implementation, height=700)
        col1, col2 = st.columns(2)
        if col1.button("返回上一步"):
            st.session_state.stage = "invention"
            st.session_state.implementation = edited_implementation
            st.rerun()

        # 汇总全文
        full_text = (
            f"# 一、发明名称\n{st.session_state.title}\n\n" +
            f"## 二、现有技术（背景技术）\n{st.session_state.background}\n\n" +
            f"## 三、发明内容\n{st.session_state.invention}\n\n" +
            f"## 四、具体实施方式\n{edited_implementation}"
        )
        st.session_state.implementation = edited_implementation
        if full_text:
            col2.download_button("📄 下载完整草稿", full_text, file_name="patent_draft.md")

if __name__ == "__main__":
    main()
