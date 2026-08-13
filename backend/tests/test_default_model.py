"""One default model, resolved server-side.

No page picks a model any more — Settings saves one under the `explore_ai` preference and every
entry point resolves it when the request runs, so a client that sends no provider/model still
answers with the user's choice rather than the .env default.
"""

import json

import pytest
from fastapi.testclient import TestClient

from backend.app.ai_defaults import preferred_ai
from backend.app.database import SessionLocal
from backend.app.main import app
from backend.app.models import UserPreference


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def save_default(provider, model):
    with SessionLocal() as db:
        preference = db.get(UserPreference, "explore_ai")
        value = {"provider": provider, "model": model}
        if preference:
            preference.value = value
        else:
            db.add(UserPreference(key="explore_ai", value=value))
        db.commit()


def clear_default():
    with SessionLocal() as db:
        preference = db.get(UserPreference, "explore_ai")
        if preference:
            db.delete(preference)
            db.commit()


def test_preferred_ai_falls_back_to_the_environment(client):
    clear_default()
    provider, model = preferred_ai()
    assert provider == "ollama"
    assert model == "llama3.2:latest"


def test_preferred_ai_reads_the_saved_default(client):
    save_default("groq", "settings-choice-model")
    try:
        assert preferred_ai() == ("groq", "settings-choice-model")
    finally:
        clear_default()


def test_preferred_ai_drops_a_provider_that_no_longer_exists(client):
    save_default("retired-provider", "settings-choice-model")
    try:
        assert preferred_ai() == ("ollama", "llama3.2:latest")
    finally:
        clear_default()


def test_chat_without_a_model_uses_the_settings_default(client, monkeypatch):
    captured = {}

    def fake_call_process_chat(payload, db, notify, cancelled=None, on_answer_token=None):
        captured["provider"] = payload.provider
        captured["model"] = payload.model
        from backend.app.schemas import ChatResponse

        return ChatResponse(answer="ok", sources=[], model=payload.model, conversation_id=1)

    monkeypatch.setattr("backend.app.main._call_process_chat", fake_call_process_chat)
    save_default("groq", "settings-choice-model")
    try:
        response = client.post("/api/chat/stream", json={"question": "hello there", "reasoning_mode": "light", "file_ids": []})
        assert response.status_code == 200
        assert any(json.loads(line).get("type") == "result" for line in response.text.strip().split("\n") if line.strip())
    finally:
        clear_default()
    assert captured == {"provider": "groq", "model": "settings-choice-model"}


def test_a_pinned_model_still_wins(client, monkeypatch):
    captured = {}

    def fake_call_process_chat(payload, db, notify, cancelled=None, on_answer_token=None):
        captured["provider"] = payload.provider
        captured["model"] = payload.model
        from backend.app.schemas import ChatResponse

        return ChatResponse(answer="ok", sources=[], model=payload.model, conversation_id=1)

    monkeypatch.setattr("backend.app.main._call_process_chat", fake_call_process_chat)
    save_default("groq", "settings-choice-model")
    try:
        response = client.post("/api/chat/stream", json={
            "question": "hello there",
            "reasoning_mode": "light",
            "file_ids": [],
            "provider": "ollama",
            "model": "pinned-model",
        })
        assert response.status_code == 200
    finally:
        clear_default()
    assert captured == {"provider": "ollama", "model": "pinned-model"}


def test_a_pinned_provider_does_not_borrow_the_saved_model(client, monkeypatch):
    """The saved model id belongs to the saved provider; a different provider gets its own."""
    captured = {}

    def fake_call_process_chat(payload, db, notify, cancelled=None, on_answer_token=None):
        captured["provider"] = payload.provider
        captured["model"] = payload.model
        from backend.app.schemas import ChatResponse

        return ChatResponse(answer="ok", sources=[], model=payload.model, conversation_id=1)

    monkeypatch.setattr("backend.app.main._call_process_chat", fake_call_process_chat)
    save_default("groq", "settings-choice-model")
    try:
        response = client.post("/api/chat/stream", json={
            "question": "hello there",
            "reasoning_mode": "light",
            "file_ids": [],
            "provider": "ollama",
        })
        assert response.status_code == 200
    finally:
        clear_default()
    assert captured == {"provider": "ollama", "model": "llama3.2:latest"}


