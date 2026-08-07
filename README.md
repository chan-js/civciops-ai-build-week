# CivicOps AI

CivicOps AI is an AI operations copilot for volunteer organisations, student societies, and non-profit teams. It turns a short event brief into a validated, editable operating plan with accountable owners, deadlines, dependencies, risks, progress reviews, and portable exports.

This repository contains a deployed Streamlit MVP that can also be run locally, prepared as an OpenAI Build Week submission.

## Live project

- **Public demo:** https://civicops-ai-build-week.streamlit.app
- **Demo video:** https://youtu.be/Luz5fzLp4Zo

## The social problem

Small community teams often coordinate important events through a mixture of WhatsApp messages, spreadsheets, and documents. Information is easy to lose, ownership is ambiguous, dependencies are rarely visible, and safety or delivery risks may only emerge when there is little time to respond. CivicOps AI gives these teams one practical view of what must happen, who owns it, what is blocked, and what requires attention next.

## Features

- Structured event brief with required-field, range, and future-date validation
- One-click Bacang Youth sample for the Primary School Foot Drill and First Aid Knowledge Competition
- AI operations plans generated through the OpenAI Responses API and GPT-5.6 Sol
- Strict Pydantic validation for plans and progress reviews
- Deterministic Demo Mode that needs no API key or network connection
- Recommended committee structure scaled to the available team
- Editable task dashboard with PIC, deadline, priority, status, dependency, and risk
- Live metrics for total, completed, blocked, high-risk tasks, and completion percentage
- Progress review based on the edited dashboard rather than the original plan
- Risk register, recommended next actions, CSV task export, and JSON plan export
- Browser-local named projects with controlled autosave, refresh/reopen recovery,
  duplication, switching, and confirmed deletion
- Versioned full-project JSON backup and validated import, independent of the
  existing task CSV and operations-plan JSON exports
- Clear API-error fallback that keeps the complete workflow usable

## Architecture

```text
Streamlit interface (app.py)
        |
        +-- validated EventBrief
        |
        +-- AI Mode --> OpenAI Responses API --> Pydantic OperationsPlan / ProgressReview
        |
        +-- Demo Mode --> deterministic local planner --> same Pydantic schemas
        |
        +-- editable dashboard --> validated task models --> metrics, review, exports
        |
        +-- ProjectSnapshot schema --> static first-party browser component
                                      --> namespaced localStorage keys
```

- `app.py` contains the Streamlit presentation and session workflow.
- `ai_service.py` contains all schemas, OpenAI calls, deterministic planning, progress analysis, and dashboard transformations.
- `project_persistence.py` contains the versioned snapshot schema, deterministic
  JSON boundary, project-management helpers, lifecycle state machine, and
  storage-adapter implementation used by unit tests.
- `browser_storage_component/index.html` is a zero-build, repository-contained
  localStorage bridge. It needs no Node.js runtime in production.
- `sample_data.py` contains the supplied Build Week sample event.
- `tests/test_core.py` verifies the offline sample flow, dashboard edits, metrics, review, and JSON serialisation.

No server database, cloud project store, user account, or external messaging
integration is claimed or required for this MVP.

## Local project recovery

Projects are saved only in the current browser profile and device. The app first
hydrates the last active validated snapshot, then enables autosave; blank defaults
cannot be written while hydration is pending. A storage warning leaves the app
usable with the full-project JSON export/import fallback.

Browser keys use the `civicops-ai.v1.` namespace. Each snapshot is capped at
512 KB, the local catalog is capped at 20 projects, and imported JSON is parsed as
data only through strict Pydantic models. Snapshots contain safe Demo/AI/fallback
provenance categories, not API keys, secrets, environment variables, model
configuration, tokens, or deployment credentials.

See [Sprint 3 persistence and manual acceptance](docs/SPRINT_3_PERSISTENCE.md)
for the schema migration contract and browser test checklist.

## Setup

Python 3.10 or newer is recommended.

### Windows PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
streamlit run app.py
```

### macOS or Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
streamlit run app.py
```

Open the local address printed by Streamlit, normally `http://localhost:8501`.

## Run in Demo Mode

Demo Mode is automatic when `OPENAI_API_KEY` is absent or empty:

```powershell
Remove-Item Env:OPENAI_API_KEY -ErrorAction SilentlyContinue
streamlit run app.py
```

The page clearly displays **Demo Mode**. Load the Bacang Youth sample, generate the plan, edit task statuses or owners, select **Review Current Progress**, and download both exports. Demo output is deterministic, so the same validated input produces the same plan.

## Configure the OpenAI API

1. Copy `.env.example` to `.env`.
2. Put your own API key in `OPENAI_API_KEY`.
3. Optionally set `OPENAI_MODEL`; otherwise the app uses `gpt-5.6-sol`.
4. Restart Streamlit after changing environment variables.

```dotenv
OPENAI_API_KEY=your_key_here
OPENAI_MODEL=gpt-5.6-sol
```

The app never displays or hardcodes the key. `.env` and Streamlit secrets are excluded by `.gitignore`.

