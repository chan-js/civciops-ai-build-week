"""Sprint 1 coverage for editable task state and planning-date safety."""

from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace

import pandas as pd
import pytest
from pydantic import ValidationError
from streamlit.testing.v1 import AppTest

import ai_service
from ai_service import (
    EventBrief,
    TaskValidationError,
    add_task_to_plan,
    apply_generated_plan_safety,
    dashboard_rows_to_tasks,
    delete_task_from_plan,
    generate_demo_plan,
    generate_operations_plan,
    tasks_to_dashboard_rows,
)
from sample_data import SAMPLE_EVENT


def sprint_brief(*, days_until_event: int = 30) -> EventBrief:
    planning_date = date.today()
    data = dict(SAMPLE_EVENT)
    data.update(
        {
            "current_planning_date": planning_date,
            "event_date": planning_date + timedelta(days=days_until_event),
        }
    )
    return EventBrief.model_validate(data)


def test_add_task_preserves_generated_tasks_and_persists_through_rows() -> None:
    original_plan = generate_demo_plan(sprint_brief())
    original_ids = [task.task_id for task in original_plan.actionable_tasks]

    updated_plan = add_task_to_plan(original_plan)
    persisted_tasks = dashboard_rows_to_tasks(
        tasks_to_dashboard_rows(updated_plan.actionable_tasks),
        brief=updated_plan.event_brief,
    )

    assert len(original_plan.actionable_tasks) == 16
    assert len(updated_plan.actionable_tasks) == 17
    assert [task.task_id for task in updated_plan.actionable_tasks[:16]] == original_ids
    assert len({task.task_id for task in updated_plan.actionable_tasks}) == 17
    assert persisted_tasks == updated_plan.actionable_tasks
    assert updated_plan.actionable_tasks[-1].task == "New task"


def test_delete_task_removes_only_selected_task() -> None:
    plan = add_task_to_plan(generate_demo_plan(sprint_brief()))
    added_task = plan.actionable_tasks[-1]

    result = delete_task_from_plan(plan, added_task.task_id)

    assert len(result.plan.actionable_tasks) == 16
    assert all(
        task.task_id != added_task.task_id for task in result.plan.actionable_tasks
    )
    assert result.deleted_task_name == added_task.task
    assert result.updated_dependent_tasks == ()


def test_delete_task_removes_dangling_dependency_references() -> None:
    plan = generate_demo_plan(sprint_brief())
    deleted_task = plan.actionable_tasks[0]
    expected_dependents = {
        task.task
        for task in plan.actionable_tasks
        if deleted_task.task in task.task_dependencies
    }

    result = delete_task_from_plan(plan, deleted_task.task_id)

    assert set(result.updated_dependent_tasks) == expected_dependents
    assert all(
        deleted_task.task not in task.task_dependencies
        for task in result.plan.actionable_tasks
    )


def test_csv_and_json_exports_follow_add_edit_and_delete_state() -> None:
    plan = add_task_to_plan(generate_demo_plan(sprint_brief()))
    rows = tasks_to_dashboard_rows(plan.actionable_tasks)
    rows[-1]["task"] = "Confirm accessibility checkpoint"
    rows[-1]["PIC"] = "Accessibility Lead"
    rows[-1]["status"] = "In progress"
    edited_tasks = dashboard_rows_to_tasks(rows, brief=plan.event_brief)
    edited_plan = plan.model_copy(update={"actionable_tasks": edited_tasks})

    deleted_name = edited_plan.actionable_tasks[1].task
    result = delete_task_from_plan(
        edited_plan, edited_plan.actionable_tasks[1].task_id
    )
    csv_text = pd.DataFrame(
        tasks_to_dashboard_rows(result.plan.actionable_tasks)
    ).to_csv(index=False)
    json_text = result.plan.model_dump_json(indent=2)

    assert "Confirm accessibility checkpoint" in csv_text
    assert "Confirm accessibility checkpoint" in json_text
    assert "Accessibility Lead" in csv_text
    assert deleted_name not in csv_text
    assert deleted_name not in json_text
    assert '"current_planning_date"' in json_text


def test_current_planning_date_defaults_and_bounds_event_date() -> None:
    data = dict(SAMPLE_EVENT)
    data.pop("current_planning_date", None)
    data["event_date"] = date.today()
    brief = EventBrief.model_validate(data)

    assert brief.current_planning_date == date.today()
    assert brief.event_date == brief.current_planning_date

    data["current_planning_date"] = date.today() + timedelta(days=2)
    with pytest.raises(ValidationError, match="current planning date"):
        EventBrief.model_validate(data)