def test_ticket_analysis_runs_on_the_settings_default(client):
    from backend.app.main import _ticket_analysis_ai
    from backend.app.schemas import TicketAnalysisRequest

    save_default("groq", "settings-choice-model")
    try:
        with SessionLocal() as db:
            assert _ticket_analysis_ai(TicketAnalysisRequest(fileId=1), db) == ("groq", "settings-choice-model")
            pinned = TicketAnalysisRequest(fileId=1, model="pinned-model", llmProvider="ollama")
            assert _ticket_analysis_ai(pinned, db) == ("ollama", "pinned-model")
    finally:
        clear_default()


def test_chat_job_records_the_settings_default(client, monkeypatch):
    # The job row is what this checks; running it would reach for a real provider.
    monkeypatch.setattr("backend.app.main._run_chat_job", lambda job_id, payload: None)
    save_default("groq", "settings-choice-model")
    try:
        response = client.post("/api/chat/jobs", json={"question": "hello there", "reasoning_mode": "light", "file_ids": []})
        assert response.status_code == 202
        job = response.json()
        assert job["provider"] == "groq"
        assert job["model"] == "settings-choice-model"
    finally:
        clear_default()


def test_testing_models_tags_the_ones_that_answer(client, monkeypatch):
    def fake_probe(provider, model):
        assert provider == "groq"
        if model == "quiet-model":
            raise RuntimeError("upstream said no")
        return {"ok": True, "latency_ms": 12, "error": ""}

    monkeypatch.setattr("backend.app.main.probe_model", lambda provider, model: (
        {"ok": False, "latency_ms": 5, "error": "upstream said no"} if model == "quiet-model" else fake_probe(provider, model)
    ))
    response = client.post("/api/llm/models/test", json={"provider": "groq", "models": ["talkative-model", "quiet-model"]})
    assert response.status_code == 200
    results = response.json()["results"]
    assert results["talkative-model"]["ok"] is True
    assert results["quiet-model"]["ok"] is False
    assert results["quiet-model"]["error"] == "upstream said no"

    # Saved, so the tags survive a reload rather than living in the page's memory.
    saved = client.get("/api/preferences/model_health").json()["value"]
    assert saved["groq"]["talkative-model"]["ok"] is True
    assert saved["groq"]["talkative-model"]["checked_at"]


def test_a_later_test_run_keeps_earlier_results(client, monkeypatch):
    monkeypatch.setattr("backend.app.main.probe_model", lambda provider, model: {"ok": True, "latency_ms": 1, "error": ""})
    client.post("/api/llm/models/test", json={"provider": "groq", "models": ["first-model"]})
    client.post("/api/llm/models/test", json={"provider": "ollama", "models": ["second-model"]})
    saved = client.get("/api/preferences/model_health").json()["value"]
    assert set(saved) == {"groq", "ollama"}
    assert saved["groq"]["first-model"]["ok"] is True


def test_a_probe_that_answers_nothing_is_not_responding(monkeypatch):
    from backend.app import llm as llm_module

    monkeypatch.setattr(llm_module, "_chat", lambda *args, **kwargs: "   ")
    assert llm_module.probe_model("groq", "empty-model")["ok"] is False

    monkeypatch.setattr(llm_module, "_chat", lambda *args, **kwargs: "ok")
    assert llm_module.probe_model("groq", "good-model")["ok"] is True


def test_the_test_batch_is_capped(client):
    response = client.post("/api/llm/models/test", json={"provider": "groq", "models": [f"m{index}" for index in range(41)]})
    assert response.status_code == 422
