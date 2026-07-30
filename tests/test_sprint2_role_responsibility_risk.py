"""Sprint 2 coverage for committee, ownership, and risk fidelity."""

from __future__ import annotations

import json
from datetime import date, timedelta
from types import SimpleNamespace

import pandas as pd
import pytest
from pydantic import ValidationError
from streamlit.testing.v1 import AppTest

import ai_service
from ai_service import (
    PLAN_INSTRUCTIONS,
    REVIEW_REQUIRED_OWNER,
    RISK_CLASSIFICATION_RUBRIC,
    ActionableTask,
    CommitteeRole,
    EventBrief,
    StructuredCommitteeRole,
    TaskValidationError,
    apply_generated_plan_safety,
    classify_task_risk,
    committee_headcount_warning,
    committee_roles_to_rows,
    committee_rows_to_roles,
    dashboard_rows_to_tasks,
    generate_demo_plan,
    generate_operations_plan,
    responsibility_owner_for_task,
    task_responsibility_domains,
    tasks_to_dashboard_rows,
)
from sample_data import SAMPLE_COMMITTEE, SAMPLE_EVENT


def sample_brief() -> EventBrief:
    data = dict(SAMPLE_EVENT)
    data["current_planning_date"] = date.today()
    data["event_date"] = date.today() + timedelta(days=90)
    return EventBrief.model_validate(data)


def test_committee_rows_support_add_edit_remove_and_persistence() -> None:
    original_roles = sample_brief().committee_structure
    rows = committee_roles_to_rows(original_roles)
    rows.append(
        {
            "role": "Accessibility Team",
            "lead": "Alicia",
            "headcount": 2,
            "responsibilities": "Plan accessible routes and participant support.",
        }
    )
    rows[0]["lead"] = "Updated Lead"
    rows.pop(1)

    persisted_roles = committee_rows_to_roles(rows)
    persisted_rows = committee_roles_to_rows(persisted_roles)

    assert persisted_roles[0].lead == "Updated Lead"
    assert any(role.role == "Accessibility Team" for role in persisted_roles)
    assert all(role.role != "Vice Chairperson" for role in persisted_roles)
    assert persisted_rows == rows


def test_committee_role_validation_rejects_blank_names_and_bad_headcount() -> None:
    with pytest.raises(ValidationError):
        committee_rows_to_roles(
            [
                {
                    "role": " ",
                    "lead": "Lead",
                    "headcount": 1,
                    "responsibilities": "Own a valid workstream.",
                }
            ]
        )

    with pytest.raises(ValidationError):
        committee_rows_to_roles(
            [
                {
                    "role": "Valid Team",
                    "lead": "Lead",
                    "headcount": 0,
                    "responsibilities": "Own a valid workstream.",
                }
            ]
        )

    duplicate_rows = [
        {
            "role": "Photo Team",
            "lead": "One",
            "headcount": 1,
            "responsibilities": "Take approved photographs.",
        },
        {
            "role": "photo team",
            "lead": "Two",
            "headcount": 1,
            "responsibilities": "Handle image delivery.",
        },
    ]
    with pytest.raises(TaskValidationError, match="unique"):
        committee_rows_to_roles(duplicate_rows)


def test_at_least_fifteen_independent_roles_are_preserved() -> None:
    committee = [
        {
            "role": f"Independent Team {index}",
            "lead": f"Lead {index}",
            "headcount": 1,
            "responsibilities": f"Own independent workstream {index}.",
        }
        for index in range(1, 16)
    ]
    data = dict(SAMPLE_EVENT)
    data.update(
        {
            "committee_size": 15,
            "committee_structure": committee,
            "current_planning_date": date.today(),
            "event_date": date.today() + timedelta(days=90),
        }
    )
    brief = EventBrief.model_validate(data)
    plan = generate_demo_plan(brief)

    assert len(brief.committee_structure) == 15
    assert [role.role for role in plan.recommended_committee_structure] == [
        item["role"] for item in committee
    ]


