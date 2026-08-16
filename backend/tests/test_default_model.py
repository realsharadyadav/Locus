"""One default model, resolved server-side.

No page picks a model any more — Settings saves one under the `explore_ai` preference and every
entry point resolves it when the request runs, so a client that sends no provider/model still
answers with the user's choice rather than the .env default.

Auto-select lives here too: when the toggle is on and that default fails on a real request, the
job retries once with the healthiest alternative and, on success, the new model becomes the
permanent default (with a record of the switch for Settings to explain).
"""

import json
import time
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend.app import auto_select
from backend.app.ai_defaults import preferred_ai
from backend.app.auto_select import choose_fallback
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


def save_preference(key, value):
    with SessionLocal() as db:
        preference = db.get(UserPreference, key)
        if preference:
            preference.value = value
        else:
            db.add(UserPreference(key=key, value=value))
        db.commit()


def clear_preference(key):
    with SessionLocal() as db:
        preference = db.get(UserPreference, key)
        if preference:
            db.delete(preference)
            db.commit()


def preference_value(key):
    with SessionLocal() as db:
        preference = db.get(UserPreference, key)
        return dict(preference.value) if preference and isinstance(preference.value, dict) else None


def health(entries):
    """A `model_health` body in the shape the test endpoint writes, all freshly checked."""
    checked_at = datetime.now(timezone.utc).isoformat()
    return {model: {**entry, "checked_at": checked_at} for model, entry in entries.items()}


def await_job(client, job_id, timeout=8):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = next((item for item in client.get("/api/chat/jobs").json() if item["id"] == job_id), None)
        if job and job["status"] in {"completed", "failed", "cancelled"}:
            return job
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} never finished")


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


def test_auto_select_is_off_by_default(client):
    with SessionLocal() as db:
        assert auto_select.enabled(db) is False


def test_auto_select_reads_the_toggle(client):
    save_preference("auto_select_model", {"enabled": True})
    try:
        with SessionLocal() as db:
            assert auto_select.enabled(db) is True
    finally:
        clear_preference("auto_select_model")


def test_choose_fallback_ranks_healthy_models_by_latency(client):
    save_preference("auto_select_model", {"enabled": True})
    save_preference("model_health", {
        "groq": health({
            "failing-model": {"ok": False, "latency_ms": 5, "error": "down"},
            "slow-model": {"ok": True, "latency_ms": 90, "error": ""},
            "fast-model": {"ok": True, "latency_ms": 10, "error": ""},
            "mid-model": {"ok": True, "latency_ms": 30, "error": ""},
            "fastest-model": {"ok": True, "latency_ms": 1, "error": ""},
        })
    })
    try:
        with SessionLocal() as db:
            # The failed model is never a candidate, even if it once answered. Best three
            # healthy models, lowest latency first — that is the try order.
            assert choose_fallback(db, "groq", "failing-model") == [
                ("groq", "fastest-model"),
                ("groq", "fast-model"),
                ("groq", "mid-model"),
            ]
    finally:
        clear_preference("auto_select_model")
        clear_preference("model_health")


def test_choose_fallback_respects_the_enabled_models_allowlist(client):
    save_preference("auto_select_model", {"enabled": True})
    save_preference("model_health", {
        "groq": health({
            "failing-model": {"ok": False, "latency_ms": 5, "error": "down"},
            "allowed-model": {"ok": True, "latency_ms": 20, "error": ""},
            "hidden-model": {"ok": True, "latency_ms": 1, "error": ""},
        })
    })
    save_preference("enabled_models", {"groq": ["allowed-model"]})
    try:
        with SessionLocal() as db:
            # hidden-model is faster but the user ticked it off, so it is not a candidate.
            assert choose_fallback(db, "groq", "failing-model") == [("groq", "allowed-model")]
    finally:
        clear_preference("auto_select_model")
        clear_preference("model_health")
        clear_preference("enabled_models")


