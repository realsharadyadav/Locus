"""Comprehensive tests for light mode, web search, long conversations, output formats, and streaming."""
import json
import time
from itertools import count

import pytest

from fastapi.testclient import TestClient

from backend.app.database import SessionLocal
from backend.app.llm import clean_final_answer, is_refusal, stream_answer
from backend.app.main import app
import backend.app.main as main_module
import backend.app.web_research as web_research_module
from backend.app.modes import MODE_CONFIG
from backend.app.models import ChatJob, ChatSession
from backend.app.schemas import ChatRequest


# Read straight off the schema so a bumped limit can never silently strand these tests
# on a boundary the API stopped enforcing.
QUESTION_MAX_CHARS = next(rule.max_length for rule in ChatRequest.model_fields["question"].metadata if getattr(rule, "max_length", None))

def fake_agentic(captured, answer="Agentic answer", sources=()):
    """Stand-in for run_agentic_pipeline that records what main.py handed it."""
    def run(question, model, progress, source_limit=5, history=None, answer_mode="light", force_web=False, web_research_fn=None, direct_answer_fn=None):
        captured.update(question=question, model=model, source_limit=source_limit, history=history, answer_mode=answer_mode, force_web=force_web)
        return {"answer": answer, "sources": list(sources), "model": model, "plan": {}}
    return run



# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def chat(client, **payload):
    response = client.post("/api/chat/stream", json=payload)
    assert response.status_code == 200
    result = None
    for line in response.text.strip().split("\n"):
        if not line.strip():
            continue
        event = json.loads(line)
        if event.get("type") == "result":
            result = event["data"]
        if event.get("type") == "error":
            raise AssertionError(event["detail"])
    assert result is not None
    return result


def _upload_text(client, store_id, name, content):
    resp = client.post(
        "/api/files",
        data={"store_id": store_id},
        files={"file": (name, content.encode() if isinstance(content, str) else content, "text/plain")},
    )
    assert resp.status_code == 201
    return resp.json()


@pytest.fixture(autouse=True)
def mock_quality_layer(monkeypatch):
    monkeypatch.setattr(
        "backend.app.main.enhance_question",
        lambda question, history, model: {
            "enhanced_question": question, "subquestions": [],
            "answer_format": "Clear answer", "supporting_details": [],
            "visualization": "none", "completeness_criteria": ["Answer the question"],
            "requires_full_relevant_files": False,
            "aggregation_operation": "none", "entity_type": None,
        },
    )
    monkeypatch.setattr(
        "backend.app.main.verify_response",
        lambda question, answer, plan, model, sources=None: {"complete": True, "missing": [], "quality_score": 95},
    )
    monkeypatch.setattr(
        "backend.app.main.answer_planned_question",
        lambda question, plan, evidence, history, model, allow_general_knowledge, guidance, notify=lambda detail: None, on_token=None: ("Test answer", model),
    )
    monkeypatch.setattr(
        "backend.app.main.extract_shared_evidence",
        lambda question, requirements, documents, model, notify=lambda detail: None: documents,
    )
    monkeypatch.setattr(
        "backend.app.main.generate_answer",
        lambda question, sources, history=None, model=None, allow_general_knowledge=True, reasoning_mode="light", guidance="", system_override=None: ("Test answer", model or "test-model"),
    )


# =====================================================================
# SECTION 1: LIGHT MODE TESTS (30 tests)
# =====================================================================

class TestLightModeDirectChat:
    """Light mode without files — should go directly to model, no pipeline."""

    def test_light_direct_returns_model_answer(self, monkeypatch):
        monkeypatch.setattr("backend.app.main.generate_answer", lambda *a, **k: ("Direct answer", "test-model"))
        with TestClient(app) as c:
            r = chat(c, question="What is Python?", reasoning_mode="light", file_ids=[])
            assert r["answer"] == "Direct answer"
            assert r["sources"] == []

    def test_light_direct_does_not_call_enhance_question(self, monkeypatch):
        called = []
        monkeypatch.setattr("backend.app.main.enhance_question", lambda *a, **k: called.append(1) or {})
        monkeypatch.setattr("backend.app.main.generate_answer", lambda *a, **k: ("ok", "m"))
        with TestClient(app) as c:
            chat(c, question="hi there", reasoning_mode="light", file_ids=[])
            assert called == []

    def test_light_direct_does_not_call_answer_planned(self, monkeypatch):
        called = []
        monkeypatch.setattr("backend.app.main.answer_planned_question", lambda *a, **k: called.append(1) or ("", ""))
        monkeypatch.setattr("backend.app.main.generate_answer", lambda *a, **k: ("ok", "m"))
        with TestClient(app) as c:
            chat(c, question="hello", reasoning_mode="light", file_ids=[])
            assert called == []

    def test_light_with_files_uses_planner(self, monkeypatch):
        calls = []
        monkeypatch.setattr("backend.app.main.answer_planned_question", lambda *a, **k: calls.append(1) or ("file answer", "m"))
        with TestClient(app) as c:
            s = c.post("/api/collections", json={"title": "S"}).json()
            _upload_text(c, s["id"], "doc.txt", "The quick brown fox jumps over the lazy dog")
            chat(c, question="What does the document say about foxes?", reasoning_mode="light")
            assert calls

    def test_light_preserves_conversation_id(self, monkeypatch):
        monkeypatch.setattr("backend.app.main.generate_answer", lambda *a, **k: ("ok", "m"))
        with TestClient(app) as c:
            r1 = chat(c, question="First question in light", reasoning_mode="light", file_ids=[])
            cid = r1["conversation_id"]
            r2 = chat(c, question="Second follow-up", conversation_id=cid, reasoning_mode="light", file_ids=[])
            assert r2["conversation_id"] == cid

    def test_light_mode_skips_quality_layer(self, monkeypatch):
        verify_calls = []
        monkeypatch.setattr("backend.app.main.verify_response", lambda *a, **k: verify_calls.append(1) or {"complete": True, "missing": [], "quality_score": 100})
        monkeypatch.setattr("backend.app.main.generate_answer", lambda *a, **k: ("ok", "m"))
        with TestClient(app) as c:
            chat(c, question="Quality check bypass", reasoning_mode="light", file_ids=[])
            assert verify_calls == []

    def test_light_mode_with_no_files_and_all_files(self, monkeypatch):
        """Light mode with file_ids=None (all files) should use the planner pipeline."""
        calls = []
        monkeypatch.setattr("backend.app.main.answer_planned_question", lambda *a, **k: calls.append(1) or ("all files answer", "m"))
        with TestClient(app) as c:
            s = c.post("/api/collections", json={"title": "Test"}).json()
            _upload_text(c, s["id"], "data.txt", "Important information about algorithms and data structures")
            r = chat(c, question="Explain algorithms", reasoning_mode="light")
            assert r["answer"] == "all files answer"
            assert calls

    def test_light_greeting_does_not_plan(self, monkeypatch):
        monkeypatch.setattr("backend.app.main.generate_answer", lambda *a, **k: ("Hi! How can I help?", "m"))
        with TestClient(app) as c:
            r = chat(c, question="hi", reasoning_mode="light", file_ids=[])
            assert r["answer"] == "Hi! How can I help?"

    def test_light_code_request_returns_code(self, monkeypatch):
        def fake_answer(question, sources, history=None, model=None, allow_general_knowledge=True, reasoning_mode="light", guidance=""):
            return "```python\nprint('hello')\n```", model or "m"
        monkeypatch.setattr("backend.app.main.generate_answer", fake_answer)
        with TestClient(app) as c:
            r = chat(c, question="Write hello world in Python", reasoning_mode="light", file_ids=[])
            assert "```python" in r["answer"]

    def test_light_list_request_returns_list(self, monkeypatch):
        def fake_answer(question, sources, history=None, model=None, allow_general_knowledge=True, reasoning_mode="light", guidance=""):
            return "1. First item\n2. Second item\n3. Third item", model or "m"
        monkeypatch.setattr("backend.app.main.generate_answer", fake_answer)
        with TestClient(app) as c:
            r = chat(c, question="List three programming languages", reasoning_mode="light", file_ids=[])
            assert "1." in r["answer"]

    def test_light_table_request_returns_table(self, monkeypatch):
        def fake_answer(question, sources, history=None, model=None, allow_general_knowledge=True, reasoning_mode="light", guidance=""):
            return "| Language | Type |\n|---|---|\n| Python | Interpreted |", model or "m"
        monkeypatch.setattr("backend.app.main.generate_answer", fake_answer)
        with TestClient(app) as c:
            r = chat(c, question="Show languages in a table", reasoning_mode="light", file_ids=[])
            assert "|" in r["answer"]

    def test_light_provider_and_model_stored(self, monkeypatch):
        monkeypatch.setattr("backend.app.main.generate_answer", lambda *a, **k: ("ok", "llama3.2:latest"))
        with TestClient(app) as c:
            r = chat(c, question="Provider check", reasoning_mode="light", file_ids=[], provider="ollama", model="llama3.2:latest")
            msgs = c.get(f"/api/chats/{r['conversation_id']}/messages").json()
            assistant_msg = [m for m in msgs if m["role"] == "assistant"][-1]
            assert assistant_msg["provider"] == "ollama"
            assert assistant_msg["model"] == "llama3.2:latest"

    def test_light_long_question_accepted(self, monkeypatch):
        monkeypatch.setattr("backend.app.main.generate_answer", lambda *a, **k: ("long q answer", "m"))
        with TestClient(app) as c:
            long_q = "What is " + "very " * 100 + "detailed?"  # within 1000 char limit
            r = chat(c, question=long_q[:1000], reasoning_mode="light", file_ids=[])
            assert r["answer"] == "long q answer"

    def test_light_minimal_question_accepted(self, monkeypatch):
        monkeypatch.setattr("backend.app.main.generate_answer", lambda *a, **k: ("ok", "m"))
        with TestClient(app) as c:
            r = chat(c, question="ok", reasoning_mode="light", file_ids=[])
            assert r["answer"] == "ok"

    def test_light_rejects_empty_question(self):
        with TestClient(app) as c:
            resp = c.post("/api/chat/stream", json={"question": "", "reasoning_mode": "light", "file_ids": []})
            assert resp.status_code == 422

    def test_light_rejects_single_char_question(self):
        with TestClient(app) as c:
            resp = c.post("/api/chat/stream", json={"question": "a", "reasoning_mode": "light", "file_ids": []})
            assert resp.status_code == 422

    def test_light_multiple_files_selects_top_excerpts(self, monkeypatch):
        captured = {}
        def fake_answer(question, plan, evidence, history, model, allow_general_knowledge, guidance, notify=lambda d: None, on_token=None):
            captured["evidence"] = evidence
            return ("multi file answer", model)
        monkeypatch.setattr("backend.app.main.answer_planned_question", fake_answer)
        with TestClient(app) as c:
            s = c.post("/api/collections", json={"title": "Multi"}).json()
            _upload_text(c, s["id"], "a.txt", "Alpha content about dogs and cats")
            _upload_text(c, s["id"], "b.txt", "Beta content about birds and fish")
            _upload_text(c, s["id"], "c.txt", "Gamma content about reptiles and amphibians")
            _upload_text(c, s["id"], "d.txt", "Delta content about insects and spiders")
            chat(c, question="What animals are mentioned?", reasoning_mode="light")
            assert len(captured["evidence"]) <= 4

    def test_light_file_id_empty_list_vs_none(self, monkeypatch):
        """file_ids=[] means 'no files', file_ids=None means 'all files'."""
        all_files_calls = []
        no_files_calls = []
        monkeypatch.setattr("backend.app.main.generate_answer", lambda *a, **k: no_files_calls.append(1) or ("no files", "m"))
        monkeypatch.setattr("backend.app.main.answer_planned_question", lambda *a, **k: all_files_calls.append(1) or ("all files", "m"))
        with TestClient(app) as c:
            s = c.post("/api/collections", json={"title": "F"}).json()
            _upload_text(c, s["id"], "doc.txt", "Some content about testing")
            chat(c, question="test empty", reasoning_mode="light", file_ids=[])
            assert no_files_calls and not all_files_calls

    def test_light_mode_title_truncated(self, monkeypatch):
        monkeypatch.setattr("backend.app.main.generate_answer", lambda *a, **k: ("ok", "m"))
        with TestClient(app) as c:
            long_title = "A" * 100
            r = chat(c, question=long_title, reasoning_mode="light", file_ids=[])
            chats = c.get("/api/chats").json()
            chat_session = next(ch for ch in chats if ch["id"] == r["conversation_id"])
            assert len(chat_session["title"]) <= 70


