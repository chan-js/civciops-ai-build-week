"""Core offline tests for CivicOps AI."""

from __future__ import annotations

from collections import Counter
from datetime import date, timedelta

from ai_service import (
    ActionableTask,
    EventBrief,
    calculate_metrics,
    dashboard_rows_to_tasks,
    generate_demo_plan,
    generate_demo_progress_review,
    tasks_to_dashboard_rows,
)
from sample_data import SAMPLE_EVENT


def sample_brief() -> EventBrief:
    return EventBrief.model_validate(SAMPLE_EVENT)


def future_sample_tasks() -> list[ActionableTask]:
    plan = generate_demo_plan(sample_brief())
    return [
        task.model_copy(
            update={
                "deadline": date.today() + timedelta(days=30 + index * 3),
                "current_status": "Not started",
            }
        )
        for index, task in enumerate(plan.actionable_tasks)
    ]


def test_sample_plan_is_valid_and_deterministic() -> None:
    brief = sample_brief()
    first = generate_demo_plan(brief)
    second = generate_demo_plan(brief)

    assert first == second
    assert first.event_brief.event_name.startswith("Primary School")
    assert len(first.actionable_tasks) >= 12
    assert len(first.risk_register) >= 5
    assert first.operational_risk_level in {"High", "Critical"}

    risk_distribution = Counter(
        task.operational_risk_level for task in first.actionable_tasks
    )
    status_distribution = Counter(task.current_status for task in first.actionable_tasks)
    committee_roles = {
        role.role for role in first.recommended_committee_structure
    }

    assert risk_distribution == {"Low": 5, "Medium": 6, "High": 2, "Critical": 3}
    assert status_distribution == {"Not started": 15, "In progress": 1}
    assert first.actionable_tasks[0].current_status == "In progress"
    assert {"Chairperson", "Secretary", "Treasurer", "Examination Lead"}.issubset(
        committee_roles
    )

    professional_brief = brief.model_copy(
        update={"organisation_type": "Professional non-profit"}
    )
    professional_plan = generate_demo_plan(professional_brief)
    assert professional_plan.recommended_committee_structure[0].role == "Event Director"


def test_dashboard_round_trip_preserves_tasks() -> None:
    plan = generate_demo_plan(sample_brief())
    rows = tasks_to_dashboard_rows(plan.actionable_tasks)
    rebuilt = dashboard_rows_to_tasks(rows)

    assert list(rows[0]) == [
        "task",
        "PIC",
        "deadline",
        "status",
        "priority",
        "risk",
        "dependency",
    ]
    assert rebuilt == plan.actionable_tasks


def test_dashboard_edits_drive_metrics_and_review() -> None:
    brief = sample_brief()
    plan = generate_demo_plan(brief)
    rows = tasks_to_dashboard_rows(plan.actionable_tasks)
    rows[1]["status"] = "Blocked"
    rows[2]["PIC"] = ""
    edited_tasks = dashboard_rows_to_tasks(rows)

    metrics = calculate_metrics(edited_tasks)
    review = generate_demo_progress_review(brief, edited_tasks)

    assert metrics["blocked_tasks"] == 1
    assert metrics["completed_tasks"] == 0
    assert metrics["completion_percentage"] == 0
    assert len(review.three_most_urgent_actions) == 3
    assert any(
        chain.blocking_task == rows[1]["task"]
        for chain in review.active_blocked_dependency_chains
    )
    assert rows[2]["task"] in {gap.task for gap in review.ownership_gaps}


def test_ordinary_dependencies_are_not_active_blockers() -> None:
    tasks = future_sample_tasks()
    review = generate_demo_progress_review(sample_brief(), tasks)

    assert review.active_blocked_dependency_chains == []


def test_blocked_task_creates_correct_downstream_chain() -> None:
    tasks = future_sample_tasks()
    blocking_task = tasks[0].model_copy(update={"current_status": "Blocked"})
    tasks[0] = blocking_task

    review = generate_demo_progress_review(sample_brief(), tasks)
    chain = next(
        item
        for item in review.active_blocked_dependency_chains
        if item.blocking_task == blocking_task.task
    )

    assert tasks[1].task in chain.blocked_downstream_tasks
    assert chain.responsible_pic == blocking_task.person_in_charge_role
    assert "explicitly marked Blocked" in chain.blocker_evidence
    assert chain.operational_impact
    assert chain.recommended_escalation_action


def test_incomplete_upstream_prerequisite_is_identified_as_root_cause() -> None:
    tasks = future_sample_tasks()
    governance_task = tasks[0]
    venue_task = tasks[1].model_copy(update={"current_status": "Blocked"})
    tasks[1] = venue_task

    review = generate_demo_progress_review(sample_brief(), tasks)
    chain = next(
        item
        for item in review.active_blocked_dependency_chains
        if item.blocking_task == venue_task.task
    )
    urgent_names = [item.task for item in review.three_most_urgent_actions]
    agenda_names = [item.task_or_workstream for item in review.suggested_meeting_agenda]

    assert governance_task.task in chain.possible_root_causes
    assert governance_task.task in chain.root_cause_analysis
    assert urgent_names.index(governance_task.task) < urgent_names.index(venue_task.task)
    assert agenda_names.index(governance_task.task) < agenda_names.index(venue_task.task)


