"""OpenAI and deterministic fallback services for CivicOps AI."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date, timedelta
from typing import ClassVar, Iterable, Literal

from openai import OpenAI
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    ValidationInfo,
    field_validator,
)


DEFAULT_MODEL = "gpt-5.6-sol"
STATUS_VALUES = ("Not started", "In progress", "Completed", "Blocked")
PRIORITY_VALUES = ("Low", "Medium", "High", "Critical")
RISK_VALUES = ("Low", "Medium", "High", "Critical")

Status = Literal["Not started", "In progress", "Completed", "Blocked"]
Priority = Literal["Low", "Medium", "High", "Critical"]
RiskLevel = Literal["Low", "Medium", "High", "Critical"]


def safe_bound_text(value: str, max_characters: int) -> str:
    """Compact and word-bound prose without weakening schema validation."""

    if max_characters < 2:
        raise ValueError("max_characters must be at least 2")
    compact = " ".join(value.split())
    if len(compact) <= max_characters:
        return compact

    available = max_characters - 1
    shortened = compact[:available].rstrip()
    word_boundary = shortened.rfind(" ")
    if word_boundary >= max(1, available // 2):
        shortened = shortened[:word_boundary].rstrip()
    shortened = shortened.rstrip(" ,;:-")
    return shortened + "…"


class StrictModel(BaseModel):
    """Base class that rejects unexpected AI output fields."""

    model_config = ConfigDict(extra="forbid")


class BoundedReviewModel(StrictModel):
    """Apply reusable text bounds before the declared Pydantic limits."""

    TEXT_BOUNDS: ClassVar[dict[str, int]] = {}
    TEXT_LIST_BOUNDS: ClassVar[dict[str, int]] = {}

    @field_validator("*", mode="before", check_fields=False)
    @classmethod
    def bound_review_text(
        cls, value: object, info: ValidationInfo
    ) -> object:
        text_limit = cls.TEXT_BOUNDS.get(info.field_name)
        if text_limit is not None and isinstance(value, str):
            return safe_bound_text(value, text_limit)

        item_limit = cls.TEXT_LIST_BOUNDS.get(info.field_name)
        if item_limit is not None and isinstance(value, list):
            return [
                safe_bound_text(item, item_limit) if isinstance(item, str) else item
                for item in value
            ]
        return value


class EventBrief(StrictModel):
    """Validated event details supplied by the user."""

    organisation_type: str = Field(min_length=2, max_length=120)
    event_name: str = Field(min_length=3, max_length=180)
    event_objective: str = Field(min_length=10, max_length=1_500)
    event_date: date
    venue: str = Field(min_length=2, max_length=200)
    expected_participants: int = Field(ge=1, le=100_000)
    available_budget: float = Field(ge=0, le=1_000_000_000)
    committee_size: int = Field(ge=1, le=1_000)
    constraints_and_special_requirements: str = Field(
        min_length=3, max_length=3_000
    )

    @field_validator(
        "organisation_type",
        "event_name",
        "event_objective",
        "venue",
        "constraints_and_special_requirements",
        mode="before",
    )
    @classmethod
    def strip_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("event_date")
    @classmethod
    def event_must_not_be_in_the_past(cls, value: date) -> date:
        if value < date.today():
            raise ValueError("Event date must be today or a future date.")
        return value


class CommitteeRole(StrictModel):
    role: str = Field(min_length=2, max_length=120)
    purpose: str = Field(min_length=5, max_length=500)
    suggested_people: int = Field(ge=1, le=100)


class ActionableTask(StrictModel):
    task: str = Field(min_length=3, max_length=240)
    person_in_charge_role: str = Field(max_length=120)
    deadline: date
    priority: Priority
    current_status: Status
    task_dependencies: list[str] = Field(max_length=20)
    operational_risk_level: RiskLevel

    @field_validator("task_dependencies")
    @classmethod
    def clean_dependencies(cls, value: list[str]) -> list[str]:
        return [item.strip() for item in value if item.strip() and item.strip() != "None"]


class RiskRegisterEntry(StrictModel):
    risk: str = Field(min_length=3, max_length=300)
    likelihood: RiskLevel
    impact: RiskLevel
    overall_level: RiskLevel
    mitigation: str = Field(min_length=5, max_length=700)
    owner_role: str = Field(min_length=1, max_length=120)


class OperationsPlan(StrictModel):
    event_brief: EventBrief
    plan_summary: str = Field(min_length=20, max_length=1_500)
    recommended_committee_structure: list[CommitteeRole] = Field(
        min_length=1, max_length=30
    )
    actionable_tasks: list[ActionableTask] = Field(min_length=1, max_length=100)
    operational_risk_level: RiskLevel
    risk_register: list[RiskRegisterEntry] = Field(min_length=1, max_length=50)
    recommended_next_actions: list[str] = Field(min_length=1, max_length=20)


class UrgentAction(BoundedReviewModel):
    TEXT_BOUNDS: ClassVar[dict[str, int]] = {
        "task": 240,
        "pic": 120,
        "recommended_action": 699,
        "why_urgent": 900,
        "work_that_can_proceed": 650,
        "work_that_must_wait": 650,
        "delay_reduction_preparation": 650,
    }
    TEXT_LIST_BOUNDS: ClassVar[dict[str, int]] = {
        "downstream_work_affected": 240,
        "active_blocking_prerequisites": 240,
    }

    task: str = Field(min_length=3, max_length=240)
    pic: str = Field(max_length=120)
    deadline: date
    urgency_score: int = Field(ge=0, le=300)
    recommended_action: str = Field(min_length=10, max_length=1_000)
    why_urgent: str = Field(min_length=10, max_length=1_000)
    downstream_work_affected: list[str] = Field(max_length=100)
    active_blocking_prerequisites: list[str] = Field(max_length=20)
    work_that_can_proceed: str = Field(min_length=5, max_length=700)
    work_that_must_wait: str = Field(min_length=5, max_length=700)
    delay_reduction_preparation: str = Field(min_length=5, max_length=700)


class BlockedDependencyChain(BoundedReviewModel):
    TEXT_BOUNDS: ClassVar[dict[str, int]] = {
        "blocking_task": 240,
        "responsible_pic": 120,
        "blocker_evidence": 450,
        "root_cause_analysis": 900,
        "operational_impact": 900,
        "recommended_escalation_action": 900,
    }
    TEXT_LIST_BOUNDS: ClassVar[dict[str, int]] = {
        "blocked_downstream_tasks": 240,
        "directly_affected_tasks": 240,
        "major_indirect_impacts": 240,
        "possible_root_causes": 240,
    }

    blocking_task: str = Field(min_length=3, max_length=240)
    blocked_downstream_tasks: list[str] = Field(min_length=1, max_length=100)
    directly_affected_tasks: list[str] = Field(max_length=3)
    major_indirect_impacts: list[str] = Field(max_length=2)
    additional_downstream_task_count: int = Field(ge=0, le=100)
    responsible_pic: str = Field(max_length=120)
    blocker_evidence: str = Field(min_length=5, max_length=500)
    possible_root_causes: list[str] = Field(max_length=20)
    root_cause_analysis: str = Field(min_length=5, max_length=1_000)
    operational_impact: str = Field(min_length=10, max_length=1_000)
    recommended_escalation_action: str = Field(min_length=10, max_length=1_000)


class IncreasingRisk(BoundedReviewModel):
    TEXT_BOUNDS: ClassVar[dict[str, int]] = {
        "risk": 300,
        "evidence": 900,
        "likely_impact": 900,
        "recommended_mitigation": 900,
    }

    risk: str = Field(min_length=5, max_length=300)
    evidence: str = Field(min_length=10, max_length=1_000)
    likely_impact: str = Field(min_length=10, max_length=1_000)
    recommended_mitigation: str = Field(min_length=10, max_length=1_000)


class OwnershipGap(BoundedReviewModel):
    TEXT_BOUNDS: ClassVar[dict[str, int]] = {
        "task": 240,
        "recommended_assignment_action": 650,
    }

    task: str = Field(min_length=3, max_length=240)
    current_status: Status
    deadline: date
    recommended_assignment_action: str = Field(min_length=10, max_length=700)


class MeetingAgendaItem(BoundedReviewModel):
    TEXT_BOUNDS: ClassVar[dict[str, int]] = {
        "task_or_workstream": 300,
        "relevant_pic": 120,
        "decision_or_action_required": 900,
        "deadline_or_escalation_point": 450,
    }

    task_or_workstream: str = Field(min_length=3, max_length=300)
    relevant_pic: str = Field(max_length=120)
    decision_or_action_required: str = Field(min_length=10, max_length=1_000)
    deadline_or_escalation_point: str = Field(min_length=3, max_length=500)


class ProgressReview(BoundedReviewModel):
    TEXT_BOUNDS: ClassVar[dict[str, int]] = {"executive_summary": 1_800}

    executive_summary: str = Field(min_length=20, max_length=2_000)
    three_most_urgent_actions: list[UrgentAction] = Field(max_length=3)
    active_blocked_dependency_chains: list[BlockedDependencyChain] = Field(
        max_length=30
    )
    increasing_risks: list[IncreasingRisk] = Field(max_length=30)
    ownership_gaps: list[OwnershipGap] = Field(max_length=30)
    suggested_meeting_agenda: list[MeetingAgendaItem] = Field(
        min_length=1, max_length=15
    )


class AIServiceError(RuntimeError):
    """A safe, user-facing error raised for OpenAI service failures."""


PLAN_INSTRUCTIONS = """You are an operations copilot for volunteer organisations,
student societies, and non-profit teams. Create a practical event operations plan in
British English. Preserve every supplied event detail exactly. Make tasks specific,
assign each task to a committee role, use ISO dates, include concrete dependencies,
and surface risks early. The recommended committee headcount should be realistic for
the supplied committee size. Do not invent external integrations or claim that an
approval, supplier, booking, or payment has already been completed. Return only the
structured result requested by the schema."""


REVIEW_INSTRUCTIONS = """You are reviewing the live, user-edited operations dashboard
for a volunteer or non-profit event. Use the edited statuses, owners, deadlines,
dependencies, priorities, risk levels, and supplied deterministic operational analysis
as the source of truth. Write concise British-English prose with short sentences. Do
not repeat task lists or restate dashboard rows.