def test_choose_fallback_reprobes_stale_health(client, monkeypatch):
    save_preference("auto_select_model", {"enabled": True})
    stale = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
    fresh = datetime.now(timezone.utc).isoformat()
    save_preference("model_health", {
        "groq": {
            "failing-model": {"ok": False, "latency_ms": 5, "error": "down", "checked_at": stale},
            "stale-model": {"ok": True, "latency_ms": 10, "error": "", "checked_at": stale},
            "fresh-model": {"ok": True, "latency_ms": 20, "error": "", "checked_at": fresh},
        }
    })
    probed = []

    def fake_probe(provider, model):
        probed.append(model)
        if model == "stale-model":
            return {"ok": False, "latency_ms": 0, "error": "also down now"}
        return {"ok": True, "latency_ms": 9, "error": ""}

    monkeypatch.setattr("backend.app.auto_select.probe_model", fake_probe)
    try:
        with SessionLocal() as db:
            # stale-model's old tag is re-probed live, turns out to be down, so the choice
            # falls through to fresh-model; fresh-model needs no live probe at all.
            assert choose_fallback(db, "groq", "failing-model") == [("groq", "fresh-model")]
        assert probed == ["stale-model"]
        # The live re-probe is folded back into model_health so the next failure is cheaper.
        saved = preference_value("model_health")
        assert saved["groq"]["stale-model"]["ok"] is False
        assert saved["groq"]["stale-model"]["error"] == "also down now"
        assert saved["groq"]["fresh-model"]["ok"] is True
    finally:
        clear_preference("auto_select_model")
        clear_preference("model_health")


def test_choose_fallback_returns_nothing_when_the_toggle_is_off(client):
    save_preference("model_health", {
        "groq": health({
            "failing-model": {"ok": False, "latency_ms": 5, "error": "down"},
            "healthy-model": {"ok": True, "latency_ms": 5, "error": ""},
        })
    })
    try:
        with SessionLocal() as db:
            assert choose_fallback(db, "groq", "failing-model") == []
    finally:
        clear_preference("model_health")


def test_job_auto_switches_to_a_healthy_model_and_persists_the_new_default(client, monkeypatch):
    save_default("groq", "failing-model")
    save_preference("auto_select_model", {"enabled": True})
    save_preference("model_health", {
        "groq": health({
            "failing-model": {"ok": False, "latency_ms": 5, "error": "down"},
            "fallback-model": {"ok": True, "latency_ms": 12, "error": ""},
            "slow-model": {"ok": True, "latency_ms": 40, "error": ""},
        })
    })

    def fake_call_process_chat(payload, db, notify, cancelled=None, on_answer_token=None):
        if payload.model == "failing-model":
            raise HTTPException(status_code=503, detail="failing-model is down")
        from backend.app.schemas import ChatResponse

        return ChatResponse(answer="ok", sources=[], model=payload.model, conversation_id=1)

    monkeypatch.setattr("backend.app.main._call_process_chat", fake_call_process_chat)
    try:
        response = client.post("/api/chat/jobs", json={"question": "hello there", "reasoning_mode": "light", "file_ids": []})
        assert response.status_code == 202
        job = await_job(client, response.json()["id"])
        assert job["status"] == "completed"
        # The request resolved to the saved default, which failed, so the successful retry
        # makes the fallback the new permanent default and leaves a record of the switch.
        assert preference_value("explore_ai") == {"provider": "groq", "model": "fallback-model"}
        switch = preference_value("auto_select_last_switch")
        assert switch["previous_model"] == "failing-model"
        assert switch["model"] == "fallback-model"
        assert switch["provider"] == "groq"
        assert switch["reason"] == "failing-model is down"
        assert switch["job_id"] == job["id"]
        assert switch["timestamp"]
    finally:
        clear_default()
        clear_preference("auto_select_model")
        clear_preference("model_health")
        clear_preference("auto_select_last_switch")