def test_headcount_mismatch_is_a_non_blocking_warning() -> None:
    roles = [
        StructuredCommitteeRole(
            role="Team A",
            lead="A",
            headcount=2,
            responsibilities="Own workstream A.",
        ),
        StructuredCommitteeRole(
            role="Team B",
            lead="B",
            headcount=1,
            responsibilities="Own workstream B.",
        ),
    ]

    warning = committee_headcount_warning(10, roles)

    assert warning is not None
    assert "headcounts total 3" in warning
    assert "committee size is 10" in warning
    assert "still generate" in warning
    assert committee_headcount_warning(3, roles) is None
    assert "headcounts total 0" in committee_headcount_warning(10, [])

    data = dict(SAMPLE_EVENT)
    data.update(
        {
            "committee_size": 10,
            "current_planning_date": date.today(),
            "event_date": date.today() + timedelta(days=90),
        }
    )
    mismatched_brief = EventBrief.model_validate(data)
    assert generate_demo_plan(mismatched_brief).actionable_tasks


def test_committee_is_included_in_ai_request_and_json_export(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    brief = sample_brief()
    captured: dict[str, object] = {}

    class SuccessfulResponses:
        def parse(self, **kwargs: object) -> object:
            captured.update(kwargs)
            return SimpleNamespace(output_parsed=generate_demo_plan(brief))

    monkeypatch.setattr(
        ai_service,
        "_openai_client",
        lambda: SimpleNamespace(responses=SuccessfulResponses()),
    )

    plan = generate_operations_plan(brief)
    request_payload = json.loads(captured["input"][1]["content"])
    exported_payload = json.loads(plan.model_dump_json())

    assert request_payload["committee_structure"][0]["lead"] == "Min Xuan"
    assert (
        request_payload["committee_structure"][-1]["role"]
        == "Sound System Team"
    )
    assert (
        exported_payload["event_brief"]["committee_structure"][9]["role"]
        == "Photography Team"
    )
    assert "preserve every role or team as a separate" in PLAN_INSTRUCTIONS


def test_merged_and_invented_roles_are_corrected_to_supplied_roles() -> None:
    brief = sample_brief()
    plan = generate_demo_plan(brief)
    invalid_plan = plan.model_copy(
        update={
            "recommended_committee_structure": [
                CommitteeRole(
                    role="Photography and Sound Team",
                    purpose="Handle photos and sound together.",
                    suggested_people=2,
                ),
                CommitteeRole(
                    role="Invented Media Team",
                    purpose="A role not supplied by the user.",
                    suggested_people=1,
                ),
            ],
            "committee_corrections": [],
        }
    )

    corrected = apply_generated_plan_safety(invalid_plan, brief)
    corrected_names = [
        role.role for role in corrected.recommended_committee_structure
    ]

    assert corrected_names == [item["role"] for item in SAMPLE_COMMITTEE]
    assert "Photography Team" in corrected_names
    assert "Sound System Team" in corrected_names
    assert "Photography and Sound Team" not in corrected_names
    assert "Invented Media Team" not in corrected_names
    assert corrected.committee_corrections
    supplied_by_name = {
        item.role: item for item in corrected.event_brief.committee_structure
    }
    assert supplied_by_name["Photography Team"].lead == "Mei Mei"
    assert supplied_by_name["Sound System Team"].lead == "Rachel"


def test_generated_owners_are_supplied_roles_or_review_required() -> None:
    brief = sample_brief()
    plan = generate_demo_plan(brief)
    allowed_owners = {role.role for role in brief.committee_structure}
    allowed_owners.update(
        role.lead for role in brief.committee_structure if role.lead
    )

    assert all(
        task.person_in_charge_role in allowed_owners
        or task.person_in_charge_role == REVIEW_REQUIRED_OWNER
        for task in plan.actionable_tasks
    )
    review_tasks = [
        task for task in plan.actionable_tasks if task.ownership_review_required
    ]
    assert review_tasks
    assert all(
        task.person_in_charge_role == REVIEW_REQUIRED_OWNER
        and task.ownership_review_reason
        for task in review_tasks
    )


def test_named_lead_is_preserved_when_their_role_owns_the_task() -> None:
    brief = sample_brief()
    plan = generate_demo_plan(brief)
    traffic_index = next(
        index
        for index, task in enumerate(plan.actionable_tasks)
        if "participant vehicle entry" in task.task
    )
    tasks = list(plan.actionable_tasks)
    tasks[traffic_index] = tasks[traffic_index].model_copy(
        update={"person_in_charge_role": "Hao Xuan"}
    )
    lead_owned_plan = plan.model_copy(
        update={"actionable_tasks": tasks, "ownership_corrections": []}
    )

    corrected = apply_generated_plan_safety(lead_owned_plan, brief)

    assert corrected.actionable_tasks[traffic_index].person_in_charge_role == "Hao Xuan"
    assert not any(
        tasks[traffic_index].task in warning
        for warning in corrected.ownership_corrections
    )


def test_wrong_or_ambiguous_owner_uses_responsibility_or_review_fallback() -> None:
    brief = sample_brief()
    plan = generate_demo_plan(brief)
    traffic_index = next(
        index
        for index, task in enumerate(plan.actionable_tasks)
        if "participant vehicle entry" in task.task
    )
    tasks = list(plan.actionable_tasks)
    tasks[traffic_index] = tasks[traffic_index].model_copy(
        update={"person_in_charge_role": "Photography Team"}
    )
    ambiguous_task = ActionableTask(
        task="Prepare a volunteer appreciation note",
        person_in_charge_role="Invented Team",
        deadline=brief.event_date - timedelta(days=1),
        priority="Low",
        current_status="Not started",
        task_dependencies=[],
        operational_risk_level="Low",
    )
    tasks.append(ambiguous_task)
    invalid_plan = plan.model_copy(
        update={"actionable_tasks": tasks, "ownership_corrections": []}
    )

    corrected = apply_generated_plan_safety(invalid_plan, brief)
    corrected_traffic = corrected.actionable_tasks[traffic_index]
    corrected_ambiguous = corrected.actionable_tasks[-1]

    assert (
        corrected_traffic.person_in_charge_role
        == "Equipment and Transport Team"
    )
    assert corrected_ambiguous.person_in_charge_role == REVIEW_REQUIRED_OWNER
    assert corrected_ambiguous.ownership_review_required is True
    assert corrected_ambiguous.ownership_review_reason


def _ownership_test_task(name: str) -> ActionableTask:
    return ActionableTask(
        task=name,
        person_in_charge_role="Safety and First Aid Lead",
        deadline=date.today() + timedelta(days=14),
        priority="High",
        current_status="Not started",
        task_dependencies=[],
        operational_risk_level="Critical",
    )


def test_generic_safety_inspection_does_not_match_food_safety() -> None:
    brief = sample_brief()
    task = _ownership_test_task(
        "Run foot drill rehearsal and safety inspection"
    )

    owner, reason = responsibility_owner_for_task(task, brief)
    plan = generate_demo_plan(brief)
    corrected_task = next(
        item
        for item in plan.actionable_tasks
        if item.task == task.task
    )

    assert owner == REVIEW_REQUIRED_OWNER
    assert reason
    assert corrected_task.person_in_charge_role == REVIEW_REQUIRED_OWNER
    assert corrected_task.ownership_review_required is True
    assert corrected_task.ownership_review_reason
    assert "Food Team" not in next(
        warning
        for warning in plan.ownership_corrections
        if task.task in warning
    ).split(" to ")[-1]


@pytest.mark.parametrize(
    "task_name",
    [
        "Confirm food hygiene controls with the caterer",
        "Confirm meal safety and dietary requirements",
    ],
)
def test_specific_food_context_still_matches_food_team(task_name: str) -> None:
    owner, reason = responsibility_owner_for_task(
        _ownership_test_task(task_name),
        sample_brief(),
    )

    assert owner == "Food Team"
    assert reason == ""


def test_rehearsal_and_site_inspection_match_venue_when_supported() -> None:
    brief = sample_brief()
    supported_roles = [
        role.model_copy(
            update={
                "responsibilities": (
                    "Manage foot drill rehearsal, site inspection, venue readiness, "
                    "and crowd movement."
                )
            }
        )
        if role.role == "Venue and Marshalling Team"
        else role
        for role in brief.committee_structure
    ]
    supported_brief = brief.model_copy(
        update={"committee_structure": supported_roles}
    )

    owner, reason = responsibility_owner_for_task(
        _ownership_test_task(
            "Run foot drill rehearsal and safety inspection"
        ),
        supported_brief,
    )

    assert owner == "Venue and Marshalling Team"
    assert reason == ""


def test_ambiguous_rehearsal_safety_falls_back_to_review_required() -> None:
    owner, reason = responsibility_owner_for_task(
        _ownership_test_task(
            "Coordinate rehearsal, operational safety inspection, and readiness"
        ),
        sample_brief(),
    )

    assert owner == REVIEW_REQUIRED_OWNER
    assert reason


def test_participant_traffic_and_equipment_logistics_remain_distinct() -> None:
    plan = generate_demo_plan(sample_brief())
    traffic_task = next(
        task
        for task in plan.actionable_tasks
        if "participant vehicle entry" in task.task
    )
    equipment_task = next(
        task
        for task in plan.actionable_tasks
        if "equipment checklist" in task.task
    )
    venue_task = next(
        task
        for task in plan.actionable_tasks
        if "participant walking flow" in task.task
    )

    assert traffic_task.task != equipment_task.task
    assert (
        traffic_task.person_in_charge_role
        == "Equipment and Transport Team"
    )
    assert (
        equipment_task.person_in_charge_role
        == "Equipment and Transport Team"
    )
    assert venue_task.person_in_charge_role == "Venue and Marshalling Team"
    assert "equipment checklist" not in venue_task.task

    bare_transport = ActionableTask(
        task="Coordinate transport schedule",
        person_in_charge_role="",
        deadline=plan.event_brief.event_date - timedelta(days=1),
        priority="Medium",
        current_status="Not started",
        task_dependencies=[],
        operational_risk_level="Medium",
    )
    assert "equipment" not in task_responsibility_domains(bare_transport)


def test_risk_rubric_classifies_consequences_without_fixed_distribution() -> None:
    base = {
        "person_in_charge_role": "Team",
        "deadline": date.today() + timedelta(days=7),
        "priority": "Medium",
        "current_status": "Not started",
        "task_dependencies": [],
        "operational_risk_level": "Medium",
    }
    safeguarding = ActionableTask(
        task="Approve safeguarding and emergency response plan", **base
    )
    traffic = ActionableTask(
        task="Design participant vehicle entry and parking flow", **base
    )
    ordinary = ActionableTask(
        task="Confirm routine volunteer update", **base
    )
    manageable = ActionableTask(
        task="Confirm meal quantities with the caterer", **base
    )

    assert set(RISK_CLASSIFICATION_RUBRIC) == {
        "Low",
        "Medium",
        "High",
        "Critical",
    }
    assert classify_task_risk(safeguarding) == "Critical"
    assert classify_task_risk(traffic) == "High"
    assert classify_task_risk(manageable) == "Medium"
    assert classify_task_risk(ordinary) == "Low"


def _risk_test_task(
    name: str,
    *,
    risk: str = "Medium",
) -> ActionableTask:
    return ActionableTask(
        task=name,
        person_in_charge_role="Main Committee",
        deadline=date.today() + timedelta(days=14),
        priority="High",
        current_status="Not started",
        task_dependencies=[],
        operational_risk_level=risk,
    )


def test_routine_food_safety_is_high_only_with_explicit_severe_escalation() -> None:
    routine = _risk_test_task(
        "Confirm meal quantities, dietary needs, and food safety controls"
    )
    severe_allergy = _risk_test_task(
        "Prevent severe allergy exposure where no safe alternative is available"
    )
    poisoning = _risk_test_task(
        "Prevent food poisoning and regulatory breach at participant meals"
    )

    assert classify_task_risk(routine) == "High"
    assert classify_task_risk(severe_allergy) == "Critical"
    assert classify_task_risk(poisoning) == "Critical"


def test_equipment_risk_depends_on_essentiality_and_fallback() -> None:
    routine = _risk_test_task(
        "Confirm equipment checklist, sourcing, setup, and return plan"
    )
    essential = _risk_test_task(
        "Secure essential sound equipment with no practical fallback"
    )
    safety_critical = _risk_test_task(
        "Replace safety-critical equipment whose failure could cause severe harm"
    )

    assert classify_task_risk(routine) == "Medium"
    assert classify_task_risk(essential) == "High"
    assert classify_task_risk(safety_critical) == "Critical"


def test_written_assessment_and_event_gate_risks_use_consequences() -> None:
    ordinary_test = _risk_test_task(
        "Prepare and securely control written first-aid test materials"
    )
    compromised_test = _risk_test_task(
        "Replace leaked test materials that cannot be replaced without "
        "compromising competition integrity"
    )
    venue_gate = _risk_test_task(
        "Confirm venue scope, school liaison, and required approvals"
    )

    assert classify_task_risk(ordinary_test) == "Medium"
    assert classify_task_risk(compromised_test) == "High"
    assert classify_task_risk(venue_gate) == "Critical"


def test_bacang_demo_risks_are_context_aware_and_include_a_downgrade() -> None:
    plan = generate_demo_plan(sample_brief())
    risks = {
        task.task: task.operational_risk_level
        for task in plan.actionable_tasks
    }

    assert (
        risks["Confirm meal quantities, dietary needs, and food safety controls"]
        == "High"
    )
    assert (
        risks["Confirm equipment checklist, sourcing, testing, setup, and return plan"]
        == "Medium"
    )
    assert (
        risks["Prepare and securely control written first-aid test materials"]
        == "Medium"
    )
    assert (
        risks["Confirm venue scope, school liaison, and required approvals"]
        == "Critical"
    )
    assert (
        risks["Run foot drill rehearsal and safety inspection"]
        == "High"
    )
    assert any(
        "Run foot drill rehearsal and safety inspection" in correction
        and "Critical to High" in correction
        for correction in plan.risk_corrections
    )


def test_risk_correction_supports_upgrades_and_downgrades() -> None:
    brief = sample_brief()
    plan = generate_demo_plan(brief)
    tasks = list(plan.actionable_tasks)
    safety_index = next(
        index
        for index, task in enumerate(tasks)
        if "safeguarding" in task.task
    )
    equipment_index = next(
        index
        for index, task in enumerate(tasks)
        if "equipment checklist" in task.task
    )
    tasks[safety_index] = tasks[safety_index].model_copy(
        update={"operational_risk_level": "Low"}
    )
    tasks[equipment_index] = tasks[equipment_index].model_copy(
        update={"operational_risk_level": "Critical"}
    )

    corrected = apply_generated_plan_safety(
        plan.model_copy(
            update={"actionable_tasks": tasks, "risk_corrections": []}
        ),
        brief,
    )

    assert corrected.actionable_tasks[safety_index].operational_risk_level == "Critical"
    assert corrected.actionable_tasks[equipment_index].operational_risk_level == "Medium"
    assert any(
        "Low to Critical" in correction
        for correction in corrected.risk_corrections
    )
    assert any(
        "Critical to Medium" in correction
        for correction in corrected.risk_corrections
    )


def test_genuine_safety_and_safeguarding_risks_remain_protected() -> None:
    safeguarding = _risk_test_task(
        "Approve safeguarding, medical, and emergency response plan"
    )
    serious_injury = _risk_test_task(
        "Prevent severe injury during the event with no safe alternative"
    )
    routine_inspection = _risk_test_task(
        "Run foot drill rehearsal and safety inspection"
    )

    assert classify_task_risk(safeguarding) == "Critical"
    assert classify_task_risk(serious_injury) == "Critical"
    assert classify_task_risk(routine_inspection) == "High"


def test_invalid_generated_risk_is_corrected_but_safety_stays_critical() -> None:
    brief = sample_brief()
    plan = generate_demo_plan(brief)
    governance_index = next(
        index
        for index, task in enumerate(plan.actionable_tasks)
        if task.task == "Confirm committee roles and decision rights"
    )
    safety_index = next(
        index
        for index, task in enumerate(plan.actionable_tasks)
        if "safeguarding" in task.task
    )
    tasks = list(plan.actionable_tasks)
    tasks[governance_index] = tasks[governance_index].model_copy(
        update={"operational_risk_level": "Critical"}
    )
    tasks[safety_index] = tasks[safety_index].model_copy(
        update={"operational_risk_level": "Critical"}
    )
    invalid_plan = plan.model_copy(
        update={"actionable_tasks": tasks, "risk_corrections": []}
    )

    corrected = apply_generated_plan_safety(invalid_plan, brief)

    assert corrected.actionable_tasks[governance_index].operational_risk_level == "Low"
    assert corrected.actionable_tasks[safety_index].operational_risk_level == "Critical"
    assert any(
        tasks[governance_index].task in warning
        for warning in corrected.risk_corrections
    )
    assert not any(
        tasks[safety_index].task in warning
        for warning in corrected.risk_corrections
    )


def test_manual_owner_and_valid_risk_edits_are_preserved() -> None:
    plan = generate_demo_plan(sample_brief())
    rows = tasks_to_dashboard_rows(plan.actionable_tasks)
    rows[7]["PIC"] = "Human-assigned External Marshal"
    rows[7]["risk"] = "Medium"

    edited_tasks = dashboard_rows_to_tasks(rows, brief=plan.event_brief)
    edited_plan = plan.model_copy(update={"actionable_tasks": edited_tasks})
    csv_text = pd.DataFrame(tasks_to_dashboard_rows(edited_tasks)).to_csv(index=False)
    json_text = edited_plan.model_dump_json()

    assert edited_tasks[7].person_in_charge_role == "Human-assigned External Marshal"
    assert edited_tasks[7].operational_risk_level == "Medium"
    assert edited_tasks[7].ownership_review_required is False
    assert "Human-assigned External Marshal" in csv_text
    assert "Human-assigned External Marshal" in json_text


def test_ai_parsing_corrects_committee_owner_and_risk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    brief = sample_brief()
    plan = generate_demo_plan(brief)
    tasks = list(plan.actionable_tasks)
    traffic_index = next(
        index
        for index, task in enumerate(tasks)
        if "participant vehicle entry" in task.task
    )
    tasks[traffic_index] = tasks[traffic_index].model_copy(
        update={
            "person_in_charge_role": "Photography and Sound Team",
            "operational_risk_level": "Critical",
        }
    )
    invalid_plan = plan.model_copy(
        update={
            "recommended_committee_structure": [
                CommitteeRole(
                    role="Photography and Sound Team",
                    purpose="An invalid merged team.",
                    suggested_people=2,
                )
            ],
            "actionable_tasks": tasks,
            "committee_corrections": [],
            "ownership_corrections": [],
            "risk_corrections": [],
        }
    )

    monkeypatch.setattr(
        ai_service,
        "_openai_client",
        lambda: SimpleNamespace(
            responses=SimpleNamespace(
                parse=lambda **_: SimpleNamespace(output_parsed=invalid_plan)
            )
        ),
    )

    corrected = generate_operations_plan(brief)

    assert [role.role for role in corrected.recommended_committee_structure] == [
        item["role"] for item in SAMPLE_COMMITTEE
    ]
    assert (
        corrected.actionable_tasks[traffic_index].person_in_charge_role
        == "Equipment and Transport Team"
    )
    assert corrected.actionable_tasks[traffic_index].operational_risk_level == "High"
    assert corrected.committee_corrections
    assert corrected.ownership_corrections
    assert corrected.risk_corrections


def test_streamlit_sample_committee_persists_in_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "")
    app = AppTest.from_file("app.py", default_timeout=60).run()

    app.button[0].click().run()
    committee_rows = app.session_state["committee_structure"]
    app.run()

    assert len(committee_rows) == 11
    assert committee_rows[0]["lead"] == "Min Xuan"
    assert app.session_state["committee_structure"] == committee_rows
    assert not app.exception


