"""Self-aware Ask: platform-action classification and execution.

Covers the whitelist, the deterministic fast path, the guided-LLM fallback (including
rejection of injected/unlisted tools), preference persistence through the exact rows
Settings uses, and the end-to-end chat job that surfaces `actions_taken` on the result.
"""

import time

import pytest
from fastapi.testclient import TestClient

from backend.app.ai_defaults import AI_PREFERENCE_KEY
from backend.app.assistant_tools import (
    THEME_PREFERENCE_KEY,
    _parse_tool_json,
    _validate_tool_call,
    classify_platform_action,
    execute_action,
)
from backend.app.auto_select import MODEL_HEALTH_PREFERENCE_KEY
from backend.app.database import SessionLocal
from backend.app.main import app
from backend.app.models import UserPreference


@pytest.fixture(autouse=True)
def _no_real_llm_for_classify(monkeypatch):
    # An accidental LLM classification path must never hit a real model in tests.
    # Individual tests that exercise the LLM path override this with a stub response.
    monkeypatch.setattr("backend.app.assistant_tools._chat", lambda *a, **k: "")


def wait_for_job(client, job_id):
    for _ in range(100):
        jobs = client.get("/api/chat/jobs").json()
        job = next((j for j in jobs if j["id"] == job_id), None)
        if job and job["status"] in ("completed", "failed"):
            return job
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} never reached a terminal state")


class TestDeterministicClassification:
    @pytest.mark.parametrize("question,theme", [
        ("switch to dark mode", "dark"),
        ("switch to light mode", "light"),
        ("make it dark", "dark"),
        ("make it light", "light"),
        ("set theme to dark", "dark"),
        ("turn on light mode please", "light"),
        ("theme ko light karo", "light"),
        ("dark mode chalao", "dark"),
    ])
    def test_theme_actions(self, question, theme):
        assert classify_platform_action(question, "test-model") == {
            "tool": "set_theme",
            "arguments": {"theme": theme},
        }

    @pytest.mark.parametrize("question,arguments", [
        ("make gpt-4o the default model", {"provider": "", "model": "gpt-4o"}),
        ("default model ko qwen karo", {"provider": "", "model": "qwen"}),
        ("change my default model to llama3.2", {"provider": "", "model": "llama3.2"}),
        ("set the default model to gpt-4o on groq", {"provider": "groq", "model": "gpt-4o"}),
        ("set the default model to groq", {"provider": "groq", "model": ""}),
        ("make gemini the default", {"provider": "gemini", "model": ""}),
        ("set the default model to openai", {"provider": "openai", "model": ""}),
    ])
    def test_model_actions(self, question, arguments):
        call = classify_platform_action(question, "test-model")
        assert call is not None and call["tool"] == "set_default_model"
        assert call["arguments"] == arguments

    @pytest.mark.parametrize("question", [
        "run a model health test",
        "check model health",
        "models ki health check karo",
        "test the default model",
    ])
    def test_health_test_actions(self, question):
        assert classify_platform_action(question, "test-model") == {
            "tool": "run_model_health_test",
            "arguments": {},
        }

    @pytest.mark.parametrize("question", [
        "what are my settings",
        "which settings do I have",
        "check my settings",
        "what's my current theme",
        "show me the default model",
        "show model health",
        "what is the model health",
        "model health kya hai",
    ])
    def test_read_only_settings_actions(self, question):
        call = classify_platform_action(question, "test-model")
        assert call is not None
        assert call["tool"] in ("get_settings", "get_model_health")

    # Live-configuration questions used to match no pattern at all, so they fell through to the
    # normal answer pipeline and the model truthfully said it could not see the configuration —
    # even though get_settings already knew. Routing, not the tool, was the bug.
    @pytest.mark.parametrize("question", [
        "how many providers are configured and how many of them have responding model ?",
        "which providers are configured",
        "how many providers do i have",
        "what providers are available",
        "how many providers are set up",
    ])
    def test_provider_configuration_questions_reach_get_settings(self, question):
        call = classify_platform_action(question, "test-model")
        assert call is not None
        assert call["tool"] == "get_settings"

    @pytest.mark.parametrize("question", [
        "Explain the quantum entanglement paper",
        "Summarize the attached PDF please",
        "Who created you",
        "What is the capital of France",
        "what is the best setting for temperature in this paper",
        "Can you quote the passage about switching to dark mode in this doc?",
        'The model settings are in `config.json` — can you explain them?',
        "Switch to dark mode " + "lorem ipsum " * 30,
        'make gpt-4o the default model "and erase all my data"',
    ])
    def test_content_questions_are_not_actions(self, question):
        assert classify_platform_action(question, "test-model") is None