def test_job_surfaces_the_original_error_without_auto_select(client, monkeypatch):
    save_default("groq", "failing-model")
    save_preference("model_health", {
        "groq": health({
            "failing-model": {"ok": False, "latency_ms": 5, "error": "down"},
            "healthy-model": {"ok": True, "latency_ms": 5, "error": ""},
        })
    })

    def fake_call_process_chat(payload, db, notify, cancelled=None, on_answer_token=None):
        raise HTTPException(status_code=503, detail="failing-model is down")

    monkeypatch.setattr("backend.app.main._call_process_chat", fake_call_process_chat)
    # Zero the backoff sleep so the three same-model retries do not take 14 real seconds.
    monkeypatch.setattr("backend.app.main.CHAT_JOB_RETRY_DELAY_SECONDS", 0)
    try:
        response = client.post("/api/chat/jobs", json={"question": "hello there", "reasoning_mode": "light", "file_ids": []})
        assert response.status_code == 202
        job = await_job(client, response.json()["id"])
        # Today's behavior, untouched: the error surfaces, no auto-switch happened.
        assert job["status"] == "failed"
        assert "failing-model is down" in job["error"]
        assert preference_value("explore_ai") == {"provider": "groq", "model": "failing-model"}
        assert preference_value("auto_select_last_switch") is None
    finally:
        clear_default()
        clear_preference("model_health")


def test_job_with_no_healthy_candidates_surfaces_the_original_error(client, monkeypatch):
    save_default("groq", "failing-model")
    save_preference("auto_select_model", {"enabled": True})
    # Every model in health is down — nothing to fall back to.
    save_preference("model_health", {
        "groq": health({
            "failing-model": {"ok": False, "latency_ms": 5, "error": "down"},
            "dead-model": {"ok": False, "latency_ms": 5, "error": "also down"},
        })
    })

    def fake_call_process_chat(payload, db, notify, cancelled=None, on_answer_token=None):
        raise HTTPException(status_code=503, detail="failing-model is down")

    monkeypatch.setattr("backend.app.main._call_process_chat", fake_call_process_chat)
    monkeypatch.setattr("backend.app.main.CHAT_JOB_RETRY_DELAY_SECONDS", 0)
    try:
        response = client.post("/api/chat/jobs", json={"question": "hello there", "reasoning_mode": "light", "file_ids": []})
        assert response.status_code == 202
        job = await_job(client, response.json()["id"])
        assert job["status"] == "failed"
        assert "failing-model is down" in job["error"]
        assert preference_value("auto_select_last_switch") is None
    finally:
        clear_default()
        clear_preference("auto_select_model")
        clear_preference("model_health")


def test_a_pinned_model_that_fails_does_not_rewrite_the_default(client, monkeypatch):
    save_default("groq", "settings-choice-model")
    save_preference("auto_select_model", {"enabled": True})
    save_preference("model_health", {
        "groq": health({
            "pinned-model": {"ok": False, "latency_ms": 5, "error": "down"},
            "fallback-model": {"ok": True, "latency_ms": 12, "error": ""},
        })
    })

    def fake_call_process_chat(payload, db, notify, cancelled=None, on_answer_token=None):
        if payload.model == "pinned-model":
            raise HTTPException(status_code=503, detail="pinned-model is down")
        from backend.app.schemas import ChatResponse

        return ChatResponse(answer="ok", sources=[], model=payload.model, conversation_id=1)

    monkeypatch.setattr("backend.app.main._call_process_chat", fake_call_process_chat)
    try:
        response = client.post("/api/chat/jobs", json={
            "question": "hello there",
            "reasoning_mode": "light",
            "file_ids": [],
            "provider": "groq",
            "model": "pinned-model",
        })
        assert response.status_code == 202
        job = await_job(client, response.json()["id"])
        assert job["status"] == "completed"
        # The request still recovered through the fallback, but the user pinned this model
        # on purpose — their saved default is not rewritten behind their back, and there
        # is no switch record to imply the default changed.
        assert preference_value("explore_ai") == {"provider": "groq", "model": "settings-choice-model"}
        assert preference_value("auto_select_last_switch") is None
    finally:
        clear_default()
        clear_preference("auto_select_model")
        clear_preference("model_health")
