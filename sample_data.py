"""Sample event data supplied for the CivicOps AI demonstration."""

from __future__ import annotations

from datetime import date


SAMPLE_COMMITTEE: list[dict[str, object]] = [
    {
        "role": "Chairperson",
        "lead": "Min Xuan",
        "headcount": 1,
        "responsibilities": (
            "Coordinate protocol, food, venue, photography, sound, and overall "
            "committee decisions."
        ),
    },
    {
        "role": "Vice Chairperson",
        "lead": "Jun Seng",
        "headcount": 1,
        "responsibilities": (
            "Coordinate the exam, gift and prize, equipment, and transport workstreams."
        ),
    },
    {
        "role": "Secretary",
        "lead": "",
        "headcount": 1,
        "responsibilities": (
            "Prepare official documents, minutes, registrations, consent records, "
            "and the closing-ceremony emcee script."
        ),
    },
    {
        "role": "Treasurer",
        "lead": "Jack",
        "headcount": 1,
        "responsibilities": (
            "Manage the budget, receipts, income and expenditure statement, "
            "financial report, and reconciliation."
        ),
    },
    {
        "role": "Exam Team",
        "lead": "Xi An",
        "headcount": 2,
        "responsibilities": (
            "Prepare competition rules, written test materials, judges, scoring, "
            "results, and dispute handling."
        ),
    },
    {
        "role": "Food Team",
        "lead": "Xue Qian",
        "headcount": 1,
        "responsibilities": (
            "Plan meals, dietary needs, food quantities, food safety, and distribution."
        ),
    },
    {
        "role": "Venue and Marshalling Team",
        "lead": "Thein Jun",
        "headcount": 1,
        "responsibilities": (
            "Plan venue layout, participant walking flow, marshalling, crowd control, "
            "signage, and wet-weather arrangements."
        ),
    },
    {
        "role": "Equipment and Transport Team",
        "lead": "Hao Xuan",
        "headcount": 1,
        "responsibilities": (
            "Manage equipment preparation, checklists, sourcing, borrowing or "
            "purchasing, testing, setup, return, plus participant vehicle entry, "
            "drop-off, parking, waiting, and exit flow."
        ),
    },
    {
        "role": "Gift and Prize Team",
        "lead": "Cai Zhu",
        "headcount": 1,
        "responsibilities": (
            "Prepare gifts, prizes, trophies, certificates, presentation order, "
            "and recipient checks."
        ),
    },
    {
        "role": "Photography Team",
        "lead": "Mei Mei",
        "headcount": 1,
        "responsibilities": (
            "Manage photography consent, event photo coverage, image handling, "
            "and approved photo delivery."
        ),
    },
    {
        "role": "Sound System Team",
        "lead": "Rachel",
        "headcount": 1,
        "responsibilities": (
            "Prepare, test, operate, and pack down microphones, speakers, "
            "music playback, and the public-address system."
        ),
    },
]


SAMPLE_EVENT: dict[str, object] = {
    "organisation_type": "Bacang Youth volunteer team",
    "event_name": "Primary School Foot Drill and First Aid Knowledge Competition",
    "event_objective": (
        "Run a safe, educational, and well-coordinated inter-school competition that "
        "strengthens foot drill discipline and practical first-aid knowledge."
    ),
    "current_planning_date": date.today(),
    "event_date": date(2026, 10, 18),
    "venue": "SJK(C) Bacang, Melaka",
    "expected_participants": 70,
    "available_budget": 3_000.0,
    "committee_size": 12,
    "committee_structure": SAMPLE_COMMITTEE,
    "constraints_and_special_requirements": (
        "Components: written first-aid test, foot drill competition, meals, transport "
        "flow and closing ceremony. Plan for primary-school safeguarding, wet weather, "
        "food allergies, fair judging, and safe vehicle movement."
    ),
}
