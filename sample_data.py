"""Sample event data supplied for the CivicOps AI demonstration."""

from __future__ import annotations

from datetime import date


SAMPLE_EVENT: dict[str, object] = {
    "organisation_type": "Bacang Youth volunteer team",
    "event_name": "Primary School Foot Drill and First Aid Knowledge Competition",
    "event_objective": (
        "Run a safe, educational, and well-coordinated inter-school competition that "
        "strengthens foot drill discipline and practical first-aid knowledge."
    ),
    "event_date": date(2026, 10, 18),
    "venue": "SJK(C) Bacang, Melaka",
    "expected_participants": 70,
    "available_budget": 3_000.0,
    "committee_size": 12,
    "constraints_and_special_requirements": (
        "Components: written first-aid test, foot drill competition, meals, transport "
        "flow and closing ceremony. Plan for primary-school safeguarding, wet weather, "
        "food allergies, fair judging, and safe vehicle movement."
    ),
}
