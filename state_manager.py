import streamlit as st
import time
from typing import Any, List, Dict
from config import UI_SECTION_CONFIG, WORKFLOW_CONFIG

def get_active_content(key: str) -> Any:
    """获取某个部分当前激活版本的内容。"""
    if f"{key}_versions" not in st.session_state or not st.session_state[f"{key}_versions"]:
        return None
    active_index = st.session_state.get(f"{key}_active_index", 0)
    version_data = st.session_state[f"{key}_versions"][active_index]

    # The complex dictionary wrapper for versions has been removed.
    # The version data is now the content itself (e.g., a string, or a list for drawings).
    return version_data

def is_stale(ui_key: str) -> bool:
    """检查某个UI章节是否因其依赖项更新而过时。"""
    timestamps = st.session_state.data_timestamps
    if ui_key not in timestamps:
        return False 
    
    section_time = timestamps[ui_key]
    for dep in UI_SECTION_CONFIG[ui_key]["dependencies"]:
        # 需要处理依赖项本身是复杂对象的情况
        dep_timestamp = timestamps.get(dep)
        if dep_timestamp and dep_timestamp > section_time:
            return True
    if 'structured_brief' in UI_SECTION_CONFIG[ui_key]['dependencies']:
        if 'structured_brief' in timestamps and timestamps['structured_brief'] > section_time:
            return True
    return False

def initialize_session_state():
    """初始化所有需要的会话状态变量。"""
    from config import load_config
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