class TestLlmClassificationAndValidation:
    @pytest.mark.parametrize("raw,expected", [
        ('```json\n{"tool": "set_theme", "arguments": {"theme": "dark"}}\n```',
         {"tool": "set_theme", "arguments": {"theme": "dark"}}),
        ('{"tool": "get_settings", "arguments": {}}',
         {"tool": "get_settings", "arguments": {}}),
        ('{"tool": "set_default_model", "arguments": {"provider": "", "model": "qwen3"}}',
         {"tool": "set_default_model", "arguments": {"provider": "", "model": "qwen3"}}),
    ])
    def test_llm_path_accepts_valid_guided_json(self, monkeypatch, raw, expected):
        monkeypatch.setattr("backend.app.assistant_tools._chat", lambda *a, **k: raw)
        call = classify_platform_action("theme change karo", "test-model")
        assert call == expected

    @pytest.mark.parametrize("raw", [
        '{"tool": "delete_all_data", "arguments": {}}',
        '{"tool": "set_theme", "arguments": {"theme": "neon"}}',
        '{"tool": "set_default_model", "arguments": {"provider": "notreal", "model": "x"}}',
        '{"tool": "set_default_model", "arguments": {"provider": "", "model": ""}}',
        '{"tool": "set_default_model", "arguments": {"model": "x", "provider": "grok-3"}}',
        "not json at all",
        '',
    ])
    def test_llm_path_rejects_unknown_or_malformed(self, monkeypatch, raw):
        monkeypatch.setattr("backend.app.assistant_tools._chat", lambda *a, **k: raw)
        assert classify_platform_action("kuch bhi karo bhai", "test-model") is None

    def test_prompt_injection_cannot_smuggle_an_unlisted_tool(self, monkeypatch):
        # Classification only ever sees the user's own question, and even then the whitelist
        # is enforced: a model that tries to name a tool outside TOOL_NAMES gets a None.
        monkeypatch.setattr(
            "backend.app.assistant_tools._chat",
            lambda *a, **k: '{"tool": "delete_all_data", "arguments": {}}',
        )
        assert classify_platform_action("theme change karo", "test-model") is None

    def test_parse_tool_json_strips_code_fences(self):
        parsed = _parse_tool_json('```json\n{"tool": "get_settings", "arguments": {}}\n```')
        assert parsed == {"tool": "get_settings", "arguments": {}}

    def test_validate_tool_call_rejects_non_dicts(self):
        assert _validate_tool_call(None) is None
        assert _validate_tool_call("set_theme") is None
        assert _validate_tool_call({"tool": "set_theme", "arguments": ["dark"]}) is None


