import os
from pathlib import Path
from dotenv import find_dotenv, set_key, load_dotenv
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
            "model": os.getenv("GOOGLE_MODEL", "gemini-1.5-flash"),
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
        "workflow_keys": [],
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