class TestLightModeFileBased:
    """Light mode with file selection — tests excerpt selection and grounding."""

    def test_light_file_grounded_answer(self, monkeypatch):
        def fake_answer(question, plan, evidence, history, model, allow_general_knowledge, guidance, notify=lambda d: None, on_token=None):
            if evidence:
                return (f"Based on {evidence[0][0]}: the answer is here", model)
            return ("no evidence", model)
        monkeypatch.setattr("backend.app.main.answer_planned_question", fake_answer)
        with TestClient(app) as c:
            s = c.post("/api/collections", json={"title": "G"}).json()
            f = _upload_text(c, s["id"], "report.txt", "The company revenue grew 25% in Q3 2024 reaching ₹50 crores")
            r = chat(c, question="What was the company revenue in Q3?", reasoning_mode="light", file_ids=[f["id"]])
            assert "report.txt" in r["answer"]

    def test_light_file_excerpt_max_length(self, monkeypatch):
        captured = {}
        def fake_answer(question, plan, evidence, history, model, allow_general_knowledge, guidance, notify=lambda d: None, on_token=None):
            captured["evidence"] = evidence
            return ("ok", model)
        monkeypatch.setattr("backend.app.main.answer_planned_question", fake_answer)
        with TestClient(app) as c:
            s = c.post("/api/collections", json={"title": "L"}).json()
            big_text = "word " * 5000
            f = _upload_text(c, s["id"], "big.txt", big_text)
            chat(c, question="word", reasoning_mode="light", file_ids=[f["id"]])
            assert captured["evidence"]
            for name, excerpt in captured["evidence"]:
                assert len(excerpt) <= 2201

    def test_light_no_general_knowledge_strict(self, monkeypatch):
        with TestClient(app) as c:
            r = chat(c, question="Explain recursion", reasoning_mode="light", allow_general_knowledge=False)
            assert "uploaded files" in r["answer"].lower() or "couldn't find" in r["answer"].lower()

    def test_light_general_knowledge_allowed(self, monkeypatch):
        monkeypatch.setattr("backend.app.main.generate_answer", lambda *a, **k: ("Recursion is calling a function within itself.", "m"))
        with TestClient(app) as c:
            r = chat(c, question="What is recursion?", reasoning_mode="light", file_ids=[], allow_general_knowledge=True)
            assert "recursion" in r["answer"].lower()


# =====================================================================
# SECTION 2: WEB SEARCH TESTS (35 tests)
# =====================================================================

class TestWebSearchAutoDetect:
    """Auto web search detection from question keywords."""

    @pytest.mark.parametrize("question", [
        "search the web for latest AI news",
        "browse for React 19 updates",
        "google best Python libraries",
        "find me the latest JavaScript frameworks",
        "look up current Rust trends",
    ])
    def test_auto_web_search_triggers_on_search_keywords(self, question):
        assert main_module.should_auto_web_search(question, "light") is True

    @pytest.mark.parametrize("question", [
        "latest news about OpenAI",
        "current trends in web development",
        "recent updates to TypeScript",
        "today's top programming languages",
        "this week in tech news",
        "breaking: new AI model released",
    ])
    def test_auto_web_search_triggers_on_recency_keywords(self, question):
        assert main_module.should_auto_web_search(question, "light") is True

    @pytest.mark.parametrize("question", [
        "difference between TCP and UDP",
        "compare Postgres and MySQL",
        "React vs Vue",
    ])
    def test_auto_web_search_triggers_on_comparison_keywords(self, question):
        assert main_module.should_auto_web_search(question, "light") is True

    @pytest.mark.parametrize("question", [
        "best youtube tutorials for Python",
        "find videos about React hooks",
    ])
    def test_auto_web_search_triggers_on_youtube(self, question):
        assert main_module.should_auto_web_search(question, "light") is True

    @pytest.mark.parametrize("question", [
        "what are the sources for this claim",
        "give me citations for this info",
        "provide links to your references",
    ])
    def test_auto_web_search_triggers_on_citation_keywords(self, question):
        assert main_module.should_auto_web_search(question, "light") is True

    @pytest.mark.parametrize("question", [
        "best phones under 15000",
        "laptops below Rs 50000",
        "monitors within 10000 rupees",
        "keyboards under 5k",
    ])
    def test_auto_web_search_triggers_on_budget_patterns(self, question):
        assert main_module.should_auto_web_search(question, "light") is True

    @pytest.mark.parametrize("question", [
        "explain recursion",
        "what is machine learning",
        "how does a neural network work",
    ])
    def test_auto_web_search_does_not_trigger_on_generic_questions(self, question):
        assert main_module.should_auto_web_search(question, "light") is False

    def test_auto_web_search_disabled_for_deep_summary(self):
        assert main_module.should_auto_web_search("search for current trends", "deep_summary") is False

    def test_auto_web_search_empty_question(self):
        assert main_module.should_auto_web_search("", "light") is False

    def test_auto_web_search_whitespace_only(self):
        assert main_module.should_auto_web_search("   ", "light") is False

    def test_web_research_mode_always_triggers(self, monkeypatch):
        monkeypatch.setattr("backend.app.main.web_research", lambda *a, **k: {"answer": "web answer", "sources": [], "model": "m"})
        with TestClient(app) as c:
            payload = {"question": "Explain recursion", "reasoning_mode": "web_research"}
            resp = c.post("/api/chat/stream", json=payload)
            assert resp.status_code == 200