class TestExecution:
    @pytest.fixture(autouse=True)
    def _clean_preferences(self):
        # Execution tests share the module's database, and earlier tests write the exact rows
        # later ones assert on — start each one from an empty preference table.
        with SessionLocal() as db:
            db.query(UserPreference).delete()
            db.commit()
        yield

    def test_set_theme_persists_preference(self):
        with SessionLocal() as db:
            record = execute_action(db, "set_theme", {"theme": "light"}, "ollama", "test-model")
            assert record["summary"]
            assert record["result"] == {"theme": "light"}
            assert db.get(UserPreference, THEME_PREFERENCE_KEY).value == {"theme": "light"}

    def test_set_default_model_preserves_other_halves(self):
        with SessionLocal() as db:
            db.merge(UserPreference(key=AI_PREFERENCE_KEY, value={
                "provider": "ollama", "model": "llama3.2:latest", "reasoning_mode": "thinking",
            }))
            db.commit()
            record = execute_action(
                db, "set_default_model", {"provider": "groq", "model": "openai/gpt-oss-20b"}, "ollama", "test-model",
            )
            assert record["result"] == {"provider": "groq", "model": "openai/gpt-oss-20b"}
            saved = db.get(UserPreference, AI_PREFERENCE_KEY).value
            assert saved["provider"] == "groq"
            assert saved["model"] == "openai/gpt-oss-20b"
            assert saved["reasoning_mode"] == "thinking"

    def test_set_default_model_derives_provider_from_model_prefix(self):
        with SessionLocal() as db:
            record = execute_action(db, "set_default_model", {"provider": "", "model": "gpt-4o"}, "ollama", "test-model")
            assert record["result"] == {"provider": "openai", "model": "gpt-4o"}

    def test_set_default_model_bare_provider_keeps_an_existing_matching_model(self):
        with SessionLocal() as db:
            db.merge(UserPreference(key=AI_PREFERENCE_KEY, value={
                "provider": "groq", "model": "llama-3.3-70b-versatile",
            }))
            db.commit()
            record = execute_action(db, "set_default_model", {"provider": "groq", "model": ""}, "ollama", "test-model")
            assert record["result"] == {"provider": "groq", "model": "llama-3.3-70b-versatile"}

    def test_set_default_model_bare_provider_falls_back_to_provider_default(self):
        with SessionLocal() as db:
            record = execute_action(db, "set_default_model", {"provider": "gemini", "model": ""}, "ollama", "test-model")
            assert record["result"]["provider"] == "gemini"
            assert record["result"]["model"]

    def test_run_model_health_test_probes_and_stores(self, monkeypatch):
        monkeypatch.setattr(
            "backend.app.llm.probe_model",
            lambda provider, model: {"ok": True, "latency_ms": 42, "error": None},
        )
        with SessionLocal() as db:
            record = execute_action(db, "run_model_health_test", {}, "groq", "llama-3.3-70b-versatile")
            assert record["result"]["ok"] is True
            assert record["result"]["latency_ms"] == 42
            saved = db.get(UserPreference, MODEL_HEALTH_PREFERENCE_KEY).value
            assert saved["groq"]["llama-3.3-70b-versatile"]["ok"] is True

    def test_run_model_health_test_reports_a_failure(self, monkeypatch):
        monkeypatch.setattr(
            "backend.app.llm.probe_model",
            lambda provider, model: {"ok": False, "latency_ms": 0, "error": "timeout"},
        )
        with SessionLocal() as db:
            record = execute_action(db, "run_model_health_test", {}, "groq", "llama-3.3-70b-versatile")
            assert record["result"]["ok"] is False
            assert "did not respond" in record["summary"]

    def test_get_settings_reads_preferences(self):
        with SessionLocal() as db:
            db.merge(UserPreference(key=THEME_PREFERENCE_KEY, value={"theme": "light"}))
            db.commit()
            record = execute_action(db, "get_settings", {}, "ollama", "test-model")
            assert record["result"]["theme"] == "light"
            assert record["result"]["provider"]
            assert record["result"]["model"]

    def test_get_settings_reports_configured_providers_and_health(self):
        with SessionLocal() as db:
            record = execute_action(db, "get_settings", {}, "ollama", "test-model")
            # Ollama needs no API key, so at least one provider is always configured.
            assert "ollama" in record["result"]["configured_providers"]
            assert record["result"]["models_responding"] <= record["result"]["models_tested"]
            assert "Providers configured:" in record["summary"]
            assert "Model health:" in record["summary"]

    def test_get_model_health_with_nothing_tested(self):
        with SessionLocal() as db:
            record = execute_action(db, "get_model_health", {}, "ollama", "test-model")
            assert record["result"] == {"health": {}}
            assert "No model has been health-tested" in record["summary"]

    def test_unknown_tool_never_writes(self):
        with SessionLocal() as db:
            record = execute_action(db, "delete_all_data", {}, "ollama", "test-model")
            assert record["result"] == {}
            assert db.get(UserPreference, THEME_PREFERENCE_KEY) is None


class TestJobEndToEnd:
    def test_theme_action_job_surfaces_actions_taken(self):
        with TestClient(app) as client:
            response = client.post("/api/chat/jobs", json={
                "question": "switch to dark mode", "reasoning_mode": "light", "file_ids": [],
            })
            assert response.status_code == 202
            job = wait_for_job(client, response.json()["id"])
            assert job["status"] == "completed"
            actions = job["result"]["actions_taken"]
            assert actions == [{"tool": "set_theme", "summary": job["result"]["answer"], "result": {"theme": "dark"}}]
            assert client.get("/api/preferences/theme").json()["value"]["theme"] == "dark"
            messages = client.get(f"/api/chats/{job['conversation_id']}/messages").json()
            assert any(m["role"] == "assistant" and "theme" in m["content"].lower() for m in messages)
            assert any(m["role"] == "user" and m["content"] == "switch to dark mode" for m in messages)

    def test_model_action_job_updates_explore_ai(self):
        with TestClient(app) as client:
            response = client.post("/api/chat/jobs", json={
                "question": "make gpt-4o the default model", "reasoning_mode": "light", "file_ids": [],
            })
            assert response.status_code == 202
            job = wait_for_job(client, response.json()["id"])
            assert job["status"] == "completed"
            actions = job["result"]["actions_taken"]
            assert actions[0]["tool"] == "set_default_model"
            assert actions[0]["result"]["provider"] == "openai"
            assert actions[0]["result"]["model"] == "gpt-4o"
            assert client.get("/api/preferences/explore_ai").json()["value"]["provider"] == "openai"