def test_blocked_downstream_task_receives_partial_progress_guidance() -> None:
    blocker = ActionableTask(
        task="Confirm school and venue approval",
        person_in_charge_role="Chairperson",
        deadline=date.today() + timedelta(days=3),
        priority="Critical",
        current_status="Blocked",
        task_dependencies=[],
        operational_risk_level="High",
    )
    downstream = ActionableTask(
        task="Complete emergency response plan",
        person_in_charge_role="Safety and First Aid Lead",
        deadline=date.today() + timedelta(days=7),
        priority="Critical",
        current_status="Not started",
        task_dependencies=[blocker.task],
        operational_risk_level="Critical",
    )
    final_task = ActionableTask(
        task="Run safety rehearsal",
        person_in_charge_role="Venue and Marshalling Lead",
        deadline=date.today() + timedelta(days=10),
        priority="High",
        current_status="Not started",
        task_dependencies=[downstream.task],
        operational_risk_level="High",
    )

    review = generate_demo_progress_review(
        sample_brief(), [blocker, downstream, final_task]
    )
    action = next(
        item for item in review.three_most_urgent_actions if item.task == downstream.task
    )

    assert blocker.task in action.active_blocking_prerequisites
    assert "sections" in action.work_that_can_proceed.lower()
    assert "must wait" in action.work_that_must_wait.lower()
    assert "prepare" in action.delay_reduction_preparation.lower()
    assert not action.recommended_action.startswith(f"Complete {downstream.task}")


def test_long_downstream_impact_is_concisely_summarised() -> None:
    tasks = future_sample_tasks()
    tasks[1] = tasks[1].model_copy(update={"current_status": "Blocked"})

    review = generate_demo_progress_review(sample_brief(), tasks)
    chain = next(
        item
        for item in review.active_blocked_dependency_chains
        if item.blocking_task == tasks[1].task
    )

    assert len(chain.directly_affected_tasks) <= 3
    assert len(chain.major_indirect_impacts) <= 2
    assert chain.additional_downstream_task_count > 0
    assert (
        chain.additional_downstream_task_count
        == len(chain.blocked_downstream_tasks)
        - len(chain.directly_affected_tasks)
        - len(chain.major_indirect_impacts)
    )
    assert f"+ {chain.additional_downstream_task_count}" in chain.operational_impact


def test_overdue_incomplete_prerequisite_is_an_operational_blocker() -> None:
    tasks = future_sample_tasks()
    overdue_task = tasks[0].model_copy(
        update={
            "current_status": "In progress",
            "deadline": date.today() - timedelta(days=2),
        }
    )
    tasks[0] = overdue_task

    review = generate_demo_progress_review(sample_brief(), tasks)
    chain = next(
        item
        for item in review.active_blocked_dependency_chains
        if item.blocking_task == overdue_task.task
    )

    assert tasks[1].task in chain.blocked_downstream_tasks
    assert "2 day(s) overdue" in chain.blocker_evidence


def test_critical_downstream_task_outranks_ordinary_low_risk_work() -> None:
    critical_task = ActionableTask(
        task="Approve emergency response plan",
        person_in_charge_role="Safety and First Aid Lead",
        deadline=date.today() + timedelta(days=10),
        priority="Critical",
        current_status="Not started",
        task_dependencies=[],
        operational_risk_level="Critical",
    )
    low_risk_task = ActionableTask(
        task="File committee meeting minutes",
        person_in_charge_role="Secretary",
        deadline=date.today() + timedelta(days=2),
        priority="Low",
        current_status="In progress",
        task_dependencies=[],
        operational_risk_level="Low",
    )
    downstream_task = ActionableTask(
        task="Run event safety rehearsal",
        person_in_charge_role="Venue and Marshalling Lead",
        deadline=date.today() + timedelta(days=12),
        priority="Critical",
        current_status="Not started",
        task_dependencies=[critical_task.task],
        operational_risk_level="High",
    )
    tasks = [low_risk_task, critical_task, downstream_task]

    review = generate_demo_progress_review(sample_brief(), tasks)

    assert review.three_most_urgent_actions[0].task == critical_task.task
    assert (
        review.three_most_urgent_actions[0].urgency_score
        > next(
            action.urgency_score
            for action in review.three_most_urgent_actions
            if action.task == low_risk_task.task
        )
    )
    assert downstream_task.task in review.three_most_urgent_actions[0].downstream_work_affected
    assert "move" not in review.three_most_urgent_actions[0].recommended_action.lower()


def test_meeting_agenda_references_real_tasks_and_pics() -> None:
    tasks = future_sample_tasks()
    review = generate_demo_progress_review(sample_brief(), tasks)
    task_lookup = {task.task: task.person_in_charge_role for task in tasks}

    assert review.suggested_meeting_agenda
    for item in review.suggested_meeting_agenda:
        assert item.task_or_workstream in task_lookup
        assert item.relevant_pic == task_lookup[item.task_or_workstream]
        assert item.decision_or_action_required
        assert item.deadline_or_escalation_point


def test_full_plan_serialises_as_json() -> None:
    plan = generate_demo_plan(sample_brief())
    payload = plan.model_dump_json(indent=2)

    assert '"recommended_committee_structure"' in payload
    assert '"actionable_tasks"' in payload
    assert '"risk_register"' in payload