class TestWebSearchManualTrigger:
    """Manual web search toggle and source limits."""

    def test_manual_web_search_enabled(self, monkeypatch):
        captured = {}
        def fake_web(question, model, progress, source_limit=5, history=None, answer_mode="web_research"):
            captured["source_limit"] = source_limit
            return {"answer": "Web answer", "sources": [], "model": model}
        monkeypatch.setattr("backend.app.main.web_research", fake_web)
        with TestClient(app) as c:
            r = chat(c, question="Research quantum computing", web_search=True, web_source_limit=10)
            assert r["answer"] == "Web answer"
            assert captured["source_limit"] == 10

    def test_web_source_limit_below_minimum_rejected(self):
        with TestClient(app) as c:
            resp = c.post("/api/chat/jobs", json={"question": "Research", "reasoning_mode": "web_research", "web_source_limit": 2})
            assert resp.status_code == 422

    def test_web_source_limit_max_200(self):
        with TestClient(app) as c:
            resp = c.post("/api/chat/jobs", json={"question": "Research", "reasoning_mode": "web_research", "web_source_limit": 201})
            assert resp.status_code == 422

    def test_web_source_limit_valid_boundaries(self):
        with TestClient(app) as c:
            resp3 = c.post("/api/chat/jobs", json={"question": "Research", "reasoning_mode": "web_research", "web_source_limit": 3})
            assert resp3.status_code == 202
            resp200 = c.post("/api/chat/jobs", json={"question": "Research", "reasoning_mode": "web_research", "web_source_limit": 200})
            assert resp200.status_code == 202


class TestWebSearchPipeline:
    """Web search pipeline: queries, synthesis, budget, format."""

    def test_web_search_budget_expansion(self):
        assert "5000" in web_research_module._expand_budget_shorthand("phones under 5k")
        assert "10000" in web_research_module._expand_budget_shorthand("laptops under 10k")

    def test_web_search_budget_parsing(self):
        assert web_research_module._budget_from_question("phones under 5000") == 5000
        assert web_research_module._budget_from_question("under ₹15000") == 15000
        assert web_research_module._budget_from_question("under 5k phones") == 5000
        assert web_research_module._budget_from_question("under 10 thousand") == 10000
        assert web_research_module._budget_from_question("laptops below Rs 50000") == 50000
        assert web_research_module._budget_from_question("no budget mentioned") is None

    def test_web_search_wants_table_detection(self):
        assert web_research_module._wants_table("show in tabular format") is True
        assert web_research_module._wants_table("create a table") is True
        assert web_research_module._wants_table("grid layout") is True
        assert web_research_module._wants_table("spreadsheet view") is True
        assert web_research_module._wants_table("give me a list") is False
        assert web_research_module._wants_table("explain recursion") is False

    def test_web_search_price_values(self):
        values = web_research_module._price_values("Phone costs ₹4,999 and another is Rs 3500")
        assert 4999 in values
        assert 3500 in values

    def test_web_search_over_budget_detection(self):
        assert web_research_module._is_over_budget_result(
            {"title": "Phone ₹7000", "snippet": "Good phone"}, 5000
        ) is True
        assert web_research_module._is_over_budget_result(
            {"title": "Phone ₹4500", "snippet": "Budget phone"}, 5000
        ) is False
        assert web_research_module._is_over_budget_result(
            {"title": "Phone", "snippet": "No price mentioned"}, 5000
        ) is False

    def test_web_search_clean_query(self):
        q = web_research_module._clean_search_query("bhai give me best phone under 5k in tabular format with mobile name and price")
        assert "bhai" not in q.lower()
        assert "tabular format" not in q.lower()
        assert "mobile name and price" not in q.lower()

    def test_web_search_unique_queries(self):
        queries = web_research_module._unique_queries(["a", "b", "a", "c", "B"])
        assert queries == ["a", "b", "c"]

    def test_web_search_constraint_queries_for_phones(self):
        queries = web_research_module._constraint_queries("best phones under 5000")
        assert len(queries) >= 2
        assert any("5000" in q for q in queries)

    def test_web_search_constraint_queries_for_generic_budget(self):
        queries = web_research_module._constraint_queries("laptops under 30000")
        assert any("30000" in q for q in queries)

    def test_web_search_fallback_answer_with_budget(self):
        answer = web_research_module._fallback_web_answer(
            "best phone under 5k",
            [{"title": "Budget Phone ₹4,500", "snippet": "Good phone under 5k", "engine": "test"}],
        )
        assert "5,000" in answer

    def test_web_search_fallback_answer_no_results(self):
        answer = web_research_module._fallback_web_answer("best phone under 5k", [])
        assert "could not" in answer.lower() or "no" in answer.lower()

    def test_web_search_fallback_table_format(self):
        answer = web_research_module._fallback_web_answer(
            "best phones under 5k in tabular format with mobile name and price",
            [{"title": "Phone ₹4,000", "snippet": "Budget phone", "engine": "test"}],
        )
        assert "|" in answer

    def test_web_search_remove_over_budget_lines(self):
        answer = "| Name | Price |\n|---|---|\n| Expensive | ₹8,000 |\n| Budget | ₹4,500 |"
        cleaned = web_research_module._remove_over_budget_lines(answer, 5000)
        assert "Expensive" not in cleaned
        assert "Budget" in cleaned

    def test_web_search_remove_over_budget_no_budget(self):
        answer = "| Name | Price |\n| Any | ₹99,999 |"
        cleaned = web_research_module._remove_over_budget_lines(answer, None)
        assert cleaned == answer

    def test_web_search_history_followup_detection(self):
        history = [("user", "best phones under 5k"), ("assistant", "Here are some options")]
        q = web_research_module._search_question_with_history("bola tha same phone", history)
        assert "best phones" in q.lower()

    def test_web_search_history_no_followup(self):
        history = [("user", "best phones under 5k"), ("assistant", "Here are some options")]
        q = web_research_module._search_question_with_history("what is recursion", history)
        assert "recursion" in q.lower()

    def test_web_search_youtube_detection(self):
        assert web_research_module._is_youtube_url("https://www.youtube.com/watch?v=abc123") is True
        assert web_research_module._is_youtube_url("https://youtu.be/abc123") is True
        assert web_research_module._is_youtube_url("https://example.com") is False


