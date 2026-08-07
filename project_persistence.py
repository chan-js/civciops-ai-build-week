"""Validated project snapshots and browser-storage-independent helpers.

The Streamlit application uses the models in this module at its trust boundary.
The small browser component mirrors the storage key layout, while these pure
helpers provide deterministic serialisation and an in-memory-testable adapter.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Literal, Protocol
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ai_service import OperationsPlan, ProgressReview


SCHEMA_VERSION = 1
MAX_LOCAL_PROJECTS = 20
MAX_SNAPSHOT_BYTES = 512_000
MAX_PROJECT_NAME_LENGTH = 80

STORAGE_PREFIX = "civicops-ai.v1."
PROJECT_INDEX_KEY = f"{STORAGE_PREFIX}project-index"
ACTIVE_PROJECT_KEY = f"{STORAGE_PREFIX}active-project-id"
PROJECT_KEY_PREFIX = f"{STORAGE_PREFIX}project."

PROJECT_ID_PATTERN = re.compile(r"^project-[0-9a-f]{32}$")
TASK_ID_PATTERN = re.compile(r"^task-[0-9a-f]{32}$")
CONTROL_CHARACTER_PATTERN = re.compile(r"[\x00-\x1f\x7f]")
SECRET_VALUE_PATTERN = re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b", re.IGNORECASE)

FORBIDDEN_FIELD_NAMES = frozenset(
    {
        "api_key",
        "openai_api_key",
        "streamlit_secrets",
        "secrets",
        "secret",
        "token",
        "authentication_token",
        "password",
        "environment",
        "environment_variables",
        "env",
        "model_configuration",
        "billing_configuration",
        "deployment_credentials",
    }
)

ProjectMode = Literal["demo", "ai", "fallback", "unknown"]
SaveStatus = Literal[
    "Loading projects",
    "Saved",
    "Unsaved changes",
    "Saving",
    "Storage error",
]
HydrationStatus = Literal["pending", "ready", "failed"]


class ProjectPersistenceError(ValueError):
    """A safe project validation, import, or storage failure."""


class UnsupportedSchemaVersionError(ProjectPersistenceError):
    """Raised when a snapshot needs a migration that is not implemented."""


class ProjectStorageError(ProjectPersistenceError):
    """Raised when the storage adapter is blocked, unavailable, or inconsistent."""


class StrictSnapshotModel(BaseModel):
    """Reject unknown data at every project snapshot boundary."""

    model_config = ConfigDict(extra="forbid")


class CommitteeRoleState(StrictSnapshotModel):
    """Editable committee data, including valid in-progress draft rows."""

    role: str = Field(default="", max_length=120)
    lead: str = Field(default="", max_length=120)
    headcount: int = Field(default=1, ge=1, le=1_000)
    responsibilities: str = Field(default="", max_length=1_000)

    @field_validator("role", "lead", "responsibilities", mode="before")
    @classmethod
    def normalise_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class EventBriefState(StrictSnapshotModel):
    """The exact editable event form, before or after plan generation."""

    organisation_type: str = Field(default="Volunteer organisation", max_length=120)
    event_name: str = Field(default="", max_length=180)
    event_objective: str = Field(default="", max_length=1_500)
    current_planning_date: date = Field(default_factory=date.today)
    event_date: date = Field(default_factory=lambda: date.today() + timedelta(days=90))
    venue: str = Field(default="", max_length=200)
    expected_participants: int = Field(default=50, ge=1, le=100_000)
    available_budget: float = Field(default=2_000.0, ge=0, le=1_000_000_000)
    committee_size: int = Field(default=10, ge=1, le=1_000)
    committee_structure: list[CommitteeRoleState] = Field(
        default_factory=list, max_length=50
    )
    constraints_and_special_requirements: str = Field(default="", max_length=3_000)

    @field_validator(
        "organisation_type",
        "event_name",
        "event_objective",
        "venue",
        "constraints_and_special_requirements",
        mode="before",
    )
    @classmethod
    def normalise_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class ProjectMetadata(StrictSnapshotModel):
    """Safe provenance categories; never stores credentials or model settings."""

    mode: ProjectMode = "unknown"
    plan_source: ProjectMode = "unknown"
    review_source: ProjectMode = "unknown"


def utc_now() -> datetime:
    """Return a consistently timezone-aware UTC timestamp."""

    return datetime.now(timezone.utc)


def new_project_id() -> str:
    """Create a stable UUID-style browser-local project identifier."""

    return f"project-{uuid4().hex}"


def validate_project_id(value: str) -> str:
    candidate = value.strip()
    if not PROJECT_ID_PATTERN.fullmatch(candidate):
        raise ProjectPersistenceError("Project ID is not a supported UUID-style ID.")
    return candidate


def validate_project_name(value: str) -> str:
    """Trim a project name and reject empty, unsafe, or oversized values."""

    candidate = value.strip()
    if not candidate:
        raise ProjectPersistenceError("Project name cannot be blank.")
    if len(candidate) > MAX_PROJECT_NAME_LENGTH:
        raise ProjectPersistenceError(
            f"Project name must be {MAX_PROJECT_NAME_LENGTH} characters or fewer."
        )
    if CONTROL_CHARACTER_PATTERN.search(candidate):
        raise ProjectPersistenceError("Project name contains unsupported characters.")
    if "<" in candidate or ">" in candidate:
        raise ProjectPersistenceError("Project name cannot contain angle brackets.")
    return candidate


class ProjectSnapshot(StrictSnapshotModel):
    """Complete, portable, versioned state for one CivicOps AI project."""

    schema_version: Literal[SCHEMA_VERSION] = SCHEMA_VERSION
    project_id: str
    project_name: str
    created_at: datetime
    updated_at: datetime
    event_brief: EventBriefState
    operations_plan: OperationsPlan | None = None
    progress_review: ProgressReview | None = None
    metadata: ProjectMetadata = Field(default_factory=ProjectMetadata)

    @field_validator("project_id", mode="before")
    @classmethod
    def valid_project_id(cls, value: object) -> str:
        if not isinstance(value, str):
            raise ValueError("Project ID must be text.")
        return validate_project_id(value)

    @field_validator("project_name", mode="before")
    @classmethod
    def valid_project_name(cls, value: object) -> str:
        if not isinstance(value, str):
            raise ValueError("Project name must be text.")
        return validate_project_name(value)

    @field_validator("created_at", "updated_at")
    @classmethod
    def require_utc_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Project timestamps must include a UTC offset.")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def validate_complete_snapshot(self) -> ProjectSnapshot:
        if self.updated_at < self.created_at:
            raise ValueError("Updated timestamp cannot precede created timestamp.")
        if self.progress_review is not None and self.operations_plan is None:
            raise ValueError("A progress review requires an operations plan.")
        if self.operations_plan is not None:
            task_ids = [task.task_id for task in self.operations_plan.actionable_tasks]
            if any(not TASK_ID_PATTERN.fullmatch(task_id) for task_id in task_ids):
                raise ValueError(
                    "Every saved task must have a supported UUID-style task ID."
                )
            if len(task_ids) != len(set(task_ids)):
                raise ValueError("Saved task IDs must be unique within a project.")
        return self


class ProjectSummary(StrictSnapshotModel):
    schema_version: Literal[SCHEMA_VERSION] = SCHEMA_VERSION
    project_id: str
    project_name: str
    updated_at: datetime

    @field_validator("project_id", mode="before")
    @classmethod
    def valid_project_id(cls, value: object) -> str:
        if not isinstance(value, str):
            raise ValueError("Project ID must be text.")
        return validate_project_id(value)

    @field_validator("project_name", mode="before")
    @classmethod
    def valid_project_name(cls, value: object) -> str:
        if not isinstance(value, str):
            raise ValueError("Project name must be text.")
        return validate_project_name(value)

    @field_validator("updated_at")
    @classmethod
    def require_utc_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Project timestamps must include a UTC offset.")
        return value.astimezone(timezone.utc)

    @classmethod
    def from_snapshot(cls, snapshot: ProjectSnapshot) -> ProjectSummary:
        return cls(
            project_id=snapshot.project_id,
            project_name=snapshot.project_name,
            updated_at=snapshot.updated_at,
        )


class ProjectIndex(StrictSnapshotModel):
    schema_version: Literal[SCHEMA_VERSION] = SCHEMA_VERSION
    projects: list[ProjectSummary] = Field(default_factory=list, max_length=MAX_LOCAL_PROJECTS)

    @model_validator(mode="after")
    def unique_project_ids(self) -> ProjectIndex:
        project_ids = [project.project_id for project in self.projects]
        if len(project_ids) != len(set(project_ids)):
            raise ValueError("Project index contains duplicate project IDs.")
        return self


def default_event_brief_state() -> EventBriefState:
    return EventBriefState()


def create_blank_project(
    name: str = "Untitled project", *, now: datetime | None = None
) -> ProjectSnapshot:
    timestamp = (now or utc_now()).astimezone(timezone.utc)
    return ProjectSnapshot(
        project_id=new_project_id(),
        project_name=validate_project_name(name),
        created_at=timestamp,
        updated_at=timestamp,
        event_brief=default_event_brief_state(),
        metadata=ProjectMetadata(),
    )


def unique_project_name(base_name: str, existing_names: set[str]) -> str:
    """Create a case-insensitively unique, bounded copy name."""

    base = validate_project_name(base_name)
    folded = {name.casefold() for name in existing_names}
    if base.casefold() not in folded:
        return base
    suffix_number = 2
    while True:
        suffix = " copy" if suffix_number == 2 else f" copy {suffix_number}"
        trimmed = base[: MAX_PROJECT_NAME_LENGTH - len(suffix)].rstrip()
        candidate = f"{trimmed}{suffix}"
        if candidate.casefold() not in folded:
            return candidate
        suffix_number += 1


def duplicate_project(
    snapshot: ProjectSnapshot,
    existing_names: set[str] | None = None,
    *,
    now: datetime | None = None,
) -> ProjectSnapshot:
    """Copy every editable field while assigning a new project identity."""

    timestamp = (now or utc_now()).astimezone(timezone.utc)
    name = unique_project_name(
        f"{snapshot.project_name} copy", existing_names or set()
    )
    return snapshot.model_copy(
        update={
            "project_id": new_project_id(),
            "project_name": name,
            "created_at": timestamp,
            "updated_at": timestamp,
        }
    )


def touch_snapshot(
    snapshot: ProjectSnapshot, *, now: datetime | None = None
) -> ProjectSnapshot:
    timestamp = (now or utc_now()).astimezone(timezone.utc)
    return snapshot.model_copy(update={"updated_at": timestamp})


def _normalise_forbidden_key(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value).casefold()).strip("_")


def _is_forbidden_key(value: object) -> bool:
    normalised = _normalise_forbidden_key(value)
    return (
        normalised in FORBIDDEN_FIELD_NAMES
        or normalised.endswith(("_api_key", "_token", "_secret", "_password"))
        or "credential" in normalised
    )


def reject_forbidden_fields(value: object, *, path: str = "project") -> None:
    """Reject secret-shaped object keys anywhere in imported JSON."""

    if isinstance(value, dict):
        for key, child in value.items():
            if _is_forbidden_key(key):
                raise ProjectPersistenceError(
                    f"Unsafe field '{key}' is not allowed in a project snapshot."
                )
            reject_forbidden_fields(child, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            reject_forbidden_fields(child, path=f"{path}[{index}]")
    elif isinstance(value, str) and SECRET_VALUE_PATTERN.search(value):
        raise ProjectPersistenceError(
            "Project text appears to contain an API key and cannot be persisted."
        )


def deterministic_snapshot_json(snapshot: ProjectSnapshot) -> str:
    """Serialise a validated snapshot deterministically and enforce its size."""

    payload = snapshot.model_dump(mode="json")
    reject_forbidden_fields(payload)
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    if len(encoded.encode("utf-8")) > MAX_SNAPSHOT_BYTES:
        raise ProjectPersistenceError(
            f"Project snapshot exceeds the {MAX_SNAPSHOT_BYTES // 1_000} KB limit."
        )
    return encoded


def snapshot_content_fingerprint(snapshot: ProjectSnapshot) -> str:
    """Hash meaningful state while ignoring the save timestamp itself."""

    payload = snapshot.model_dump(mode="json", exclude={"updated_at"})
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def parse_project_json(payload: bytes | str) -> ProjectSnapshot:
    """Validate a complete current-version snapshot without partial mutation."""

    raw = payload.encode("utf-8") if isinstance(payload, str) else payload
    if len(raw) > MAX_SNAPSHOT_BYTES:
        raise ProjectPersistenceError(
            f"Project import exceeds the {MAX_SNAPSHOT_BYTES // 1_000} KB limit."
        )
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ProjectPersistenceError("Project import must be UTF-8 JSON.") from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ProjectPersistenceError("Project import is not valid JSON.") from exc
    if not isinstance(data, dict):
        raise ProjectPersistenceError("Project import must contain one JSON object.")
    reject_forbidden_fields(data)
    version = data.get("schema_version")
    if version != SCHEMA_VERSION:
        raise UnsupportedSchemaVersionError(
            f"Unsupported project schema version {version!r}; this app supports "
            f"version {SCHEMA_VERSION}."
        )
    try:
        snapshot = ProjectSnapshot.model_validate(data)
    except Exception as exc:
        raise ProjectPersistenceError(
            "Project import failed complete snapshot validation."
        ) from exc
    deterministic_snapshot_json(snapshot)
    return snapshot


def resolve_imported_project(
    snapshot: ProjectSnapshot,
    existing_ids: set[str],
    existing_names: set[str],
    *,
    now: datetime | None = None,
) -> ProjectSnapshot:
    """Keep a portable ID when safe, or assign a new ID for a local collision."""

    if snapshot.project_id not in existing_ids:
        return snapshot
    timestamp = (now or utc_now()).astimezone(timezone.utc)
    return snapshot.model_copy(
        update={
            "project_id": new_project_id(),
            "project_name": unique_project_name(snapshot.project_name, existing_names),
            "created_at": timestamp,
            "updated_at": timestamp,
        }
    )


def safe_project_filename(snapshot: ProjectSnapshot, *, on_date: date | None = None) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", snapshot.project_name.casefold()).strip("-")
    slug = slug[:80].strip("-") or "civicops-project"
    stamp = (on_date or date.today()).isoformat()
    return f"{slug}-{stamp}-project.json"


class StorageAdapter(Protocol):
    def get_item(self, key: str) -> str | None: ...

    def set_item(self, key: str, value: str) -> None: ...

    def remove_item(self, key: str) -> None: ...


@dataclass
class InMemoryStorageAdapter:
    """A deterministic localStorage substitute for unit tests."""

    values: dict[str, str] = field(default_factory=dict)
    available: bool = True
    quota_bytes: int | None = None

    def _require_available(self) -> None:
        if not self.available:
            raise ProjectStorageError("Browser storage is unavailable or blocked.")

    def get_item(self, key: str) -> str | None:
        self._require_available()
        return self.values.get(key)

    def set_item(self, key: str, value: str) -> None:
        self._require_available()
        proposed = dict(self.values)
        proposed[key] = value
        total = sum(
            len(item_key.encode("utf-8")) + len(item_value.encode("utf-8"))
            for item_key, item_value in proposed.items()
        )
        if self.quota_bytes is not None and total > self.quota_bytes:
            raise ProjectStorageError("Browser storage quota was exceeded.")
        self.values[key] = value

    def remove_item(self, key: str) -> None:
        self._require_available()
        self.values.pop(key, None)


@dataclass(frozen=True)
class StoreHydration:
    summaries: tuple[ProjectSummary, ...]
    active_project_id: str | None
    active_snapshot: ProjectSnapshot | None
    warning: str | None = None


class LocalProjectStore:
    """Project management over a storage adapter with localStorage semantics."""

    def __init__(self, adapter: StorageAdapter):
        self.adapter = adapter

    @staticmethod
    def project_key(project_id: str) -> str:
        return f"{PROJECT_KEY_PREFIX}{validate_project_id(project_id)}"

    def _read_index(self) -> ProjectIndex:
        try:
            raw = self.adapter.get_item(PROJECT_INDEX_KEY)
        except ProjectStorageError:
            raise
        except Exception as exc:
            raise ProjectStorageError("Browser storage could not be read.") from exc
        if raw is None:
            return ProjectIndex()
        try:
            return ProjectIndex.model_validate_json(raw)
        except Exception as exc:
            raise ProjectStorageError("The local project index is invalid.") from exc

    def _write_index(self, index: ProjectIndex) -> None:
        payload = json.dumps(
            index.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        try:
            self.adapter.set_item(PROJECT_INDEX_KEY, payload)
        except ProjectStorageError:
            raise
        except Exception as exc:
            raise ProjectStorageError("The local project index could not be saved.") from exc

    def list_projects(self) -> list[ProjectSummary]:
        return sorted(
            self._read_index().projects,
            key=lambda item: (item.updated_at, item.project_id),
            reverse=True,
        )

    def load(self, project_id: str, *, make_active: bool = True) -> ProjectSnapshot:
        key = self.project_key(project_id)
        try:
            raw = self.adapter.get_item(key)
        except ProjectStorageError:
            raise
        except Exception as exc:
            raise ProjectStorageError("The selected local project could not be read.") from exc
        if raw is None:
            raise ProjectStorageError("The selected local project is missing.")
        snapshot = parse_project_json(raw)
        if snapshot.project_id != project_id:
            raise ProjectStorageError("The selected local project ID does not match its key.")
        if make_active:
            self.adapter.set_item(ACTIVE_PROJECT_KEY, project_id)
        return snapshot

    def save(self, snapshot: ProjectSnapshot) -> None:
        payload = deterministic_snapshot_json(snapshot)
        index = self._read_index()
        existing = {item.project_id: item for item in index.projects}
        if snapshot.project_id not in existing and len(existing) >= MAX_LOCAL_PROJECTS:
            raise ProjectStorageError(
                f"A maximum of {MAX_LOCAL_PROJECTS} local projects can be saved."
            )
        old_project = self.adapter.get_item(self.project_key(snapshot.project_id))
        old_index = self.adapter.get_item(PROJECT_INDEX_KEY)
        old_active = self.adapter.get_item(ACTIVE_PROJECT_KEY)
        existing[snapshot.project_id] = ProjectSummary.from_snapshot(snapshot)
        updated_index = ProjectIndex(projects=list(existing.values()))
        try:
            self.adapter.set_item(self.project_key(snapshot.project_id), payload)
            self._write_index(updated_index)
            self.adapter.set_item(ACTIVE_PROJECT_KEY, snapshot.project_id)
        except Exception as exc:
            try:
                if old_project is None:
                    self.adapter.remove_item(self.project_key(snapshot.project_id))
                else:
                    self.adapter.set_item(self.project_key(snapshot.project_id), old_project)
                if old_index is None:
                    self.adapter.remove_item(PROJECT_INDEX_KEY)
                else:
                    self.adapter.set_item(PROJECT_INDEX_KEY, old_index)
                if old_active is None:
                    self.adapter.remove_item(ACTIVE_PROJECT_KEY)
                else:
                    self.adapter.set_item(ACTIVE_PROJECT_KEY, old_active)
            except Exception:
                pass
            if isinstance(exc, ProjectStorageError):
                raise
            raise ProjectStorageError("The local project could not be saved.") from exc

    def hydrate(self) -> StoreHydration:
        summaries = tuple(self.list_projects())
        active_id = self.adapter.get_item(ACTIVE_PROJECT_KEY)
        if active_id is None:
            return StoreHydration(summaries, None, None)
        try:
            snapshot = self.load(active_id, make_active=False)
        except (ProjectPersistenceError, ProjectStorageError) as exc:
            return StoreHydration(
                summaries,
                active_id,
                None,
                "The last active project could not be restored. "
                "Other valid local projects remain available.",
            )
        return StoreHydration(summaries, active_id, snapshot)

    def delete(self, project_id: str, *, confirmation_project_id: str) -> ProjectSnapshot | None:
        """Delete exactly one confirmed ID and safely select the next project."""

        project_id = validate_project_id(project_id)
        if confirmation_project_id != project_id:
            raise ProjectStorageError("Project deletion confirmation did not match.")
        index = self._read_index()
        if project_id not in {item.project_id for item in index.projects}:
            raise ProjectStorageError("The selected local project no longer exists.")
        remaining = [item for item in index.projects if item.project_id != project_id]
        self._write_index(ProjectIndex(projects=remaining))
        self.adapter.remove_item(self.project_key(project_id))
        active_id = self.adapter.get_item(ACTIVE_PROJECT_KEY)
        if active_id != project_id:
            return self.load(active_id, make_active=False) if active_id else None
        if not remaining:
            self.adapter.remove_item(ACTIVE_PROJECT_KEY)
            return None
        next_summary = max(
            remaining, key=lambda item: (item.updated_at, item.project_id)
        )
        return self.load(next_summary.project_id, make_active=True)


@dataclass
class PersistenceLifecycle:
    """Small state machine that prevents saving before hydration completes."""

    hydration_status: HydrationStatus = "pending"
    save_status: SaveStatus = "Loading projects"
    dirty: bool = False
    saved_fingerprint: str | None = None
    error: str | None = None

    def mark_dirty(self) -> None:
        self.dirty = True
        if self.hydration_status == "ready":
            self.save_status = "Unsaved changes"

    def begin_save(self) -> None:
        if self.hydration_status != "ready":
            raise ProjectStorageError("Project hydration must finish before saving.")
        self.save_status = "Saving"

    def complete_hydration(self, snapshot: ProjectSnapshot | None) -> None:
        self.hydration_status = "ready"
        self.error = None
        self.dirty = snapshot is None
        self.saved_fingerprint = (
            snapshot_content_fingerprint(snapshot) if snapshot is not None else None
        )
        self.save_status = "Saved" if snapshot is not None else "Unsaved changes"

    def fail_hydration(self, message: str) -> None:
        self.hydration_status = "failed"
        self.save_status = "Storage error"
        self.error = message

    def complete_save(self, snapshot: ProjectSnapshot) -> None:
        if self.hydration_status != "ready":
            raise ProjectStorageError("Cannot complete a save before hydration.")
        self.saved_fingerprint = snapshot_content_fingerprint(snapshot)
        self.dirty = False
        self.save_status = "Saved"
        self.error = None

    def fail_save(self, message: str) -> None:
        self.dirty = True
        self.save_status = "Storage error"
        self.error = message