def _committee_mismatch_warnings(app: AppTest) -> list[str]:
    return [
        str(warning.value)
        for warning in app.warning
        if "Committee role headcounts total" in str(warning.value)
    ]


def _sample_streamlit_app() -> AppTest:
    app = AppTest.from_file("app.py", default_timeout=60).run()
    app.button[0].click().run()
    return app


def test_streamlit_committee_warning_reacts_to_edit_add_and_delete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "")
    app = _sample_streamlit_app()

    assert app.dataframe[0].form_id == ""
    assert _committee_mismatch_warnings(app) == []

    app.session_state["committee_editor"] = {
        "edited_rows": {0: {"headcount": 7}},
        "added_rows": [],
        "deleted_rows": [],
    }
    app.run()

    assert app.session_state["committee_structure"][0]["headcount"] == 7
    edit_warnings = _committee_mismatch_warnings(app)
    assert len(edit_warnings) == 1
    assert "headcounts total 18" in edit_warnings[0]
    assert "committee size is 12" in edit_warnings[0]
    app.run()
    assert app.session_state["committee_structure"][0]["headcount"] == 7
    assert _committee_mismatch_warnings(app) == edit_warnings

    matching_app = _sample_streamlit_app()
    next(
        item
        for item in matching_app.number_input
        if item.label == "Committee size"
    ).set_value(18).run()
    assert _committee_mismatch_warnings(matching_app)
    matching_app.session_state["committee_editor"] = {
        "edited_rows": {0: {"headcount": 7}},
        "added_rows": [],
        "deleted_rows": [],
    }
    matching_app.run()

    assert matching_app.session_state["committee_structure"][0]["headcount"] == 7
    assert _committee_mismatch_warnings(matching_app) == []

    add_app = _sample_streamlit_app()
    add_app.session_state["committee_editor"] = {
        "edited_rows": {},
        "added_rows": [
            {
                "role": "Accessibility Team",
                "lead": "Aisyah",
                "headcount": 2,
                "responsibilities": "Coordinate accessibility support.",
            }
        ],
        "deleted_rows": [],
    }
    add_app.run()

    assert (
        add_app.session_state["committee_structure"][-1]["role"]
        == "Accessibility Team"
    )
    add_warnings = _committee_mismatch_warnings(add_app)
    assert len(add_warnings) == 1
    assert "headcounts total 14" in add_warnings[0]
    assert "committee size is 12" in add_warnings[0]

    delete_app = _sample_streamlit_app()
    delete_app.session_state["committee_editor"] = {
        "edited_rows": {},
        "added_rows": [],
        "deleted_rows": [0],
    }
    delete_app.run()

    assert all(
        row["role"] != "Chairperson"
        for row in delete_app.session_state["committee_structure"]
    )
    delete_warnings = _committee_mismatch_warnings(delete_app)
    assert len(delete_warnings) == 1
    assert "headcounts total 11" in delete_warnings[0]
    assert "committee size is 12" in delete_warnings[0]
    assert not app.exception
    assert not matching_app.exception
    assert not add_app.exception
    assert not delete_app.exception


def test_streamlit_generation_remains_allowed_with_committee_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "")
    app = _sample_streamlit_app()
    app.session_state["committee_editor"] = {
        "edited_rows": {0: {"headcount": 7}},
        "added_rows": [],
        "deleted_rows": [],
    }
    app.run()

    assert _committee_mismatch_warnings(app)
    next(
        button
        for button in app.button
        if button.label == "Generate operations plan"
    ).click().run()

    assert app.session_state["operations_plan"] is not None
    assert _committee_mismatch_warnings(app)
    assert not app.exception