class TestWebSearchIntegration:
    """End-to-end web search through the API."""

    def test_web_research_mode_routes_to_web(self, monkeypatch):
        captured = {}
        def fake_web(question, model, progress, source_limit=5, history=None, answer_mode="web_research"):
            captured["question"] = question
            captured["answer_mode"] = answer_mode
            return {"answer": "Web research answer", "sources": [{"title": "T", "url": "https://x.com", "snippet": "S", "engine": "ddg"}], "model": model}
        monkeypatch.setattr("backend.app.main.web_research", fake_web)
        with TestClient(app) as c:
            r = chat(c, question="Research Python web frameworks", reasoning_mode="web_research")
            assert r["answer"] == "Web research answer"
            assert captured["answer_mode"] == "web_research"
            assert len(r["sources"]) == 1

    def test_auto_web_search_routes_to_web(self, monkeypatch):
        captured = {}
        def fake_web(question, model, progress, source_limit=5, history=None, answer_mode="web_research"):
            captured["question"] = question
            return {"answer": "Auto web answer", "sources": [], "model": model}
        monkeypatch.setattr("backend.app.main.web_research", fake_web)
        with TestClient(app) as c:
            r = chat(c, question="Search the latest React 19 features", reasoning_mode="light")
            assert r["answer"] == "Auto web answer"

    def test_web_search_with_conversation_history(self, monkeypatch):
        captured = {}
        monkeypatch.setattr("backend.app.main.run_agentic_pipeline", fake_agentic(captured))
        with TestClient(app) as c:
            r1 = chat(c, question="Tell me about Python", reasoning_mode="light", file_ids=[])
        # Conversation history reaches the agentic pipeline, which threads it into
        # planning and answer composition. It is deliberately NOT forwarded to the
        # nested web_research() searches — those run the planner's self-contained
        # queries, so passing history there would only pollute the search terms.
            chat(c, question="Search for latest Python updates", conversation_id=r1["conversation_id"], reasoning_mode="light")
            assert captured["history"]
            assert ("user", "Tell me about Python") in captured["history"]

    def test_web_search_stores_sources_in_message(self, monkeypatch):
        def fake_web(question, model, progress, source_limit=5, history=None, answer_mode="web_research"):
            return {"answer": "Answer", "sources": [{"title": "Source 1", "url": "https://example.com", "snippet": "Snippet", "engine": "ddg"}], "model": model}
        monkeypatch.setattr("backend.app.main.web_research", fake_web)
        with TestClient(app) as c:
            r = chat(c, question="Search for Python tips", reasoning_mode="web_research")
            msgs = c.get(f"/api/chats/{r['conversation_id']}/messages").json()
            assistant_msg = [m for m in msgs if m["role"] == "assistant"][-1]
            assert len(assistant_msg["sources"]) == 1
            assert assistant_msg["sources"][0]["url"] == "https://example.com"


# =====================================================================
# SECTION 3: LONG CONVERSATION TESTS (25 tests)
# =====================================================================

class TestHistoryManagement:
    """History trimming, summarization, and context budget management."""

    def test_long_conversation_history_preserved_in_db(self, monkeypatch):
        monkeypatch.setattr("backend.app.main.generate_answer", lambda *a, **k: ("ok", "m"))
        with TestClient(app) as c:
            r1 = chat(c, question="msg1", reasoning_mode="light", file_ids=[])
            cid = r1["conversation_id"]
            for i in range(15):
                chat(c, question=f"message {i+2}", conversation_id=cid, reasoning_mode="light", file_ids=[])
            msgs = c.get(f"/api/chats/{cid}/messages").json()
            assert len(msgs) == 32  # 2 initial + 15 follow-ups * 2 = 32

    def test_history_passed_to_enhance_question(self, monkeypatch):
        captured = {}
        def fake_enhance(question, history, model):
            captured["history_len"] = len(history) if history else 0
            return {"enhanced_question": question, "subquestions": [], "answer_format": "Clear answer", "supporting_details": [], "visualization": "none", "completeness_criteria": ["Answer"], "requires_full_relevant_files": False, "aggregation_operation": "none", "entity_type": None}
        monkeypatch.setattr("backend.app.main.enhance_question", fake_enhance)
        with TestClient(app) as c:
            # file_ids=None (whole library, empty here), not file_ids=[] (explicit no-files) —
            # the latter now routes thinking mode to web research instead of enhance_question.
            chat(c, question="first", reasoning_mode="thinking", file_ids=None)
            assert captured["history_len"] == 0

    def test_long_conversation_with_files(self, monkeypatch):
        captured = {}
        def fake_answer(question, plan, evidence, history, model, allow_general_knowledge, guidance, notify=lambda d: None, on_token=None):
            captured["history_len"] = len(history) if history else 0
            return ("file answer", model)
        monkeypatch.setattr("backend.app.main.answer_planned_question", fake_answer)
        with TestClient(app) as c:
            s = c.post("/api/collections", json={"title": "Long"}).json()
            f = _upload_text(c, s["id"], "doc.txt", "Content about algorithms and data structures")
            r1 = chat(c, question="Tell me about algorithms", reasoning_mode="thinking", file_ids=[f["id"]])
            cid = r1["conversation_id"]
            for i in range(5):
                chat(c, question=f"Follow-up {i}", conversation_id=cid, reasoning_mode="thinking", file_ids=[f["id"]])
            assert captured["history_len"] > 0

    def test_long_conversation_web_search(self, monkeypatch):
        captured = {}
        monkeypatch.setattr("backend.app.main.run_agentic_pipeline", fake_agentic(captured))
        with TestClient(app) as c:
            r1 = chat(c, question="Search for Python", reasoning_mode="web_research")
            cid = r1["conversation_id"]
            chat(c, question="Search for more", conversation_id=cid, reasoning_mode="web_research")
            assert len(captured["history"]) == 2

    def test_conversation_truncation_from_message(self, monkeypatch):
        monkeypatch.setattr("backend.app.main.generate_answer", lambda *a, **k: ("ok", "m"))
        with TestClient(app) as c:
            r1 = chat(c, question="first message", reasoning_mode="light", file_ids=[])
            cid = r1["conversation_id"]
            chat(c, question="second message", conversation_id=cid, reasoning_mode="light", file_ids=[])
            chat(c, question="third message", conversation_id=cid, reasoning_mode="light", file_ids=[])
            msgs = c.get(f"/api/chats/{cid}/messages").json()
            assert len(msgs) == 6
            edit_from_id = msgs[2]["id"]
            resp = c.delete(f"/api/chats/{cid}/messages/{edit_from_id}/from")
            assert resp.status_code == 200
            remaining = resp.json()
            assert len(remaining) == 2

    def test_conversation_deletion(self, monkeypatch):
        monkeypatch.setattr("backend.app.main.generate_answer", lambda *a, **k: ("ok", "m"))
        with TestClient(app) as c:
            r1 = chat(c, question="delete me unique 12345", reasoning_mode="light", file_ids=[])
            cid = r1["conversation_id"]
            assert any(ch["id"] == cid for ch in c.get("/api/chats").json())
            resp = c.delete(f"/api/chats/{cid}")
            assert resp.status_code == 204
            assert not any(ch["id"] == cid for ch in c.get("/api/chats").json())


# =====================================================================
# SECTION 4: OUTPUT FORMAT TESTS (20 tests)
# =====================================================================

