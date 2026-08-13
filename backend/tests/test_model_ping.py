"""Tests for the Settings "test models" ping — `ping_model`/`ping_models` and the endpoint."""

import time

from fastapi.testclient import TestClient

import backend.app.llm as llm_module
import backend.app.main as main_module
from backend.app.llm import ping_model, ping_models
from backend.app.main import app


class FakeClient:
    """Stands in for a provider client: answers, stays silent, fails, or hangs."""

    def __init__(self, behavior):
        self.behavior = behavior

    def generate(self, messages, temperature=None, max_tokens=None, **kwargs):
        if self.behavior == "ok":
            return "  pong  "
        if self.behavior == "empty":
            return "   "
        if self.behavior == "slow":
            time.sleep(5)
            return "pong"
        raise RuntimeError("Model is not available for this key")


def fake_clients(monkeypatch, behaviors):
    def factory(model=None, provider=None):
        return FakeClient(behaviors.get(model, "ok"))

    monkeypatch.setattr(llm_module, "get_llm_client", factory)


def test_ping_model_reports_success_with_latency(monkeypatch):
    fake_clients(monkeypatch, {"good": "ok"})
    result = ping_model("groq", "good")
    assert result["ok"] is True
    assert result["reply"] == "pong"
    assert result["error"] is None
    assert result["latency_ms"] >= 0


def test_ping_model_reports_provider_failure_instead_of_raising(monkeypatch):
    fake_clients(monkeypatch, {"gated": "error"})
    result = ping_model("groq", "gated")
    assert result["ok"] is False
    assert "not available" in result["error"]


def test_ping_model_treats_empty_reply_as_failure(monkeypatch):
    fake_clients(monkeypatch, {"quiet": "empty"})
    result = ping_model("groq", "quiet")
    assert result["ok"] is False
    assert result["error"] == "Model returned an empty response"


def test_ping_models_dedupes_and_covers_every_model(monkeypatch):
    fake_clients(monkeypatch, {"a": "ok", "b": "error", "c": "ok"})
    results = ping_models("groq", ["a", "b", "c", "a", "  ", ""])
    assert [result["model"] for result in results] == ["a", "b", "c"]
    assert [result["ok"] for result in results] == [True, False, True]


def test_ping_models_times_out_without_blocking_the_batch(monkeypatch):
    fake_clients(monkeypatch, {"fast": "ok", "hung": "slow"})
    started = time.perf_counter()
    results = ping_models("groq", ["fast", "hung"], timeout_seconds=0.5)
    elapsed = time.perf_counter() - started
    assert elapsed < 4, "a hung model must not hold the whole batch open"
    by_model = {result["model"]: result for result in results}
    assert by_model["fast"]["ok"] is True
    assert by_model["hung"]["ok"] is False
    assert by_model["hung"]["error"] == "Timed out waiting for a response"


def test_test_models_endpoint_summarizes_respondents(monkeypatch):
    monkeypatch.setattr(main_module, "ping_models", lambda provider, models, timeout_seconds=None: [
        {"model": "a", "ok": True, "latency_ms": 12.5, "reply": "pong", "error": None},
        {"model": "b", "ok": False, "latency_ms": 8.0, "reply": "", "error": "HTTP 404"},
    ])
    with TestClient(app) as client:
        response = client.post("/api/llm/models/test", json={"provider": "groq", "models": ["a", "b"]})
        assert response.status_code == 200
        body = response.json()
        assert body == {
            "provider": "groq",
            "tested": 2,
            "responded": 1,
            "results": [
                {"model": "a", "ok": True, "latency_ms": 12.5, "reply": "pong", "error": None},
                {"model": "b", "ok": False, "latency_ms": 8.0, "reply": "", "error": "HTTP 404"},
            ],
        }


def test_test_models_endpoint_rejects_unknown_provider_and_empty_list():
    with TestClient(app) as client:
        assert client.post("/api/llm/models/test", json={"provider": "nope", "models": ["a"]}).status_code == 422
        assert client.post("/api/llm/models/test", json={"provider": "groq", "models": []}).status_code == 422