Treat a dependency chain as blocked only when the prerequisite task is explicitly
Blocked, or when that prerequisite is overdue and incomplete. An ordinary incomplete
prerequisite is not an active blocked chain. Preserve the supplied active blocker list
and transparent urgency-score ordering exactly. When a blocked task has incomplete
ancestors, explain the possible root cause and prioritise that root cause before the
downstream symptom when resolving it is necessary to clear the blockage.

For urgent actions, state the task, PIC, deadline, score, why it is urgent, and affected
downstream work. Use direct natural language such as “Complete the venue approval by
2 August because it unlocks transport and rehearsal planning.” Never use the phrase
“move [task] forward”. Each recommended_action should normally be 250–600 characters
and must remain under 700 characters.

Never tell a downstream task owner to complete work that requires an unresolved
prerequisite. Separate work that can proceed independently, work that must wait, and
preparation that will reduce delay after the blocker clears. Keep the main downstream
impact concise: no more than three direct tasks, two major indirect impacts, and an
additional-task count such as “+ 17 additional downstream tasks”. Never place the full
transitive downstream-task list in any recommendation or narrative field. The full
list is supplied separately for the expandable interface section.

Increasing risks must cite dashboard evidence and give a likely impact and concrete
mitigation. Consider overdue work, active blockers, high/critical work near its
deadline, missing owners, overloaded critical-task owners, compressed dependency
timings, and unresolved work close to the event.

