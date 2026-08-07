"""Sprint 3 project snapshot, local store, and recovery coverage."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

import pytest

import ai_service
from ai_service import (
    EventBrief,
    add_task_to_plan,
    dashboard_rows_to_tasks,
    delete_task_from_plan,
    generate_demo_plan,
    generate_demo_progress_review,
    tasks_to_dashboard_rows,
)
from project_persistence import (
    ACTIVE_PROJECT_KEY,
    MAX_SNAPSHOT_BYTES,
    PROJECT_INDEX_KEY,
    EventBriefState,
    InMemoryStorageAdapter,
    LocalProjectStore,
    PersistenceLifecycle,
    ProjectMetadata,
    ProjectPersistenceError,
    ProjectSnapshot,
    ProjectStorageError,
    UnsupportedSchemaVersionError,
    create_blank_project,
    deterministic_snapshot_json,
    duplicate_project,
    new_project_id,
    parse_project_json,
    resolve_imported_project,
    safe_project_filename,
    snapshot_content_fingerprint,
    touch_snapshot,
    validate_project_name,
)
from sample_data import SAMPLE_EVENT


FIXED_NOW = datetime(2026, 8, 4, 7, 30, tzinfo=timezone.utc)


def sample_brief() -> EventBrief:
    data = dict(SAMPLE_EVENT)
    data["current_planning_date"] = date(2026, 8, 4)
    data["event_date"] = date(2026, 10, 18)
    return EventBrief.model_validate(data)


def complete_snapshot(
    *,
    name: str = "Bacang readiness",
    mode: str = "demo",
    include_review: bool = True,
) -> ProjectSnapshot:
    brief = sample_brief()
    plan = generate_demo_plan(brief)
    review = (
        generate_demo_progress_review(brief, plan.actionable_tasks)
        if include_review
        else None
    )
    return ProjectSnapshot(
        project_id=new_project_id(),
        project_name=name,
        created_at=FIXED_NOW,
        updated_at=FIXED_NOW,
        event_brief=EventBriefState.model_validate(brief.model_dump()),
        operations_plan=plan,
        progress_review=review,
        metadata=ProjectMetadata(
            mode=mode,
            plan_source=mode,
            review_source=mode if include_review else "unknown",
        ),
    )


def test_project_snapshot_serialisation_and_complete_round_trip() -> None:
    snapshot = complete_snapshot()

    payload = deterministic_snapshot_json(snapshot)
    restored = parse_project_json(payload)

    assert restored == snapshot
    assert deterministic_snapshot_json(restored) == payload
    assert restored.schema_version == 1
    assert restored.operations_plan is not None
    assert restored.progress_review is not None
    assert restored.event_brief.committee_structure
    assert restored.operations_plan.recommended_committee_structure
    assert restored.operations_plan.risk_register
    assert restored.operations_plan.recommended_next_actions


def test_schema_version_validation_and_unknown_fields_are_rejected() -> None:
    data = json.loads(deterministic_snapshot_json(complete_snapshot()))
    data["schema_version"] = 99
    with pytest.raises(UnsupportedSchemaVersionError, match="supports version 1"):
        parse_project_json(json.dumps(data))

    data["schema_version"] = 1
    data["unexpected"] = "not accepted"
    with pytest.raises(ProjectPersistenceError, match="complete snapshot validation"):
        parse_project_json(json.dumps(data))


def test_project_id_generation_is_uuid_style_and_unique() -> None:
    generated = {new_project_id() for _ in range(100)}

    assert len(generated) == 100
    assert all(identifier.startswith("project-") for identifier in generated)
    assert all(len(identifier) == 40 for identifier in generated)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  Community event  ", "Community event"),
        ("One", "One"),
    ],
)
def test_project_name_validation_trims_valid_names(raw: str, expected: str) -> None:
    assert validate_project_name(raw) == expected


@pytest.mark.parametrize(
    "raw",
    ["", "   ", "x" * 81, "unsafe<script>", "line\nbreak"],
)
def test_project_name_validation_rejects_invalid_names(raw: str) -> None:
    with pytest.raises(ProjectPersistenceError):
        validate_project_name(raw)


def test_duplicate_project_creates_new_identity_and_preserves_data() -> None:
    original = complete_snapshot()
    duplicate = duplicate_project(
        original,
        {original.project_name, f"{original.project_name} copy"},
        now=FIXED_NOW + timedelta(minutes=5),
    )

    assert duplicate.project_id != original.project_id
    assert duplicate.project_name != original.project_name
    assert duplicate.operations_plan == original.operations_plan
    assert duplicate.event_brief == original.event_brief
    assert duplicate.progress_review == original.progress_review
    assert duplicate.created_at == FIXED_NOW + timedelta(minutes=5)


def test_new_project_does_not_corrupt_an_existing_project() -> None:
    adapter = InMemoryStorageAdapter()
    store = LocalProjectStore(adapter)
    original = complete_snapshot()
    store.save(original)
    original_payload = deterministic_snapshot_json(original)

    new_project = create_blank_project("Second project", now=FIXED_NOW + timedelta(hours=1))
    store.save(new_project)

    assert deterministic_snapshot_json(store.load(original.project_id)) == original_payload
    assert store.load(new_project.project_id) == new_project
    assert len(store.list_projects()) == 2


def test_autosave_dirty_state_transitions_and_hydration_gate() -> None:
    lifecycle = PersistenceLifecycle()
    snapshot = complete_snapshot()

    lifecycle.mark_dirty()
    assert lifecycle.dirty is True
    assert lifecycle.save_status == "Loading projects"
    with pytest.raises(ProjectStorageError, match="hydration"):
        lifecycle.begin_save()

    lifecycle.complete_hydration(snapshot)
    assert lifecycle.hydration_status == "ready"
    assert lifecycle.save_status == "Saved"
    assert lifecycle.saved_fingerprint == snapshot_content_fingerprint(snapshot)

    lifecycle.mark_dirty()
    lifecycle.begin_save()
    assert lifecycle.save_status == "Saving"
    lifecycle.complete_save(touch_snapshot(snapshot, now=FIXED_NOW + timedelta(minutes=1)))
    assert lifecycle.save_status == "Saved"
    assert lifecycle.dirty is False


def test_hydration_restores_before_defaults_can_be_saved() -> None:
    adapter = InMemoryStorageAdapter()
    store = LocalProjectStore(adapter)
    restored = complete_snapshot(name="Restored exact project")
    restored = restored.model_copy(
        update={
            "event_brief": restored.event_brief.model_copy(
                update={
                    "event_name": "Exact recovered event",
                    "current_planning_date": date(2026, 8, 9),
                }
            )
        }
    )
    store.save(restored)

    hydration = store.hydrate()

    assert hydration.active_snapshot == restored
    assert hydration.active_snapshot.event_brief.event_name == "Exact recovered event"
    assert hydration.active_snapshot.event_brief != create_blank_project().event_brief
    assert adapter.get_item(ACTIVE_PROJECT_KEY) == restored.project_id


def test_active_project_selection_and_multiple_independent_projects() -> None:
    adapter = InMemoryStorageAdapter()
    store = LocalProjectStore(adapter)
    first = complete_snapshot(name="First")
    second = complete_snapshot(name="Second").model_copy(
        update={
            "created_at": FIXED_NOW + timedelta(hours=1),
            "updated_at": FIXED_NOW + timedelta(hours=1),
        }
    )
    store.save(first)
    store.save(second)

    assert store.hydrate().active_snapshot == second
    assert store.load(first.project_id) == first
    assert store.hydrate().active_snapshot == first
    assert {item.project_name for item in store.list_projects()} == {"First", "Second"}


def test_deletion_confirmation_and_deleting_active_project_safely() -> None:
    adapter = InMemoryStorageAdapter()
    store = LocalProjectStore(adapter)
    first = complete_snapshot(name="First")
    second = touch_snapshot(
        complete_snapshot(name="Second"), now=FIXED_NOW + timedelta(hours=1)
    )
    store.save(first)
    store.save(second)

    with pytest.raises(ProjectStorageError, match="confirmation"):
        store.delete(second.project_id, confirmation_project_id=first.project_id)
    assert store.load(second.project_id) == second

    replacement = store.delete(
        second.project_id, confirmation_project_id=second.project_id
    )
    assert replacement == first
    assert store.hydrate().active_snapshot == first
    assert [item.project_id for item in store.list_projects()] == [first.project_id]

    assert store.delete(first.project_id, confirmation_project_id=first.project_id) is None
    assert store.hydrate().active_snapshot is None
    assert store.list_projects() == []


def test_full_project_json_export_import_and_safe_filename() -> None:
    snapshot = complete_snapshot(name="Roadshow: North / South")
    exported = deterministic_snapshot_json(snapshot)
    imported = parse_project_json(exported.encode("utf-8"))

    assert imported == snapshot
    assert safe_project_filename(snapshot, on_date=date(2026, 8, 4)) == (
        "roadshow-north-south-2026-08-04-project.json"
    )


def test_malformed_unsupported_and_oversized_imports_are_rejected() -> None:
    with pytest.raises(ProjectPersistenceError, match="not valid JSON"):
        parse_project_json(b"{broken")
    with pytest.raises(ProjectPersistenceError, match="one JSON object"):
        parse_project_json(b"[]")

    unsupported = json.loads(deterministic_snapshot_json(complete_snapshot()))
    unsupported["schema_version"] = 2
    with pytest.raises(UnsupportedSchemaVersionError):
        parse_project_json(json.dumps(unsupported))

    oversized = b"{" + b" " * MAX_SNAPSHOT_BYTES + b"}"
    with pytest.raises(ProjectPersistenceError, match="exceeds"):
        parse_project_json(oversized)


def test_failed_import_does_not_mutate_current_state() -> None:
    current = complete_snapshot()
    active = current

    with pytest.raises(ProjectPersistenceError):
        candidate = parse_project_json("not-json")
        active = candidate

    assert active is current


def test_duplicate_imported_project_id_is_resolved_safely() -> None:
    imported = complete_snapshot(name="Portable project")
    resolved = resolve_imported_project(
        imported,
        {imported.project_id},
        {imported.project_name},
        now=FIXED_NOW + timedelta(days=1),
    )

    assert resolved.project_id != imported.project_id
    assert resolved.project_name != imported.project_name
    assert resolved.operations_plan == imported.operations_plan
    assert resolved.created_at == FIXED_NOW + timedelta(days=1)


def test_snapshot_never_serialises_api_keys_or_secret_fields() -> None:
    payload = deterministic_snapshot_json(complete_snapshot())
    folded = payload.casefold()

    assert "openai_api_key" not in folded
    assert "streamlit_secrets" not in folded
    assert "authentication_token" not in folded
    assert "model_configuration" not in folded

    unsafe = json.loads(payload)
    unsafe["OPENAI_API_KEY"] = "should-never-be-accepted"
    with pytest.raises(ProjectPersistenceError, match="Unsafe field"):
        parse_project_json(json.dumps(unsafe))

    unsafe = json.loads(payload)
    unsafe["access_token"] = "should-never-be-accepted"
    with pytest.raises(ProjectPersistenceError, match="Unsafe field"):
        parse_project_json(json.dumps(unsafe))

    secret_text = complete_snapshot().model_copy(
        update={
            "event_brief": complete_snapshot().event_brief.model_copy(
                update={"event_objective": "Accidentally pasted sk-example12345678901234567890"}
            )
        }
    )
    with pytest.raises(ProjectPersistenceError, match="API key"):
        deterministic_snapshot_json(secret_text)


def test_added_edited_deleted_tasks_and_dependency_fields_round_trip() -> None:
    base = complete_snapshot(include_review=False)
    assert base.operations_plan is not None
    plan = add_task_to_plan(base.operations_plan)
    rows = tasks_to_dashboard_rows(plan.actionable_tasks)
    added_id = rows[-1]["task_id"]
    dependency_name = str(rows[0]["task"])
    rows[-1].update(
        {
            "task": "Confirm accessible participant route",
            "PIC": "Venue and Marshalling Team",
            "deadline": date(2026, 9, 1),
            "status": "In progress",
            "priority": "High",
            "risk": "High",
            "dependency": dependency_name,
        }
    )
    edited = dashboard_rows_to_tasks(rows, brief=plan.event_brief)
    edited_plan = plan.model_copy(update={"actionable_tasks": edited})
    deleted_id = edited_plan.actionable_tasks[1].task_id
    deleted_name = edited_plan.actionable_tasks[1].task
    final_plan = delete_task_from_plan(edited_plan, deleted_id).plan
    snapshot = base.model_copy(update={"operations_plan": final_plan})

    restored = parse_project_json(deterministic_snapshot_json(snapshot))
    assert restored.operations_plan is not None
    restored_by_id = {
        task.task_id: task for task in restored.operations_plan.actionable_tasks
    }
    added = restored_by_id[str(added_id)]
    assert added.task == "Confirm accessible participant route"
    assert added.person_in_charge_role == "Venue and Marshalling Team"
    assert added.deadline == date(2026, 9, 1)
    assert added.current_status == "In progress"
    assert added.priority == "High"
    assert added.operational_risk_level == "High"
    assert added.task_dependencies == [dependency_name]
    assert deleted_id not in restored_by_id
    assert all(
        deleted_name not in task.task_dependencies
        for task in restored.operations_plan.actionable_tasks
    )


def test_committee_roles_and_editable_event_fields_round_trip() -> None:
    snapshot = complete_snapshot()
    edited_brief = snapshot.event_brief.model_copy(
        update={
            "event_name": "Edited event name",
            "current_planning_date": date(2026, 8, 12),
            "committee_structure": [
                snapshot.event_brief.committee_structure[0].model_copy(
                    update={
                        "lead": "New Chair",
                        "responsibilities": "Own final decisions and escalation.",
                    }
                ),
                *snapshot.event_brief.committee_structure[1:],
            ],
        }
    )
    edited = snapshot.model_copy(update={"event_brief": edited_brief})

    restored = parse_project_json(deterministic_snapshot_json(edited))
    assert restored.event_brief.event_name == "Edited event name"
    assert restored.event_brief.current_planning_date == date(2026, 8, 12)
    assert restored.event_brief.committee_structure[0].lead == "New Chair"
    assert "final decisions" in (
        restored.event_brief.committee_structure[0].responsibilities
    )


@pytest.mark.parametrize("mode", ["demo", "ai"])
def test_restoration_never_calls_the_api(
    monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    snapshot = complete_snapshot(mode=mode)

    def unexpected_api_call(*_: object, **__: object) -> None:
        raise AssertionError("restoration must not call the API")

    monkeypatch.setattr(ai_service, "generate_operations_plan", unexpected_api_call)
    monkeypatch.setattr(ai_service, "review_current_progress", unexpected_api_call)

    restored = parse_project_json(deterministic_snapshot_json(snapshot))
    assert restored.operations_plan == snapshot.operations_plan
    assert restored.progress_review == snapshot.progress_review
    assert restored.metadata.mode == mode


def test_browser_storage_failure_keeps_manual_json_fallback_available() -> None:
    snapshot = complete_snapshot()
    adapter = InMemoryStorageAdapter(available=False)
    store = LocalProjectStore(adapter)

    with pytest.raises(ProjectStorageError, match="unavailable"):
        store.hydrate()

    exported = deterministic_snapshot_json(snapshot)
    assert parse_project_json(exported) == snapshot


def test_quota_failure_does_not_corrupt_an_existing_saved_project() -> None:
    first = complete_snapshot(name="Original")
    adapter = InMemoryStorageAdapter()
    store = LocalProjectStore(adapter)
    store.save(first)
    original_project_payload = adapter.get_item(store.project_key(first.project_id))
    original_index = adapter.get_item(PROJECT_INDEX_KEY)
    current_size = sum(
        len(key.encode()) + len(value.encode()) for key, value in adapter.values.items()
    )
    adapter.quota_bytes = current_size + 50

    with pytest.raises(ProjectStorageError, match="quota"):
        store.save(complete_snapshot(name="Too large for remaining quota"))

    assert adapter.get_item(store.project_key(first.project_id)) == original_project_payload
    assert adapter.get_item(PROJECT_INDEX_KEY) == original_index
    assert store.hydrate().active_snapshot == first
