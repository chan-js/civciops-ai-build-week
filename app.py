"""Streamlit interface for CivicOps AI."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
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
    TaskValidationError,
    add_task_to_plan,
    calculate_metrics,
    committee_headcount_warning,
    committee_rows_to_roles,
    dashboard_rows_to_tasks,
    delete_task_from_plan,
    generate_demo_plan,
    generate_demo_progress_review,
    generate_operations_plan,
    get_model_name,
    has_api_key,
    review_current_progress,
    summarise_downstream_impacts,
    tasks_to_dashboard_rows,
)
from project_persistence import (
    MAX_LOCAL_PROJECTS,
    MAX_SNAPSHOT_BYTES,
    CommitteeRoleState,
    EventBriefState,
    ProjectMetadata,
    ProjectPersistenceError,
    ProjectSnapshot,
    ProjectSummary,
    create_blank_project,
    deterministic_snapshot_json,
    duplicate_project,
    parse_project_json,
    resolve_imported_project,
    safe_project_filename,
    snapshot_content_fingerprint,
    touch_snapshot,
    unique_project_name,
    utc_now,
    validate_project_name,
)
from sample_data import SAMPLE_EVENT


load_dotenv()

_browser_storage = components.declare_component(
    "civicops_browser_storage",
    path=str(Path(__file__).with_name("browser_storage_component")),
)

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
    blank_project = create_blank_project()
    defaults: dict[str, object] = {
        "organisation_type": "Volunteer organisation",
        "event_name": "",
        "event_objective": "",
        "current_planning_date": date.today(),
        "event_date": date.today() + timedelta(days=90),
        "venue": "",
        "expected_participants": 50,
        "available_budget": 2_000.0,
        "committee_size": 10,
        "committee_structure": [],
        "constraints_and_special_requirements": "",
        "operations_plan": None,
        "plan_source": None,
        "progress_review": None,
        "review_source": None,
        "task_signature": None,
        "pending_delete_task_id": None,
        "task_mutation_notice": None,
        "project_id": blank_project.project_id,
        "project_name": blank_project.project_name,
        "project_created_at": blank_project.created_at,
        "project_updated_at": blank_project.updated_at,
        "project_last_saved_at": None,
        "project_catalog": [],
        "project_dirty": False,
        "project_saved_fingerprint": None,
        "project_save_status": "Loading projects",
        "project_validation_error": None,
        "persistence_phase": "pending",
        "storage_available": None,
        "storage_error": None,
        "storage_notice": None,
        "autosave_blocked": False,
        "processed_storage_response_ids": [],
        "storage_command": {
            "action": "hydrate",
            "request_id": f"request-{uuid4().hex}",
        },
        "pending_session_snapshot_json": None,
        "pending_session_snapshot_restored": False,
        "pending_session_snapshot_message": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def source_mode(source: object) -> str:
    """Reduce source labels to safe persistence metadata categories."""

    normalised = str(source or "").casefold()
    if "fallback" in normalised:
        return "fallback"
    if "openai" in normalised or "ai-generated" in normalised:
        return "ai"
    if "demo" in normalised:
        return "demo"
    return "unknown"


def restored_source_label(mode: str, *, review: bool = False) -> str | None:
    if mode == "ai":
        return "Restored AI-generated review (no API call)" if review else (
            "Restored AI-generated plan (no API call)"
        )
    if mode == "demo":
        return "Restored Deterministic Demo Mode"
    if mode == "fallback":
        return "Restored deterministic fallback (no API call)"
    return "Restored project snapshot" if not review else "Restored project review"


def current_project_snapshot() -> ProjectSnapshot:
    """Validate the exact editable Streamlit state as a portable snapshot."""

    committee = [
        CommitteeRoleState.model_validate(row)
        for row in st.session_state.committee_structure
    ]
    brief = EventBriefState(
        organisation_type=st.session_state.organisation_type,
        event_name=st.session_state.event_name,
        event_objective=st.session_state.event_objective,
        current_planning_date=st.session_state.current_planning_date,
        event_date=st.session_state.event_date,
        venue=st.session_state.venue,
        expected_participants=st.session_state.expected_participants,
        available_budget=st.session_state.available_budget,
        committee_size=st.session_state.committee_size,
        committee_structure=committee,
        constraints_and_special_requirements=(
            st.session_state.constraints_and_special_requirements
        ),
    )
    plan: OperationsPlan | None = st.session_state.operations_plan
    review: ProgressReview | None = st.session_state.progress_review
    plan_mode = source_mode(st.session_state.plan_source)
    review_mode = source_mode(st.session_state.review_source)
    mode = plan_mode if plan_mode != "unknown" else review_mode
    return ProjectSnapshot(
        project_id=st.session_state.project_id,
        project_name=st.session_state.project_name,
        created_at=st.session_state.project_created_at,
        updated_at=st.session_state.project_updated_at,
        event_brief=brief,
        operations_plan=plan,
        progress_review=review,
        metadata=ProjectMetadata(
            mode=mode,
            plan_source=plan_mode,
            review_source=review_mode,
        ),
    )


def apply_project_snapshot(
    snapshot: ProjectSnapshot, *, restored: bool, saved: bool
) -> None:
    """Hydrate session state without generating a plan or calling an API."""

    brief = snapshot.event_brief
    st.session_state.organisation_type = brief.organisation_type
    st.session_state.event_name = brief.event_name
    st.session_state.event_objective = brief.event_objective
    st.session_state.current_planning_date = brief.current_planning_date
    st.session_state.event_date = brief.event_date
    st.session_state.venue = brief.venue
    st.session_state.expected_participants = brief.expected_participants
    st.session_state.available_budget = brief.available_budget
    st.session_state.committee_size = brief.committee_size
    st.session_state.committee_structure = [
        row.model_dump(mode="python") for row in brief.committee_structure
    ]
    st.session_state.constraints_and_special_requirements = (
        brief.constraints_and_special_requirements
    )
    st.session_state.operations_plan = snapshot.operations_plan
    st.session_state.progress_review = snapshot.progress_review
    st.session_state.plan_source = (
        restored_source_label(snapshot.metadata.plan_source)
        if snapshot.operations_plan is not None
        else None
    )
    st.session_state.review_source = (
        restored_source_label(snapshot.metadata.review_source, review=True)
        if snapshot.progress_review is not None
        else None
    )
    st.session_state.project_id = snapshot.project_id
    st.session_state.project_name = snapshot.project_name
    st.session_state.project_created_at = snapshot.created_at
    st.session_state.project_updated_at = snapshot.updated_at
    st.session_state.project_last_saved_at = snapshot.updated_at if saved else None
    st.session_state.project_saved_fingerprint = (
        snapshot_content_fingerprint(snapshot) if saved else None
    )
    st.session_state.project_dirty = not saved
    st.session_state.project_save_status = "Saved" if saved else "Unsaved changes"
    st.session_state.project_validation_error = None
    st.session_state.autosave_blocked = False
    st.session_state.task_signature = (
        task_signature(snapshot.operations_plan)
        if snapshot.operations_plan is not None
        else None
    )
    st.session_state.pending_delete_task_id = None
    st.session_state.task_mutation_notice = None
    for widget_key in (
        "task_editor",
        "committee_editor",
        "project_selector",
        "confirm_project_delete",
    ):
        st.session_state.pop(widget_key, None)
    if restored:
        st.session_state.storage_notice = (
            f"Restored “{snapshot.project_name}” from this browser without an API call."
        )


def queue_session_snapshot(
    snapshot: ProjectSnapshot, *, restored: bool, message: str
) -> None:
    """Defer a project transition until the next rerun, before widgets render."""

    st.session_state.pending_session_snapshot_json = deterministic_snapshot_json(
        snapshot
    )
    st.session_state.pending_session_snapshot_restored = restored
    st.session_state.pending_session_snapshot_message = message


def apply_pending_session_snapshot() -> None:
    payload = st.session_state.pending_session_snapshot_json
    if not isinstance(payload, str):
        return
    restored = bool(st.session_state.pending_session_snapshot_restored)
    message = st.session_state.pending_session_snapshot_message
    st.session_state.pending_session_snapshot_json = None
    st.session_state.pending_session_snapshot_restored = False
    st.session_state.pending_session_snapshot_message = None
    snapshot = parse_project_json(payload)
    apply_project_snapshot(snapshot, restored=restored, saved=False)
    if isinstance(message, str):
        st.session_state.storage_notice = message


def _safe_storage_error(action: str, response: dict[str, object]) -> str:
    raw = str(response.get("error", "")).casefold()
    if "quota" in raw or "maximum" in raw:
        return (
            "Browser storage is full. Delete a local project or export a backup, "
            "then try Save Now again."
        )
    if action == "hydrate":
        return (
            "Browser storage is unavailable or blocked. The app remains usable; "
            "use full-project JSON export and import for recovery."
        )
    return (
        "The browser could not complete the local project operation. "
        "Export a project backup and try again."
    )


def _validated_catalog(response: dict[str, object]) -> list[dict[str, object]]:
    summaries: list[ProjectSummary] = []
    seen: set[str] = set()
    raw_projects = response.get("projects", [])
    if not isinstance(raw_projects, list):
        return []
    for item in raw_projects:
        try:
            summary = ProjectSummary.model_validate(item)
        except Exception:
            continue
        if summary.project_id in seen:
            continue
        seen.add(summary.project_id)
        summaries.append(summary)
    summaries.sort(
        key=lambda item: (item.updated_at, item.project_id), reverse=True
    )
    return [item.model_dump(mode="json") for item in summaries]


def handle_storage_response(response: object) -> None:
    """Apply one browser response exactly once and never trust unvalidated data."""

    if not isinstance(response, dict):
        return
    request_id = response.get("request_id")
    if not isinstance(request_id, str):
        return
    processed: list[str] = st.session_state.processed_storage_response_ids
    if request_id in processed:
        return
    processed.append(request_id)
    del processed[:-30]

    command = st.session_state.storage_command
    action = str(response.get("action") or command.get("action") or "")
    matching_command = command if command.get("request_id") == request_id else {}
    st.session_state.storage_command = {"action": "idle", "request_id": request_id}

    if response.get("ok") is not True:
        message = _safe_storage_error(action, response)
        st.session_state.storage_error = message
        st.session_state.project_save_status = "Storage error"
        st.session_state.autosave_blocked = True
        if action == "hydrate":
            st.session_state.persistence_phase = "failed"
            st.session_state.storage_available = False
        return

    st.session_state.storage_available = True
    st.session_state.project_catalog = _validated_catalog(response)
    st.session_state.storage_error = None

    if action == "hydrate":
        st.session_state.persistence_phase = "ready"
        snapshot_json = response.get("snapshot_json")
        if isinstance(snapshot_json, str):
            try:
                snapshot = parse_project_json(snapshot_json)
            except ProjectPersistenceError:
                st.session_state.storage_error = (
                    "The last active project is invalid and was not loaded. "
                    "Other valid saved projects remain available."
                )
                st.session_state.project_save_status = "Storage error"
                st.session_state.autosave_blocked = True
                return
            apply_project_snapshot(snapshot, restored=True, saved=True)
        elif response.get("active_project_id"):
            st.session_state.storage_error = (
                "The last active project is missing. Other valid saved projects "
                "remain available."
            )
            st.session_state.project_save_status = "Storage error"
            st.session_state.autosave_blocked = True
        else:
            st.session_state.project_dirty = True
            st.session_state.project_save_status = "Unsaved changes"
        return

    if action == "load":
        snapshot_json = response.get("snapshot_json")
        if not isinstance(snapshot_json, str):
            st.session_state.storage_error = (
                "The selected project is missing and the current project was unchanged."
            )
            st.session_state.project_save_status = "Storage error"
            return
        try:
            snapshot = parse_project_json(snapshot_json)
        except ProjectPersistenceError:
            st.session_state.storage_error = (
                "The selected project is invalid and the current project was unchanged."
            )
            st.session_state.project_save_status = "Storage error"
            return
        apply_project_snapshot(snapshot, restored=True, saved=True)
        return

    if action == "save":
        saved_json = matching_command.get("snapshot_json")
        if not isinstance(saved_json, str):
            st.session_state.storage_error = "The completed save could not be verified."
            st.session_state.project_save_status = "Storage error"
            return
        try:
            saved_snapshot = parse_project_json(saved_json)
        except ProjectPersistenceError:
            st.session_state.storage_error = "The completed save could not be verified."
            st.session_state.project_save_status = "Storage error"
            return
        st.session_state.project_name = saved_snapshot.project_name
        st.session_state.project_updated_at = saved_snapshot.updated_at
        st.session_state.project_last_saved_at = saved_snapshot.updated_at
        st.session_state.project_saved_fingerprint = snapshot_content_fingerprint(
            saved_snapshot
        )
        st.session_state.project_dirty = False
        st.session_state.project_save_status = "Saved"
        st.session_state.autosave_blocked = False
        return

    if action == "delete":
        deleted_id = response.get("deleted_project_id")
        if deleted_id == st.session_state.project_id:
            snapshot_json = response.get("snapshot_json")
            if isinstance(snapshot_json, str):
                try:
                    apply_project_snapshot(
                        parse_project_json(snapshot_json), restored=True, saved=True
                    )
                    st.session_state.storage_notice = (
                        "Project deleted. The most recently saved remaining project "
                        "was loaded."
                    )
                    return
                except ProjectPersistenceError:
                    pass
            existing_names = {
                str(item["project_name"])
                for item in st.session_state.project_catalog
                if "project_name" in item
            }
            blank = create_blank_project(
                unique_project_name("Untitled project", existing_names)
            )
            apply_project_snapshot(blank, restored=False, saved=False)
            st.session_state.storage_notice = (
                "Project deleted. A new blank project is ready."
            )


def sync_browser_storage() -> None:
    """Render the zero-height component and consume any completed operation."""

    response = _browser_storage(
        command=st.session_state.storage_command,
        default=None,
        key="civicops_browser_storage_bridge",
    )
    handle_storage_response(response)


def queue_storage_command(action: str, **values: object) -> None:
    st.session_state.storage_command = {
        "action": action,
        "request_id": f"request-{uuid4().hex}",
        **values,
    }


def queue_project_save(*, manual: bool) -> bool:
    """Validate and queue one idempotent browser write."""

    try:
        snapshot = touch_snapshot(current_project_snapshot())
        snapshot_json = deterministic_snapshot_json(snapshot)
    except (ProjectPersistenceError, ValidationError, TypeError, ValueError):
        st.session_state.project_validation_error = (
            "Project data is invalid and was not saved. Correct the highlighted "
            "project, event, committee, or task value and try again."
        )
        st.session_state.project_dirty = True
        st.session_state.project_save_status = "Unsaved changes"
        return False
    if st.session_state.storage_available is not True:
        st.session_state.storage_error = (
            "Browser storage is unavailable. Export a full-project JSON backup instead."
        )
        st.session_state.project_save_status = "Storage error"
        return False
    if manual:
        st.session_state.autosave_blocked = False
    queue_storage_command(
        "save",
        snapshot_json=snapshot_json,
        max_snapshot_bytes=MAX_SNAPSHOT_BYTES,
        max_projects=MAX_LOCAL_PROJECTS,
    )
    st.session_state.project_save_status = "Saving"
    st.session_state.project_validation_error = None
    return True


def load_sample() -> None:
    for key, value in SAMPLE_EVENT.items():
        st.session_state[key] = (
            [dict(row) for row in value]
            if key == "committee_structure"
            else value
        )
    for key in (
        "operations_plan",
        "plan_source",
        "progress_review",
        "review_source",
        "task_signature",
        "pending_delete_task_id",
        "task_mutation_notice",
    ):
        st.session_state[key] = None
    st.session_state.pop("task_editor", None)
    st.session_state.pop("committee_editor", None)


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
    if isinstance(error, AIServiceError) and error.timed_out:
        return (
            "The live AI request timed out. The deterministic plan remains available. "
            "Please try once more."
        )
    category = "validation" if isinstance(error, ValidationError) else "unknown"
    if isinstance(error, AIServiceError):
        category = error.category
    if category not in {
        "authentication",
        "insufficient_quota",
        "model_access",
        "network",
        "invalid_request",
        "validation",
        "unknown",
    }:
        category = "unknown"
    return (
        f"The OpenAI request failed. Error category: {category}. "
        "The deterministic plan remains available."
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

    with st.container(border=True):
        col1, col2 = st.columns(2, gap="large")
        with col1:
            st.text_input("Organisation type", key="organisation_type")
            st.text_input("Event name", key="event_name")
            st.text_area("Event objective", key="event_objective", height=115)
            st.date_input(
                "Current planning date",
                key="current_planning_date",
                format="DD/MM/YYYY",
                help="No pre-event task may be due before this date.",
            )
            st.date_input(
                "Event date",
                key="event_date",
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

        st.markdown("#### Committee roles and teams")
        st.caption(
            "Add, edit, or remove independent roles. Keep distinct teams on "
            "separate rows so ownership can follow their actual responsibilities."
        )
        committee_columns = [
            "role",
            "lead",
            "headcount",
            "responsibilities",
        ]
        committee_frame = pd.DataFrame(
            st.session_state.committee_structure,
            columns=committee_columns,
        )
        edited_committee_frame = st.data_editor(
            committee_frame,
            key="committee_editor",
            hide_index=True,
            width="stretch",
            height=390,
            num_rows="dynamic",
            column_order=committee_columns,
            column_config={
                "role": st.column_config.TextColumn(
                    "Role or team", required=True, width="medium"
                ),
                "lead": st.column_config.TextColumn(
                    "Lead / PIC", width="medium"
                ),
                "headcount": st.column_config.NumberColumn(
                    "Headcount",
                    min_value=1,
                    max_value=1_000,
                    step=1,
                    required=True,
                    width="small",
                ),
                "responsibilities": st.column_config.TextColumn(
                    "Responsibilities", required=True, width="large"
                ),
            },
        )
        committee_rows = edited_committee_frame.to_dict(orient="records")
        st.session_state.committee_structure = committee_rows
        committee_roles = None
        committee_error: ValidationError | TaskValidationError | None = None
        try:
            committee_roles = committee_rows_to_roles(committee_rows)
        except (ValidationError, TaskValidationError) as exc:
            committee_error = exc
        if committee_roles is not None:
            mismatch_warning = committee_headcount_warning(
                st.session_state.committee_size,
                committee_roles,
            )
            if mismatch_warning:
                st.warning(mismatch_warning)

        submitted = st.button(
            "Generate operations plan", type="primary", width="stretch"
        )

    if not submitted:
        return

    if committee_error is not None:
        if isinstance(committee_error, ValidationError):
            details = format_validation_error(committee_error)
        else:
            details = f" {committee_error}"
        st.error("Committee roles are invalid." + details, icon="⚠️")
        return

    try:
        brief = EventBrief(
            organisation_type=st.session_state.organisation_type,
            event_name=st.session_state.event_name,
            event_objective=st.session_state.event_objective,
            current_planning_date=st.session_state.current_planning_date,
            event_date=st.session_state.event_date,
            venue=st.session_state.venue,
            expected_participants=st.session_state.expected_participants,
            available_budget=st.session_state.available_budget,
            committee_size=st.session_state.committee_size,
            committee_structure=committee_roles or [],
            constraints_and_special_requirements=st.session_state.constraints_and_special_requirements,
        )
    except ValidationError as exc:
        st.error(format_validation_error(exc), icon="⚠️")
        return

    if has_api_key():
        model_label = (
            "GPT-5.6 Sol"
            if get_model_name() == "gpt-5.6-sol"
            else get_model_name()
        )
        with st.spinner(
            f"{model_label} is building the operations plan. "
            "This may take up to two minutes."
        ):
            try:
                plan = generate_operations_plan(brief)
                source = f"OpenAI Responses API · {get_model_name()}"
                st.success("AI operations plan generated and schema-validated.")
            except AIServiceError as exc:
                st.error(sanitised_review_error_message(exc), icon="⚠️")
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
    st.session_state.pending_delete_task_id = None
    st.session_state.task_mutation_notice = None
    st.session_state.pop("task_editor", None)


def render_committee(plan: OperationsPlan) -> None:
    supplied_roles = {
        item.role: item for item in plan.event_brief.committee_structure
    }
    with st.expander("Recommended committee structure", expanded=True):
        columns = st.columns(3)
        for index, role in enumerate(plan.recommended_committee_structure):
            with columns[index % 3]:
                st.markdown(f"**{role.role}** · {role.suggested_people} person(s)")
                supplied = supplied_roles.get(role.role)
                if supplied and supplied.lead:
                    st.caption(f"Lead / PIC: {supplied.lead}")
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


def store_dashboard_plan(plan: OperationsPlan, notice: str) -> None:
    """Persist a task mutation and invalidate review/editor state safely."""

    st.session_state.operations_plan = plan
    st.session_state.progress_review = None
    st.session_state.review_source = None
    st.session_state.task_signature = None
    st.session_state.task_mutation_notice = notice
    st.session_state.pop("task_editor", None)


def render_task_controls(plan: OperationsPlan) -> None:
    """Render API-free add and confirmed delete controls for dashboard tasks."""

    notice = st.session_state.task_mutation_notice
    if notice:
        st.success(notice)
        st.session_state.task_mutation_notice = None

    add_column, guidance_column = st.columns([1, 3], gap="large")
    with add_column:
        if st.button("Add task", icon="➕", width="stretch"):
            updated_plan = add_task_to_plan(plan)
            store_dashboard_plan(
                updated_plan,
                "A new task was added locally and is ready to edit.",
            )
            st.rerun()
    with guidance_column:
        st.caption(
            "New tasks are local to this session and do not call the OpenAI API."
        )

    with st.expander("Delete a task"):
        if not plan.actionable_tasks:
            st.caption("There are no tasks to delete.")
        for task in plan.actionable_tasks:
            name_column, delete_column = st.columns([5, 1])
            name_column.write(task.task)
            if delete_column.button(
                "Delete",
                key=f"delete_task_{task.task_id}",
                help=f"Request deletion of {task.task}",
                width="stretch",
            ):
                st.session_state.pending_delete_task_id = task.task_id

    pending_task_id = st.session_state.pending_delete_task_id
    if not pending_task_id:
        return
    pending_task = next(
        (
            task
            for task in plan.actionable_tasks
            if task.task_id == pending_task_id
        ),
        None,
    )
    if pending_task is None:
        st.session_state.pending_delete_task_id = None
        st.warning("The selected task no longer exists.")
        return

    dependent_names = [
        task.task
        for task in plan.actionable_tasks
        if pending_task.task in task.task_dependencies
    ]
    st.warning(
        f"Confirm deletion of “{pending_task.task}”. This cannot be undone "
        "during the current session."
    )
    if dependent_names:
        st.info(
            "Its dependency reference will be removed safely from: "
            + "; ".join(dependent_names)
        )
    confirm_column, cancel_column = st.columns(2)
    if confirm_column.button("Confirm deletion", type="primary"):
        result = delete_task_from_plan(plan, pending_task_id)
        dependency_note = ""
        if result.updated_dependent_tasks:
            dependency_note = (
                " Removed its dependency reference from "
                + "; ".join(result.updated_dependent_tasks)
                + "."
            )
        st.session_state.pending_delete_task_id = None
        store_dashboard_plan(
            result.plan,
            f"Deleted “{result.deleted_task_name}”.{dependency_note}",
        )
        st.rerun()
    if cancel_column.button("Cancel deletion"):
        st.session_state.pending_delete_task_id = None
        st.rerun()


def render_dashboard(plan: OperationsPlan) -> OperationsPlan:
    st.markdown("## 3. Operations dashboard")
    st.markdown(
        '<p class="section-note">Edit the working plan directly. Use semicolons to separate multiple dependencies.</p>',
        unsafe_allow_html=True,
    )
    metrics_slot = st.container()
    render_task_controls(plan)

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
        edited_tasks = dashboard_rows_to_tasks(
            edited_frame.to_dict(orient="records"),
            brief=plan.event_brief,
        )
        updated_plan = plan.model_copy(update={"actionable_tasks": edited_tasks})
        st.session_state.operations_plan = updated_plan
    except (ValidationError, TaskValidationError) as exc:
        if isinstance(exc, ValidationError):
            details = format_validation_error(exc)
        else:
            details = f" {exc}"
        st.error("One or more task edits are invalid." + details)
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
                        review = generate_demo_progress_review(
                            plan.event_brief, plan.actionable_tasks
                        )
                        source = "Demo fallback after API validation error"
                    except AIServiceError as exc:
                        st.error(sanitised_review_error_message(exc), icon="⚠️")
                        review = generate_demo_progress_review(
                            plan.event_brief, plan.actionable_tasks
                        )
                        source = "Demo fallback after API error"
                    except Exception as exc:
                        st.error(sanitised_review_error_message(exc), icon="⚠️")
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
    st.caption(
        "For refresh/reopen recovery, use the distinct full-project JSON backup "
        "in the Project section of the sidebar."
    )


def _catalog_names() -> dict[str, str]:
    return {
        str(item["project_id"]): str(item["project_name"])
        for item in st.session_state.project_catalog
        if "project_id" in item and "project_name" in item
    }


def _current_project_is_saved() -> bool:
    """Recheck at action time so a same-rerun edit cannot be discarded."""

    try:
        fingerprint = snapshot_content_fingerprint(current_project_snapshot())
    except (ProjectPersistenceError, ValidationError, TypeError, ValueError):
        st.session_state.project_validation_error = (
            "Correct invalid project data and save before switching projects."
        )
        st.session_state.project_dirty = True
        st.session_state.project_save_status = "Unsaved changes"
        return False
    if fingerprint != st.session_state.project_saved_fingerprint:
        st.session_state.project_dirty = True
        st.session_state.project_save_status = "Unsaved changes"
        st.session_state.storage_notice = (
            "Save the current project before switching or creating another."
        )
        return False
    return True


def _start_new_project() -> None:
    existing_names = set(_catalog_names().values())
    name = unique_project_name("Untitled project", existing_names)
    queue_session_snapshot(
        create_blank_project(name),
        restored=False,
        message=(
            "A new project was created. The previous saved project remains available."
        ),
    )


def _duplicate_current_project() -> None:
    snapshot = current_project_snapshot()
    duplicate = duplicate_project(snapshot, set(_catalog_names().values()))
    queue_session_snapshot(
        duplicate,
        restored=False,
        message=f"Created “{duplicate.project_name}” with a separate project ID.",
    )


def _import_uploaded_project(uploaded_file: object) -> None:
    """Validate the whole upload before applying any session-state mutation."""

    size = int(getattr(uploaded_file, "size", MAX_SNAPSHOT_BYTES + 1))
    if size > MAX_SNAPSHOT_BYTES:
        raise ProjectPersistenceError(
            f"Project import exceeds the {MAX_SNAPSHOT_BYTES // 1_000} KB limit."
        )
    payload = uploaded_file.getvalue()
    imported = parse_project_json(payload)
    existing = _catalog_names()
    existing_ids = set(existing)
    existing_ids.add(st.session_state.project_id)
    resolved = resolve_imported_project(
        imported,
        existing_ids,
        set(existing.values()) | {st.session_state.project_name},
    )
    queue_session_snapshot(
        resolved,
        restored=True,
        message=f"Imported “{resolved.project_name}”. Save or export it as needed.",
    )


def render_project_sidebar() -> None:
    """Render browser-local project controls after primary workflow buttons."""

    with st.sidebar:
        st.divider()
        st.markdown("### Project")
        st.caption(
            "Projects are saved locally in this browser and device. Export a "
            "project backup before clearing browser data or moving to another device."
        )

        if st.session_state.persistence_phase == "pending":
            st.info("Loading browser projects before local autosave starts…")
            return

        st.text_input(
            "Current project name",
            key="project_name",
            max_chars=80,
        )
        try:
            validate_project_name(st.session_state.project_name)
        except ProjectPersistenceError as exc:
            st.error(str(exc))

        status = st.session_state.project_save_status
        if status == "Saved":
            st.success("Saved")
        elif status == "Saving":
            st.info("Saving")
        elif status == "Storage error":
            st.error("Storage error")
        else:
            st.warning("Unsaved changes")
        last_saved = st.session_state.project_last_saved_at
        if isinstance(last_saved, datetime):
            local_saved = last_saved.astimezone()
            st.caption(f"Last saved: {local_saved.strftime('%d %b %Y, %H:%M:%S %Z')}")
        else:
            st.caption("Last saved: not yet saved")

        if st.session_state.storage_notice:
            st.info(st.session_state.storage_notice)
            st.session_state.storage_notice = None
        if st.session_state.storage_error:
            st.warning(st.session_state.storage_error)
        if st.session_state.project_validation_error:
            st.warning(st.session_state.project_validation_error)

        storage_ready = (
            st.session_state.persistence_phase == "ready"
            and st.session_state.storage_available is True
        )
        command_idle = st.session_state.storage_command.get("action") == "idle"

        if storage_ready:
            save_col, new_col = st.columns(2)
            if save_col.button(
                "Save now",
                key="save_project_now",
                disabled=not command_idle,
                width="stretch",
            ):
                if queue_project_save(manual=True):
                    st.rerun()
            if new_col.button(
                "New project",
                key="new_local_project",
                disabled=st.session_state.project_dirty or not command_idle,
                width="stretch",
            ):
                if _current_project_is_saved():
                    _start_new_project()
                    st.rerun()
            if st.session_state.project_dirty:
                st.caption("Save the current project before switching or creating another.")

            if st.button(
                "Save a copy / duplicate project",
                key="duplicate_local_project",
                disabled=st.session_state.project_dirty or not command_idle,
                width="stretch",
            ):
                if _current_project_is_saved():
                    try:
                        _duplicate_current_project()
                    except (ProjectPersistenceError, ValidationError, TypeError, ValueError):
                        st.session_state.project_validation_error = (
                            "The project could not be duplicated until its invalid data is corrected."
                        )
                    else:
                        st.rerun()

            names = _catalog_names()
            project_ids = list(names)
            if project_ids:
                if st.session_state.project_id in project_ids:
                    default_index = project_ids.index(st.session_state.project_id)
                else:
                    default_index = 0
                selected_id = st.selectbox(
                    "Existing local projects",
                    options=project_ids,
                    index=default_index,
                    format_func=lambda project_id: names.get(project_id, "Unknown project"),
                    key="project_selector",
                )
                if st.button(
                    "Load selected project",
                    key="load_local_project",
                    disabled=(
                        st.session_state.project_dirty
                        or not command_idle
                        or selected_id == st.session_state.project_id
                    ),
                    width="stretch",
                ):
                    if _current_project_is_saved():
                        queue_storage_command("load", project_id=selected_id)
                        st.rerun()
            else:
                st.caption("No saved local projects yet.")

            with st.expander("Delete current project"):
                st.warning(
                    f"Delete “{st.session_state.project_name}” from this browser?"
                )
                confirmed = st.checkbox(
                    "I confirm this exact project should be deleted.",
                    key="confirm_project_delete",
                )
                if st.button(
                    "Delete confirmed project",
                    key="delete_local_project",
                    disabled=not confirmed or not command_idle,
                    width="stretch",
                ):
                    target_id = st.session_state.project_id
                    queue_storage_command(
                        "delete",
                        project_id=target_id,
                        confirmation_project_id=target_id,
                    )
                    st.rerun()
        else:
            st.warning(
                "Local browser storage controls are unavailable. Full-project JSON "
                "export and import remain available below."
            )

        st.markdown("#### Full-project backup")
        try:
            export_snapshot = touch_snapshot(current_project_snapshot())
            export_json = deterministic_snapshot_json(export_snapshot)
        except (ProjectPersistenceError, ValidationError, TypeError, ValueError):
            st.warning(
                "Correct invalid project data before exporting a full-project backup."
            )
        else:
            st.download_button(
                "Export full project JSON",
                data=export_json,
                file_name=safe_project_filename(export_snapshot),
                mime="application/json",
                key="export_full_project",
                width="stretch",
            )

        uploaded = st.file_uploader(
            "Import full project JSON",
            type=["json"],
            accept_multiple_files=False,
            key="full_project_import",
            help=f"Maximum file size: {MAX_SNAPSHOT_BYTES // 1_000} KB.",
        )
        if st.button(
            "Validate and import project",
            key="import_full_project",
            disabled=uploaded is None,
            width="stretch",
        ):
            try:
                _import_uploaded_project(uploaded)
            except ProjectPersistenceError as exc:
                st.error(str(exc))
            except Exception:
                st.error(
                    "Project import failed validation. The current project was unchanged."
                )
            else:
                if storage_ready:
                    st.session_state.autosave_blocked = False
                st.rerun()


def finalise_project_autosave() -> None:
    """Detect meaningful committed edits and queue at most one validated write."""

    if st.session_state.persistence_phase == "pending":
        return
    try:
        snapshot = current_project_snapshot()
        fingerprint = snapshot_content_fingerprint(snapshot)
    except (ProjectPersistenceError, ValidationError, TypeError, ValueError):
        st.session_state.project_dirty = True
        if st.session_state.project_save_status != "Storage error":
            st.session_state.project_save_status = "Unsaved changes"
        st.session_state.project_validation_error = (
            "Project data is invalid and autosave is paused until it is corrected."
        )
        return

    saved_fingerprint = st.session_state.project_saved_fingerprint
    if fingerprint == saved_fingerprint:
        st.session_state.project_dirty = False
        if st.session_state.project_save_status not in {"Saving", "Storage error"}:
            st.session_state.project_save_status = "Saved"
        return

    st.session_state.project_dirty = True
    if st.session_state.project_save_status != "Storage error":
        st.session_state.project_save_status = "Unsaved changes"
    if (
        st.session_state.persistence_phase == "ready"
        and st.session_state.storage_available is True
        and st.session_state.storage_command.get("action") == "idle"
        and not st.session_state.autosave_blocked
    ):
        if queue_project_save(manual=False):
            st.rerun()


def main() -> None:
    initialise_state()
    apply_pending_session_snapshot()
    sync_browser_storage()
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
        render_project_sidebar()
        finalise_project_autosave()
        return

    st.divider()
    st.markdown("## 2. AI operations plan")
    st.caption(f"Plan source: {st.session_state.plan_source}")
    st.write(plan.plan_summary)
    if plan.deadline_corrections:
        st.warning(
            "Deadline safety corrected "
            f"{len(plan.deadline_corrections)} generated task deadline(s)."
        )
        with st.expander("View deadline corrections"):
            for correction in plan.deadline_corrections:
                st.markdown(f"- {correction}")
    if plan.committee_corrections:
        st.warning(
            "Committee fidelity corrected the generated committee structure."
        )
        with st.expander("View committee corrections"):
            for correction in plan.committee_corrections:
                st.markdown(f"- {correction}")
    review_required_tasks = [
        task
        for task in plan.actionable_tasks
        if task.ownership_review_required
    ]
    if plan.ownership_corrections or review_required_tasks:
        st.warning(
            "Responsibility validation corrected generated task owners; "
            f"{len(review_required_tasks)} task(s) require human ownership review."
        )
        with st.expander("View ownership corrections"):
            for correction in plan.ownership_corrections:
                st.markdown(f"- {correction}")
            for task in review_required_tasks:
                st.markdown(
                    f"- **{task.task}** — {task.ownership_review_reason}"
                )
    if plan.risk_corrections:
        st.warning(
            "Risk calibration corrected "
            f"{len(plan.risk_corrections)} generated task rating(s)."
        )
        with st.expander("View risk corrections"):
            for correction in plan.risk_corrections:
                st.markdown(f"- {correction}")
    render_committee(plan)
    plan = render_dashboard(plan)
    render_review(plan)
    render_risks_and_actions(plan)
    render_exports(plan)
    render_project_sidebar()
    finalise_project_autosave()


if __name__ == "__main__":
    main()