Every meeting-agenda item must name an actual task or workstream, its PIC, the decision
or action required, and a deadline or escalation point. Avoid generic project-management
language. Do not claim work is completed unless its status is Completed. Return only
the structured result requested by the schema."""


def get_model_name() -> str:
    """Return the configured model, falling back to the explicit GPT-5.6 Sol ID."""

    return os.getenv("OPENAI_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL


def has_api_key() -> bool:
    """Whether a non-empty API key is available in the process environment."""

    return bool(os.getenv("OPENAI_API_KEY", "").strip())


def _openai_client() -> OpenAI:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise AIServiceError("OPENAI_API_KEY is not configured.")
    return OpenAI(api_key=api_key, timeout=90.0, max_retries=2)


def generate_operations_plan(brief: EventBrief) -> OperationsPlan:
    """Generate and validate an operations plan with the Responses API."""

    try:
        response = _openai_client().responses.parse(
            model=get_model_name(),
            input=[
                {"role": "system", "content": PLAN_INSTRUCTIONS},
                {
                    "role": "user",
                    "content": "Create an operations plan for this validated event brief:\n"
                    + json.dumps(brief.model_dump(mode="json"), ensure_ascii=False),
                },
            ],
            reasoning={"effort": "medium"},
            text_format=OperationsPlan,
        )
        parsed = response.output_parsed
        if parsed is None:
            status = getattr(response, "status", "unknown")
            raise AIServiceError(
                f"OpenAI returned no structured plan (response status: {status})."
            )
        plan = (
            parsed
            if isinstance(parsed, OperationsPlan)
            else OperationsPlan.model_validate(parsed)
        )
        return plan.model_copy(update={"event_brief": brief})
    except AIServiceError:
        raise
    except ValidationError as exc:
        raise AIServiceError(
            "OpenAI returned a plan that did not pass schema validation."
        ) from exc
    except Exception as exc:
        raise AIServiceError(
            "The OpenAI request could not be completed. Check the API key, model "
            "access, network connection, and account limits."
        ) from exc


def review_current_progress(
    brief: EventBrief, tasks: list[ActionableTask]
) -> ProgressReview:
    """Review the edited dashboard with the Responses API and validate the result."""

    deterministic_analysis = generate_demo_progress_review(brief, tasks)
    payload = {
        "event_brief": brief.model_dump(mode="json"),
        "edited_dashboard_tasks": [task.model_dump(mode="json") for task in tasks],
        "review_date": date.today().isoformat(),
        "authoritative_operational_analysis": deterministic_analysis.model_dump(
            mode="json"
        ),
    }
    try:
        response = _openai_client().responses.parse(
            model=get_model_name(),
            input=[
                {"role": "system", "content": REVIEW_INSTRUCTIONS},
                {
                    "role": "user",
                    "content": "Review this current dashboard state:\n"
                    + json.dumps(payload, ensure_ascii=False),
                },
            ],
            reasoning={"effort": "medium"},
            text_format=ProgressReview,
        )
        parsed = response.output_parsed
        if parsed is None:
            status = getattr(response, "status", "unknown")
            raise AIServiceError(
                f"OpenAI returned no structured review (response status: {status})."
            )
        validated_review = (
            parsed
            if isinstance(parsed, ProgressReview)
            else ProgressReview.model_validate(parsed)
        )
        return validated_review.model_copy(
            update={
                "three_most_urgent_actions": deterministic_analysis.three_most_urgent_actions,
                "active_blocked_dependency_chains": deterministic_analysis.active_blocked_dependency_chains,
                "ownership_gaps": deterministic_analysis.ownership_gaps,
            }
        )
    except AIServiceError:
        raise
    except ValidationError as exc:
        raise AIServiceError(
            "OpenAI returned a progress review that did not pass schema validation."
        ) from exc
    except Exception as exc:
        raise AIServiceError(
            "The progress review request could not be completed. Check the API key, "
            "model access, network connection, and account limits."
        ) from exc


def _deadline(event_date: date, days_before: int) -> date:
    return event_date - timedelta(days=days_before)


def generate_demo_plan(brief: EventBrief) -> OperationsPlan:
    """Create a realistic deterministic plan without making any network request."""

    event_date = brief.event_date
    organisation = brief.organisation_type.lower()
    uses_volunteer_roles = any(
        marker in organisation
        for marker in ("volunteer", "student", "society", "youth", "club")
    )

    if uses_volunteer_roles:
        event_lead = "Chairperson"
        deputy_lead = "Vice Chairperson"
        secretariat_lead = "Secretary"
        finance_lead = "Treasurer"
        programme_lead = "Examination Lead"
        venue_lead = "Venue and Marshalling Lead"
        logistics_lead = "Equipment and Transport Lead"
        welfare_lead = "Food and Welfare Lead"
        safety_lead = "Safety and First Aid Lead"
        media_lead = "Media Lead"
        committee = [
            CommitteeRole(
                role=event_lead,
                purpose="Chair the committee, own key approvals, and make event-day escalation decisions.",
                suggested_people=1,
            ),
            CommitteeRole(
                role=deputy_lead,
                purpose="Coordinate workstreams, cover the Chairperson, and follow up overdue actions.",
                suggested_people=1,
            ),
            CommitteeRole(
                role=secretariat_lead,
                purpose="Maintain minutes, registrations, consent records, rosters, and committee communications.",
                suggested_people=1,
            ),
            CommitteeRole(
                role=finance_lead,
                purpose="Track the budget, approve purchases, retain receipts, and reconcile expenditure.",
                suggested_people=1,
            ),
            CommitteeRole(
                role=programme_lead,
                purpose="Prepare test materials, competition rules, judges, scoring, and results.",
                suggested_people=2,
            ),
            CommitteeRole(
                role=venue_lead,
                purpose="Plan the site layout, foot drill area, signage, crowd movement, and marshalling.",
                suggested_people=2,
            ),
            CommitteeRole(
                role=logistics_lead,
                purpose="Coordinate equipment, deliveries, arrivals, departures, and transport flow.",
                suggested_people=1,
            ),
            CommitteeRole(
                role=welfare_lead,
                purpose="Coordinate meals, dietary needs, participant comfort, and welfare support.",
                suggested_people=1,
            ),
            CommitteeRole(
                role=safety_lead,
                purpose="Own safeguarding, first-aid readiness, emergency procedures, and incident response.",
                suggested_people=1,
            ),
            CommitteeRole(
                role=media_lead,
                purpose="Prepare participant information, approved event updates, photography consent, and results communications.",
                suggested_people=1,
            ),
        ]
    else:
        event_lead = "Event Director"
        deputy_lead = "Deputy Event Director"
        secretariat_lead = "Operations Coordinator"
        finance_lead = "Finance and Procurement Lead"
        programme_lead = "Programme and Judging Lead"
        venue_lead = "Venue Operations Lead"
        logistics_lead = "Logistics and Transport Lead"
        welfare_lead = "Participant Welfare and Communications Lead"
        safety_lead = "Safety and First Aid Lead"
        media_lead = "Communications Lead"
        committee = [
            CommitteeRole(
                role=event_lead,
                purpose="Own the master plan, approvals, escalation decisions, and committee coordination.",
                suggested_people=1,
            ),
            CommitteeRole(
                role=programme_lead,
                purpose="Design competition flow, rules, judging, results, and the closing ceremony.",
                suggested_people=max(1, round(brief.committee_size * 0.22)),
            ),
            CommitteeRole(
                role=safety_lead,
                purpose="Own safeguarding, first-aid readiness, emergency procedures, and incident response.",
                suggested_people=max(1, round(brief.committee_size * 0.16)),
            ),
            CommitteeRole(
                role=logistics_lead,
                purpose="Coordinate venue layout, equipment, arrivals, departures, and movement on site.",
                suggested_people=max(1, round(brief.committee_size * 0.22)),
            ),
            CommitteeRole(
                role=finance_lead,
                purpose="Control the budget, purchasing records, supplier confirmations, and reconciliation.",
                suggested_people=1,
            ),
            CommitteeRole(
                role=welfare_lead,
                purpose="Manage registration, school liaison, meals, accessibility, and participant information.",
                suggested_people=max(1, brief.committee_size - 1),
            ),
        ]
        allocated = sum(role.suggested_people for role in committee[:-1])
        committee[-1] = committee[-1].model_copy(
            update={"suggested_people": max(1, brief.committee_size - allocated)}
        )

    if brief.committee_size == 1:
        combined_role = (
            "Chairperson (combined committee roles)"
            if uses_volunteer_roles
            else "Event Director (combined operations)"
        )
        event_lead = deputy_lead = secretariat_lead = combined_role
        finance_lead = programme_lead = venue_lead = combined_role
        logistics_lead = welfare_lead = safety_lead = media_lead = combined_role
        committee = [
            CommitteeRole(
                role=combined_role,
                purpose=(
                    "Hold the single accountable role across governance, programme, "
                    "finance, logistics, welfare, safety, and communications; obtain "
                    "external support for activities that require separation of duties."
                ),
                suggested_people=1,
            )
        ]

    tasks = [
        ActionableTask(
            task="Confirm committee roles and decision rights",
            person_in_charge_role=event_lead,
            deadline=_deadline(event_date, 84),
            priority="Critical",
            current_status="In progress",
            task_dependencies=[],
            operational_risk_level="Low",
        ),
        ActionableTask(
            task="Confirm venue scope, school liaison, and required approvals",
            person_in_charge_role=event_lead,
            deadline=_deadline(event_date, 77),
            priority="Critical",
            current_status="Not started",
            task_dependencies=["Confirm committee roles and decision rights"],
            operational_risk_level="High",
        ),
        ActionableTask(
            task="Approve safeguarding, medical, and emergency response plan",
            person_in_charge_role=safety_lead,
            deadline=_deadline(event_date, 70),
            priority="Critical",
            current_status="Not started",
            task_dependencies=["Confirm venue scope, school liaison, and required approvals"],
            operational_risk_level="Critical",
        ),
        ActionableTask(
            task="Finalise competition rules, scoring, and dispute process",
            person_in_charge_role=programme_lead,
            deadline=_deadline(event_date, 63),
            priority="High",
            current_status="Not started",
            task_dependencies=["Confirm venue scope, school liaison, and required approvals"],
            operational_risk_level="Medium",
        ),
        ActionableTask(
            task="Recruit and brief judges and first-aid assessors",
            person_in_charge_role=programme_lead,
            deadline=_deadline(event_date, 56),
            priority="High",
            current_status="Not started",
            task_dependencies=["Finalise competition rules, scoring, and dispute process"],
            operational_risk_level="High",
        ),
        ActionableTask(
            task="Approve itemised budget and procurement limits",
            person_in_charge_role=finance_lead,
            deadline=_deadline(event_date, 56),
            priority="High",
            current_status="Not started",
            task_dependencies=["Confirm committee roles and decision rights"],
            operational_risk_level="Medium",
        ),
        ActionableTask(
            task="Issue registration, consent, and participant information pack",
            person_in_charge_role=secretariat_lead,
            deadline=_deadline(event_date, 49),
            priority="High",
            current_status="Not started",
            task_dependencies=["Approve safeguarding, medical, and emergency response plan"],
            operational_risk_level="Medium",
        ),
        ActionableTask(
            task="Design arrival, parking, drop-off, and transport flow",
            person_in_charge_role=logistics_lead,
            deadline=_deadline(event_date, 42),
            priority="High",
            current_status="Not started",
            task_dependencies=["Confirm venue scope, school liaison, and required approvals"],
            operational_risk_level="Medium",
        ),
        ActionableTask(
            task="Confirm meal quantities, dietary needs, and food safety controls",
            person_in_charge_role=welfare_lead,
            deadline=_deadline(event_date, 35),
            priority="Medium",
            current_status="Not started",
            task_dependencies=["Issue registration, consent, and participant information pack"],
            operational_risk_level="Medium",
        ),
        ActionableTask(
            task="Lock venue layout, equipment list, signage, and wet-weather option",
            person_in_charge_role=venue_lead,
            deadline=_deadline(event_date, 28),
            priority="High",
            current_status="Not started",
            task_dependencies=[
                "Design arrival, parking, drop-off, and transport flow",
                "Finalise competition rules, scoring, and dispute process",
            ],
            operational_risk_level="Medium",
        ),
        ActionableTask(
            task="Prepare and securely control written first-aid test materials",
            person_in_charge_role=programme_lead,
            deadline=_deadline(event_date, 21),
            priority="High",
            current_status="Not started",
            task_dependencies=["Recruit and brief judges and first-aid assessors"],
            operational_risk_level="Low",
        ),
        ActionableTask(
            task="Run foot drill rehearsal and safety inspection",
            person_in_charge_role=safety_lead,
            deadline=_deadline(event_date, 18),
            priority="Critical",
            current_status="Not started",
            task_dependencies=[
                "Lock venue layout, equipment list, signage, and wet-weather option",
                "Approve safeguarding, medical, and emergency response plan",
            ],
            operational_risk_level="Critical",
        ),
        ActionableTask(
            task="Publish volunteer roster, briefing pack, and escalation contacts",
            person_in_charge_role=secretariat_lead,
            deadline=_deadline(event_date, 14),
            priority="High",
            current_status="Not started",
            task_dependencies=[
                "Lock venue layout, equipment list, signage, and wet-weather option"
            ],
            operational_risk_level="Low",
        ),
        ActionableTask(
            task="Confirm suppliers, deliveries, petty cash, and final budget position",
            person_in_charge_role=finance_lead,
            deadline=_deadline(event_date, 7),
            priority="Critical",
            current_status="Not started",
            task_dependencies=[
                "Approve itemised budget and procurement limits",
                "Confirm meal quantities, dietary needs, and food safety controls",
            ],
            operational_risk_level="Low",
        ),
        ActionableTask(
            task="Operate event command desk, check-ins, and incident log",
            person_in_charge_role=event_lead,
            deadline=event_date,
            priority="Critical",
            current_status="Not started",
            task_dependencies=[
                "Publish volunteer roster, briefing pack, and escalation contacts",
                "Run foot drill rehearsal and safety inspection",
                "Confirm suppliers, deliveries, petty cash, and final budget position",
            ],
            operational_risk_level="Critical",
        ),
        ActionableTask(
            task="Complete evaluation, financial reconciliation, and lessons review",
            person_in_charge_role=finance_lead,
            deadline=event_date + timedelta(days=7),
            priority="Medium",
            current_status="Not started",
            task_dependencies=["Operate event command desk, check-ins, and incident log"],
            operational_risk_level="Low",
        ),
    ]

    risks = [
        RiskRegisterEntry(
            risk="Participant injury, heat stress, or other medical incident during activities",
            likelihood="Medium",
            impact="Critical",
            overall_level="Critical",
            mitigation="Use a documented emergency plan, trained first-aid coverage, hydration points, rest breaks, and clear ambulance access.",
            owner_role=safety_lead,
        ),
        RiskRegisterEntry(
            risk="Wet weather or unsafe grounds disrupt the foot drill component",
            likelihood="Medium",
            impact="High",
            overall_level="High",
            mitigation="Set a weather decision time, inspect surfaces, reserve a sheltered alternative, and publish the change process.",
            owner_role=venue_lead,
        ),
        RiskRegisterEntry(
            risk="Traffic congestion creates unsafe arrival or dismissal conditions",
            likelihood="High",
            impact="High",
            overall_level="High",
            mitigation="Use staggered arrivals, marked vehicle routes, trained marshals, a pedestrian exclusion zone, and school-approved signage.",
            owner_role=logistics_lead,
        ),
        RiskRegisterEntry(
            risk="Food allergy, dietary mismatch, or delayed meal service affects participants",
            likelihood="Medium",
            impact="High",
            overall_level="High",
            mitigation="Collect dietary information early, confirm allergen labelling, retain supplier contacts, and keep safe contingency meals.",
            owner_role=welfare_lead,
        ),
        RiskRegisterEntry(
            risk="Scoring inconsistency or a dispute undermines confidence in results",
            likelihood="Medium",
            impact="High",
            overall_level="High",
            mitigation="Use approved rubrics, judge calibration, signed score sheets, a verification step, and a time-limited dispute route.",
            owner_role=programme_lead,
        ),
        RiskRegisterEntry(
            risk="Late procurement or cost growth exceeds the available budget",
            likelihood="Medium",
            impact="High",
            overall_level="High",
            mitigation="Maintain an itemised budget, require approval thresholds, confirm quotes, keep a contingency reserve, and review weekly.",
            owner_role=finance_lead,
        ),
        RiskRegisterEntry(
            risk="Insufficient volunteer coverage leaves critical posts unattended",
            likelihood="Medium",
            impact="High",
            overall_level="High",
            mitigation="Publish a named roster, identify backups for safety-critical posts, record attendance, and brief escalation cover.",
            owner_role=deputy_lead,
        ),
    ]

    budget_text = f"RM{brief.available_budget:,.2f}"
    return OperationsPlan(
        event_brief=brief,
        plan_summary=(
            f"A staged operations plan for {brief.event_name} at {brief.venue}, "
            f"serving approximately {brief.expected_participants} participants with a "
            f"{budget_text} budget and a committee of {brief.committee_size}. The plan "
            "prioritises school approval, safeguarding, fair competition delivery, "
            "participant welfare, controlled transport flow, and early risk escalation."
        ),
        recommended_committee_structure=committee,
        actionable_tasks=tasks,
        operational_risk_level="High",
        risk_register=risks,
        recommended_next_actions=[
            "Confirm the committee role allocation and named owners at the next meeting.",
            "Secure venue and school approvals before committing material expenditure.",
            "Approve the safeguarding and emergency response plan as an early critical gate.",
            "Set a weekly dashboard review cadence with owners updating status and blockers.",
            "Protect a budget contingency and record every procurement commitment.",
        ],
    )


def _is_unclear_owner(owner: str) -> bool:
    normalised = owner.strip().lower()
    return not normalised or normalised in {
        "tbc",
        "unassigned",
        "none",
        "unknown",
        "to be confirmed",
    }


def _format_date(value: date) -> str:
    return f"{value.day} {value.strftime('%B %Y')}"


def _human_list(values: list[str]) -> str:
    if not values:
        return ""
    if len(values) == 1:
        return values[0]
    if len(values) == 2:
        return f"{values[0]} and {values[1]}"
    return f"{', '.join(values[:-1])}, and {values[-1]}"


def _summarise_names(values: list[str], limit: int = 3) -> str:
    shown = values[:limit]
    summary = _human_list(shown)
    remaining = len(values) - len(shown)
    if remaining > 0:
        return f"{summary}, and {remaining} more"
    return summary


@dataclass(frozen=True)
class DownstreamImpactSummary:
    """Concise dependency impact plus the count hidden behind the full-list expander."""

    directly_affected_tasks: tuple[str, ...]
    major_indirect_impacts: tuple[str, ...]
    additional_downstream_task_count: int

    def as_sentence(self) -> str:
        direct = _human_list(
            [safe_bound_text(name, 60) for name in self.directly_affected_tasks]
        )
        indirect = _human_list(
            [safe_bound_text(name, 60) for name in self.major_indirect_impacts]
        )
        if not direct and not indirect:
            return "No recorded downstream task dependencies."
        parts = [f"Direct impacts: {direct or 'none recorded'}." ]
        if indirect:
            parts.append(f"Major indirect impacts: {indirect}.")
        if self.additional_downstream_task_count:
            parts.append(
                f"+ {self.additional_downstream_task_count} additional downstream tasks."
            )
        return " ".join(parts)


def _direct_downstream_map(
    tasks: list[ActionableTask],
) -> dict[str, list[ActionableTask]]:
    task_names = {task.task for task in tasks}
    downstream: dict[str, list[ActionableTask]] = {task.task: [] for task in tasks}
    for task in tasks:
        for dependency in task.task_dependencies:
            if dependency in task_names:
                downstream[dependency].append(task)
    return downstream


def _transitive_downstream_names(
    task_name: str, downstream: dict[str, list[ActionableTask]]
) -> list[str]:
    discovered: list[str] = []
    visited = {task_name}
    pending = list(downstream.get(task_name, []))
    while pending:
        task = pending.pop(0)
        if task.task in visited:
            continue
        visited.add(task.task)
        discovered.append(task.task)
        pending.extend(downstream.get(task.task, []))
    return discovered


def summarise_downstream_impacts(
    tasks: list[ActionableTask],
    task_name: str,
    affected_names: list[str] | None = None,
) -> DownstreamImpactSummary:
    """Select bounded direct and major indirect impacts without losing the full list."""

    downstream = _direct_downstream_map(tasks)
    task_lookup = {task.task: task for task in tasks}
    all_affected = list(
        dict.fromkeys(
            affected_names
            if affected_names is not None
            else _transitive_downstream_names(task_name, downstream)
        )
    )
    affected_set = set(all_affected)
    direct_all = [
        task.task
        for task in downstream.get(task_name, [])
        if task.task in affected_set
    ]
    directly_affected = direct_all[:3]
    direct_set = set(direct_all)
    indirect_all = [name for name in all_affected if name not in direct_set]
    impact_weight = {"Low": 0, "Medium": 1, "High": 2, "Critical": 3}
    major_indirect = sorted(
        indirect_all,
        key=lambda name: (
            -max(
                impact_weight[task_lookup[name].priority],
                impact_weight[task_lookup[name].operational_risk_level],
            )
            if name in task_lookup
            else 0,
            task_lookup[name].deadline if name in task_lookup else date.max,
            name,
        ),
    )[:2]
    additional_count = max(
        0,
        len(all_affected) - len(directly_affected) - len(major_indirect),
    )
    return DownstreamImpactSummary(
        directly_affected_tasks=tuple(directly_affected),
        major_indirect_impacts=tuple(major_indirect),
        additional_downstream_task_count=additional_count,
    )


def _incomplete_root_cause_paths(
    task_name: str, task_lookup: dict[str, ActionableTask]
) -> list[list[str]]:
    """Return root-to-symptom paths through incomplete upstream prerequisites."""

    paths: list[list[str]] = []

    def explore(current_name: str, reverse_path: list[str], visited: set[str]) -> None:
        current = task_lookup.get(current_name)
        if current is None:
            return
        incomplete_dependencies = [
            dependency
            for dependency in current.task_dependencies
            if dependency in task_lookup
            and task_lookup[dependency].current_status != "Completed"
            and dependency not in visited
        ]
        if not incomplete_dependencies:
            if len(reverse_path) > 1:
                paths.append(list(reversed(reverse_path)))
            return
        for dependency in incomplete_dependencies:
            explore(
                dependency,
                reverse_path + [dependency],
                visited | {dependency},
            )

    explore(task_name, [task_name], {task_name})
    return paths


def _root_cause_targets(tasks: list[ActionableTask]) -> dict[str, list[str]]:
    task_lookup = {task.task: task for task in tasks}
    targets: dict[str, list[str]] = {}
    for task in tasks:
        if task.current_status != "Blocked":
            continue
        for path in _incomplete_root_cause_paths(task.task, task_lookup):
            root_name = path[0]
            targets.setdefault(root_name, []).append(task.task)
    return targets


def _active_blocking_prerequisites(
    task: ActionableTask,
    task_lookup: dict[str, ActionableTask],
    as_of: date,
) -> list[str]:
    blocking: list[str] = []
    visited = {task.task}
    pending = list(task.task_dependencies)
    while pending:
        dependency_name = pending.pop(0)
        if dependency_name in visited:
            continue
        visited.add(dependency_name)
        dependency = task_lookup.get(dependency_name)
        if dependency is None:
            continue
        if _active_blocker_reason(dependency, as_of) is not None:
            blocking.append(dependency.task)
        pending.extend(dependency.task_dependencies)
    return blocking


def _active_blocker_reason(task: ActionableTask, as_of: date) -> str | None:
    if task.current_status == "Blocked":
        return "The prerequisite is explicitly marked Blocked."
    if task.current_status != "Completed" and task.deadline < as_of:
        days_overdue = (as_of - task.deadline).days
        return (
            f"The prerequisite is {days_overdue} day(s) overdue and remains "
            f"{task.current_status.lower()}."
        )
    return None


def _build_blocked_chains(
    tasks: list[ActionableTask], as_of: date
) -> list[BlockedDependencyChain]:
    downstream = _direct_downstream_map(tasks)
    task_lookup = {task.task: task for task in tasks}
    chains: list[BlockedDependencyChain] = []
    for task in tasks:
        reason = _active_blocker_reason(task, as_of)
        all_affected_names = _transitive_downstream_names(task.task, downstream)
        if reason is None or not all_affected_names:
            continue
        impact_summary = summarise_downstream_impacts(
            tasks, task.task, all_affected_names
        )
        directly_affected = list(impact_summary.directly_affected_tasks)
        major_indirect = list(impact_summary.major_indirect_impacts)
        additional_count = impact_summary.additional_downstream_task_count
        root_paths = _incomplete_root_cause_paths(task.task, task_lookup)
        possible_roots = list(dict.fromkeys(path[0] for path in root_paths))[:20]
        if root_paths:
            path_summary = "; ".join(
                " → ".join(path) for path in root_paths[:2]
            )
            root_analysis = (
                f"Incomplete upstream path(s) {path_summary} indicate that "
                f"{_human_list(possible_roots)} may need to be completed or resolved "
                f"before the blocker on {task.task} can clear."
            )
        else:
            root_analysis = (
                "No incomplete upstream prerequisite is recorded; the cause appears "
                "to sit within the blocking task or an external decision."
            )
        critical_affected = [
            name
            for name in all_affected_names
            if task_lookup[name].priority == "Critical"
            or task_lookup[name].operational_risk_level == "Critical"
        ]
        critical_text = (
            f" {len(critical_affected)} affected downstream task(s) are Critical."
            if critical_affected
            else ""
        )
        if task.current_status == "Blocked":
            escalation = (
                f"{task.person_in_charge_role or 'The committee chair'} should identify "
                "the constraint, assign an escalation owner, and agree a recovery date "
                f"by {_format_date(as_of + timedelta(days=1))}."
            )
        else:
            escalation = (
                f"{task.person_in_charge_role or 'The committee chair'} should confirm "
                "completion evidence or agree a dated recovery plan today, then re-baseline "
                "the affected downstream deadlines."
            )
        chains.append(
            BlockedDependencyChain(
                blocking_task=task.task,
                blocked_downstream_tasks=all_affected_names,
                directly_affected_tasks=directly_affected,
                major_indirect_impacts=major_indirect,
                additional_downstream_task_count=additional_count,
                responsible_pic=task.person_in_charge_role or "Unassigned",
                blocker_evidence=reason,
                possible_root_causes=possible_roots,
                root_cause_analysis=root_analysis,
                operational_impact=(
                    f"Directly affected: {_human_list(directly_affected)}. "
                    f"Major indirect impacts: {_human_list(major_indirect) or 'none identified'}. "
                    f"+ {additional_count} additional downstream task(s).{critical_text}"
                ),
                recommended_escalation_action=escalation,
            )
        )
    return chains


def _urgency_score(
    task: ActionableTask,
    as_of: date,
    downstream_count: int,
    blocks_critical_workstream: bool,
    root_cause_for_blocked_tasks: list[str],
) -> tuple[int, list[str]]:
    if task.current_status == "Completed":
        return 0, ["completed"]

    score = 0
    reasons: list[str] = []
    days_until = (task.deadline - as_of).days
    if days_until < 0:
        overdue_days = abs(days_until)
        score += 55 + min(overdue_days, 20)
        reasons.append(f"it is {overdue_days} day(s) overdue")
    elif days_until <= 3:
        score += 35
        reasons.append(f"the deadline is in {days_until} day(s)")
    elif days_until <= 7:
        score += 28
        reasons.append(f"the deadline is in {days_until} days")
    elif days_until <= 14:
        score += 20
        reasons.append(f"the deadline is in {days_until} days")
    elif days_until <= 30:
        score += 12
        reasons.append(f"the deadline is in {days_until} days")
    elif days_until <= 60:
        score += 6

    priority_points = {"Low": 0, "Medium": 10, "High": 20, "Critical": 30}
    risk_points = {"Low": 0, "Medium": 10, "High": 20, "Critical": 32}
    status_points = {"Not started": 14, "In progress": 5, "Blocked": 30, "Completed": 0}
    score += priority_points[task.priority]
    score += risk_points[task.operational_risk_level]
    score += status_points[task.current_status]

    if task.priority in {"High", "Critical"}:
        reasons.append(f"it has {task.priority.lower()} priority")
    if task.operational_risk_level in {"High", "Critical"}:
        reasons.append(
            f"it carries {task.operational_risk_level.lower()} operational risk"
        )
    if task.current_status == "Blocked":
        reasons.append("its status is Blocked")
    elif task.current_status == "Not started":
        reasons.append("work has not started")

    if downstream_count:
        score += min(downstream_count, 8) * 4
        reasons.append(f"{downstream_count} downstream task(s) depend on it")
    if blocks_critical_workstream:
        score += 25
        reasons.append("it is actively blocking a critical workstream")
    if root_cause_for_blocked_tasks:
        score += 65 + min(len(root_cause_for_blocked_tasks), 3) * 5
        reasons.append(
            "it is a possible root cause of blocked "
            + _human_list(root_cause_for_blocked_tasks)
        )
    if _is_unclear_owner(task.person_in_charge_role):
        score += 12
        reasons.append("it has no clear owner")
    return score, reasons


def _rank_open_tasks(
    tasks: list[ActionableTask], as_of: date
) -> list[tuple[ActionableTask, int, list[str], list[str]]]:
    downstream = _direct_downstream_map(tasks)
    task_lookup = {task.task: task for task in tasks}
    root_targets = _root_cause_targets(tasks)
    ranked: list[tuple[ActionableTask, int, list[str], list[str]]] = []
    for task in tasks:
        if task.current_status == "Completed":
            continue
        all_affected_names = _transitive_downstream_names(task.task, downstream)
        is_active_blocker = _active_blocker_reason(task, as_of) is not None
        blocks_critical = is_active_blocker and any(
            task_lookup[name].priority == "Critical"
            or task_lookup[name].operational_risk_level == "Critical"
            for name in all_affected_names
        )
        score, reasons = _urgency_score(
            task,
            as_of,
            len(all_affected_names),
            blocks_critical,
            root_targets.get(task.task, []),
        )
        ranked.append((task, score, reasons, all_affected_names))
    return sorted(
        ranked,
        key=lambda item: (-item[1], item[0].deadline, item[0].task),
    )


def _build_increasing_risks(
    brief: EventBrief,
    tasks: list[ActionableTask],
    as_of: date,
    blocked_chains: list[BlockedDependencyChain],
) -> list[IncreasingRisk]:
    risks: list[IncreasingRisk] = []
    seen: set[str] = set()

    def add_risk(
        key: str, risk: str, evidence: str, impact: str, mitigation: str
    ) -> None:
        if key in seen:
            return
        seen.add(key)
        risks.append(
            IncreasingRisk(
                risk=risk,
                evidence=evidence,
                likely_impact=impact,
                recommended_mitigation=mitigation,
            )
        )

    blocker_names = {chain.blocking_task for chain in blocked_chains}
    for chain in blocked_chains:
        add_risk(
            f"blocker:{chain.blocking_task}",
            f"Dependency blockage around {chain.blocking_task}",
            (
                f"{chain.blocker_evidence} Directly affected: "
                f"{_human_list(chain.directly_affected_tasks)}. Major indirect impacts: "
                f"{_human_list(chain.major_indirect_impacts) or 'none identified'}. "
                f"+ {chain.additional_downstream_task_count} additional task(s)."
            ),
            chain.operational_impact,
            chain.recommended_escalation_action,
        )

    open_tasks = [task for task in tasks if task.current_status != "Completed"]
    for task in open_tasks:
        days_until = (task.deadline - as_of).days
        if task.deadline < as_of and task.task not in blocker_names:
            add_risk(
                f"overdue:{task.task}",
                f"Overdue delivery: {task.task}",
                f"The task was due {_format_date(task.deadline)} and remains {task.current_status.lower()} under {task.person_in_charge_role or 'no assigned PIC'}.",
                "The missed date reduces recovery time and may force dependent work to overlap or be rushed.",
                f"{task.person_in_charge_role or 'The committee chair'} should agree a recovery date and completion evidence today.",
            )
        if (
            task.current_status == "Not started"
            and task.operational_risk_level in {"High", "Critical"}
            and 0 <= days_until <= 21
        ):
            add_risk(
                f"near-critical:{task.task}",
                f"Late start exposure: {task.task}",
                f"This {task.operational_risk_level.lower()}-risk task has not started and is due in {days_until} day(s) on {_format_date(task.deadline)}.",
                "A late start leaves little time to obtain approvals, test controls, or recover from rejection or rework.",
                f"{task.person_in_charge_role or 'The committee chair'} should confirm the first deliverable, support needed, and a dated check-in within 48 hours.",
            )
        if _is_unclear_owner(task.person_in_charge_role):
            add_risk(
                f"owner:{task.task}",
                f"Unowned work: {task.task}",
                f"The dashboard has no clear PIC for this {task.priority.lower()}-priority task due {_format_date(task.deadline)}.",
                "Decisions and follow-up may be missed because accountability is not explicit.",
                "Assign one accountable PIC at the next committee check-in and record their acceptance of the deadline.",
            )

    owner_load: dict[str, list[ActionableTask]] = {}
    for task in open_tasks:
        if _is_unclear_owner(task.person_in_charge_role):
            continue
        if task.priority == "Critical" or task.operational_risk_level == "Critical":
            owner_load.setdefault(task.person_in_charge_role, []).append(task)
    for owner, critical_tasks in owner_load.items():
        if len(critical_tasks) >= 3:
            names = [task.task for task in critical_tasks]
            add_risk(
                f"load:{owner}",
                f"Critical-task concentration under {owner}",
                f"{owner} owns {len(names)} open critical tasks: {_human_list(names)}.",
                "A delay or absence affecting one person could slow several critical decisions at once.",
                "Delegate preparation or deputy cover while keeping one named accountable owner for each task.",
            )

    task_lookup = {task.task: task for task in tasks}
    compressed_count = 0
    for downstream_task in open_tasks:
        for dependency_name in downstream_task.task_dependencies:
            prerequisite = task_lookup.get(dependency_name)
            if prerequisite is None or prerequisite.current_status == "Completed":
                continue
            available_gap = (downstream_task.deadline - prerequisite.deadline).days
            if available_gap <= 3 and compressed_count < 2:
                compressed_count += 1
                timing_evidence = (
                    f"The downstream deadline is {abs(available_gap)} day(s) before "
                    "the prerequisite deadline"
                    if available_gap < 0
                    else f"Only {available_gap} day(s) separate the prerequisite and downstream deadlines"
                )
                add_risk(
                    f"compressed:{dependency_name}:{downstream_task.task}",
                    f"Compressed hand-off from {dependency_name}",
                    f"{timing_evidence} for {downstream_task.task}, and both tasks remain incomplete.",
                    "Any slippage in the prerequisite transfers immediately to the downstream task with almost no recovery margin.",
                    f"{prerequisite.person_in_charge_role or 'The prerequisite PIC'} and {downstream_task.person_in_charge_role or 'the downstream PIC'} should agree an early hand-off checkpoint and contingency date.",
                )

    days_to_event = (brief.event_date - as_of).days
    if 0 <= days_to_event <= 14 and open_tasks:
        add_risk(
            "event-proximity",
            "Unresolved work close to the event date",
            f"{len(open_tasks)} task(s) remain incomplete with {days_to_event} day(s) until {brief.event_name}.",
            "Late unresolved work may force unsafe shortcuts, supplier changes, or programme reductions.",
            "Freeze non-essential scope, confirm readiness evidence for every critical task, and run daily exception reviews until the event.",
        )
    return risks[:30]


def _concise_recommended_action(value: str) -> str:
    """Keep deterministic recommendations useful, concise, and schema-safe."""

    compact = " ".join(value.split())
    if len(compact) < 250:
        compact += (
            " Record the accountable owner, immediate deliverable, completion evidence, "
            "and next checkpoint in the dashboard so the committee can verify progress."
        )
    if len(compact) < 250:
        compact += (
            " Escalate any decision that cannot be resolved at that checkpoint."
        )
    return safe_bound_text(compact, 600)


def generate_demo_progress_review(
    brief: EventBrief, tasks: list[ActionableTask]
) -> ProgressReview:
    """Perform deterministic dependency, urgency, risk, and ownership analysis."""

    as_of = date.today()
    task_lookup = {task.task: task for task in tasks}
    root_targets = _root_cause_targets(tasks)
    ranked = _rank_open_tasks(tasks, as_of)
    blocked_chains = _build_blocked_chains(tasks, as_of)
    urgent_actions: list[UrgentAction] = []
    for task, score, reasons, affected_names in ranked[:3]:
        owner = task.person_in_charge_role or "Unassigned"
        why = "; ".join(reasons) or "it is the next incomplete task by deadline"
        active_prerequisite_blockers = _active_blocking_prerequisites(
            task, task_lookup, as_of
        )
        root_paths = (
            _incomplete_root_cause_paths(task.task, task_lookup)
            if task.current_status == "Blocked"
            else []
        )
        possible_roots = list(dict.fromkeys(path[0] for path in root_paths))
        waiting_on = list(
            dict.fromkeys(active_prerequisite_blockers or possible_roots)
        )[:20]
        deadline_phrase = (
            f"without further delay; its original deadline was {_format_date(task.deadline)}"
            if task.deadline < as_of
            else f"by {_format_date(task.deadline)}"
        )
        impact_summary = summarise_downstream_impacts(
            tasks, task.task, affected_names
        )
        downstream_sentence = impact_summary.as_sentence()
        if waiting_on:
            blocker_summary = _summarise_names(waiting_on)
            work_that_can_proceed = (
                f"Complete the sections of {task.task} that do not require "
                f"{blocker_summary}."
            )
            work_that_must_wait = (
                f"Final approval, confirmation, and commitments that depend on "
                f"{blocker_summary} must wait until the blocker is resolved."
            )
            delay_reduction_preparation = (
                "Prepare draft content, evidence, checklists, questions, and provisional "
                "options so the remaining work can restart immediately after resolution."
            )
            recommended_action = _concise_recommended_action(
                f"{work_that_can_proceed} The PIC is {owner}, and the task deadline is "
                f"{_format_date(task.deadline)}. {downstream_sentence} "
                f"{work_that_must_wait} {delay_reduction_preparation} This is urgent "
                f"because {why}."
            )
        elif task.current_status == "Blocked":
            work_that_can_proceed = (
                f"Complete independent preparation, evidence gathering, and draft work "
                f"for {task.task}."
            )
            work_that_must_wait = (
                "Final completion must wait until the recorded external or task-level "
                "constraint is identified and resolved."
            )
            delay_reduction_preparation = (
                "Name an escalation owner, document the decision required, and prepare "
                "a recovery schedule for approval."
            )
            recommended_action = _concise_recommended_action(
                f"By {_format_date(as_of + timedelta(days=1))}, {owner} should identify "
                f"and escalate the unresolved constraint on {task.task}. "
                f"{downstream_sentence} {work_that_can_proceed} "
                f"{work_that_must_wait} {delay_reduction_preparation}"
            )
        else:
            if task.current_status == "Not started":
                action_verb = "Start and complete"
            else:
                action_verb = "Complete"
            work_that_can_proceed = "All recorded work for this task can proceed."
            work_that_must_wait = "No active prerequisite blocker requires this task to wait."
            delay_reduction_preparation = (
                "Confirm the next deliverable and completion evidence with the PIC."
            )
            recommended_action = _concise_recommended_action(
                f"{owner} should {action_verb.lower()} {task.task} {deadline_phrase}. "
                f"{downstream_sentence} This is urgent because {why}. Confirm the next "
                "deliverable, support required, completion evidence, and dashboard "
                "checkpoint with the committee."
            )
        urgent_actions.append(
            UrgentAction(
                task=task.task,
                pic=owner,
                deadline=task.deadline,
                urgency_score=score,
                recommended_action=recommended_action,
                why_urgent=why.capitalize() + ".",
                downstream_work_affected=affected_names,
                active_blocking_prerequisites=waiting_on,
                work_that_can_proceed=work_that_can_proceed,
                work_that_must_wait=work_that_must_wait,
                delay_reduction_preparation=delay_reduction_preparation,
            )
        )

    ownership_gaps = [
        OwnershipGap(
            task=task.task,
            current_status=task.current_status,
            deadline=task.deadline,
            recommended_assignment_action=(
                "Assign one accountable PIC at the next committee check-in and record "
                "their acceptance of the task and deadline."
            ),
        )
        for task in tasks
        if task.current_status != "Completed"
        and _is_unclear_owner(task.person_in_charge_role)
    ]
    increasing_risks = _build_increasing_risks(
        brief, tasks, as_of, blocked_chains
    )

    agenda: list[MeetingAgendaItem] = []
    agenda_tasks: set[str] = set()
    for chain in blocked_chains:
        for root_name in chain.possible_root_causes:
            if root_name in agenda_tasks or root_name not in task_lookup:
                continue
            root_task = task_lookup[root_name]
            agenda.append(
                MeetingAgendaItem(
                    task_or_workstream=root_task.task,
                    relevant_pic=root_task.person_in_charge_role or "Unassigned",
                    decision_or_action_required=(
                        f"Confirm what is required to complete this possible root cause "
                        f"and whether doing so will clear the blocker on {chain.blocking_task}."
                    ),
                    deadline_or_escalation_point=(
                        f"Agree completion or escalation by {_format_date(root_task.deadline)}."
                    ),
                )
            )
            agenda_tasks.add(root_name)

    for urgent in urgent_actions:
        task = task_lookup[urgent.task]
        if task.task in agenda_tasks:
            continue
        if urgent.active_blocking_prerequisites:
            decision = (
                f"Agree which sections can proceed independently, which must wait for "
                f"{_human_list(urgent.active_blocking_prerequisites)}, and what preparation "
                "will shorten the restart."
            )
        elif task.current_status == "Blocked":
            task_chain = next(
                (
                    chain
                    for chain in blocked_chains
                    if chain.blocking_task == task.task
                ),
                None,
            )
            possible_causes = task_chain.possible_root_causes if task_chain else []
            cause_text = (
                f" after reviewing {_human_list(possible_causes)} as possible upstream causes"
                if possible_causes
                else ""
            )
            decision = (
                f"Identify the blocker{cause_text}, name the escalation owner, and "
                "approve a recovery date plus independent preparation."
            )
        elif task.current_status == "Not started":
            decision = "Confirm immediate start, required support, and the first evidence of completion."
        else:
            decision = "Confirm the remaining work, completion evidence, and whether the deadline is still achievable."
        escalation_point = (
            f"Escalate at this meeting; original deadline was {_format_date(task.deadline)}."
            if task.deadline < as_of
            else f"Task deadline: {_format_date(task.deadline)}."
        )
        agenda.append(
            MeetingAgendaItem(
                task_or_workstream=task.task,
                relevant_pic=task.person_in_charge_role or "Unassigned",
                decision_or_action_required=decision,
                deadline_or_escalation_point=escalation_point,
            )
        )
        agenda_tasks.add(task.task)

    for chain in blocked_chains:
        if chain.blocking_task in agenda_tasks:
            continue
        agenda.append(
            MeetingAgendaItem(
                task_or_workstream=chain.blocking_task,
                relevant_pic=chain.responsible_pic,
                decision_or_action_required=chain.recommended_escalation_action,
                deadline_or_escalation_point=(
                    f"Escalation required by {_format_date(as_of + timedelta(days=1))}."
                ),
            )
        )
        agenda_tasks.add(chain.blocking_task)

    for gap in ownership_gaps:
        if gap.task in agenda_tasks:
            continue
        agenda.append(
            MeetingAgendaItem(
                task_or_workstream=gap.task,
                relevant_pic="Unassigned",
                decision_or_action_required=gap.recommended_assignment_action,
                deadline_or_escalation_point=f"Assign before {_format_date(gap.deadline)}.",
            )
        )
        agenda_tasks.add(gap.task)

    if not agenda:
        fallback_task = tasks[0]
        agenda.append(
            MeetingAgendaItem(
                task_or_workstream=fallback_task.task,
                relevant_pic=fallback_task.person_in_charge_role or "Unassigned",
                decision_or_action_required=(
                    "Confirm the recorded completion evidence and formally close the workstream."
                ),
                deadline_or_escalation_point=(
                    f"Close-out confirmation at this meeting; recorded deadline was {_format_date(fallback_task.deadline)}."
                ),
            )
        )

    completed_count = sum(task.current_status == "Completed" for task in tasks)
    overdue_count = sum(
        task.current_status != "Completed" and task.deadline < as_of for task in tasks
    )
    high_risk_count = sum(
        task.current_status != "Completed"
        and task.operational_risk_level in {"High", "Critical"}
        for task in tasks
    )
    urgent_names = [action.task for action in urgent_actions]
    blocker_summary = (
        f"{len(blocked_chains)} active blocked dependency chain(s) require escalation"
        if blocked_chains
        else "no active blocked dependency chains are detected"
    )
    focus_summary = (
        f"Immediate attention should focus on {_human_list(urgent_names)}."
        if urgent_names
        else "No incomplete tasks currently require urgent action."
    )
    executive_summary = (
        f"As of {_format_date(as_of)}, {completed_count} of {len(tasks)} tasks are "
        f"complete, {overdue_count} are overdue, and {high_risk_count} open tasks carry "
        f"High or Critical risk; {blocker_summary}. {focus_summary}"
    )
    return ProgressReview(
        executive_summary=executive_summary,
        three_most_urgent_actions=urgent_actions,
        active_blocked_dependency_chains=blocked_chains,
        increasing_risks=increasing_risks,
        ownership_gaps=ownership_gaps,
        suggested_meeting_agenda=agenda[:15],
    )


def tasks_to_dashboard_rows(tasks: Iterable[ActionableTask]) -> list[dict[str, object]]:
    """Map validated tasks to the user-facing editable table schema."""

    return [
        {
            "task": task.task,
            "PIC": task.person_in_charge_role,
            "deadline": task.deadline,
            "status": task.current_status,
            "priority": task.priority,
            "risk": task.operational_risk_level,
            "dependency": "; ".join(task.task_dependencies),
        }
        for task in tasks
    ]


def dashboard_rows_to_tasks(rows: Iterable[dict[str, object]]) -> list[ActionableTask]:
    """Validate user-edited dashboard rows back into the canonical task model."""

    tasks: list[ActionableTask] = []
    for row in rows:
        raw_dependencies = str(row.get("dependency", "") or "")
        dependencies = [part.strip() for part in raw_dependencies.split(";") if part.strip()]
        tasks.append(
            ActionableTask(
                task=str(row.get("task", "") or "").strip(),
                person_in_charge_role=str(row.get("PIC", "") or "").strip(),
                deadline=row.get("deadline"),
                priority=str(row.get("priority", "Medium")),
                current_status=str(row.get("status", "Not started")),
                task_dependencies=dependencies,
                operational_risk_level=str(row.get("risk", "Medium")),
            )
        )
    return tasks


def calculate_metrics(tasks: Iterable[ActionableTask]) -> dict[str, int | float]:
    """Calculate dashboard summary metrics from the current edited state."""

    task_list = list(tasks)
    total = len(task_list)
    completed = sum(task.current_status == "Completed" for task in task_list)
    blocked = sum(task.current_status == "Blocked" for task in task_list)
    high_risk = sum(
        task.operational_risk_level in {"High", "Critical"} for task in task_list
    )
    completion_percentage = (completed / total * 100.0) if total else 0.0
    return {
        "total_tasks": total,
        "completed_tasks": completed,
        "blocked_tasks": blocked,
        "high_risk_tasks": high_risk,
        "completion_percentage": completion_percentage,
    }