class TestOutputFormats:
    """Different output formats: markdown, tables, code, lists, etc."""

    def test_markdown_bold_format(self, monkeypatch):
        def fake_answer(question, sources, history=None, model=None, allow_general_knowledge=True, reasoning_mode="light", guidance=""):
            return "**Important**: This is bold text.", model or "m"
        monkeypatch.setattr("backend.app.main.generate_answer", fake_answer)
        with TestClient(app) as c:
            r = chat(c, question="Give me important info", reasoning_mode="light", file_ids=[])
            assert "**Important**" in r["answer"]

    def test_markdown_italic_format(self, monkeypatch):
        def fake_answer(question, sources, history=None, model=None, allow_general_knowledge=True, reasoning_mode="light", guidance=""):
            return "*Emphasis* on this point.", model or "m"
        monkeypatch.setattr("backend.app.main.generate_answer", fake_answer)
        with TestClient(app) as c:
            r = chat(c, question="Emphasize this", reasoning_mode="light", file_ids=[])
            assert "*Emphasis*" in r["answer"]

    def test_markdown_heading_format(self, monkeypatch):
        def fake_answer(question, sources, history=None, model=None, allow_general_knowledge=True, reasoning_mode="light", guidance=""):
            return "## Main Topic\n\nContent here.", model or "m"
        monkeypatch.setattr("backend.app.main.generate_answer", fake_answer)
        with TestClient(app) as c:
            r = chat(c, question="Structure this content", reasoning_mode="light", file_ids=[])
            assert "## Main Topic" in r["answer"]

    def test_code_block_python(self, monkeypatch):
        def fake_answer(question, sources, history=None, model=None, allow_general_knowledge=True, reasoning_mode="light", guidance=""):
            return "```python\ndef hello():\n    print('hello')\n```", model or "m"
        monkeypatch.setattr("backend.app.main.generate_answer", fake_answer)
        with TestClient(app) as c:
            r = chat(c, question="Write hello world function", reasoning_mode="light", file_ids=[])
            assert "```python" in r["answer"]
            assert "def hello" in r["answer"]

    def test_code_block_javascript(self, monkeypatch):
        def fake_answer(question, sources, history=None, model=None, allow_general_knowledge=True, reasoning_mode="light", guidance=""):
            return "```javascript\nfunction hello() {\n  console.log('hello');\n}\n```", model or "m"
        monkeypatch.setattr("backend.app.main.generate_answer", fake_answer)
        with TestClient(app) as c:
            r = chat(c, question="Write hello world in JS", reasoning_mode="light", file_ids=[])
            assert "```javascript" in r["answer"]

    def test_unordered_list_format(self, monkeypatch):
        def fake_answer(question, sources, history=None, model=None, allow_general_knowledge=True, reasoning_mode="light", guidance=""):
            return "- Item one\n- Item two\n- Item three", model or "m"
        monkeypatch.setattr("backend.app.main.generate_answer", fake_answer)
        with TestClient(app) as c:
            r = chat(c, question="List three items", reasoning_mode="light", file_ids=[])
            assert "- Item one" in r["answer"]

    def test_ordered_list_format(self, monkeypatch):
        def fake_answer(question, sources, history=None, model=None, allow_general_knowledge=True, reasoning_mode="light", guidance=""):
            return "1. First step\n2. Second step\n3. Third step", model or "m"
        monkeypatch.setattr("backend.app.main.generate_answer", fake_answer)
        with TestClient(app) as c:
            r = chat(c, question="Give me three steps", reasoning_mode="light", file_ids=[])
            assert "1. First step" in r["answer"]

    def test_markdown_table_format(self, monkeypatch):
        def fake_answer(question, sources, history=None, model=None, allow_general_knowledge=True, reasoning_mode="light", guidance=""):
            return "| Name | Age |\n|---|---|\n| Alice | 30 |\n| Bob | 25 |", model or "m"
        monkeypatch.setattr("backend.app.main.generate_answer", fake_answer)
        with TestClient(app) as c:
            r = chat(c, question="Show people in a table", reasoning_mode="light", file_ids=[])
            assert "| Name | Age |" in r["answer"]

    def test_blockquote_format(self, monkeypatch):
        def fake_answer(question, sources, history=None, model=None, allow_general_knowledge=True, reasoning_mode="light", guidance=""):
            return "> This is an important quote\n> from a reliable source", model or "m"
        monkeypatch.setattr("backend.app.main.generate_answer", fake_answer)
        with TestClient(app) as c:
            r = chat(c, question="Quote this for me", reasoning_mode="light", file_ids=[])
            assert "> This is an important quote" in r["answer"]

    def test_mixed_format(self, monkeypatch):
        def fake_answer(question, sources, history=None, model=None, allow_general_knowledge=True, reasoning_mode="light", guidance=""):
            return "**Summary**: Here is a summary.\n\n1. Point one\n2. Point two\n\n```python\ncode()\n```", model or "m"
        monkeypatch.setattr("backend.app.main.generate_answer", fake_answer)
        with TestClient(app) as c:
            r = chat(c, question="Give me a comprehensive answer", reasoning_mode="light", file_ids=[])
            assert "**Summary**" in r["answer"]
            assert "1. Point one" in r["answer"]
            assert "```python" in r["answer"]

    def test_clean_final_answer_removes_plan(self):
        answer = 'Plan: {"format":"table"}\n\nAnswer:\nActual answer here'
        cleaned = clean_final_answer(answer)
        assert "Plan:" not in cleaned
        assert "Actual answer here" in cleaned

    def test_clean_final_answer_removes_sources_section(self):
        answer = "The answer is 42.\n\n## Sources\n1. Wikipedia\n2. GitHub"
        cleaned = clean_final_answer(answer)
        assert "## Sources" not in cleaned
        assert "The answer is 42." in cleaned

    def test_clean_final_answer_preserves_code_blocks(self):
        answer = "Here is code:\n\n```python\nprint('hello')\n```\n\nDone."
        cleaned = clean_final_answer(answer)
        assert "```python" in cleaned
        assert "print('hello')" in cleaned

    def test_clean_final_answer_preserves_tables(self):
        answer = "| A | B |\n|---|---|\n| 1 | 2 |"
        cleaned = clean_final_answer(answer)
        assert "| A | B |" in cleaned

    def test_web_research_table_format(self, monkeypatch):
        captured = {}
        def fake_chat(system, prompt, model, temperature=0.2, max_tokens=None):
            captured["system"] = system
            return "| Phone | Price |\n|---|---|\n| iPhone | ₹50,000 |"
        monkeypatch.setattr(web_research_module, "_chat", fake_chat)
        answer = web_research_module._synthesize_answer(
            "best phones in tabular format",
            [{"title": "Phones", "url": "https://x.com", "snippet": "iPhone ₹50000", "engine": "test"}],
            "model", lambda *args: None,
        )
        assert "Markdown table" in captured["system"]
        assert answer.startswith("| Phone | Price |")

    def test_web_research_conversational_format(self, monkeypatch):
        def fake_chat(system, prompt, model, temperature=0.2, max_tokens=None):
            return "The best phone is the iPhone 16 based on multiple sources [1][2]."
        monkeypatch.setattr(web_research_module, "_chat", fake_chat)
        answer = web_research_module._synthesize_answer(
            "best phone",
            [{"title": "Phones", "url": "https://x.com", "snippet": "iPhone", "engine": "test"}],
            "model", lambda *args: None,
        )
        assert "[1]" in answer


# =====================================================================
# SECTION 5: MODE SWITCHING AND SLASH COMMANDS (15 tests)
# =====================================================================

class TestModeSwitching:
    """Mode switching, slash commands, and mode-specific behavior."""

    def test_mode_configurations_are_distinct(self):
        modes = list(MODE_CONFIG.keys())
        assert len(modes) == 4
        # At least light should differ from thinking in key ways
        assert MODE_CONFIG["light"].inspect_all_chunks != MODE_CONFIG["thinking"].inspect_all_chunks
        assert MODE_CONFIG["light"].use_quality_layer != MODE_CONFIG["thinking"].use_quality_layer
        assert MODE_CONFIG["light"].select_strongest_excerpts_only != MODE_CONFIG["thinking"].select_strongest_excerpts_only

    def test_light_mode_config(self):
        cfg = MODE_CONFIG["light"]
        assert cfg.use_initial_retrieval_only is True
        assert cfg.select_strongest_excerpts_only is True
        assert cfg.inspect_all_chunks is False
        assert cfg.use_quality_layer is False

    def test_thinking_mode_config(self):
        cfg = MODE_CONFIG["thinking"]
        assert cfg.inspect_all_chunks is True
        assert cfg.extract_evidence_from_every_chunk is True
        assert cfg.use_quality_layer is True

    def test_deep_summary_mode_config(self):
        cfg = MODE_CONFIG["deep_summary"]
        assert cfg.inspect_all_chunks is True
        assert cfg.use_quality_layer is True

    def test_web_research_mode_config(self):
        cfg = MODE_CONFIG["web_research"]
        assert cfg.use_initial_retrieval_only is True
        assert cfg.inspect_all_chunks is False

    def test_thinking_mode_quality_layer_active(self, monkeypatch):
        verify_calls = []
        monkeypatch.setattr("backend.app.main.verify_response", lambda *a, **k: verify_calls.append(1) or {"complete": True, "missing": [], "quality_score": 100})
        with TestClient(app) as c:
            # file_ids=None, not [] — an explicit empty selection at High effort now researches
            # the web instead of running the local quality-layer pipeline this test checks.
            chat(c, question="Think about this", reasoning_mode="thinking", file_ids=None)
            assert verify_calls

    def test_light_mode_no_quality_layer(self, monkeypatch):
        verify_calls = []
        monkeypatch.setattr("backend.app.main.verify_response", lambda *a, **k: verify_calls.append(1) or {"complete": True, "missing": [], "quality_score": 100})
        monkeypatch.setattr("backend.app.main.generate_answer", lambda *a, **k: ("ok", "m"))
        with TestClient(app) as c:
            chat(c, question="Quick question", reasoning_mode="light", file_ids=[])
            assert verify_calls == []

    def test_direct_stream_only_light(self):
        with TestClient(app) as c:
            resp = c.post("/api/chat/direct-stream", json={"question": "Hello", "reasoning_mode": "thinking", "file_ids": []})
            assert resp.status_code == 422

    def test_direct_stream_rejects_files(self):
        with TestClient(app) as c:
            resp = c.post("/api/chat/direct-stream", json={"question": "Hello", "reasoning_mode": "light", "file_ids": [1]})
            assert resp.status_code == 422

    def test_direct_stream_rejects_web_search(self):
        with TestClient(app) as c:
            resp = c.post("/api/chat/direct-stream", json={"question": "Search this", "reasoning_mode": "light", "web_search": True, "file_ids": []})
            assert resp.status_code == 422


