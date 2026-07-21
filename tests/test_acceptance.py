"""Pre-submission acceptance coverage for edge cases and service failures."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest
from pydantic import ValidationError
from streamlit.testing.v1 import AppTest

import ai_service
from ai_service import (
    AIServiceError,
    EventBrief,
    dashboard_rows_to_tasks,
    generate_demo_plan,
    generate_operations_plan,
    tasks_to_dashboard_rows,
)
from sample_data import SAMPLE_EVENT


def valid_brief_data() -> dict[str, object]:
    data = dict(SAMPLE_EVENT)
    data["event_date"] = date.today() + timedelta(days=90)
    return data


def test_missing_required_fields_are_rejected() -> None:
    with pytest.raises(ValidationError) as exc_info:
        EventBrief.model_validate({})

    missing_fields = {error["loc"][0] for error in exc_info.value.errors()}
    assert {"event_name", "event_date", "venue"}.issubset(missing_fields)


def test_past_date_and_very_long_constraints_are_rejected() -> None:
    past_data = valid_brief_data()
    past_data["event_date"] = date.today() - timedelta(days=1)
    with pytest.raises(ValidationError, match="future date"):
        EventBrief.model_validate(past_data)

    long_data = valid_brief_data()
    long_data["constraints_and_special_requirements"] = "x" * 3_001
    with pytest.raises(ValidationError):
        EventBrief.model_validate(long_data)


def test_zero_budget_and_single_person_committee_remain_usable() -> None:
    data = valid_brief_data()
    data["available_budget"] = 0
    data["committee_size"] = 1
    brief = EventBrief.model_validate(data)
    plan = generate_demo_plan(brief)

    assert plan.event_brief.available_budget == 0
    assert sum(role.suggested_people for role in plan.recommended_committee_structure) == 1
    assert len(plan.recommended_committee_structure) == 1
    assert {task.person_in_charge_role for task in plan.actionable_tasks} == {
        "Chairperson (combined committee roles)"
    }


@pytest.mark.parametrize(
    "failure_message",
    ["invalid API key", "connection refused"],
    ids=["invalid-api-key", "unavailable-connection"],
)
def test_openai_failures_return_safe_service_error(
    monkeypatch: pytest.MonkeyPatch, failure_message: str
) -> None:
    class FailingResponses:
        def parse(self, **_: object) -> object:
            raise RuntimeError(failure_message)

    class FailingClient:
        responses = FailingResponses()

    monkeypatch.setattr(ai_service, "_openai_client", lambda: FailingClient())

    with pytest.raises(AIServiceError) as exc_info:
        generate_operations_plan(EventBrief.model_validate(valid_brief_data()))

    assert "could not be completed" in str(exc_info.value)
    assert failure_message not in str(exc_info.value)


def test_csv_and_json_exports_reflect_edited_tasks() -> None:
    plan = generate_demo_plan(EventBrief.model_validate(valid_brief_data()))
    rows = tasks_to_dashboard_rows(plan.actionable_tasks)
    rows[0]["status"] = "Completed"
    rows[1]["status"] = "Blocked"
    edited_tasks = dashboard_rows_to_tasks(rows)
    edited_plan = plan.model_copy(update={"actionable_tasks": edited_tasks})

    csv_text = pd.DataFrame(tasks_to_dashboard_rows(edited_tasks)).to_csv(index=False)
    json_text = edited_plan.model_dump_json(indent=2)

    assert "Completed" in csv_text
    assert "Blocked" in csv_text
    assert '"current_status": "Completed"' in json_text
    assert '"current_status": "Blocked"' in json_text


def test_fresh_demo_flow_uses_latest_edits_and_exposes_exports(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "")
    app = AppTest.from_file("app.py", default_timeout=60).run()

    assert not app.exception
    app.button[0].click().run()
    app.button[1].click().run()
    app.session_state["task_editor"] = {
        "edited_rows": {
            0: {"status": "Completed"},
            1: {"status": "Blocked"},
        },
        "added_rows": [],
        "deleted_rows": [],
    }
    app.run()

    metric_values = {metric.label: metric.value for metric in app.metric}
    assert metric_values["Completed"] == "1"
    assert metric_values["Blocked"] == "1"
    assert metric_values["Completion"] == "6%"

    app.button[2].click().run()
    assert not app.exception
    review = app.session_state["progress_review"]
    assert "1 of 16 tasks are complete" in review.executive_summary
    assert any(
        chain.blocking_task
        == "Confirm venue scope, school liaison, and required approvals"
        for chain in review.active_blocked_dependency_chains
    )
    assert [button.proto.label for button in app.download_button] == [
        "Download tasks as CSV",
        "Download full operations plan as JSON",
    ]
    assert app.download_button[0].proto.url.endswith(".csv")
    assert app.download_button[1].proto.url.endswith(".json")


def test_new_plan_and_sample_reload_clear_stale_editor_and_review_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "")
    app = AppTest.from_file("app.py", default_timeout=60).run()
    app.button[0].click().run()
    app.button[1].click().run()
    app.session_state["task_editor"] = {
        "edited_rows": {0: {"status": "Completed"}},
        "added_rows": [],
        "deleted_rows": [],
    }
    app.run()
    app.button[2].click().run()
    assert app.session_state["progress_review"] is not None

    app.button[1].click().run()
    reset_plan = app.session_state["operations_plan"]
    assert app.session_state["progress_review"] is None
    assert reset_plan.actionable_tasks[0].current_status == "In progress"
    assert all(
        task.current_status not in {"Completed", "Blocked"}
        for task in reset_plan.actionable_tasks
    )
    assert app.session_state["task_editor"] == {
        "edited_rows": {},
        "added_rows": [],
        "deleted_rows": [],
    }

    app.button[0].click().run()
    assert app.session_state["operations_plan"] is None
    assert app.session_state["progress_review"] is None
    assert "task_editor" not in app.session_state.filtered_state