def test_generated_deadlines_are_corrected_and_warning_details_are_saved() -> None:
    brief = sprint_brief(days_until_event=14)
    plan = generate_demo_plan(brief)
    unsafe_task = plan.actionable_tasks[0].model_copy(
        update={"deadline": brief.current_planning_date - timedelta(days=10)}
    )
    unsafe_plan = plan.model_copy(
        update={
            "actionable_tasks": [unsafe_task, *plan.actionable_tasks[1:]],
            "deadline_corrections": [],
        }
    )

    corrected = apply_generated_plan_safety(unsafe_plan, brief)
    pre_event_deadlines = [
        task.deadline
        for task in corrected.actionable_tasks
        if task.task_phase == "Pre-event"
    ]

    assert corrected.actionable_tasks[0].deadline == brief.current_planning_date
    assert corrected.deadline_corrections
    assert unsafe_task.task in corrected.deadline_corrections[0]
    assert pre_event_deadlines == sorted(pre_event_deadlines)
    assert all(
        brief.current_planning_date <= deadline <= brief.event_date
        for deadline in pre_event_deadlines
    )


def test_ai_parsing_applies_deadline_safety_after_structured_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    brief = sprint_brief(days_until_event=30)
    plan = generate_demo_plan(brief)
    unsafe_plan = plan.model_copy(
        update={
            "actionable_tasks": [
                plan.actionable_tasks[0].model_copy(
                    update={
                        "deadline": brief.current_planning_date
                        - timedelta(days=2)
                    }
                ),
                *plan.actionable_tasks[1:],
            ],
            "deadline_corrections": [],
        }
    )
    captured: dict[str, object] = {}

    class SuccessfulResponses:
        def parse(self, **kwargs: object) -> object:
            captured.update(kwargs)
            return SimpleNamespace(output_parsed=unsafe_plan)

    monkeypatch.setattr(
        ai_service,
        "_openai_client",
        lambda: SimpleNamespace(responses=SuccessfulResponses()),
    )

    corrected = generate_operations_plan(brief)

    assert corrected.actionable_tasks[0].deadline == brief.current_planning_date
    assert corrected.deadline_corrections
    assert (
        '"current_planning_date": '
        f'"{brief.current_planning_date.isoformat()}"'
        in captured["input"][1]["content"]
    )


def test_manual_deadline_before_planning_date_is_rejected() -> None:
    plan = generate_demo_plan(sprint_brief())
    rows = tasks_to_dashboard_rows(plan.actionable_tasks)
    rows[0]["deadline"] = (
        plan.event_brief.current_planning_date - timedelta(days=1)
    )

    with pytest.raises(TaskValidationError, match="before the current planning date"):
        dashboard_rows_to_tasks(rows, brief=plan.event_brief)

    delivery_rows = tasks_to_dashboard_rows(plan.actionable_tasks)
    delivery_row = next(
        row
        for row in delivery_rows
        if row["task_phase"] == "Event-day delivery"
    )
    delivery_row["deadline"] = plan.event_brief.event_date - timedelta(days=1)
    with pytest.raises(TaskValidationError, match="must be due on"):
        dashboard_rows_to_tasks(delivery_rows, brief=plan.event_brief)

    closeout_rows = tasks_to_dashboard_rows(plan.actionable_tasks)
    closeout_row = next(
        row
        for row in closeout_rows
        if row["task_phase"] == "Post-event closeout"
    )
    closeout_row["deadline"] = plan.event_brief.event_date
    with pytest.raises(TaskValidationError, match="must be due after"):
        dashboard_rows_to_tasks(closeout_rows, brief=plan.event_brief)


def test_delivery_and_closeout_are_separate_and_date_safe() -> None:
    plan = generate_demo_plan(sprint_brief())
    delivery_tasks = [
        task
        for task in plan.actionable_tasks
        if task.task_phase == "Event-day delivery"
    ]
    closeout_tasks = [
        task
        for task in plan.actionable_tasks
        if task.task_phase == "Post-event closeout"
    ]

    assert len(delivery_tasks) == 1
    assert delivery_tasks[0].task == "Deliver and conduct the event"
    assert delivery_tasks[0].deadline == plan.event_brief.event_date
    assert len(closeout_tasks) == 1
    assert closeout_tasks[0].task != delivery_tasks[0].task
    assert closeout_tasks[0].deadline > plan.event_brief.event_date
    assert closeout_tasks[0].task_dependencies == [delivery_tasks[0].task]


def test_streamlit_add_and_confirmed_delete_persist_without_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "")
    app = AppTest.from_file("app.py", default_timeout=60).run()
    app.button[0].click().run()
    app.button[1].click().run()

    next(button for button in app.button if button.label == "Add task").click().run()
    assert len(app.session_state["operations_plan"].actionable_tasks) == 17

    next(button for button in app.button if button.label == "Delete").click().run()
    assert len(app.session_state["operations_plan"].actionable_tasks) == 17
    assert any(button.label == "Confirm deletion" for button in app.button)

    next(
        button for button in app.button if button.label == "Confirm deletion"
    ).click().run()
    assert len(app.session_state["operations_plan"].actionable_tasks) == 16
    assert not app.exception