# =====================================================================
# SECTION 6: STREAMING TESTS (15 tests)
# =====================================================================

class TestStreaming:
    """Streaming response tests: direct-stream and job-based streaming."""

    def test_direct_stream_emits_tokens(self, monkeypatch):
        monkeypatch.setattr("backend.app.main.stream_answer", lambda *a, **k: (iter(["Hello", " ", "World"]), "test-model"))
        with TestClient(app) as c:
            with c.stream("POST", "/api/chat/direct-stream", json={"question": "hi", "provider": "groq", "model": "test-model", "reasoning_mode": "light", "file_ids": []}) as resp:
                assert resp.status_code == 200
                events = [json.loads(line) for line in resp.iter_lines() if line.strip()]
        tokens = "".join(e["text"] for e in events if e["type"] == "token")
        assert tokens == "Hello World"

    def test_direct_stream_persists_message(self, monkeypatch):
        monkeypatch.setattr("backend.app.main.stream_answer", lambda *a, **k: (iter(["Response"]), "test-model"))
        with TestClient(app) as c:
            with c.stream("POST", "/api/chat/direct-stream", json={"question": "persist test", "provider": "groq", "model": "test-model", "reasoning_mode": "light", "file_ids": []}) as resp:
                events = [json.loads(line) for line in resp.iter_lines() if line.strip()]
            result = next(e["data"] for e in events if e["type"] == "result")
            msgs = c.get(f"/api/chats/{result['conversation_id']}/messages").json()
        assert any(m["role"] == "assistant" and m["content"] == "Response" for m in msgs)

    def test_direct_stream_includes_start_event(self, monkeypatch):
        monkeypatch.setattr("backend.app.main.stream_answer", lambda *a, **k: (iter(["ok"]), "test-model"))
        with TestClient(app) as c:
            with c.stream("POST", "/api/chat/direct-stream", json={"question": "start event", "provider": "groq", "model": "test-model", "reasoning_mode": "light", "file_ids": []}) as resp:
                events = [json.loads(line) for line in resp.iter_lines() if line.strip()]
        start_events = [e for e in events if e["type"] == "start"]
        assert len(start_events) == 1
        assert "conversation_id" in start_events[0]

    def test_job_stream_emits_stages(self, monkeypatch):
        with TestClient(app) as c:
            resp = c.post("/api/chat/jobs", json={"question": "Stage test", "reasoning_mode": "light", "file_ids": []})
            assert resp.status_code == 202
            job = resp.json()
            for _ in range(100):
                jobs = c.get("/api/chat/jobs").json()
                job = next((j for j in jobs if j["id"] == job["id"]), None)
                if job["status"] in ("completed", "failed"):
                    break
                time.sleep(0.02)
            assert job["status"] == "completed"
            stages = [e["stage"] for e in job["events"]]
            assert "complete" in stages

    def test_job_stream_emits_result(self, monkeypatch):
        with TestClient(app) as c:
            resp = c.post("/api/chat/jobs", json={"question": "Result test", "reasoning_mode": "light", "file_ids": []})
            job = resp.json()
            for _ in range(100):
                jobs = c.get("/api/chat/jobs").json()
                job = next((j for j in jobs if j["id"] == job["id"]), None)
                if job["status"] in ("completed", "failed"):
                    break
                time.sleep(0.02)
            assert job["result"] is not None
            assert "answer" in job["result"]

    def test_stream_answer_returns_iterator_and_model(self, monkeypatch):
        monkeypatch.setattr("backend.app.llm._stream_chat", lambda *a, **k: (iter(["tok1", "tok2"])))
        result = stream_answer("hi", [], model="test-model", provider="groq")
        tokens, model = result
        assert list(tokens) == ["tok1", "tok2"]
        assert model == "test-model"

    def test_direct_stream_empty_answer_raises(self, monkeypatch):
        monkeypatch.setattr("backend.app.main.stream_answer", lambda *a, **k: (iter([]), "test-model"))
        with TestClient(app) as c:
            with c.stream("POST", "/api/chat/direct-stream", json={"question": "empty", "provider": "groq", "model": "test-model", "reasoning_mode": "light", "file_ids": []}) as resp:
                events = [json.loads(line) for line in resp.iter_lines() if line.strip()]
            error_events = [e for e in events if e["type"] == "error"]
            assert len(error_events) == 1

    def test_stream_cancellation(self, monkeypatch):
        cancelled_by_event = {"called": False}
        def fake_stream(*args, **kwargs):
            cancelled_by_event["called"] = True
            return iter(["partial"]), "test-model"
        monkeypatch.setattr("backend.app.main.stream_answer", fake_stream)
        with TestClient(app) as c:
            with c.stream("POST", "/api/chat/direct-stream", json={"question": "cancel me", "provider": "groq", "model": "test-model", "reasoning_mode": "light", "file_ids": []}) as resp:
                events = [json.loads(line) for line in resp.iter_lines() if line.strip()]
            tokens = [e for e in events if e["type"] == "token"]
            assert len(tokens) == 1
            result = next(e for e in events if e["type"] == "result")
            assert result["data"]["answer"] == "partial"

    def test_multiple_sequential_streams(self, monkeypatch):
        call_count = count()
        def fake_stream(*args, **kwargs):
            n = next(call_count)
            return (iter([f"response {n}"]), "test-model")
        monkeypatch.setattr("backend.app.main.stream_answer", fake_stream)
        with TestClient(app) as c:
            for i in range(3):
                with c.stream("POST", "/api/chat/direct-stream", json={"question": f"q{i}", "provider": "groq", "model": "test-model", "reasoning_mode": "light", "file_ids": []}) as resp:
                    events = [json.loads(line) for line in resp.iter_lines() if line.strip()]
                tokens = "".join(e["text"] for e in events if e["type"] == "token")
                assert tokens == f"response {i}"

    def test_job_cancel(self):
        with TestClient(app) as c:
            with SessionLocal() as db:
                session = ChatSession(title="Cancel test")
                db.add(session)
                db.flush()
                job = ChatJob(id="cancel_test_999", status="running", stage="drafting", detail="Running", question="Cancel me", conversation_id=session.id, model="test-model")
                db.add(job)
                db.commit()
            event = main_module._chat_job_cancel_event("cancel_test_999")
            assert not event.is_set()
            cancel_resp = c.post("/api/chat/jobs/cancel_test_999/cancel")
            assert cancel_resp.status_code == 200
            assert cancel_resp.json()["status"] == "cancelled"
            assert event.is_set()
            main_module._forget_chat_job_cancel_event("cancel_test_999")

    def test_job_mark_seen(self):
        with TestClient(app) as c:
            resp = c.post("/api/chat/jobs", json={"question": "Seen test", "reasoning_mode": "light", "file_ids": []})
            job = resp.json()
            for _ in range(100):
                jobs = c.get("/api/chat/jobs").json()
                job = next((j for j in jobs if j["id"] == job["id"]), None)
                if job["status"] in ("completed", "failed"):
                    break
                time.sleep(0.02)
            seen = c.patch(f"/api/chat/jobs/{job['id']}/seen")
            assert seen.json()["seen"] is True


# =====================================================================
# SECTION 7: EDGE CASES AND ERROR HANDLING (20 tests)
# =====================================================================

