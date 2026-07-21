"""Regression tests for bounded and safely rendered progress reviews."""

from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace

from streamlit.testing.v1 import AppTest

import ai_service
from ai_service import (
    ActionableTask,
    EventBrief,
    ProgressReview,
    generate_demo_plan,
    generate_demo_progress_review,
    review_current_progress,
    summarise_downstream_impacts,
)
from sample_data import SAMPLE_EVENT


def sample_brief() -> EventBrief:
    return EventBrief.model_validate(SAMPLE_EVENT)


def long_dependency_chain() -> list[ActionableTask]:
    root = ActionableTask(
        task="Resolve school approval blocker",
        person_in_charge_role="Chairperson",
        deadline=date.today() + timedelta(days=2),
        priority="Critical",
        current_status="Blocked",
        task_dependencies=[],
        operational_risk_level="Critical",
    )
    tasks = [root]
    previous_name = root.task
    for index in range(1, 28):
        task = ActionableTask(
            task=f"Dependent task {index:02d}",
            person_in_charge_role=f"Workstream Lead {index:02d}",
            deadline=date.today() + timedelta(days=2 + index),
            priority="Critical" if index % 9 == 0 else "Medium",
            current_status="Not started",
            task_dependencies=[previous_name],
            operational_risk_level="High" if index % 7 == 0 else "Medium",
        )
        tasks.append(task)
        previous_name = task.task
    return tasks


def test_very_long_dependency_chain_keeps_full_list_out_of_recommendation() -> None:
    tasks = long_dependency_chain()
    review = generate_demo_progress_review(sample_brief(), tasks)
    root_name = tasks[0].task
    chain = next(
        item
        for item in review.active_blocked_dependency_chains
        if item.blocking_task == root_name
    )
    action = next(
        item for item in review.three_most_urgent_actions if item.task == root_name
    )
    summary = summarise_downstream_impacts(
        tasks, root_name, action.downstream_work_affected
    )

    assert len(action.downstream_work_affected) == 27
    assert len(chain.blocked_downstream_tasks) == 27
    assert len(summary.directly_affected_tasks) <= 3
    assert len(summary.major_indirect_impacts) <= 2
    assert summary.additional_downstream_task_count == 24
    assert f"+ {summary.additional_downstream_task_count}" in action.recommended_action
    assert action.recommended_action.count("Dependent task") <= 5
    assert 250 <= len(action.recommended_action) <= 600
    assert all(
        250 <= len(item.recommended_action) <= 600
        for item in review.three_most_urgent_actions
    )


def test_oversized_mocked_ai_review_is_bounded_before_schema_validation(
    monkeypatch,
) -> None:
    brief = sample_brief()
    tasks = generate_demo_plan(brief).actionable_tasks
    draft = generate_demo_progress_review(brief, tasks).model_dump(mode="json")
    draft["executive_summary"] = "Oversized executive detail " * 500
    for action in draft["three_most_urgent_actions"]:
        action["recommended_action"] = "Oversized recommended action " * 500
        action["why_urgent"] = "Oversized urgency evidence " * 500
        action["work_that_can_proceed"] = "Oversized independent work " * 500
    for risk in draft["increasing_risks"]:
        risk["evidence"] = "Oversized risk evidence " * 500
        risk["recommended_mitigation"] = "Oversized mitigation " * 500
    for item in draft["suggested_meeting_agenda"]:
        item["decision_or_action_required"] = "Oversized meeting decision " * 500

    captured: dict[str, ProgressReview] = {}

    class FakeResponses:
        def parse(self, **kwargs: object) -> object:
            text_format = kwargs["text_format"]
            parsed = text_format.model_validate(draft)  # type: ignore[union-attr]
            captured["parsed"] = parsed
            return SimpleNamespace(output_parsed=parsed, status="completed")

    class FakeClient:
        responses = FakeResponses()

    monkeypatch.setattr(ai_service, "_openai_client", lambda: FakeClient())
    review = review_current_progress(brief, tasks)

    parsed = captured["parsed"]
    assert len(parsed.executive_summary) <= 1_800
    assert all(
        len(item.recommended_action) <= 699
        for item in parsed.three_most_urgent_actions
    )
    assert all(
        len(item.why_urgent) <= 900
        for item in parsed.three_most_urgent_actions
    )
    assert ProgressReview.model_validate(review.model_dump(mode="json")) == review
    assert all(
        250 <= len(item.recommended_action) <= 600
        for item in review.three_most_urgent_actions
    )


def test_application_boundary_sanitises_unexpected_review_error(
    monkeypatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "configured-test-placeholder")
    monkeypatch.setattr(ai_service, "generate_operations_plan", generate_demo_plan)

    def fail_review(*_: object, **__: object) -> ProgressReview:
        raise RuntimeError(
            "Traceback at C:\\private\\service.py with credential=SENSITIVE_MARKER"
        )

    monkeypatch.setattr(ai_service, "review_current_progress", fail_review)

    app = AppTest.from_file("app.py", default_timeout=60).run()
    app.button[0].click().run()
    app.button[1].click().run()
    review_button = next(
        button for button in app.button if button.label == "Review Current Progress"
    )
    review_button.click().run()

    rendered_errors = " ".join(str(error.value) for error in app.error)
    assert not app.exception
    assert "The AI progress review could not be completed." in rendered_errors
    assert "SENSITIVE_MARKER" not in rendered_errors
    assert "Traceback" not in rendered_errors
    assert "C:\\private" not in rendered_errors
    assert app.session_state["review_source"] == (
        "Demo fallback after unexpected review error"
    )

