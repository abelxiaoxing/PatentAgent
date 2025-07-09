import streamlit as st
import json
import time
from typing import List, Dict, Any
import prompts
from llm_client import LLMClient
from state_manager import get_active_content
from config import UI_SECTION_CONFIG, WORKFLOW_CONFIG, UI_SECTION_ORDER
from ui_components import clean_mermaid_code

def generate_all_drawings(llm_client: LLMClient, invention_solution_detail: str):
    """统一生成所有附图：先构思，然后为每个构思生成代码。"""
    if not invention_solution_detail:
        st.warning("无法生成附图，因为“发明内容”>“技术解决方案”内容为空。")
        return

    with st.spinner("正在为附图构思..."):
        ideas_prompt = prompts.PROMPT_MERMAID_IDEAS.format(invention_solution_detail=invention_solution_detail)
        ideas_response_str = llm_client.call([{"role": "user", "content": ideas_prompt}], json_mode=True)
        try:
            ideas = json.loads(ideas_response_str.strip())
        except json.JSONDecodeError:
            st.error(f"附图构思返回格式错误，期望列表但得到: {ideas_response_str}")
            return
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
            original_generation_prompt = "\n---\n".join(original_prompts)
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
