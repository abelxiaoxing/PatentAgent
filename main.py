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
import base64
import streamlit.components.v1 as components

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

# --- Prompt 模板 ---
ROLE_INSTRUCTION = "你是一位资深的专利代理师，擅长撰写结构清晰、逻辑严谨的专利申请文件。你的回答必须严格遵循格式要求，直接输出内容，不包含任何解释性文字。"


# 0. 分析代理
PROMPT_ANALYZE = (
    f"{ROLE_INSTRUCTION}\n"
    "任务描述：请深入、细致地阅读并分析以下技术交底材料，将其拆解并提炼成一个结构化的、内容详实的JSON对象。\n"
    "**重要：请直接返回有效的JSON对象，不要包含任何解释性文字、前言或代码块标记。你的回答必须以 `{{\n` 开头，并以 `}}` 结尾。**\n"
    "JSON结构应包含以下字段：\n"
    "1. `background_technology`: 详细描述与本发明最相关的现有技术（Prior Art）。说明这些技术通常是如何工作的，以及它们的应用领域，为理解问题提供充分的背景。\n"
    "2. `problem_statement`: 基于上述背景技术，清晰、具体地阐述现有技术中存在的一个或多个关键问题、缺陷或技术痛点。请分析这些问题为何会成为障碍，例如导致效率低下、成本高昂、功能受限或用户体验不佳等。\n"
    "3. `core_inventive_concept`: 提炼出发明区别于现有技术的**本质性创新点**。这不仅仅是一个功能，而是一种新的技术思想、工作原理或系统架构。请用几句话解释这个核心思想是什么，以及它是如何从根本上解决上述问题的。\n"
    "4. `technical_solution_summary`: 概述为实现上述创新点所提出的完整技术方案。应描述该方案的**整体架构、主要工作流程或关键方法步骤**，清晰地展现各个部分是如何协同工作以实现发明目的的。\n"
    "5. `key_components_or_steps`: 以JSON对象列表的形式，列出实现技术方案所需的**所有关键物理组件或核心工艺步骤**。每个对象应包含`name`（组件/步骤名称）和`function`（该组件/步骤在本方案中的具体作用和目的）两个字段。示例：`[{{\"name\": \"组件A\", \"function\": \"负责接收原始信号并进行初步滤波。\"}}]`。\n"
    "6. `achieved_effects`: 与现有技术进行对比，详细列出本发明能够带来的**具体、可量化或可验证的有益效果**。例如：'处理速度提升30%'、'能耗降低50%'、'识别准确率从85%提高到98%'、'结构简化，减少了两个必要部件'等。避免空泛的描述。\n\n"
    "技术交底材料：\n{user_input}"
)
# 1. 发明名称代理
PROMPT_TITLE = (
    f"{ROLE_INSTRUCTION}\n"
    "请根据以下核心创新点与技术方案内容，生成3个不超过25字的中文发明名称建议。\n"
    "要求：\n"
    "1. 准确体现技术内容，突出创新点\n"
    "2. 命名风格需符合中国专利申请规范（避免口语化、广告词、过度抽象）\n"
    "**输出格式为JSON数组：例如 [\"名称一\", \"名称二\", \"名称三\"]，不得包含解释或注释。**\n\n"
    "核心创新点：{core_inventive_concept}\n"
    "技术方案概述：{technical_solution_summary}"
)


PROMPT_BACKGROUND_PROBLEM = (
    f"{ROLE_INSTRUCTION}\n"
    "任务：请根据以下技术问题概要，撰写一段逻辑严密、论证充分的“现有技术存在的问题”段落。\n"
    "要求：\n"
    "1. **问题深化**：清晰地指出当前技术存在的具体缺陷或不足。\n"
    "2. **原因分析**：深入分析导致这些缺陷产生的技术性或结构性根本原因。\n"
    "3. **影响阐述**：具体说明这些缺陷对设备性能、生产成本、用户体验或安全可靠性等方面造成的实际不良影响。\n"
    "4. **语言专业**：使用客观、严谨的技术术语，避免主观臆断和夸张修辞。\n"
    "**请直接输出段落内容，不要包含标题或任何说明文字。**\n\n"
    "技术问题概要：{problem_statement}"
)

