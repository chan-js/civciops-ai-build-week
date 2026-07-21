"""Regression tests for bounded cloud requests and timeout-only retry behaviour."""

from __future__ import annotations

import json
from datetime import date, timedelta
from types import SimpleNamespace

import httpx
import pytest
from openai import APITimeoutError, AuthenticationError
from streamlit.testing.v1 import AppTest

import ai_service
from ai_service import (
    AIServiceError,
    EventBrief,
    OPENAI_CONNECT_TIMEOUT_SECONDS,
    OPENAI_MAX_RETRIES,
    OPENAI_POOL_TIMEOUT_SECONDS,
    OPENAI_READ_TIMEOUT_SECONDS,
    OPENAI_TIMEOUT_DEFAULT_SECONDS,
    OPENAI_WRITE_TIMEOUT_SECONDS,
    OperationsPlan,
    PLAN_INSTRUCTIONS,
    PLAN_MAX_OUTPUT_TOKENS,
    PLAN_REASONING_EFFORT,
    generate_demo_plan,
    generate_operations_plan,
)
from sample_data import SAMPLE_EVENT


def _brief() -> EventBrief:
    data = dict(SAMPLE_EVENT)
    data["event_date"] = date.today() + timedelta(days=90)
    return EventBrief.model_validate(data)


def _timeout_error() -> APITimeoutError:
    return APITimeoutError(
        httpx.Request("POST", "https://api.openai.com/v1/responses")
    )


def _authentication_error() -> AuthenticationError:
    request = httpx.Request("POST", "https://api.openai.com/v1/responses")
    response = httpx.Response(401, request=request)
    private_key_marker = "sk" + "-test-secret-material"
    return AuthenticationError(
        "Traceback at C:\\private\\service.py "
        f"credential={private_key_marker}",
        response=response,
        body={"code": "invalid_api_key"},
    )


def test_client_uses_intended_httpx_timeout_without_hidden_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "configured-test-placeholder")

    client = ai_service._openai_client()
    try:
        assert isinstance(client.timeout, httpx.Timeout)
        assert client.timeout.connect == OPENAI_CONNECT_TIMEOUT_SECONDS == 15.0
        assert client.timeout.read == OPENAI_READ_TIMEOUT_SECONDS == 180.0
        assert client.timeout.write == OPENAI_WRITE_TIMEOUT_SECONDS == 30.0
        assert client.timeout.pool == OPENAI_POOL_TIMEOUT_SECONDS == 30.0
        assert OPENAI_TIMEOUT_DEFAULT_SECONDS == 195.0
        assert OPENAI_TIMEOUT_DEFAULT_SECONDS >= OPENAI_READ_TIMEOUT_SECONDS
        assert client.max_retries == OPENAI_MAX_RETRIES == 0
    finally:
        client.close()


def test_timeout_is_retried_exactly_once(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    class AlwaysTimeoutResponses:
        calls = 0

        def parse(self, **_: object) -> object:
            self.calls += 1
            raise _timeout_error()

    responses = AlwaysTimeoutResponses()
    monkeypatch.setattr(
        ai_service,
        "_openai_client",
        lambda: SimpleNamespace(responses=responses),
    )

    with pytest.raises(AIServiceError) as exc_info:
        generate_operations_plan(_brief())

    assert responses.calls == 2
    assert exc_info.value.timed_out is True
    assert exc_info.value.category == "network"
    log_lines = [line for line in capsys.readouterr().err.splitlines() if line]
    assert len(log_lines) == 2
    assert "attempt_number=1" in log_lines[0]
    assert "attempt_number=2" in log_lines[1]
    assert all("category=network" in line for line in log_lines)
    assert all("Traceback" not in line and "sk-" not in line for line in log_lines)


def test_non_timeout_api_error_is_not_retried(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    class AuthenticationFailureResponses:
        calls = 0

        def parse(self, **_: object) -> object:
            self.calls += 1
            raise _authentication_error()

    responses = AuthenticationFailureResponses()
    monkeypatch.setattr(
        ai_service,
        "_openai_client",
        lambda: SimpleNamespace(responses=responses),
    )

    with pytest.raises(AIServiceError) as exc_info:
        generate_operations_plan(_brief())

    assert responses.calls == 1
    assert exc_info.value.category == "authentication"
    assert exc_info.value.timed_out is False
    log_lines = [line for line in capsys.readouterr().err.splitlines() if line]
    assert len(log_lines) == 1
    assert "attempt_number=1" in log_lines[0]
    assert "category=authentication" in log_lines[0]
    assert "C:\\private" not in log_lines[0]
    assert "sk-" not in log_lines[0]
    assert "Traceback" not in log_lines[0]


def test_plan_request_and_output_are_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    brief = _brief()
    captured: dict[str, object] = {}

    class SuccessfulResponses:
        def parse(self, **kwargs: object) -> object:
            captured.update(kwargs)
            return SimpleNamespace(
                output_parsed=generate_demo_plan(brief), status="completed"
            )

    monkeypatch.setattr(
        ai_service,
        "_openai_client",
        lambda: SimpleNamespace(responses=SuccessfulResponses()),
    )

    plan = generate_operations_plan(brief)
    schema = OperationsPlan.model_json_schema()["properties"]
    prompt = " ".join(PLAN_INSTRUCTIONS.split())
    request_input = captured["input"]

    assert len(plan.actionable_tasks) == 16
    assert len(plan.recommended_committee_structure) <= 10
    assert len(plan.risk_register) <= 6
    assert len(plan.recommended_next_actions) <= 5
    assert schema["actionable_tasks"]["minItems"] == 12
    assert schema["actionable_tasks"]["maxItems"] == 16
    assert schema["recommended_committee_structure"]["maxItems"] == 10
    assert schema["risk_register"]["maxItems"] == 6
    assert schema["recommended_next_actions"]["maxItems"] == 5
    assert captured["reasoning"] == {"effort": PLAN_REASONING_EFFORT}
    assert PLAN_REASONING_EFFORT == "low"
    assert captured["max_output_tokens"] == PLAN_MAX_OUTPUT_TOKENS == 10_000
    assert "timeout" not in captured
    assert "12–16 specific operational tasks" in prompt
    assert "only direct prerequisites" in prompt
    assert "no full transitive dependency lists" in prompt
    assert isinstance(request_input, list)
    assert len(request_input) == 2
    assert json.loads(request_input[1]["content"]) == brief.model_dump(mode="json")


def test_timeout_message_is_safe_and_deterministic_fallback_remains(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "configured-test-placeholder")

    def fail_plan(_: EventBrief) -> OperationsPlan:
        raise AIServiceError(
            "Traceback at C:\\private\\service.py credential=SENSITIVE_MARKER",
            category="network",
            diagnostic_logged=True,
            timed_out=True,
        )

    monkeypatch.setattr(ai_service, "generate_operations_plan", fail_plan)

    app = AppTest.from_file("app.py", default_timeout=60).run()
    app.button[0].click().run()
    app.button[1].click().run()

    rendered_errors = " ".join(str(error.value) for error in app.error)
    assert not app.exception
    assert rendered_errors == (
        "The live AI request timed out. The deterministic plan remains available. "
        "Please try once more."
    )
    assert "SENSITIVE_MARKER" not in rendered_errors
    assert "Traceback" not in rendered_errors
    assert "C:\\private" not in rendered_errors
    assert app.session_state["plan_source"] == "Demo fallback after API error"
    assert app.session_state["operations_plan"] is not None
