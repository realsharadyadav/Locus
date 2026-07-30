import json

from fastapi import HTTPException

import backend.app.diagnostics as diagnostics
import backend.app.main as main_module
from backend.app.schemas import ChatRequest, ChatResponse


def records(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_diagnostics_redact_secrets_and_content(monkeypatch, tmp_path):
    monkeypatch.setattr(diagnostics, "DIAGNOSTICS_DIR", tmp_path)
    monkeypatch.setenv("GROQ_API_KEY", "real-secret-value")
    diagnostics.initialize_job_log("safe-job", provider="groq", question_chars=20)
    with diagnostics.diagnostic_job("safe-job"):
        diagnostics.diagnostic_event(
            "test.event",
            authorization="Bearer real-secret-value",
            api_key="real-secret-value",
            messages=[{"content": "private prompt"}],
            error="Authorization: Bearer real-secret-value",
        )
    text = diagnostics.log_path("safe-job").read_text()
    assert "real-secret-value" not in text
    assert "private prompt" not in text
    assert "<redacted>" in text


def test_successful_job_deletes_diagnostic_log(monkeypatch, tmp_path):
    monkeypatch.setattr(diagnostics, "DIAGNOSTICS_DIR", tmp_path)
    monkeypatch.setattr(main_module, "_update_chat_job", lambda *args, **kwargs: None)

    result = ChatResponse(answer="done", sources=[], model="llama3.2:latest", conversation_id=1)
    monkeypatch.setattr(main_module, "_process_chat", lambda *args, **kwargs: result)
    main_module._run_chat_job("successful-job", ChatRequest(question="Successful request", provider="ollama", model="llama3.2:latest"))
    assert not diagnostics.log_path("successful-job").exists()


def test_failed_job_retains_actionable_diagnostic_log(monkeypatch, tmp_path):
    monkeypatch.setattr(diagnostics, "DIAGNOSTICS_DIR", tmp_path)
    monkeypatch.setattr(main_module, "_update_chat_job", lambda *args, **kwargs: None)

    def fail(*args, **kwargs):
        raise HTTPException(status_code=413, detail="Request was too large")

    monkeypatch.setattr(main_module, "_process_chat", fail)
    main_module._run_chat_job("failed-job", ChatRequest(question="Private question text", provider="groq", model="openai/gpt-oss-20b"))

    path = diagnostics.log_path("failed-job")
    assert path.exists()
    events = records(path)
    assert events[0]["event"] == "job.created"
    assert events[0]["question_chars"] == len("Private question text")
    assert "Private question text" not in path.read_text()
    failure = next(item for item in events if item["event"] == "pipeline.attempt_failed")
    assert failure["status_code"] == 413
    assert failure["retryable"] is False
    assert "traceback" in failure
    assert events[-1]["event"] == "job.failed"