class TestEdgeCases:
    """Edge cases: invalid inputs, boundary conditions, error recovery."""

    def test_question_too_long(self):
        with TestClient(app) as c:
            resp = c.post("/api/chat/stream", json={"question": "x" * (QUESTION_MAX_CHARS + 1), "reasoning_mode": "light", "file_ids": []})
            assert resp.status_code == 422

    def test_question_at_maximum_length_accepted(self, monkeypatch):
        monkeypatch.setattr("backend.app.main.generate_answer", lambda *a, **k: ("ok", "m"))
        with TestClient(app) as c:
            r = chat(c, question="a" * QUESTION_MAX_CHARS, reasoning_mode="light", file_ids=[])
            assert r["answer"] == "ok"

    def test_invalid_reasoning_mode(self):
        with TestClient(app) as c:
            resp = c.post("/api/chat/stream", json={"question": "test", "reasoning_mode": "invalid_mode", "file_ids": []})
            assert resp.status_code == 422

    def test_invalid_provider(self):
        with TestClient(app) as c:
            resp = c.post("/api/chat/stream", json={"question": "test", "provider": "invalid_provider", "file_ids": []})
            assert resp.status_code == 422

    def test_nonexistent_conversation(self):
        with TestClient(app) as c:
            resp = c.post("/api/chat/stream", json={"question": "test", "conversation_id": 99999, "reasoning_mode": "light", "file_ids": []})
            assert resp.status_code == 200
            events = [json.loads(line) for line in resp.text.strip().split("\n") if line.strip()]
            error_events = [e for e in events if e.get("type") == "error"]
            assert len(error_events) == 1
            assert "not found" in error_events[0]["detail"].lower()

    def test_nonexistent_file_id(self, monkeypatch):
        with TestClient(app) as c:
            resp = c.post("/api/chat/stream", json={"question": "test", "reasoning_mode": "light", "file_ids": [99999]})
            assert resp.status_code in (404, 200)

    def test_special_characters_in_question(self, monkeypatch):
        monkeypatch.setattr("backend.app.main.generate_answer", lambda *a, **k: ("ok", "m"))
        with TestClient(app) as c:
            r = chat(c, question="What about <script>alert('xss')</script>?", reasoning_mode="light", file_ids=[])
            assert r["answer"] == "ok"

    def test_unicode_in_question(self, monkeypatch):
        monkeypatch.setattr("backend.app.main.generate_answer", lambda *a, **k: ("ok", "m"))
        with TestClient(app) as c:
            r = chat(c, question="What is 你好 world in Japanese?", reasoning_mode="light", file_ids=[])
            assert r["answer"] == "ok"

    def test_emoji_in_question(self, monkeypatch):
        monkeypatch.setattr("backend.app.main.generate_answer", lambda *a, **k: ("ok", "m"))
        with TestClient(app) as c:
            r = chat(c, question="What does 🐍 mean in programming?", reasoning_mode="light", file_ids=[])
            assert r["answer"] == "ok"

    def test_very_long_answer_preserved(self, monkeypatch):
        long_answer = "word " * 5000
        monkeypatch.setattr("backend.app.main.generate_answer", lambda *a, **k: (long_answer, "m"))
        with TestClient(app) as c:
            r = chat(c, question="Give me a long answer", reasoning_mode="light", file_ids=[])
            assert len(r["answer"]) > 1000

    def test_empty_answer_handled(self, monkeypatch):
        monkeypatch.setattr("backend.app.main.generate_answer", lambda *a, **k: ("", "m"))
        with TestClient(app) as c:
            r = chat(c, question="Empty answer test", reasoning_mode="light", file_ids=[])
            assert isinstance(r["answer"], str)

    def test_concurrent_chats(self, monkeypatch):
        monkeypatch.setattr("backend.app.main.generate_answer", lambda *a, **k: ("ok", "m"))
        with TestClient(app) as c:
            r1 = chat(c, question="Chat one", reasoning_mode="light", file_ids=[])
            r2 = chat(c, question="Chat two", reasoning_mode="light", file_ids=[])
            assert r1["conversation_id"] != r2["conversation_id"]

    def test_chats_listing_order(self, monkeypatch):
        monkeypatch.setattr("backend.app.main.generate_answer", lambda *a, **k: ("ok", "m"))
        with TestClient(app) as c:
            r1 = chat(c, question="First chat order unique", reasoning_mode="light", file_ids=[])
            time.sleep(0.02)
            r2 = chat(c, question="Second chat order unique", reasoning_mode="light", file_ids=[])
            chats = c.get("/api/chats").json()
            chat_ids = [ch["id"] for ch in chats]
            assert r2["conversation_id"] in chat_ids
            assert r1["conversation_id"] in chat_ids
            assert chat_ids.index(r2["conversation_id"]) < chat_ids.index(r1["conversation_id"])

    def test_delete_all_chats(self, monkeypatch):
        monkeypatch.setattr("backend.app.main.generate_answer", lambda *a, **k: ("ok", "m"))
        with TestClient(app) as c:
            chat(c, question="Delete me 1", reasoning_mode="light", file_ids=[])
            chat(c, question="Delete me 2", reasoning_mode="light", file_ids=[])
            assert c.get("/api/chats").json()
            resp = c.delete("/api/chats")
            assert resp.status_code == 204
            assert c.get("/api/chats").json() == []

    def test_chat_messages_ordering(self, monkeypatch):
        monkeypatch.setattr("backend.app.main.generate_answer", lambda *a, **k: ("ok", "m"))
        with TestClient(app) as c:
            r = chat(c, question="Order test", reasoning_mode="light", file_ids=[])
            msgs = c.get(f"/api/chats/{r['conversation_id']}/messages").json()
            assert msgs[0]["role"] == "user"
            assert msgs[1]["role"] == "assistant"
            assert msgs[0]["id"] < msgs[1]["id"]

    def test_web_search_error_returns_error_event(self, monkeypatch):
        def fake_web(*args, **kwargs):
            raise RuntimeError("Search service unavailable")
        monkeypatch.setattr("backend.app.main.web_research", fake_web)
        with TestClient(app) as c:
            resp = c.post("/api/chat/stream", json={"question": "Search for errors", "reasoning_mode": "web_research"})
            assert resp.status_code == 200
            events = [json.loads(line) for line in resp.text.strip().split("\n") if line.strip()]
            error_events = [e for e in events if e.get("type") == "error"]
            assert len(error_events) == 1
            assert "search service unavailable" in error_events[0]["detail"].lower()

    def test_web_search_provider_error_returns_error_event(self, monkeypatch):
        def fake_web(*args, **kwargs):
            raise main_module.LLMProviderError("Rate limited", 429)
        monkeypatch.setattr("backend.app.main.web_research", fake_web)
        with TestClient(app) as c:
            resp = c.post("/api/chat/stream", json={"question": "Rate limit test", "reasoning_mode": "web_research"})
            assert resp.status_code == 200
            events = [json.loads(line) for line in resp.text.strip().split("\n") if line.strip()]
            error_events = [e for e in events if e.get("type") == "error"]
            assert len(error_events) == 1
            assert "rate limited" in error_events[0]["detail"].lower()

    def test_refusal_detection(self):
        assert is_refusal("I'm sorry, but I cannot help with that.") is True
        assert is_refusal("I can't provide that information.") is True
        assert is_refusal("As an AI, I cannot assist with that.") is True
        assert is_refusal("Here is the information you requested.") is False
        assert is_refusal("") is True

    def test_budget_pattern_variations(self):
        assert web_research_module._budget_from_question("under 5000") == 5000
        assert web_research_module._budget_from_question("below ₹15000") == 15000
        assert web_research_module._budget_from_question("less than 10k") == 10000
        assert web_research_module._budget_from_question("within 20000 inr") == 20000
        assert web_research_module._budget_from_question("budget of 30000") == 30000
        assert web_research_module._budget_from_question("upto 50000") == 50000
        assert web_research_module._budget_from_question("nothing about price") is None


# =====================================================================
# SECTION: GAP-DRIVEN EVIDENCE ROUNDS
# =====================================================================

