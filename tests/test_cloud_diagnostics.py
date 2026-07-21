"""Security and categorisation tests for cloud-safe OpenAI diagnostics."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Type

import httpx
import pytest
from openai import (
    APIConnectionError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
)
from pydantic import ValidationError

from ai_service import (
    EventBrief,
    extract_openai_exception_metadata,
    generate_demo_plan,
    log_openai_failure,
)
from sample_data import SAMPLE_EVENT


StatusError = Type[
    AuthenticationError
    | RateLimitError
    | PermissionDeniedError
    | NotFoundError
    | BadRequestError
]


def _status_error(
    error_type: StatusError, status_code: int, error_code: str
) -> Exception:
    request = httpx.Request("POST", "https://api.openai.com/v1/responses")
    response = httpx.Response(status_code, request=request)
    private_key_marker = "sk" + "-test-secret-material"
    return error_type(
        "Private failure at C:\\private\\service.py "
        f"credential={private_key_marker} prompt=PRIVATE_EVENT_DATA",
        response=response,
        body={"code": error_code},
    )


@pytest.mark.parametrize(
    ("error", "expected_category", "expected_status"),
    [
        (_status_error(AuthenticationError, 401, "invalid_api_key"), "authentication", 401),
        (_status_error(RateLimitError, 429, "insufficient_quota"), "insufficient_quota", 429),
        (_status_error(PermissionDeniedError, 403, "permission_denied"), "model_access", 403),
        (_status_error(NotFoundError, 404, "model_not_found"), "model_access", 404),
        (_status_error(BadRequestError, 400, "invalid_request_error"), "invalid_request", 400),
        (
            APIConnectionError(
                message="Private network detail",
                request=httpx.Request("POST", "https://api.openai.com/v1/responses"),
            ),
            "network",
            None,
        ),
        (
            APITimeoutError(
                httpx.Request("POST", "https://api.openai.com/v1/responses")
            ),
            "network",
            None,
        ),
    ],
)
def test_sdk_exception_categories(
    error: Exception, expected_category: str, expected_status: int | None
) -> None:
    metadata = extract_openai_exception_metadata(error, "gpt-5.6-sol")

    assert metadata.category == expected_category
    assert metadata.http_status_code == expected_status
    assert metadata.requested_model == "gpt-5.6-sol"


def test_pydantic_validation_error_maps_to_validation() -> None:
    with pytest.raises(ValidationError) as exc_info:
        EventBrief.model_validate({})

    metadata = extract_openai_exception_metadata(
        exc_info.value, "gpt-5.6-sol"
    )
    assert metadata.category == "validation"


def test_log_line_contains_only_safe_metadata(capsys: pytest.CaptureFixture[str]) -> None:
    error = _status_error(AuthenticationError, 401, "invalid_api_key")

    log_openai_failure(
        "plan_generation",
        error,
        "gpt-5.6-sol",
        attempt_number=2,
        elapsed_seconds=123.456,
    )
    captured = capsys.readouterr()
    log_lines = [line for line in captured.err.splitlines() if line]

    assert len(log_lines) == 1
    fields = log_lines[0].split()
    assert len(fields) == 6
    assert fields == [
        "operation=plan_generation",
        "exception_class=AuthenticationError",
        "category=authentication",
        "requested_model=gpt-5.6-sol",
        "attempt_number=2",
        "elapsed_seconds=123.46",
    ]
    prohibited = (
        "sk-",
        "PRIVATE_EVENT_DATA",
        "C:\\private",
        "Traceback",
        "credential",
        "request_headers",
        "invalid_api_key",
        "http_status_code",
        "openai_error_code",
    )
    assert all(item not in log_lines[0] for item in prohibited)
    assert captured.out == ""


def test_demo_plan_generation_does_not_require_openai() -> None:
    data = dict(SAMPLE_EVENT)
    data["event_date"] = date.today() + timedelta(days=90)
    plan = generate_demo_plan(EventBrief.model_validate(data))

    assert plan.actionable_tasks
