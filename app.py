"""Streamlit interface for CivicOps AI."""

from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta

import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from pydantic import ValidationError

from ai_service import (
    AIServiceError,
    DEFAULT_MODEL,
    PRIORITY_VALUES,
    RISK_VALUES,
    STATUS_VALUES,
    EventBrief,
    OperationsPlan,
    ProgressReview,
    calculate_metrics,
    dashboard_rows_to_tasks,
    generate_demo_plan,
    generate_demo_progress_review,
    generate_operations_plan,
    get_model_name,
    has_api_key,
    review_current_progress,
    summarise_downstream_impacts,
    tasks_to_dashboard_rows,
)
from sample_data import SAMPLE_EVENT


load_dotenv()

st.set_page_config(
    page_title="CivicOps AI",
    page_icon="🏛️",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    :root { --civic-blue: #123b5d; --civic-green: #14866d; --warm: #f5f7f8; }
    .stApp { background: linear-gradient(180deg, #f7fafb 0%, #ffffff 28%); }
    .block-container { max-width: 1450px; padding-top: 1.7rem; padding-bottom: 4rem; }
    h1, h2, h3 { color: var(--civic-blue); letter-spacing: -0.02em; }
    .hero {
        padding: 1.8rem 2rem; border-radius: 18px;
        background: linear-gradient(120deg, #123b5d 0%, #176a72 100%);
        color: white; margin-bottom: 1.1rem; box-shadow: 0 12px 35px rgba(18,59,93,.14);
    }
    .hero h1 { color: white; margin: 0 0 .35rem 0; font-size: 2.35rem; }
    .hero p { margin: 0; opacity: .9; font-size: 1.05rem; }
    .mode-card {
        border: 1px solid #d8e3e8; border-left: 5px solid #14866d;
        padding: .8rem 1rem; border-radius: 10px; background: white; margin-bottom: 1rem;
    }
    div[data-testid="stMetric"] {
        background: white; border: 1px solid #e1e8eb; padding: .9rem 1rem;
        border-radius: 12px; box-shadow: 0 4px 14px rgba(18,59,93,.05);
    }
    div[data-testid="stForm"] { background: white; border-radius: 14px; padding: 1rem; }
    .section-note { color: #526875; margin-top: -.4rem; margin-bottom: 1rem; }
    .risk-pill { display: inline-block; padding: .2rem .65rem; border-radius: 999px;
        background: #fff1e6; color: #9a4317; font-weight: 650; }
    .small-muted { color: #60727d; font-size: .9rem; }
    </style>
    """,
    unsafe_allow_html=True,
)


def initialise_state() -> None:
    defaults: dict[str, object] = {
        "organisation_type": "Volunteer organisation",
        "event_name": "",
        "event_objective": "",
        "event_date": date.today() + timedelta(days=90),
        "venue": "",
        "expected_participants": 50,
        "available_budget": 2_000.0,
        "committee_size": 10,
        "constraints_and_special_requirements": "",
        "operations_plan": None,
        "plan_source": None,
        "progress_review": None,
        "review_source": None,
        "task_signature": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def load_sample() -> None:
    for key, value in SAMPLE_EVENT.items():
        st.session_state[key] = value
    for key in (
        "operations_plan",
        "plan_source",
        "progress_review",
        "review_source",
        "task_signature",
    ):
        st.session_state[key] = None
    st.session_state.pop("task_editor", None)


def format_validation_error(exc: ValidationError) -> str:
    messages = []
    for error in exc.errors():
        field = str(error["loc"][-1]).replace("_", " ").capitalize()
        messages.append(f"{field}: {error['msg']}")
    return " Please correct the following: " + " ".join(messages)


def sanitised_review_error_message(
    error: Exception, *, fallback_failed: bool = False
) -> str:
    """Return a stable user message without exposing exception internals."""

    if fallback_failed:
        if isinstance(error, ValidationError):
            return (
                "The local progress review could not be validated. No review was "
                "displayed; please check the task data and try again."
            )
        return (
            "The progress review could not be completed safely. No internal details "
            "were displayed; please try again."
        )
    if isinstance(error, ValidationError):
        return (
            "The AI progress review did not meet the required data format. A validated "
            "local review is shown instead."
        )
    return (
        "The AI progress review could not be completed. A validated local review is "
        "shown instead."
    )


def render_sidebar() -> None:
    api_enabled = has_api_key()
    with st.sidebar:
        st.markdown("### CivicOps AI")
        if api_enabled:
            st.success("AI Mode")
            st.caption(f"Responses API model: `{get_model_name()}`")
        else:
            st.warning("Demo Mode")
            st.caption(
                "No API key detected. Plans and reviews use the deterministic local "
                "workflow; no network request is made."
            )
        st.divider()
        st.markdown("**Workflow**")
        st.caption("1. Complete or load the event brief")
        st.caption("2. Generate a validated operations plan")
        st.caption("3. Edit owners, deadlines, status, and risk")
        st.caption("4. Review progress and export")
        st.divider()
        st.caption(
            "API keys are read only from `OPENAI_API_KEY`. They are never displayed "
            "or stored by this app."
        )


def render_event_form() -> None:
    st.markdown("## 1. Event brief")
    st.markdown(
        '<p class="section-note">Give the copilot enough operational context to build an accountable plan.</p>',
        unsafe_allow_html=True,
    )
    if st.button("Load Bacang Youth sample demo", icon="🧭", width="content"):
        load_sample()
        st.rerun()

    with st.form("event_brief_form", border=True):
        col1, col2 = st.columns(2, gap="large")
        with col1:
            st.text_input("Organisation type", key="organisation_type")
            st.text_input("Event name", key="event_name")
            st.text_area("Event objective", key="event_objective", height=115)
            st.date_input(
                "Event date",
                key="event_date",
                min_value=date.today(),
                format="DD/MM/YYYY",
            )
            st.text_input("Venue", key="venue")
        with col2:
            st.number_input(
                "Expected participants",
                min_value=1,
                max_value=100_000,
                step=1,
                key="expected_participants",
            )
            st.number_input(
                "Available budget (RM)",
                min_value=0.0,
                max_value=1_000_000_000.0,
                step=100.0,
                format="%.2f",
                key="available_budget",
            )
            st.number_input(
                "Committee size",
                min_value=1,
                max_value=1_000,
                step=1,
                key="committee_size",
            )
            st.text_area(
                "Constraints and special requirements",
                key="constraints_and_special_requirements",
                height=175,
                help="Include programme components, accessibility, safety, food, transport, venue, or policy constraints.",
            )
        submitted = st.form_submit_button(
            "Generate operations plan", type="primary", width="stretch"
        )

    if not submitted:
        return

    try:
        brief = EventBrief(
            organisation_type=st.session_state.organisation_type,
            event_name=st.session_state.event_name,
            event_objective=st.session_state.event_objective,
            event_date=st.session_state.event_date,
            venue=st.session_state.venue,
            expected_participants=st.session_state.expected_participants,
            available_budget=st.session_state.available_budget,
            committee_size=st.session_state.committee_size,
            constraints_and_special_requirements=st.session_state.constraints_and_special_requirements,
        )
    except ValidationError as exc:
        st.error(format_validation_error(exc), icon="⚠️")
        return

    if has_api_key():
        with st.spinner(f"Building a validated plan with {get_model_name()}…"):
            try:
                plan = generate_operations_plan(brief)
                source = f"OpenAI Responses API · {get_model_name()}"
                st.success("AI operations plan generated and schema-validated.")
            except AIServiceError as exc:
                st.error(str(exc), icon="⚠️")
                st.warning(
                    "A deterministic plan has been loaded so the dashboard remains usable."
                )
                plan = generate_demo_plan(brief)
                source = "Demo fallback after API error"
    else:
        plan = generate_demo_plan(brief)
        source = "Deterministic Demo Mode"
        st.success("Demo operations plan generated locally.")

    st.session_state.operations_plan = plan
    st.session_state.plan_source = source
    st.session_state.progress_review = None
    st.session_state.review_source = None
    st.session_state.task_signature = None
    st.session_state.pop("task_editor", None)


def render_committee(plan: OperationsPlan) -> None:
    with st.expander("Recommended committee structure", expanded=True):
        columns = st.columns(3)
        for index, role in enumerate(plan.recommended_committee_structure):
            with columns[index % 3]:
                st.markdown(f"**{role.role}** · {role.suggested_people} person(s)")
                st.caption(role.purpose)


def task_signature(plan: OperationsPlan) -> str:
    payload = json.dumps(
        [task.model_dump(mode="json") for task in plan.actionable_tasks],
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def render_metrics(plan: OperationsPlan) -> None:
    metrics = calculate_metrics(plan.actionable_tasks)
    metric_columns = st.columns(5)
    values = [
        ("Total tasks", metrics["total_tasks"]),
        ("Completed", metrics["completed_tasks"]),
        ("Blocked", metrics["blocked_tasks"]),
        ("High / critical risk", metrics["high_risk_tasks"]),
        ("Completion", f"{metrics['completion_percentage']:.0f}%"),
    ]
    for column, (label, value) in zip(metric_columns, values):
        column.metric(label, value)


def render_dashboard(plan: OperationsPlan) -> OperationsPlan:
    st.markdown("## 3. Operations dashboard")
    st.markdown(
        '<p class="section-note">Edit the working plan directly. Use semicolons to separate multiple dependencies.</p>',
        unsafe_allow_html=True,
    )
    metrics_slot = st.container()

    task_frame = pd.DataFrame(tasks_to_dashboard_rows(plan.actionable_tasks))
    edited_frame = st.data_editor(
        task_frame,
        key="task_editor",
        hide_index=True,
        width="stretch",
        height=570,
        column_order=[
            "task",
            "PIC",
            "deadline",
            "status",
            "priority",
            "risk",
            "dependency",
        ],
        column_config={
            "task": st.column_config.TextColumn("Task", width="medium", required=True),
            "PIC": st.column_config.TextColumn(
                "PIC", width="medium", help="Leave blank to flag an ownership gap."
            ),
            "deadline": st.column_config.DateColumn(
                "Deadline", format="DD/MM/YYYY", required=True, width="small"
            ),
            "status": st.column_config.SelectboxColumn(
                "Status", options=list(STATUS_VALUES), required=True, width="medium"
            ),
            "priority": st.column_config.SelectboxColumn(
                "Priority", options=list(PRIORITY_VALUES), required=True, width="small"
            ),
            "risk": st.column_config.SelectboxColumn(
                "Risk", options=list(RISK_VALUES), required=True, width="small"
            ),
            "dependency": st.column_config.TextColumn(
                "Dependency", width="medium"
            ),
        },
        disabled=[],
    )
    try:
        edited_tasks = dashboard_rows_to_tasks(edited_frame.to_dict(orient="records"))
        updated_plan = plan.model_copy(update={"actionable_tasks": edited_tasks})
        st.session_state.operations_plan = updated_plan
    except ValidationError as exc:
        st.error("One or more task edits are invalid." + format_validation_error(exc))
        updated_plan = plan

    with metrics_slot:
        render_metrics(updated_plan)

    current_signature = task_signature(updated_plan)
    previous_signature = st.session_state.task_signature
    if previous_signature is not None and current_signature != previous_signature:
        st.session_state.progress_review = None
        st.session_state.review_source = None
    st.session_state.task_signature = current_signature
    return updated_plan


def render_review(plan: OperationsPlan) -> None:
    st.markdown("## 4. AI progress review")
    st.markdown(
        '<p class="section-note">The review uses the current edited dashboard, not the original generated task state.</p>',
        unsafe_allow_html=True,
    )
    if st.button("Review Current Progress", type="primary", icon="🔎"):
        review: ProgressReview | None = None
        source: str | None = None
        try:
            if has_api_key():
                with st.spinner(f"Reviewing current progress with {get_model_name()}…"):
                    try:
                        review = review_current_progress(
                            plan.event_brief, plan.actionable_tasks
                        )
                        source = f"OpenAI Responses API · {get_model_name()}"
                        st.success("Current progress reviewed and schema-validated.")
                    except ValidationError as exc:
                        st.error(sanitised_review_error_message(exc), icon="⚠️")
                        st.warning(
                            "A deterministic progress review is shown so the workflow can continue."
                        )
                        review = generate_demo_progress_review(
                            plan.event_brief, plan.actionable_tasks
                        )
                        source = "Demo fallback after API validation error"
                    except AIServiceError as exc:
                        st.error(sanitised_review_error_message(exc), icon="⚠️")
                        st.warning(
                            "A deterministic progress review is shown so the workflow can continue."
                        )
                        review = generate_demo_progress_review(
                            plan.event_brief, plan.actionable_tasks
                        )
                        source = "Demo fallback after API error"
                    except Exception as exc:
                        st.error(sanitised_review_error_message(exc), icon="⚠️")
                        st.warning(
                            "A deterministic progress review is shown so the workflow can continue."
                        )
                        review = generate_demo_progress_review(
                            plan.event_brief, plan.actionable_tasks
                        )
                        source = "Demo fallback after unexpected review error"
            else:
                review = generate_demo_progress_review(
                    plan.event_brief, plan.actionable_tasks
                )
                source = "Deterministic Demo Mode"
                st.success("Progress reviewed locally in Demo Mode.")
        except ValidationError as exc:
            st.error(
                sanitised_review_error_message(exc, fallback_failed=True),
                icon="⚠️",
            )
        except Exception as exc:
            st.error(
                sanitised_review_error_message(exc, fallback_failed=True),
                icon="⚠️",
            )

        st.session_state.progress_review = review
        st.session_state.review_source = source

    review = st.session_state.progress_review
    if review is None:
        st.info("Edit the dashboard as needed, then request a progress review.")
        return

    st.caption(f"Review source: {st.session_state.review_source}")
    st.markdown("### Executive summary")
    st.info(review.executive_summary)

    st.markdown("### Three most urgent actions")
    if review.three_most_urgent_actions:
        for index, action in enumerate(review.three_most_urgent_actions, start=1):
            with st.container(border=True):
                st.markdown(
                    f"**{index}. {action.task}** · Urgency score `{action.urgency_score}`"
                )
                st.write(action.recommended_action)
                st.caption(
                    f"PIC: {action.pic} · Deadline: {action.deadline.strftime('%d/%m/%Y')}"
                )
                st.markdown(f"**Why urgent:** {action.why_urgent}")
                if action.active_blocking_prerequisites:
                    st.warning(
                        "Active prerequisite blocker(s): "
                        + "; ".join(action.active_blocking_prerequisites)
                    )
                    st.markdown(
                        f"**Work that can proceed:** {action.work_that_can_proceed}"
                    )
                    st.markdown(
                        f"**Work that must wait:** {action.work_that_must_wait}"
                    )
                    st.markdown(
                        "**Preparation to reduce delay:** "
                        + action.delay_reduction_preparation
                    )
                if action.downstream_work_affected:
                    impact_summary = summarise_downstream_impacts(
                        plan.actionable_tasks,
                        action.task,
                        action.downstream_work_affected,
                    )
                    if impact_summary.directly_affected_tasks:
                        st.markdown(
                            "**Direct impacts:** "
                            + "; ".join(impact_summary.directly_affected_tasks)
                        )
                    if impact_summary.major_indirect_impacts:
                        st.markdown(
                            "**Major indirect impacts:** "
                            + "; ".join(impact_summary.major_indirect_impacts)
                        )
                    if impact_summary.additional_downstream_task_count:
                        st.caption(
                            f"+ {impact_summary.additional_downstream_task_count} additional downstream task(s)"
                        )
                    with st.expander("View full downstream task list"):
                        for downstream_task in action.downstream_work_affected:
                            st.markdown(f"- {downstream_task}")
                else:
                    st.caption("No recorded downstream task dependencies.")
    else:
        st.success("No incomplete tasks require urgent action.")

    st.markdown("### Active blocked dependency chains")
    if review.active_blocked_dependency_chains:
        for chain in review.active_blocked_dependency_chains:
            with st.container(border=True):
                st.markdown(f"**Blocking task:** {chain.blocking_task}")
                st.caption(f"Responsible PIC: {chain.responsible_pic}")
                st.markdown(f"**Evidence:** {chain.blocker_evidence}")
                st.markdown(
                    "**Possible root cause(s):** "
                    + (
                        "; ".join(chain.possible_root_causes)
                        if chain.possible_root_causes
                        else "No incomplete upstream prerequisite identified."
                    )
                )
                st.markdown(f"**Root-cause analysis:** {chain.root_cause_analysis}")
                st.markdown(
                    "**Directly affected tasks:** "
                    + "; ".join(chain.directly_affected_tasks)
                )
                if chain.major_indirect_impacts:
                    st.markdown(
                        "**Major indirect impacts:** "
                        + "; ".join(chain.major_indirect_impacts)
                    )
                if chain.additional_downstream_task_count:
                    st.caption(
                        f"+ {chain.additional_downstream_task_count} additional downstream task(s)"
                    )
                st.markdown(f"**Operational impact:** {chain.operational_impact}")
                st.markdown(
                    "**Recommended escalation:** "
                    + chain.recommended_escalation_action
                )
                with st.expander("View full blocked downstream task list"):
                    for downstream_task in chain.blocked_downstream_tasks:
                        st.markdown(f"- {downstream_task}")
    else:
        st.success("No active blocked dependency chains detected.")

    st.markdown("### Increasing risks")
    if review.increasing_risks:
        for item in review.increasing_risks:
            with st.container(border=True):
                st.markdown(f"**{item.risk}**")
                st.markdown(f"**Evidence:** {item.evidence}")
                st.markdown(f"**Likely impact:** {item.likely_impact}")
                st.markdown(
                    f"**Recommended mitigation:** {item.recommended_mitigation}"
                )
    else:
        st.success("No increasing operational risks detected from the current data.")

    st.markdown("### Ownership gaps")
    if review.ownership_gaps:
        for gap in review.ownership_gaps:
            st.markdown(
                f"- **{gap.task}** — {gap.current_status}; due "
                f"{gap.deadline.strftime('%d/%m/%Y')}. "
                f"{gap.recommended_assignment_action}"
            )
    else:
        st.success("No tasks without a clear owner detected.")

    st.markdown("### Suggested committee meeting agenda")
    for index, item in enumerate(review.suggested_meeting_agenda, start=1):
        with st.container(border=True):
            st.markdown(f"**{index}. {item.task_or_workstream}**")
            st.caption(f"PIC: {item.relevant_pic}")
            st.markdown(
                f"**Decision or action required:** {item.decision_or_action_required}"
            )
            st.markdown(
                "**Deadline or escalation point:** "
                + item.deadline_or_escalation_point
            )


def render_risks_and_actions(plan: OperationsPlan) -> None:
    st.markdown("## 5. Risk register and next actions")
    st.markdown(
        f'<span class="risk-pill">Overall operational risk: {plan.operational_risk_level}</span>',
        unsafe_allow_html=True,
    )
    risk_frame = pd.DataFrame(
        [
            {
                "Risk": item.risk,
                "Likelihood": item.likelihood,
                "Impact": item.impact,
                "Overall level": item.overall_level,
                "Mitigation": item.mitigation,
                "Owner": item.owner_role,
            }
            for item in plan.risk_register
        ]
    )
    st.dataframe(risk_frame, hide_index=True, width="stretch")
    with st.expander("Recommended next actions", expanded=True):
        for index, action in enumerate(plan.recommended_next_actions, start=1):
            st.markdown(f"{index}. {action}")


def render_exports(plan: OperationsPlan) -> None:
    st.markdown("## 6. Export")
    task_frame = pd.DataFrame(tasks_to_dashboard_rows(plan.actionable_tasks))
    safe_name = "".join(
        character.lower() if character.isalnum() else "-"
        for character in plan.event_brief.event_name
    ).strip("-")
    safe_name = safe_name or "event"
    col1, col2 = st.columns(2)
    col1.download_button(
        "Download tasks as CSV",
        data=task_frame.to_csv(index=False).encode("utf-8-sig"),
        file_name=f"{safe_name}-tasks.csv",
        mime="text/csv",
        width="stretch",
    )
    col2.download_button(
        "Download full operations plan as JSON",
        data=plan.model_dump_json(indent=2),
        file_name=f"{safe_name}-operations-plan.json",
        mime="application/json",
        width="stretch",
    )


def main() -> None:
    initialise_state()
    render_sidebar()
    st.markdown(
        """
        <div class="hero">
            <h1>CivicOps AI</h1>
            <p>An AI operations copilot for volunteer organisations, student societies, and non-profit teams.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if has_api_key():
        st.markdown(
            f'<div class="mode-card"><strong>AI Mode</strong><br><span class="small-muted">Using the OpenAI Responses API with {get_model_name()}.</span></div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            '<div class="mode-card"><strong>Demo Mode</strong><br><span class="small-muted">No OpenAI API key detected. The complete workflow runs locally with deterministic sample logic.</span></div>',
            unsafe_allow_html=True,
        )

    render_event_form()
    plan: OperationsPlan | None = st.session_state.operations_plan
    if plan is None:
        st.info(
            "Complete the event brief or load the Bacang Youth sample, then generate a plan."
        )
        return

    st.divider()
    st.markdown("## 2. AI operations plan")
    st.caption(f"Plan source: {st.session_state.plan_source}")
    st.write(plan.plan_summary)
    render_committee(plan)
    plan = render_dashboard(plan)
    render_review(plan)
    render_risks_and_actions(plan)
    render_exports(plan)


if __name__ == "__main__":
    main()
