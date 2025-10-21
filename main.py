import streamlit as st
import json
import time
from typing import Any

# --- 从模块导入 ---
import prompts
from config import UI_SECTION_ORDER, UI_SECTION_CONFIG
from llm_client import LLMClient
from state_manager import (
    initialize_session_state,
    get_active_content,
    is_stale,
)
from ui_components import (
    render_sidebar,
    render_mermaid_component,
    clean_mermaid_code,
)
from workflows import (
    generate_ui_section,
    generate_all_drawings,
    run_global_refinement,
)

# --- 重构辅助函数 ---

def add_new_version(key: str, content: Any):
    """
    为指定key添加一个新版本，更新状态并触发UI刷新。
    """
    # The content is the new version, typically a string or a list for drawings.
    st.session_state[f"{key}_versions"].append(content)

    # 更新激活版本的索引指向新创建的版本
    st.session_state[f"{key}_active_index"] = len(st.session_state[f"{key}_versions"]) - 1
    # 更新时间戳以进行依赖跟踪
    st.session_state.data_timestamps[key] = time.time()
    # 刷新UI以显示更新
    st.rerun()

# --- 阶段渲染函数 ---

def render_input_stage(llm_client: LLMClient):
    """渲染阶段一：输入核心技术构思"""
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

def render_review_brief_stage(llm_client: LLMClient):
    """渲染阶段二：审核并确认核心要素"""
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

def render_writing_stage(llm_client: LLMClient):
    """渲染阶段三：分步生成与撰写"""
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
                render_drawings_section(llm_client)
                continue

            render_standard_section(llm_client, key, versions)

def render_drawings_section(llm_client: LLMClient):
    """渲染'附图'专属UI和逻辑"""
    if not get_active_content("invention"):
        st.info("请先生成“发明内容”章节。")
        return

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
                col1.markdown(f"**附图 {i+1}: {drawing.get('title', '无标题')}**")
                if col2.button(f"🔄 重新生成此图", key=f"regen_drawing_{i}"):
                    with st.spinner(f"正在重新生成附图: {drawing.get('title', '无标题')}..."):
                        code_prompt = prompts.PROMPT_MERMAID_CODE.format(
                            title=drawing.get('title', ''),
                            description=drawing.get('description', ''),
                            invention_solution_detail=invention_solution_detail
                        )
                        new_code = llm_client.call([{"role": "user", "content": code_prompt}], json_mode=False)
                        
                        active_drawings = json.loads(json.dumps(get_active_content("drawings")))
                        active_drawings[i]["code"] = clean_mermaid_code(new_code)
                        add_new_version('drawings', active_drawings)

                st.markdown(f"**构思说明:** *{drawing.get('description', '无')}*")
                
                render_mermaid_component(f"mermaid_{i}", drawing)
                
                edited_code = st.text_area("编辑Mermaid代码:", value=drawing["code"], key=f"edit_code_{i}", height=150)
                if edited_code != drawing["code"]:
                    active_drawings = json.loads(json.dumps(get_active_content("drawings")))
                    active_drawings[i]["code"] = edited_code
                    add_new_version('drawings', active_drawings)

def render_standard_section(llm_client: LLMClient, key: str, versions: list):
    """渲染标准章节的UI和逻辑（非附图）"""
    config = UI_SECTION_CONFIG[key]
    label = config["label"]

    col1, col2 = st.columns([3, 1])
    with col1:
        deps_met = all(
            (st.session_state.get("structured_brief") if dep == "structured_brief" else get_active_content(dep))
            for dep in config["dependencies"]
        )
        if deps_met:
            if st.button(f"🔄 重新生成 {label}" if versions else f"✍️ 生成 {label}", key=f"btn_{key}"):
                with st.spinner(f"正在执行 {label} 的生成流程..."):
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
        active_content = get_active_content(key)

        with st.form(key=f'form_edit_{key}'):
            if key == 'title':
                edited_content = st.text_input("编辑区", value=active_content)
            else:
                edited_content = st.text_area("编辑区", value=active_content, height=300)
            
            submitted = st.form_submit_button("💾 保存修改 (快捷键: Ctrl+Enter)")

            if submitted and edited_content != active_content:
                add_new_version(key, edited_content)

def render_preview_stage(llm_client: LLMClient):
    """渲染阶段四：预览、精炼与下载"""
    if not all(get_active_content(key) for key in UI_SECTION_ORDER if key != 'drawings'):
        return
        
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

# --- 主应用逻辑 ---

def main():
    st.set_page_config(page_title="智能专利撰写助手", layout="wide", page_icon="📝")
    st.title("📝 智能专利申请书撰写助手")
    st.caption("新功能：支持全局回顾精炼。")

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

    # 使用分派字典来调用对应阶段的渲染函数
    stage_renderers = {
        "input": render_input_stage,
        "review_brief": render_review_brief_stage,
        "writing": render_writing_stage,
    }
    
    renderer = stage_renderers.get(st.session_state.stage)
    if renderer:
        renderer(llm_client)

    # 预览阶段是写作阶段的一部分，在写作阶段的末尾渲染
    if st.session_state.stage == "writing":
        render_preview_stage(llm_client)


if __name__ == "__main__":
    main()