PROMPT_BACKGROUND_CONTEXT = (
    f"{ROLE_INSTRUCTION}\n"
    "任务：请根据以下对现有技术的描述，撰写“2.1 对最接近的现有技术状况的分析说明”段落。\n"
    "要求：\n"
    "1. **客观描述**：首先客观、清晰地介绍与本发明最相关的一至两种主流现有技术方案、其基本工作原理和应用场景。\n"
    "2. **逻辑铺垫**：在描述的基础上，巧妙地引出或暗示这些现有技术方案在特定方面存在的固有局限性或技术瓶颈，为下一节“现有技术存在的问题”做好铺垫。\n"
    "**请直接输出段落内容，不包含标题或其他标识。**\n\n"
    "现有技术详细描述：\n{background_technology}\n"
    "现有技术存在的问题：\n{background_problem}"
)

PROMPT_INVENTION_PURPOSE = (
    f"{ROLE_INSTRUCTION}\n"
    "任务：请将以下“现有技术存在的问题”内容，改写为一段清晰、明确的“3.1 发明目的”段落。\n"
    "要求：\n"
    "1. **正向转换**：将对问题的批判性描述，转换为旨在解决这些问题的正面陈述。\n"
    "2. **严格对应**：确保提出的每一个发明目的都直接、精确地对应于“现有技术存在的问题”中指出的一个或多个具体缺陷。\n"
    "3. **标准句式**：以“鉴于现有技术存在的上述缺陷，本发明的目的在于提供一种...”或“为了解决现有技术中...的问题，本发明提供...”等标准句式开头。\n"
    "**请直接输出段落内容，不包含标题。**\n\n"
    "现有技术存在的问题：\n{background_problem}"
)

PROMPT_INVENTION_SOLUTION_POINTS = (
    f"{ROLE_INSTRUCTION}\n"
    "任务：请根据以下技术方案的核心组成及功能，提炼出3-5个最能体现本发明技术构思的核心技术特征要点。\n"
    "要求：\n"
    "1. **特征化描述**：每个要点应高度概括一项关键技术特征，清晰描述“什么组件/步骤”以及它“执行了什么关键功能”或“达到了什么技术目的”。\n"
    "2. **逻辑递进**：这些要点组合起来应能逻辑地呈现出整个技术方案的轮廓。\n"
    "3. **语言精炼**：语言专业、精炼，避免口语化表达。\n"
    "**输出格式为JSON数组，例如：[\"特征一：一种包含A模块的系统，所述A模块用于...\", \"特征二：一种方法，包括步骤B，所述步骤B用于...\"]，不得包含说明文字。**\n\n"
    "技术方案概述：{technical_solution_summary}\n"
    "关键组件/步骤及其功能清单：\n{key_components_or_steps}"
)

PROMPT_INVENTION_SOLUTION_DETAIL = (
    f"{ROLE_INSTRUCTION}\n"
    "任务：根据以下材料，撰写一段结构清晰、内容详尽、技术深度充足的“3.2 技术解决方案”段落。\n"
    "要求：\n"
    "1. **结构化叙述**：\n"
    "   a. **总体阐述**：首先用一两句话概括本发明的整体技术方案，点明其要解决的核心问题。\n"
    "   b. **分部详述**：逐一详细描述每个关键组件或步骤。不仅要说明“是什么”，更要深入解释“为什么”这样设计以及它“如何”与其他部分交互协同工作。\n"
    "   c. **总结升华**：最后总结这些组成部分如何共同作用，完整地实现了发明的总体目的。\n"
    "2. **深度与细节**：\n"
    "   a. **技术原理**：必须结合具体技术内容，引入并解释相关的物理原理、数学公式（使用LaTeX格式，如`$$F=ma$$`）或算法伪代码，以支撑技术方案的合理性。\n"
    "   b. **量化参数**：尽可能给出具体的、合理的参数范围、材料选型、信号特征或操作条件，使方案具体化，具备可实施性。\n"
    "3. **紧扣创新**：全文应围绕核心创新点展开，清晰地体现出本方案与现有技术的本质区别。\n"
    "**直接输出详细的“技术解决方案”段落内容，不要包含标题。**\n\n"
    "核心创新点：{core_inventive_concept}\n"
    "技术方案概述：{technical_solution_summary}\n"
    "关键组件/步骤及其功能清单：\n{key_components_or_steps}"
)