class TestEvidenceGapRounds:
    """The quality layer re-retrieves for the verifier's gaps before repairing."""

    @staticmethod
    def _hit(excerpt, file_id=1, score=0.9):
        from backend.app.vector_store import SemanticHit
        return SemanticHit(file_id=file_id, store_id=1, name="gap.txt", excerpt=excerpt, score=score, chunk_index=0)

    def _setup(self, monkeypatch, hits_per_call, verify_results):
        """Wire a thinking-mode run whose verifier reports gaps and whose vector store has more to give."""
        calls = {"verify": 0, "repair": 0, "gap_search": 0, "repair_sources": []}

        def fake_verify(question, answer, plan, model, sources=None):
            index = min(calls["verify"], len(verify_results) - 1)
            calls["verify"] += 1
            return verify_results[index]

        def fake_repair(question, answer, plan, missing, sources, model, allow_general_knowledge, shape_guidance=""):
            calls["repair"] += 1
            calls["repair_sources"].append(len(sources))
            return f"Repaired {calls['repair']}"

        def fake_search(query, file_ids=None, top_k=None):
            index = min(calls["gap_search"], len(hits_per_call) - 1)
            calls["gap_search"] += 1
            return hits_per_call[index]

        monkeypatch.setattr("backend.app.main.verify_response", fake_verify)
        monkeypatch.setattr("backend.app.main.repair_response", fake_repair)
        monkeypatch.setattr("backend.app.main.semantic_search", fake_search)
        return calls

    def test_gap_round_adds_new_evidence_before_repair(self, monkeypatch):
        calls = self._setup(
            monkeypatch,
            hits_per_call=[[self._hit("Fresh chunk about company names")], []],
            verify_results=[{"complete": False, "missing": ["Company names"], "quality_score": 40},
                            {"complete": True, "missing": [], "quality_score": 95}],
        )
        with TestClient(app) as client:
            store = client.post("/api/collections", json={"title": "Gap store"}).json()
            _upload_text(client, store["id"], "gap.txt", "Some company records live here.")
            chat(client, question="Which companies are listed?", reasoning_mode="thinking")

        assert calls["gap_search"] >= 1, "verifier gaps should trigger a fresh retrieval"
        assert calls["repair"] >= 1
        # The repair after a productive gap round must see more context than the first pass had.
        assert calls["repair_sources"][0] > 0

    def test_no_progress_guard_stops_after_one_repair(self, monkeypatch):
        """A gap round that finds nothing new must not loop — re-verifying would grade the same facts."""
        calls = self._setup(
            monkeypatch,
            hits_per_call=[[]],
            verify_results=[{"complete": False, "missing": ["Something absent"], "quality_score": 10}],
        )
        with TestClient(app) as client:
            store = client.post("/api/collections", json={"title": "Empty gap store"}).json()
            _upload_text(client, store["id"], "gap.txt", "Unrelated text.")
            chat(client, question="What is missing?", reasoning_mode="thinking")

        assert calls["repair"] == 1, "no new evidence means exactly one repair, not a retry loop"
        assert calls["verify"] == 1

    def test_rounds_are_capped(self, monkeypatch):
        """Even when every round finds new evidence, CHAT_EVIDENCE_ROUNDS bounds the work."""
        monkeypatch.setattr(main_module, "CHAT_EVIDENCE_ROUNDS", 2)
        endless = [[self._hit(f"Fresh chunk {index}")] for index in range(1, 8)]
        calls = self._setup(
            monkeypatch,
            hits_per_call=endless,
            verify_results=[{"complete": False, "missing": ["Still missing"], "quality_score": 10}],
        )
        with TestClient(app) as client:
            store = client.post("/api/collections", json={"title": "Deep gap store"}).json()
            _upload_text(client, store["id"], "gap.txt", "Plenty of text here.")
            chat(client, question="Dig as deep as you can", reasoning_mode="thinking")

        assert calls["repair"] <= main_module.CHAT_EVIDENCE_ROUNDS + 1
        assert calls["verify"] <= main_module.CHAT_EVIDENCE_ROUNDS + 1

    def test_light_mode_runs_no_gap_rounds(self, monkeypatch):
        """Light mode has no quality layer, so it must stay a single retrieval pass."""
        calls = self._setup(
            monkeypatch,
            hits_per_call=[[self._hit("Fresh chunk")]],
            verify_results=[{"complete": False, "missing": ["Anything"], "quality_score": 10}],
        )
        with TestClient(app) as client:
            store = client.post("/api/collections", json={"title": "Light store"}).json()
            _upload_text(client, store["id"], "light.txt", "Light mode content.")
            chat(client, question="Quick question", reasoning_mode="light")

        assert calls["verify"] == 0
        assert calls["repair"] == 0


class TestAnswerShapeGuidance:
    """The scannable answer shape reaches composition, but not the modes that own their own shape."""

    def test_shape_reaches_composition_guidance(self, monkeypatch):
        captured = {}
        monkeypatch.setattr(
            "backend.app.main.answer_planned_question",
            lambda question, plan, evidence, history, model, allow_general_knowledge, guidance, notify=lambda detail: None, on_token=None: (captured.update(guidance=guidance) or ("Answer", model)),
        )
        with TestClient(app) as client:
            store = client.post("/api/collections", json={"title": "Shape store"}).json()
            _upload_text(client, store["id"], "shape.txt", "Content to answer from.")
            chat(client, question="Explain this", reasoning_mode="thinking")

        assert "scanned in seconds" in captured["guidance"]

    def test_deep_summary_keeps_its_own_shape(self):
        assert main_module._answer_shape_guidance("deep_summary") == ""
        assert main_module._answer_shape_guidance("thinking") != ""
        assert main_module._answer_shape_guidance("light") != ""


class TestFollowUpSuggestions:
    """Follow-up chips are a nicety — a bad model response must not turn them into a 500."""

    def test_malformed_json_yields_empty_suggestions_not_an_error(self, monkeypatch):
        # Braces present so the salvage path in _json_object engages, but the content between
        # them is not valid JSON — this used to escape as JSONDecodeError and 500 the request.
        monkeypatch.setattr("backend.app.llm._chat", lambda *a, **k: 'here you go: {suggestions: [oops,,]}')
        with TestClient(app) as client:
            response = client.post("/api/chat/suggestions", json={"question": "What is this?", "answer": "A thing."})
        assert response.status_code == 200
        assert response.json()["suggestions"] == []

    def test_provider_failure_yields_empty_suggestions(self, monkeypatch):
        def boom(*args, **kwargs):
            raise RuntimeError("provider exploded")
        monkeypatch.setattr("backend.app.main.generate_followup_questions", boom)
        with TestClient(app) as client:
            response = client.post("/api/chat/suggestions", json={"question": "Q", "answer": "A"})
        assert response.status_code == 200
        assert response.json()["suggestions"] == []

    def test_valid_response_returns_suggestions(self, monkeypatch):
        monkeypatch.setattr(
            "backend.app.llm._chat",
            lambda *a, **k: '{"suggestions": ["What about latency?", "How does it scale?"]}',
        )
        with TestClient(app) as client:
            response = client.post("/api/chat/suggestions", json={"question": "Q", "answer": "A"})
        assert response.status_code == 200
        assert response.json()["suggestions"] == ["What about latency?", "How does it scale?"]

    def test_json_object_raises_runtime_error_on_unsalvageable_braces(self):
        from backend.app.llm import _json_object
        with pytest.raises(RuntimeError):
            _json_object("prefix {not: valid, json,,} suffix")

    def test_bare_array_response_still_yields_suggestions(self, monkeypatch):
        # Smaller/local models often ignore the "object with a suggestions key" instruction and
        # return a plain JSON array — this used to raise inside _json_object (no {...} present)
        # and get swallowed into an empty list, so the chips never rendered.
        monkeypatch.setattr(
            "backend.app.llm._chat",
            lambda *a, **k: 'Sure, here you go:\n```json\n["What about latency?", "How does it scale?"]\n```',
        )
        with TestClient(app) as client:
            response = client.post("/api/chat/suggestions", json={"question": "Q", "answer": "A"})
        assert response.status_code == 200
        assert response.json()["suggestions"] == ["What about latency?", "How does it scale?"]

    def test_clean_bare_array_response_yields_suggestions(self, monkeypatch):
        # A *clean* bare array with no surrounding text or code fence is the trap the previous
        # fix missed: json.loads succeeds on the very first try and hands back a list, so there
        # is no exception for a "catch RuntimeError and fall back" path to catch. Calling .get()
        # on that list threw an uncaught AttributeError, which looked identical to "no suggestions".
        monkeypatch.setattr(
            "backend.app.llm._chat",
            lambda *a, **k: '["What about latency?", "How does it scale?"]',
        )
        with TestClient(app) as client:
            response = client.post("/api/chat/suggestions", json={"question": "Q", "answer": "A"})
        assert response.status_code == 200
        assert response.json()["suggestions"] == ["What about latency?", "How does it scale?"]

    def test_long_answer_is_not_rejected_before_it_ever_reaches_generate_followup_questions(self, monkeypatch):
        # A comprehensive web-research/deep_summary answer with several cited
        # sources easily runs tens of thousands of characters. The old 20000-char ceiling on
        # SuggestionsRequest.answer rejected those with a 422 from Pydantic validation - which
        # runs before this endpoint's own try/except, so it never even showed up as a diagnostic
        # event, and the frontend's catch turned it into indistinguishable-from-"no suggestions"
        # silence. generate_followup_questions only ever uses the first 4000 chars anyway.
        monkeypatch.setattr(
            "backend.app.llm._chat",
            lambda *a, **k: '{"suggestions": ["What about latency?", "How does it scale?"]}',
        )
        long_answer = "Detailed, source-backed finding. " * 1000  # ~34,000 chars
        assert len(long_answer) > 20_000
        with TestClient(app) as client:
            response = client.post("/api/chat/suggestions", json={"question": "Q", "answer": long_answer})
        assert response.status_code == 200
        assert response.json()["suggestions"] == ["What about latency?", "How does it scale?"]
