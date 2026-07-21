"""Streamlit interaction smoke test for the complete Demo Mode sample flow."""

from __future__ import annotations

from streamlit.testing.v1 import AppTest


def test_sample_demo_streamlit_flow(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.delenv("OPENAI_MODEL", raising=False)

    app = AppTest.from_file("app.py", default_timeout=60).run()
    assert not app.exception
    assert any("Demo Mode" in warning.value for warning in app.warning)

    app.button[0].click().run()
    assert not app.exception
    assert app.text_input[1].value.startswith("Primary School Foot Drill")
    assert app.text_input[2].value == "SJK(C) Bacang, Melaka"

    app.button[1].click().run()
    assert not app.exception
    assert len(app.metric) == 5
    assert app.metric[0].value == "16"
    assert app.metric[1].value == "0"
    assert app.metric[2].value == "0"
    assert app.metric[3].label == "High / critical risk"
    assert app.metric[3].value == "5"
    assert app.metric[4].value == "0%"

    review_button = next(
        button for button in app.button if button.label == "Review Current Progress"
    )
    review_button.click().run()
    assert not app.exception
    assert any(
        "Progress reviewed locally" in success.value for success in app.success
    )
    assert any(
        success.value == "No active blocked dependency chains detected."
        for success in app.success
    )
