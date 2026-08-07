# Sprint 3 persistence and manual acceptance

## Storage architecture

CivicOps AI stores validated project snapshots in browser `localStorage` through
the repository-contained static component in
`browser_storage_component/index.html`. The deployed component is plain HTML and
JavaScript and has no Node.js runtime or third-party persistence dependency.

All keys are scoped to the `civicops-ai.v1.` namespace:

- `civicops-ai.v1.project-index` contains bounded project summaries.
- `civicops-ai.v1.active-project-id` identifies the most recently opened project.
- `civicops-ai.v1.project.<project-id>` contains one deterministic snapshot.

The Python trust boundary in `project_persistence.py` validates every snapshot
before save and after restore. The browser component performs a second set of
basic size, version, ID, and forbidden-field checks before writing.

## Hydration and autosave sequence

1. Streamlit creates volatile blank defaults and enters `pending` hydration.
2. The browser component discovers the project index and last active snapshot.
3. Python validates the complete snapshot before changing editable session state.
4. Only a successful hydration or a confirmed empty store moves persistence to
   `ready`.
5. Autosave compares a content fingerprint that excludes `updated_at`; it writes
   only after a committed edit changes meaningful project data.
6. A failed write blocks automatic retry loops and exposes **Save now** for an
   explicit retry.

The event form remains usable if storage is blocked, but no default project is
saved before hydration finishes. Restoring a Demo or AI project assigns a safe
restored-source label and never invokes plan generation or progress review.

## Snapshot schema and migration contract

Current schema version: `1`.

Version 1 contains project identity and UTC timestamps, exact editable event-form
state, structured committee rows, the validated operations plan (generated
committee, editable tasks, owners, deadlines, status, priority, risk,
dependencies, risk register, next actions, and correction/review flags), optional
progress-review state, and safe categorical source metadata.

Unknown fields and unsupported versions are rejected. Future schema changes must:

1. Add a new explicit schema model and deterministic migration function in
   `project_persistence.py`.
2. Parse the old schema with its own strict model before migration.
3. Migrate in memory without modifying the active project on failure.
4. Validate the complete current schema and size limit after migration.
5. Add fixtures and round-trip tests for every supported source version.
6. Preserve project and task IDs unless a documented collision requires a new ID.

No implicit best-effort migration is allowed at the storage boundary.

## Security and limits

- Maximum 20 indexed local projects, subject to the browser's smaller quota.
- Maximum 512 KB UTF-8 JSON per snapshot/import.
- Strict JSON parsing only; imported content is never evaluated or rendered as
  unsafe HTML.
- Project names are trimmed, bounded, and reject control characters and angle
  brackets; export filenames are slugged.
- Unknown object fields and secret-shaped field names are rejected recursively.
- Snapshots never contain API keys, Streamlit secrets, environment variables,
  authentication tokens, model configuration, billing settings, or deployment
  credentials.
- Browser failures never fall back to a shared server filesystem or SQLite.

## Manual acceptance checklist

Run locally and repeat the refresh/reopen checks in the deployed Streamlit app:

- [ ] Open the app in a browser with no existing CivicOps keys; confirm hydration
  finishes before the first project reports **Saved**.
- [ ] Name a project, load the Bacang sample, generate a Demo plan, edit the event
  brief, planning date, committee roles, and several task fields.
- [ ] Add a task, give it an owner/deadline/status/priority/risk/dependency, delete
  another task, and confirm dangling dependencies are removed.
- [ ] Wait for **Saved**, refresh, and confirm every edit and generated plan is
  restored without another plan-generation request.
- [ ] Close the tab, reopen the same app URL in the same browser profile, and
  confirm the same active project returns.
- [ ] Create a new project; confirm the prior project remains in the local project
  selector.
- [ ] Duplicate a saved project; confirm the copy has a distinct name/ID and edits
  to either project do not affect the other.
- [ ] Switch between at least two projects and confirm independent event, committee,
  task, risk, and review state.
- [ ] Attempt deletion without confirmation; confirm the button is disabled. Then
  confirm and delete the active project; verify another valid project or a safe
  blank project loads.
- [ ] Export the distinct full-project JSON backup, import it successfully, and
  confirm a duplicate local project ID is resolved to a new ID.
- [ ] Try malformed JSON, an unsupported `schema_version`, an oversized file, an
  unknown field, and a secret-shaped field; confirm none changes the active project.
- [ ] Block browser storage (or use a private policy that disables it); confirm a
  clear warning appears and full-project JSON export/import remains usable.
- [ ] In Demo Mode, restore a generated plan and review and confirm no network/API
  request is made.
- [ ] In AI Mode, restore a generated plan and review and confirm no OpenAI request
  is made until the user explicitly generates or reviews again.
- [ ] Clear browser data only after exporting a backup; confirm the limitation
  notice accurately explains that local projects will be removed.