## How GPT-5.6 is used

The default model is the explicit model identifier `gpt-5.6-sol`. The integration uses the OpenAI Responses API with structured Pydantic outputs:

```python
response = client.responses.parse(
    model="gpt-5.6-sol",
    input=[...],
    reasoning={"effort": "low"},
    text_format=OperationsPlan,
)
plan = response.output_parsed
```

The application validates the parsed object again before using it. The same approach is used for progress reviews. The official references consulted during implementation were OpenAI's [GPT-5.6 model guidance](https://developers.openai.com/api/docs/guides/model-guidance?model=gpt-5.6), [GPT-5.6 Sol model page](https://developers.openai.com/api/docs/models/gpt-5.6-sol), [Structured Outputs guide](https://developers.openai.com/api/docs/guides/structured-outputs), and [Responses API migration guide](https://developers.openai.com/api/docs/guides/migrate-to-responses).

`OPENAI_MODEL` is intentionally supported for deployments whose OpenAI project uses a permitted snapshot or another compatible model. The default remains the requested GPT-5.6 Sol model.

## How Codex contributed

Codex was used as the primary engineering partner throughout the project.

It helped:

- Translate the original product brief into an MVP architecture
- Scaffold the Streamlit interface and application workflow
- Design the Pydantic schemas for operations plans and progress reviews
- Integrate the OpenAI Responses API with GPT-5.6 Sol
- Implement deterministic fallback planning and review logic
- Build task dependency, urgency-scoring, and dashboard transformation logic
- Generate and improve automated tests
- Diagnose structured-output validation failures
- Investigate differences between local and Streamlit Community Cloud behaviour
- Add sanitised cloud diagnostics without exposing credentials or tracebacks
- Identify the original 90-second API timeout and hidden retry behaviour
- Configure a 180-second read timeout with one controlled retry for `APITimeoutError`
- Reduce request latency by tightening output limits and using low reasoning effort
- Prepare clean deployment copies that excluded `.env`, Git metadata, virtual environments, caches, logs, and credentials

Codex was especially valuable during cloud deployment. When the application worked locally but timed out on Streamlit Community Cloud, Codex helped inspect the actual SDK configuration, add safe diagnostics, identify the timeout failure, implement controlled recovery, and verify the final result with automated tests.

Codex assisted with implementation and debugging, while the product concept, event context, operational requirements, testing decisions, and final deployment choices were directed and reviewed by the developer.

## Testing

The canonical suite covers:

- Core deterministic planning
- Dashboard edits and metrics
- Structured plan and progress-review validation
- Sanitised cloud diagnostics
- Safe user-facing error handling
- Timeout configuration
- Controlled retry behaviour
- Prevention of secret or traceback exposure
- Sprint 1 task add/delete, dependency cleanup, and deadline safety
- Sprint 2 committee-role, responsibility, ownership, and risk fidelity
- Sprint 3 snapshot round trips, browser-store semantics, import safety,
  hydration gating, autosave transitions, and fallback recovery

Run all offline tests:

```powershell
python -m pytest tests -q
```

Run a syntax check:

```powershell
python -m compileall app.py ai_service.py project_persistence.py sample_data.py tests
```

Run a headless startup smoke test:

```powershell
streamlit run app.py --server.headless true --server.port 8501
```

The automated tests require no API key and do not make network requests. A live AI-mode test requires a valid OpenAI API key, model access, network access, and available account limits.

## Limitations

- Projects persist only in the same browser profile and device; there is no
  cross-device synchronisation, shared persistence, or collaborative editing.
- Clearing browser data removes local projects unless the user exported a
  full-project JSON backup.
- Dependencies are displayed as task-name references and are not a full project-scheduling engine.
- AI recommendations still require committee judgement, especially for safeguarding, medical, legal, food-safety, and venue decisions.
- No WhatsApp, email, calendar, payment, school system, or supplier integration is implemented.
- CSV and JSON downloads are user-initiated; the app does not write operational data to disk automatically.
- Live AI quality and latency depend on API access and the selected model. Automated validation covers schema conformance, not factual confirmation of venue or supplier details.

## Future development

- Secure team workspaces with role-based access and an audit trail
- Cloud-synchronised team plans, version history, comments, and notifications
- Calendar and messaging integrations with explicit user authorisation
- Dependency graph and critical-path views
- Budget ledger and procurement approval workflow
- Reusable event templates and multilingual participant communications
- Post-event evaluation, outcome measurement, and organisational learning

## OpenAI Build Week submission notes

CivicOps AI demonstrates a complete path from an unstructured community-team problem to an accountable operational workflow. The submission highlights:

- GPT-5.6 structured reasoning applied to a socially useful coordination problem
- Reliable Responses API structured outputs rather than fragile free-form JSON parsing
- Human control through an editable dashboard
- A second AI pass grounded in live user edits
- A deterministic no-key experience for reliable judging and demonstration
- Transparent limitations with no fabricated third-party integrations

## Licence

Released under the MIT Licence. See [LICENSE](LICENSE).