PROMPT_INVENTION_EFFECTS = (
    f"{ROLE_INSTRUCTION}\n"
    "任务：请撰写一段论证严谨、说服力强的“3.3 技术效果”段落。\n"
    "要求：\n"
    "1. **因果论证**：以分点形式列出有益效果。对于每一点，都必须遵循“声明效果 -> 关联特征 -> 对比现有技术”的逻辑。清晰阐述是**由于**本方案中的哪个/哪些技术特征，才带来了这项有益效果，并与现有技术进行对比，突出优势。\n"
    "2. **具体可信**：效果描述应尽可能具体、量化（引用`achieved_effects`中的数据），避免使用“更好”、“更快”等模糊词汇。\n"
    "3. **标准开头**：段落以“与现有技术相比，本发明由于采用了上述技术方案，至少具有以下一项或多项有益效果：”或类似表述开始。\n"
    "**请直接输出段落内容，不包含标题。**\n\n"
    "本发明的技术方案要点：\n{solution_points_str}\n"
    "本发明的有益效果概述：{achieved_effects}"
)


PROMPT_MERMAID_IDEAS = (
    f"{ROLE_INSTRUCTION}\n"
    "任务：基于以下“技术解决方案”，构思出最能清晰、准确地展示发明点的附图列表。\n"
    "要求：\n"
    "1. **识别核心**: 准确识别技术方案中的关键流程、核心组件、或创新结构。\n"
    "2. **多样化视角**: 提供至少2个、至多5个附图构思，应至少包含一个总体流程/结构图，以及若干个关键模块的细节图。\n"
    "3. **清晰描述**: 每个构思需包含一个简洁的`title`（如“系统总体架构图”）和一个`description`（说明该图旨在展示什么，帮助绘图AI理解意图）。\n"
    "**重要：直接返回一个包含构思对象的JSON数组。示例：`[{{\"title\": \"构思一标题\", \"description\": \"构思一描述\"}}]`**\n\n"
    "技术解决方案详细描述：\n{invention_solution_detail}"
)

PROMPT_MERMAID_CODE = (
    f"{ROLE_INSTRUCTION}\n"
    "任务：根据“技术解决方案”的完整描述和指定的“附图构思”，生成一份符合 Mermaid 语法规范的流程图代码。\n"
    "\n"
    "【输出要求】\n"
    "1. **准确表达技术内容**：图结构必须准确反映附图构思中的功能流程或结构关系。\n"
    "2. **选择合适的图类型**：根据内容选择最合适的 Mermaid 图类型，例如 `graph TD`, `flowchart TD`, `sequenceDiagram`, `classDiagram`, `stateDiagram` 等。\n"
    "3. **严格 Mermaid 语法规范，避免一切语法错误**，特别注意以下禁止事项：\n"
    "   - **禁止公式**：不得使用 `$...$`、`\\frac`、`\\sum`、上标、下标、希腊字母等任何数学表达式；请以通俗文字表达；\n"
    "   - **禁止注释**：不得在任何图中插入注释（如 `// 注释`、`# 注释`、`% 注释` 等），也不得夹在图结构行末；\n"
    "   - **禁止节点中嵌套 `[]` 或引号**：所有节点标签必须使用英文双引号包裹，内部不能再使用中括号；\n"
    "   - **禁止节点内公式、代码、特殊字符**：不使用 `*`, `{}`, `[]`, `< >` 中的嵌套结构，内容尽量简单明了；\n"
    "4. **节点标签换行规范**：\n"
    "   - 若需换行，使用 `<br>` 标签（仅在标签中使用）；\n"
    "   - 节点格式统一为 A[\"内容\"]；始终使用双引号包裹内容；\n"
    "5. **输出格式严格要求**：\n"
    "   - 仅返回 Mermaid 图代码正文；\n"
    "   - 不得包含 Markdown 代码块标记（如 ```mermaid）；\n"
    "   - 不添加任何非 Mermaid 内容或额外解释说明。\n"
    "\n"
    "附图构思标题：{title}\n"
    "附图构思描述：{description}\n\n"
    "技术解决方案全文参考：\n{invention_solution_detail}"
)


