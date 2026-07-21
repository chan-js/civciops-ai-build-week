# CivicOps AI

CivicOps AI is an AI operations copilot for volunteer organisations, student societies, and non-profit teams. It turns a short event brief into a validated, editable operating plan with accountable owners, deadlines, dependencies, risks, progress reviews, and portable exports.

This repository is a complete local Streamlit MVP prepared as an OpenAI Build Week submission.

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
```

- `app.py` contains the Streamlit presentation and session workflow.
- `ai_service.py` contains all schemas, OpenAI calls, deterministic planning, progress analysis, and dashboard transformations.
- `sample_data.py` contains the supplied Build Week sample event.
- `tests/test_core.py` verifies the offline sample flow, dashboard edits, metrics, review, and JSON serialisation.

No database or external messaging integration is claimed or required for this MVP.

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

The default model is the explicit GPT-5.6 flagship identifier `gpt-5.6-sol`. OpenAI also documents `gpt-5.6` as an alias that routes to Sol. The integration uses the current Python Responses API structured-output pattern:

```python
response = client.responses.parse(
    model="gpt-5.6-sol",
    input=[...],
    reasoning={"effort": "medium"},
    text_format=OperationsPlan,
)
plan = response.output_parsed
```

The application validates the parsed object again before using it. The same approach is used for progress reviews. The official references consulted during implementation were OpenAI's [GPT-5.6 model guidance](https://developers.openai.com/api/docs/guides/model-guidance?model=gpt-5.6), [GPT-5.6 Sol model page](https://developers.openai.com/api/docs/models/gpt-5.6-sol), [Structured Outputs guide](https://developers.openai.com/api/docs/guides/structured-outputs), and [Responses API migration guide](https://developers.openai.com/api/docs/guides/migrate-to-responses).

`OPENAI_MODEL` is intentionally supported for deployments whose OpenAI project uses a permitted snapshot or another compatible model. The default remains the requested GPT-5.6 Sol model.

## How Codex contributed

Codex helped translate the product brief into the working architecture, verified the current OpenAI API integration against official documentation, implemented the Streamlit interface and local fallback, created validation schemas and tests, and exercised the Demo Mode and startup path. This is a development contribution statement, not a claim that Codex operates the deployed application.

## Testing

Run all offline tests:

```powershell
python -m pytest -q
```

Run a syntax check:

```powershell
python -m compileall app.py ai_service.py sample_data.py tests
```

Run a headless startup smoke test:

```powershell
streamlit run app.py --server.headless true --server.port 8501
```

The automated tests require no API key and do not make network requests. A live AI-mode test requires a valid OpenAI API key, model access, network access, and available account limits.

## Limitations

- The MVP keeps state in the current Streamlit session; it has no user accounts, shared persistence, or collaborative editing.
- Dependencies are displayed as task-name references and are not a full project-scheduling engine.
- AI recommendations still require committee judgement, especially for safeguarding, medical, legal, food-safety, and venue decisions.
- No WhatsApp, email, calendar, payment, school system, or supplier integration is implemented.
- CSV and JSON downloads are user-initiated; the app does not write operational data to disk automatically.
- Live AI quality and latency depend on API access and the selected model. Automated validation covers schema conformance, not factual confirmation of venue or supplier details.

## Future development

- Secure team workspaces with role-based access and an audit trail
- Persistent plans, version history, comments, and notifications
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