PROMPT_IMPLEMENTATION_POINT = (
    f"{ROLE_INSTRUCTION}\n"
    "任务：你正在撰写“五、具体实施方式”章节。请针对以下这一个技术要点，提供一个详细、可操作的具体实现方式描述。\n"
    "要求：描述应具体化，可包括但不限于：具体参数、组件选型、操作流程、工作原理等，使本领域技术人员能够照此实施。\n"
    "**直接输出针对该要点的具体实施描述段落，不要包含标题或编号。**\n\n"
    "当前要详细阐述的技术要点：\n{point}"
)

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
    "title_options": {"prompt": PROMPT_TITLE, "json_mode": True, "dependencies": ["core_inventive_concept", "technical_solution_summary"]},
    "background_problem": {"prompt": PROMPT_BACKGROUND_PROBLEM, "json_mode": False, "dependencies": ["problem_statement"]},
    "background_context": {"prompt": PROMPT_BACKGROUND_CONTEXT, "json_mode": False, "dependencies": ["background_problem"]},
    "invention_purpose": {"prompt": PROMPT_INVENTION_PURPOSE, "json_mode": False, "dependencies": ["background_problem"]},
    "solution_points": {"prompt": PROMPT_INVENTION_SOLUTION_POINTS, "json_mode": True, "dependencies": ["technical_solution_summary", "key_components_or_steps"]},
    "invention_solution_detail": {"prompt": PROMPT_INVENTION_SOLUTION_DETAIL, "json_mode": False, "dependencies": ["core_inventive_concept", "technical_solution_summary", "key_components_or_steps"]},
    "invention_effects": {"prompt": PROMPT_INVENTION_EFFECTS, "json_mode": False, "dependencies": ["solution_points", "achieved_effects"]},
    "implementation_details": {"prompt": PROMPT_IMPLEMENTATION_POINT, "json_mode": False, "dependencies": ["solution_points"]},
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
    if 'structured_brief' in UI_SECTION_CONFIG[ui_key]["dependencies"]:
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

def generate_all_drawings(llm_client: LLMClient, invention_solution_detail: str):
    """统一生成所有附图：先构思，然后为每个构思生成代码。"""
    if not invention_solution_detail:
        st.warning("无法生成附图，因为“技术解决方案”内容为空。")
        return

    # 1. Generate ideas
    ideas_prompt = PROMPT_MERMAID_IDEAS.format(invention_solution_detail=invention_solution_detail)
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
        
        code_prompt = PROMPT_MERMAID_CODE.format(
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
    if ui_key == "drawings": # Drawings section has its own logic
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
                prompt = PROMPT_ANALYZE.format(user_input=user_input)
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
            # Format list of dicts into a display string
            key_steps_str = "\n".join([f"{item.get('name', '')}: {item.get('function', '')}" for item in key_steps_list])
        elif isinstance(key_steps_list, list):
            # If it's already a list of strings (e.g., after an edit), just join
            key_steps_str = "\n".join(key_steps_list)
        else:
            # Fallback for other types
            key_steps_str = str(key_steps_list)

        edited_steps_str = st.text_area("关键组件/步骤清单", value=key_steps_str, on_change=update_brief_timestamp)
        # Always update the brief with the content from the text area, which is now a list of strings
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
                                            code_prompt = PROMPT_MERMAID_CODE.format(
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
                                
                                escaped_code = drawing["code"].replace("`", "\
")

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
                                                mermaid.initialize({{ startOnLoad: false, theme: 'base', themeVariables: {{ 'background': 'white' }} }});
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
                                                
                                                const svgData = new XMLSerializer().serializeToString(svgElement);
                                                const img = new Image();
                                                const canvas = document.createElement('canvas');
                                                const ctx = canvas.getContext('2d');

                                                img.onload = function() {{
                                                    const scale = 2;
                                                    const rect = svgElement.getBoundingClientRect();
                                                    canvas.width = rect.width * scale;
                                                    canvas.height = rect.height * scale;
                                                    ctx.fillStyle = 'white';
                                                    ctx.fillRect(0, 0, canvas.width, canvas.height);
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