import json
import os
import time
from types import SimpleNamespace
from threading import Event, Thread
import pytest

os.environ["LOCUS_DATABASE_URL"] = "sqlite:///./test_locus.db"

from fastapi.testclient import TestClient

from backend.app.database import Base, engine
from backend.app.database import SessionLocal
from backend.app.config import ENV_PATH, require_environment_variable
from backend.app.deep_summary import CoverageManifest, chunk_document, deep_summarize_documents, is_full_summary_intent, missing_sections
from backend.app.llm import _chat, _context_budget, _pack_sources, _trim_history, answer_planned_question, clean_final_answer, summarize_document
from backend.app.main import app
import backend.app.main as main_module
import backend.app.web_research as web_research_module
from backend.app.modes import MODE_CONFIG
from backend.app.models import ChatJob, ChatMessage, ChatSession


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


@pytest.fixture(autouse=True)
def mock_quality_layer(monkeypatch):
    monkeypatch.setattr("backend.app.main.enhance_question", lambda question, history, model: {"enhanced_question": question, "subquestions": [], "answer_format": "Clear answer", "supporting_details": [], "visualization": "none", "completeness_criteria": ["Answer the question"], "requires_full_relevant_files": False, "aggregation_operation": "none", "entity_type": None})
    monkeypatch.setattr("backend.app.main.verify_response", lambda question, answer, plan, model, sources=None: {"complete": True, "missing": [], "quality_score": 95})
    monkeypatch.setattr("backend.app.main.answer_planned_question", lambda question, plan, evidence, history, model, allow_general_knowledge, guidance, notify=lambda detail: None: ("Test answer", model))
    monkeypatch.setattr("backend.app.main.extract_shared_evidence", lambda question, requirements, documents, model, notify=lambda detail: None: documents)


def setup_module():
    Base.metadata.drop_all(bind=engine)


def teardown_module():
    Base.metadata.drop_all(bind=engine)
    if os.path.exists("test_locus.db"):
        os.remove("test_locus.db")


def test_health_and_seeded_data():
    with TestClient(app) as client:
        assert client.get("/api/health").json() == {"status": "ok"}
        assert len(client.get("/api/collections").json()) == 3


def test_delete_all_chats_removes_sessions_messages_and_jobs():
    with TestClient(app) as client:
        first = chat(client, question="First bulk-delete chat")
        second = chat(client, question="Second bulk-delete chat")
        assert first["conversation_id"] != second["conversation_id"]
        assert client.get("/api/chats").json()
        response = client.delete("/api/chats")
        assert response.status_code == 204
        assert client.get("/api/chats").json() == []
        assert client.get("/api/chat/jobs").json() == []


def test_delete_chat_cancels_active_job():
    with TestClient(app) as client:
        with SessionLocal() as db:
            session = ChatSession(title="Cancel me")
            db.add(session)
            db.flush()
            job = ChatJob(id="canceljob1", status="running", stage="drafting", detail="Running", question="Cancel", conversation_id=session.id, model="test-model")
            db.add(job)
            db.commit()
            chat_id = session.id
        event = main_module._chat_job_cancel_event("canceljob1")
        assert not event.is_set()

        response = client.delete(f"/api/chats/{chat_id}")

        assert response.status_code == 204
        assert event.is_set()
        assert client.get("/api/chats").json() == []
        assert client.get("/api/chat/jobs").json() == []
        main_module._forget_chat_job_cancel_event("canceljob1")


def test_delete_chat_only_cancels_that_chat_jobs():
    with TestClient(app) as client:
        with SessionLocal() as db:
            first_session = ChatSession(title="First chat")
            second_session = ChatSession(title="Second chat")
            db.add_all([first_session, second_session])
            db.flush()
            first_job = ChatJob(id="deleteonly1", status="running", stage="drafting", detail="Running", question="First", conversation_id=first_session.id, model="test-model")
            second_job = ChatJob(id="deleteonly2", status="running", stage="drafting", detail="Running", question="Second", conversation_id=second_session.id, model="test-model")
            db.add_all([first_job, second_job])
            db.commit()
            first_chat_id = first_session.id

        first_event = main_module._chat_job_cancel_event("deleteonly1")
        second_event = main_module._chat_job_cancel_event("deleteonly2")
        assert not first_event.is_set()
        assert not second_event.is_set()

        response = client.delete(f"/api/chats/{first_chat_id}")

        assert response.status_code == 204
        assert first_event.is_set()
        assert not second_event.is_set()
        jobs = client.get("/api/chat/jobs").json()
        assert any(job["id"] == "deleteonly2" for job in jobs)
        assert not any(job["id"] == "deleteonly1" for job in jobs)
        main_module._forget_chat_job_cancel_event("deleteonly1")
        main_module._forget_chat_job_cancel_event("deleteonly2")


def test_load_chat_history_keeps_more_than_ten_messages_with_char_cap():
    with SessionLocal() as db:
        session = ChatSession(title="Long context")
        db.add(session)
        db.flush()
        for index in range(15):
            db.add(ChatMessage(session_id=session.id, role="user" if index % 2 == 0 else "assistant", content=f"message-{index} " + ("x" * 20)))
        db.commit()
        session_id = session.id

    with SessionLocal() as db:
        history = main_module._load_chat_history(db, session_id, limit=40, max_chars=10_000)
        capped = main_module._load_chat_history(db, session_id, limit=40, max_chars=45)

    assert len(history) == 15
    assert history[0][1].startswith("message-0")
    assert history[-1][1].startswith("message-14")
    assert sum(len(content) for _, content in capped) <= 45
    assert capped


def test_process_chat_emits_selected_tools_status():
    events = []
    with SessionLocal() as db:
        response = main_module._process_chat(
            main_module.ChatRequest(question="Explain dependency injection", file_ids=None),
            db,
            lambda stage, detail: events.append((stage, detail)),
            lambda: False,
        )

    assert response.answer == "Test answer"
    assert any("Selected tools:" in detail for _, detail in events)


def test_cancel_chat_job_marks_user_stopped():
    with TestClient(app) as client:
        with SessionLocal() as db:
            session = ChatSession(title="Stop one job")
            db.add(session)
            db.flush()
            job = ChatJob(id="stopjob1", status="running", stage="drafting", detail="Running", question="Stop", conversation_id=session.id, model="test-model")
            db.add(job)
            db.commit()

        event = main_module._chat_job_cancel_event("stopjob1")
        assert not event.is_set()

        response = client.post("/api/chat/jobs/stopjob1/cancel")

        assert response.status_code == 200
        stopped = response.json()
        assert stopped["status"] == "cancelled"
        assert stopped["detail"] == "Answer stopped by user"
        assert event.is_set()
        assert main_module._chat_job_cancel_reason("stopjob1") == "Answer stopped by user"
        messages = client.get(f"/api/chats/{stopped['conversation_id']}/messages").json()
        assert [message["content"] for message in messages] == ["Stop"]
        main_module._forget_chat_job_cancel_event("stopjob1")


def test_stop_chat_cancels_jobs_without_deleting_messages():
    with TestClient(app) as client:
        with SessionLocal() as db:
            session = ChatSession(title="Stop chat")
            db.add(session)
            db.flush()
            db.add(ChatMessage(session_id=session.id, role="user", content="Keep this"))
            job = ChatJob(id="stopchat1", status="queued", stage="starting", detail="Queued", question="Stop", conversation_id=session.id, model="test-model")
            db.add(job)
            db.commit()
            chat_id = session.id

        response = client.post(f"/api/chats/{chat_id}/stop")

        assert response.status_code == 200
        assert response.json() == {"status": "stopped", "cancelled_jobs": ["stopchat1"]}
        assert main_module._chat_job_cancel_event("stopchat1").is_set()
        messages = client.get(f"/api/chats/{chat_id}/messages").json()
        assert [message["content"] for message in messages] == ["Keep this", "Stop"]
        main_module._forget_chat_job_cancel_event("stopchat1")


def test_delete_chat_cancels_streaming_llm_work():
    with TestClient(app) as client:
        with SessionLocal() as db:
            session = ChatSession(title="Stream cancel me")
            db.add(session)
            db.flush()
            chat_id = session.id
            db.commit()

        started = Event()
        cancelled = Event()
        response_holder = {}

        def fake_call_process_chat(payload, db, notify, cancelled_check):
            started.set()
            while not cancelled_check():
                time.sleep(0.01)
            cancelled.set()
            raise main_module.ChatJobCancelled("Chat was deleted; answer pipeline cancelled")

        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(main_module, "_call_process_chat", fake_call_process_chat)

        def run_stream():
            response_holder["response"] = client.post("/api/chat/stream", json={
                "question": "Keep going",
                "conversation_id": chat_id,
                "provider": "groq",
                "model": "test-model",
                "allow_general_knowledge": True,
                "reasoning_mode": "light",
            })

        thread = Thread(target=run_stream, daemon=True)
        thread.start()
        assert started.wait(1)

        with SessionLocal() as db:
            response = main_module.delete_chat(chat_id, db=db)
            assert response.status_code == 204

        assert cancelled.wait(1)
        thread.join(timeout=1)
        monkeypatch.undo()

        assert response_holder["response"].status_code == 200
        assert "Chat was deleted; answer pipeline cancelled" in response_holder["response"].text


def test_delete_all_chats_cancels_active_jobs():
    with TestClient(app) as client:
        with SessionLocal() as db:
            session = ChatSession(title="Cancel all")
            db.add(session)
            db.flush()
            job = ChatJob(id="canceljob2", status="queued", stage="starting", detail="Queued", question="Cancel all", conversation_id=session.id, model="test-model")
            db.add(job)
            db.commit()
        event = main_module._chat_job_cancel_event("canceljob2")
        assert not event.is_set()

        response = client.delete("/api/chats")

        assert response.status_code == 204
        assert event.is_set()
        assert client.get("/api/chats").json() == []
        assert client.get("/api/chat/jobs").json() == []
        main_module._forget_chat_job_cancel_event("canceljob2")


def test_truncate_chat_from_message_removes_later_messages_and_jobs():
    with TestClient(app) as client:
        with SessionLocal() as db:
            session = ChatSession(title="Edit from here")
            db.add(session)
            db.flush()
            first = ChatMessage(session_id=session.id, role="user", content="First")
            first_answer = ChatMessage(session_id=session.id, role="assistant", content="First answer")
            edit_from = ChatMessage(session_id=session.id, role="user", content="Second")
            second_answer = ChatMessage(session_id=session.id, role="assistant", content="Second answer")
            db.add_all([first, first_answer, edit_from, second_answer])
            db.flush()
            job = ChatJob(id="truncatejob1", status="running", stage="drafting", detail="Running", question="Second", conversation_id=session.id, model="test-model")
            db.add(job)
            db.commit()
            chat_id = session.id
            edit_from_id = edit_from.id

        response = client.delete(f"/api/chats/{chat_id}/messages/{edit_from_id}/from")

        assert response.status_code == 200
        remaining = response.json()
        assert [message["content"] for message in remaining] == ["First", "First answer"]
        assert not any(job["id"] == "truncatejob1" for job in client.get("/api/chat/jobs").json())
        assert main_module._chat_job_cancel_event("truncatejob1").is_set()
        main_module._forget_chat_job_cancel_event("truncatejob1")


def test_upload_file_and_chat_from_its_content(monkeypatch):
    monkeypatch.setattr(
        "backend.app.main.answer_planned_question",
        lambda question, plan, evidence, history, model, allow_general_knowledge, guidance, notify=lambda detail: None: (f"Grounded answer from [{evidence[0][0]}]", "test-model"),
    )
    with TestClient(app) as client:
        upload = client.post(
            "/api/files",
            data={"store_id": 2},
            files={"file": ("agent-notes.txt", b"Agent memory should retain provenance and source context.", "text/plain")},
        )
        assert upload.status_code == 201
        result = chat(client, question="What should agent memory retain?")
        assert result["sources"][0]["name"] == "agent-notes.txt"
        assert result["model"] == "test-model"
        chat_id = result["conversation_id"]
        messages = client.get(f"/api/chats/{chat_id}/messages").json()
        assert [message["role"] for message in messages] == ["user", "assistant"]


def test_delete_store_and_its_files():
    with TestClient(app) as client:
        store = client.post("/api/collections", json={"title": "Temporary store"}).json()
        client.post("/api/files", data={"store_id": store["id"]}, files={"file": ("temp.txt", b"temporary", "text/plain")})
        response = client.delete(f"/api/collections/{store['id']}")
        assert response.status_code == 204
        assert all(file["store_id"] != store["id"] for file in client.get("/api/files").json())


def test_general_question_does_not_require_file_context(monkeypatch):
    captured = {}

    def fake_answer(question, plan, evidence, history, model, allow_general_knowledge, guidance, notify=lambda detail: None):
        captured["sources"] = evidence
        return "```python\nsum(numbers)\n```", model or "test-model"

    monkeypatch.setattr("backend.app.main.answer_planned_question", fake_answer)
    with TestClient(app) as client:
        result = chat(client, question="Write Python code to add any number of numbers")
        assert result["sources"] == []
        assert captured["sources"] == []


def test_chat_only_searches_selected_files(monkeypatch):
    captured = {}

    def fake_answer(question, plan, evidence, history, model, allow_general_knowledge, guidance, notify=lambda detail: None):
        captured["evidence"] = evidence
        return "Selected file answer", model

    monkeypatch.setattr("backend.app.main.answer_planned_question", fake_answer)
    with TestClient(app) as client:
        store = client.post("/api/collections", json={"title": "Selection test"}).json()
        chosen = client.post("/api/files", data={"store_id": store["id"]}, files={"file": ("chosen.txt", b"selectionmarker appears in the chosen file", "text/plain")}).json()
        client.post("/api/files", data={"store_id": store["id"]}, files={"file": ("excluded.txt", b"selectionmarker appears in the excluded file", "text/plain")})
        result = chat(client, question="What mentions selectionmarker?", file_ids=[chosen["id"]])
        assert [source[0] for source in captured["evidence"]] == ["chosen.txt"]
        assert [source["name"] for source in result["sources"]] == ["chosen.txt"]


def test_greeting_uses_generic_pipeline(monkeypatch):
    calls = []
    monkeypatch.setattr("backend.app.main.enhance_question", lambda question, history, model: calls.append(question) or {"enhanced_question": question, "subquestions": [], "answer_format": "Clear answer", "supporting_details": [], "visualization": "none", "completeness_criteria": ["Answer"], "requires_full_relevant_files": False, "aggregation_operation": "none", "entity_type": None})
    with TestClient(app) as client:
        result = chat(client, question="hi")
        assert result["sources"] == []
        assert calls == ["hi"]


@pytest.mark.parametrize("question", ["what are you doing", "review this incident", "summarize every description"])
def test_former_trigger_phrases_use_the_generic_pipeline(monkeypatch, question):
    calls = []
    monkeypatch.setattr("backend.app.main.answer_planned_question", lambda received, *args, **kwargs: calls.append(received) or ("Generic answer", "test-model"))
    with TestClient(app) as client:
        result = chat(client, question=question)
        assert result["answer"] == "Generic answer"
        assert calls == [question]


def test_light_skips_quality_layer_and_thinking_uses_it(monkeypatch):
    calls = []
    monkeypatch.setattr("backend.app.main.verify_response", lambda *args, **kwargs: calls.append("verify") or {"complete": True, "missing": [], "quality_score": 100})
    with TestClient(app) as client:
        chat(client, question="A generic light question", reasoning_mode="light")
        assert calls == []
        chat(client, question="A generic thinking question", reasoning_mode="thinking", file_ids=[])
        assert calls == ["verify"]


def test_light_mode_with_empty_file_selection_uses_direct_model_chat(monkeypatch):
    monkeypatch.setattr("backend.app.main.enhance_question", lambda *args, **kwargs: pytest.fail("Light mode with no selected files should not plan"))
    monkeypatch.setattr("backend.app.main.answer_planned_question", lambda *args, **kwargs: pytest.fail("Light mode with no selected files should not compose"))
    monkeypatch.setattr("backend.app.main.generate_answer", lambda question, sources, history, model, allow_general_knowledge, reasoning_mode, guidance: ("Direct model chat", model))
    with TestClient(app) as client:
        result = chat(client, question="What does this file say?", reasoning_mode="light", file_ids=[])
        assert result["answer"] == "Direct model chat"
        assert result["sources"] == []


def test_direct_chat_stream_emits_tokens_and_persists(monkeypatch):
    monkeypatch.setattr("backend.app.main.stream_answer", lambda *args, **kwargs: (iter(["Hello", " there"]), "test-model"))
    with TestClient(app) as client:
        with client.stream("POST", "/api/chat/direct-stream", json={"question": "hi", "provider": "groq", "model": "test-model", "reasoning_mode": "light", "file_ids": []}) as response:
            assert response.status_code == 200
            events = [json.loads(line) for line in response.iter_lines() if line.strip()]
        token_text = "".join(event["text"] for event in events if event["type"] == "token")
        result = next(event["data"] for event in events if event["type"] == "result")
        messages = client.get(f"/api/chats/{result['conversation_id']}/messages").json()

    assert token_text == "Hello there"
    assert result["answer"] == "Hello there"
    assert [message["role"] for message in messages[-2:]] == ["user", "assistant"]
    assert messages[-1]["content"] == "Hello there"


def test_unrestricted_direct_chat_stream_uses_expert_mode(monkeypatch):
    captured = {}

    def fake_stream(question, sources, history=None, model=None, allow_general_knowledge=True, reasoning_mode="light", guidance="", system_override=None, provider=None):
        captured.update(reasoning_mode=reasoning_mode, provider=provider, model=model)
        return iter(["Expert", " answer"]), model

    monkeypatch.setattr("backend.app.main.stream_answer", fake_stream)
    with TestClient(app) as client:
        with client.stream("POST", "/api/chat/direct-stream", json={"question": "go deep", "provider": "groq", "model": "test-model", "reasoning_mode": "unrestricted", "file_ids": []}) as response:
            assert response.status_code == 200
            events = [json.loads(line) for line in response.iter_lines() if line.strip()]

    assert "".join(event["text"] for event in events if event["type"] == "token") == "Expert answer"
    assert captured == {"reasoning_mode": "unrestricted", "provider": "groq", "model": "test-model"}


def test_thinking_mode_with_empty_selection_uses_no_files(monkeypatch):
    captured = {}

    def fake_answer(question, plan, evidence, history, model, allow_general_knowledge, guidance, notify=lambda detail: None):
        captured["evidence"] = evidence
        return "General answer", model

    monkeypatch.setattr("backend.app.main.answer_planned_question", fake_answer)
    monkeypatch.setattr("backend.app.main.extract_shared_evidence", lambda *args, **kwargs: pytest.fail("No files were selected"))
    with TestClient(app) as client:
        result = chat(client, question="Explain recursion simply", reasoning_mode="thinking", file_ids=[])
        assert result["sources"] == []
        assert captured["evidence"] == []


def test_strict_mode_rejects_unsupported_question():
    with TestClient(app) as client:
        result = chat(client, question="Explain quantum gravity", allow_general_knowledge=False)
        assert result["sources"] == []
        assert "uploaded files" in result["answer"]


def test_web_research_uses_requested_source_limit(monkeypatch):
    captured = {}

    def fake_web_research(question, model, progress, source_limit=5, history=None, answer_mode="web_research"):
        captured["source_limit"] = source_limit
        return {"answer": "Web answer", "sources": [], "model": model}

    monkeypatch.setattr("backend.app.main.web_research", fake_web_research)
    with TestClient(app) as client:
        result = chat(client, question="Research this", reasoning_mode="web_research", web_source_limit=25)

    assert result["answer"] == "Web answer"
    assert 5 <= captured["source_limit"] <= 200  # LLM decides dynamically, clamped by user cap


def test_search_intent_auto_enables_web_research(monkeypatch):
    captured = {}

    def fake_web_research(question, model, progress, source_limit=5, history=None, answer_mode="web_research"):
        captured.update(question=question, model=model, source_limit=source_limit, answer_mode=answer_mode)
        return {"answer": "Auto web answer", "sources": [], "model": model}

    monkeypatch.setattr("backend.app.main.web_research", fake_web_research)
    with TestClient(app) as client:
        result = chat(client, question="Search the web for the latest React 19 updates", reasoning_mode="light", web_search=False)

    assert result["answer"] == "Auto web answer"
    assert "React 19" in captured["question"]
    assert "latest" in captured["question"].lower()
    assert 5 <= captured["source_limit"] <= 200  # LLM decides dynamically, must be reasonable


def test_non_search_prompt_does_not_auto_enable_web_research(monkeypatch):
    assert main_module.should_auto_web_search("Explain recursion simply", "light") is False
    assert main_module.should_auto_web_search("Search the web for React updates", "light") is True
    assert main_module.should_auto_web_search("under 5k bola tha tabular format", "light") is True


def test_unrestricted_mode_can_use_web_search(monkeypatch):
    captured = {}

    def fake_web_research(question, model, progress, source_limit=5, history=None, answer_mode="web_research"):
        captured.update(question=question, model=model, source_limit=source_limit, answer_mode=answer_mode)
        return {"answer": "Unrestricted web answer", "sources": [], "model": model}

    monkeypatch.setattr("backend.app.main.web_research", fake_web_research)
    with TestClient(app) as client:
        result = chat(client, question="Research freely", model="llama3.2:latest", reasoning_mode="unrestricted", web_search=True, web_source_limit=25)

    assert result["answer"] == "Unrestricted web answer"
    assert captured["question"] == "Research freely"
    assert captured["model"] == "llama3.2:latest"
    assert captured["answer_mode"] == "unrestricted"
    assert 5 <= captured["source_limit"] <= 25  # LLM decides dynamically, clamped by user cap of 25


def test_web_source_limit_is_validated():
    with TestClient(app) as client:
        too_small = client.post("/api/chat/jobs", json={"question": "Research this", "reasoning_mode": "web_research", "web_source_limit": 2})
        too_large = client.post("/api/chat/jobs", json={"question": "Research this", "reasoning_mode": "web_research", "web_source_limit": 201})

    assert too_small.status_code == 422
    assert too_large.status_code == 422


def test_web_search_caps_merged_engine_results(monkeypatch):
    ddg_results = [
        {"title": f"Ddg {index}", "href": f"https://ddg.example/{index}", "body": "snippet"}
        for index in range(5)
    ]
    serp_results = [
        {"title": f"Serp {index}", "url": f"https://serp.example/{index}", "snippet": "snippet"}
        for index in range(5)
    ]

    class FakeDDGS:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def text(self, query, max_results):
            return ddg_results

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"results": serp_results}

    monkeypatch.setattr(web_research_module, "DDGS", lambda: FakeDDGS())
    monkeypatch.setattr(web_research_module, "OPENSERP_BASE_URL", "https://search.example")
    monkeypatch.setattr(web_research_module.httpx, "get", lambda *args, **kwargs: FakeResponse())

    results = web_research_module._search_web("query", max_results=5)

    assert len(results) == 5


def test_web_search_includes_default_youtube_query(monkeypatch):
    searched_queries = []

    def fake_ddg(query, max_results):
        searched_queries.append(query)
        if query.startswith(web_research_module.YOUTUBE_SEARCH_PREFIX):
            return [
                {
                    "title": "Video result",
                    "url": "https://www.youtube.com/watch?v=abc123",
                    "snippet": "Video snippet",
                    "engine": "ddg",
                }
            ]
        return [
            {
                "title": "Article result",
                "url": "https://example.com/article",
                "snippet": "Article snippet",
                "engine": "ddg",
            }
        ]

    monkeypatch.setattr(web_research_module, "_search_ddg", fake_ddg)
    monkeypatch.setattr(web_research_module, "_search_openserp", lambda query, max_results: [])

    results = web_research_module._search_web("python tutorial", max_results=5)

    assert "site:youtube.com/watch python tutorial" in searched_queries
    assert any(result["url"] == "https://example.com/article" for result in results)
    assert any(
        result["engine"] == "youtube" and result["url"] == "https://www.youtube.com/watch?v=abc123"
        for result in results
    )


def test_web_research_expands_5k_budget_and_filters_over_budget_sources(monkeypatch):
    monkeypatch.setattr(web_research_module, "_generate_followup_queries", lambda *args, **kwargs: [])
    monkeypatch.setattr(web_research_module, "_synthesize_answer", lambda question, results, model, progress, history=None, answer_mode="web_research", intent=None: question)

    searched_queries = []

    def fake_search(query, max_results=50):
        searched_queries.append(query)
        return [
            {"title": "Best phones under Rs 30000", "url": "https://example.com/30000", "snippet": "Under Rs 30000 list", "engine": "test"},
            {"title": "Best phones under Rs 5000", "url": "https://example.com/5000", "snippet": "Under Rs 5000 list", "engine": "test"},
        ]

    monkeypatch.setattr(web_research_module, "_search_web", fake_search)
    monkeypatch.setattr(web_research_module, "_call_llm_json", lambda *args, **kwargs: ["iPhone 16 pro"])

    result = web_research_module.web_research("search best phone in 5k now in india", "model", lambda *args: None, source_limit=5)

    assert any("under 5000 rupees" in query.lower() or "under 5000" in query.lower() for query in searched_queries)
    assert all(source["url"] != "https://example.com/30000" for source in result["sources"])
    assert any(source["url"] == "https://example.com/5000" for source in result["sources"])
    assert "5000" in result["answer"]


def test_web_research_enriches_product_sources_with_page_content(monkeypatch):
    captured = {}

    monkeypatch.setattr(web_research_module, "_generate_initial_queries", lambda question, model, count: ["best phones under 10000 India"])
    monkeypatch.setattr(web_research_module, "_generate_followup_queries", lambda *args, **kwargs: [])
    monkeypatch.setattr(web_research_module, "_search_web", lambda query, max_results=50, include_youtube=True: [
        {
            "title": "Best phones under 10000 India",
            "url": "https://example.com/phones",
            "snippet": "Budget smartphone list",
            "engine": "ddg",
        }
    ])
    monkeypatch.setattr(
        web_research_module,
        "_read_webpage_text",
        lambda url: "Moto G35 5G price ₹9,999, 5,000mAh battery, 50MP camera, 120Hz display, launched July 2026.",
    )

    def fake_synthesize(question, results, model, progress, history=None, answer_mode="web_research", intent=None):
        captured["snippet"] = results[0]["snippet"]
        return "answer"

    monkeypatch.setattr(web_research_module, "_synthesize_answer", fake_synthesize)

    result = web_research_module.web_research("best phone under 10k", "model", lambda *args: None, source_limit=5)

    assert "Page content:" in captured["snippet"]
    assert "Moto G35 5G price ₹9,999" in captured["snippet"]
    assert result["sources"][0]["page_read"] is True


def test_web_research_filters_under_7_thousand_for_5k_budget():
    assert web_research_module._is_over_budget_result(
        {"title": "Samsung Galaxy M05 Smartphone", "snippet": "good phone under 7 thousand category"},
        5000,
    ) is True
    assert web_research_module._is_over_budget_result(
        {"title": "Mobiles Under 5000", "snippet": "best phones under Rs 5000"},
        5000,
    ) is False


def test_web_research_removes_answer_rows_above_budget():
    answer = """| Mobile name | Price |\n|---|---|\n| Poco C61 | ₹4,900–₹5,200 |\n| Redmi Go | ₹4,500 |\n"""

    cleaned = web_research_module._remove_over_budget_lines(answer, 5000)

    assert "Poco C61" not in cleaned
    assert "Redmi Go" in cleaned
    assert "exceeded the ₹5,000 budget" in cleaned


def test_web_research_cleans_followup_search_query_with_history():
    query = web_research_module._search_question_with_history(
        "bhai under 5k bola tha and give me in tabular format with mobile name and price",
        [("user", "search best phone in 5k now in india"), ("assistant", "old answer")],
    )

    assert "bhai" not in query.lower()
    assert "bola tha" not in query.lower()
    assert "tabular format" not in query.lower()
    assert "mobile name and price" not in query.lower()
    assert "best phone" in query.lower()
    assert "5000" in query


def test_web_research_contextual_followup_keeps_previous_topic_and_location():
    query = web_research_module._search_question_with_history(
        "kr bhai mujhe bta kaisa rhe ga",
        [("user", "weather here in my location deoria"), ("assistant", "old answer")],
    )

    assert "deoria" in query.lower()
    assert "weather" in query.lower()
    assert "kaisa" not in query.lower()


def test_web_research_generic_fallback_does_not_turn_sources_into_options():
    answer = web_research_module._fallback_web_answer(
        "weather here in my location deoria",
        [
            {
                "title": "Deoria, UP, IN Current Weather",
                "url": "https://example.com/weather",
                "snippet": "Get Deoria current weather report with temperature and humidity.",
                "engine": "test",
            }
        ],
    )

    assert "Best options I could verify" not in answer
    assert "Please check the attached sources" not in answer
    assert "strongest evidence" in answer or "direct values" in answer


def test_web_research_falls_back_when_synthesis_model_fails(monkeypatch):
    def failing_chat(*args, **kwargs):
        raise web_research_module.LLMProviderError("bad request", 400)

    monkeypatch.setattr(web_research_module, "_chat", failing_chat)

    answer = web_research_module._synthesize_answer(
        "best phone under 5k in india in tabular format with mobile name and price",
        [
            {
                "title": "Best Android Phone Under 5000 - Amazon.in",
                "url": "https://example.com",
                "snippet": "Forme Mi 5 pro Smartphone In 4.05 Qhd Display under Rs 5000",
                "engine": "test",
            }
        ],
        "model",
        lambda *args: None,
    )

    assert answer.startswith("| Mobile name | Price | Source |")
    assert "Forme Mi 5 Pro" in answer
    assert "₹5,000" in answer


def test_web_research_falls_back_honestly_for_current_info_when_model_fails(monkeypatch):
    def failing_chat(*args, **kwargs):
        raise web_research_module.LLMProviderError("bad request", 400)

    monkeypatch.setattr(web_research_module, "_chat", failing_chat)

    answer = web_research_module._synthesize_answer(
        "weather here in my location deoria",
        [
            {
                "title": "Deoria, UP, IN Current Weather",
                "url": "https://example.com/weather",
                "snippet": "Get Deoria current weather report with temperature and humidity.",
                "engine": "test",
            }
        ],
        "model",
        lambda *args: None,
    )

    assert "Best options I could verify" not in answer
    assert "Please check the attached sources" not in answer
    assert "strongest evidence" in answer or "direct values" in answer


def test_web_research_fallback_extracts_generic_values_from_snippets():
    answer = web_research_module._fallback_web_answer(
        "current price of AAPL",
        [
            {
                "title": "AAPL Stock Price Today",
                "url": "https://example.com/aapl",
                "snippet": "Apple stock is trading at $214.50 with live market updates.",
                "engine": "test",
            }
        ],
    )

    assert "$214.50" in answer
    assert "direct values" in answer


def test_web_research_fallback_extracts_multiple_phone_names():
    answer = web_research_module._fallback_web_answer(
        "best phone under 5k in india",
        [
            {
                "title": "AI+ Smartphone | Pulse and Nova 5G Starting under ₹5000",
                "snippet": "AI+ Pulse and AI+ Nova 5G starting under ₹5000",
            },
            {
                "title": "Best 4G Mobile Under 5000 Rupees in 2020",
                "snippet": "Redmi go https://example Infinix smart 2 https://example Asus",
            },
            {
                "title": "Best Phone Under 5000 in 2025",
                "snippet": "Poco C61- https://example",
            },
        ],
    )

    assert "AI+ Pulse" in answer
    assert "AI+ Nova 5G" in answer
    assert "Redmi Go" in answer
    assert "Infinix Smart 2" in answer
    assert "Poco C61" in answer


def test_web_research_table_request_allows_markdown_table(monkeypatch):
    captured = {}

    def fake_chat(system, prompt, model, temperature=0.2, max_tokens=None):
        captured["system"] = system
        return "| Mobile name | Price |\n|---|---|\n| Example | ₹4,999 |"

    monkeypatch.setattr(web_research_module, "_chat", fake_chat)
    answer = web_research_module._synthesize_answer(
        "under 5k phone in India in tabular format with mobile name and price",
        [{"title": "Best phones under Rs 5000", "url": "https://example.com", "snippet": "Example phone ₹4,999", "engine": "test"}],
        "model",
        lambda *args: None,
    )

    assert "Markdown table" in captured["system"]
    assert "₹5,000" in captured["system"]
    assert answer.startswith("| Mobile name | Price |")


def test_web_research_repairs_source_dump_or_missing_table(monkeypatch):
    calls = []

    def fake_chat(system, prompt, model, temperature=0.2, max_tokens=None):
        calls.append(prompt)
        if len(calls) == 1:
            return "Source 1: A\nURL: https://a.example\nContent: x\n\nSource 2: B\nURL: https://b.example\nContent: y"
        return "| Mobile name | Price |\n|---|---|\n| Fixed | ₹4,999 |"

    monkeypatch.setattr(web_research_module, "_chat", fake_chat)

    answer = web_research_module._synthesize_answer(
        "best phone under 5k in india in tabular format with mobile name and price",
        [
            {"title": "A", "url": "https://a.example", "snippet": "Fixed phone ₹4,999", "engine": "test"},
            {"title": "B", "url": "https://b.example", "snippet": "Other phone ₹4,799", "engine": "test"},
        ],
        "model",
        lambda *args: None,
    )

    assert len(calls) == 2
    assert "Do not output raw Source/URL/Content blocks" in calls[1]
    assert answer.startswith("| Mobile name | Price |")


def test_web_research_repairs_source_directory_answer(monkeypatch):
    calls = []

    def fake_chat(system, prompt, model, temperature=0.2, max_tokens=None):
        calls.append(prompt)
        if len(calls) == 1:
            return "Best options I could verify:\n\n- **Deoria Weather** — Check source\n- **Deoria Current Weather** — Check source"
        return "The forecast sources mention Deoria current weather and a 48-hour forecast, but the snippets do not show exact temperature."

    monkeypatch.setattr(web_research_module, "_chat", fake_chat)

    answer = web_research_module._synthesize_answer(
        "weather here in my location deoria",
        [
            {"title": "Deoria Weather", "url": "https://a.example", "snippet": "Deoria forecast and current weather", "engine": "test"},
            {"title": "Deoria Current Weather", "url": "https://b.example", "snippet": "Current weather for Deoria", "engine": "test"},
        ],
        "model",
        lambda *args: None,
    )

    assert len(calls) == 2
    assert "Do not list source titles as if they are the answer" in calls[1]
    assert "Best options I could verify" not in answer


def test_web_research_skips_youtube_for_current_info_without_video_intent(monkeypatch):
    called = {"youtube": False}

    monkeypatch.setattr(web_research_module, "_search_ddg", lambda query, max_results: [])
    monkeypatch.setattr(web_research_module, "_search_openserp", lambda query, max_results: [])

    def fake_youtube(query, max_results):
        called["youtube"] = True
        return []

    monkeypatch.setattr(web_research_module, "_search_youtube", fake_youtube)

    web_research_module._search_web("current gold rate today", max_results=5, include_youtube=False)

    assert called["youtube"] is False


def test_web_research_does_not_mix_history_into_standalone_search(monkeypatch):
    planned_questions = []

    def fake_initial(question, model, count):
        planned_questions.append(question)
        return ["live cricket score india today"]

    monkeypatch.setattr(web_research_module, "_generate_initial_queries", fake_initial)
    monkeypatch.setattr(web_research_module, "_generate_followup_queries", lambda *args, **kwargs: [])
    monkeypatch.setattr(web_research_module, "_synthesize_answer", lambda question, results, model, progress, history=None, answer_mode="web_research", intent=None: "answer")
    monkeypatch.setattr(web_research_module, "_search_web", lambda query, max_results=50: [
        {"title": "Live Cricket Score India Today", "url": "https://example.com/cricket", "snippet": "Live cricket score for India today", "engine": "test"}
    ])

    web_research_module.web_research(
        "live cricket score india today",
        "model",
        lambda *args: None,
        source_limit=5,
        history=[("user", "current stock price of AAPL"), ("assistant", "old answer")],
    )

    assert planned_questions
    assert "AAPL" not in planned_questions[0]
    assert "stock price" not in planned_questions[0]


def test_web_research_requests_only_remaining_sources(monkeypatch):
    requested_limits = []

    monkeypatch.setattr(web_research_module, "_generate_initial_queries", lambda question, model, count: ["query"])
    monkeypatch.setattr(web_research_module, "_generate_followup_queries", lambda *args, **kwargs: [])
    monkeypatch.setattr(web_research_module, "_synthesize_answer", lambda question, results, model, progress, history=None, answer_mode="web_research", intent=None: "answer")

    def fake_search(query, max_results=50):
        requested_limits.append(max_results)
        return [
            {"title": f"Result {index}", "url": f"https://example.com/{index}", "snippet": "snippet", "engine": "test"}
            for index in range(20)
        ]

    monkeypatch.setattr(web_research_module, "_search_web", fake_search)

    result = web_research_module.web_research("question", "model", lambda *args: None, source_limit=5)

    assert requested_limits == [5]
    assert len(result["sources"]) == 5


def test_web_research_keeps_following_up_until_target_sources(monkeypatch):
    searched_queries = []

    monkeypatch.setattr(web_research_module, "_generate_initial_queries", lambda question, model, count: ["initial"])

    def fake_followups(question, found_topics, model, count, previous_queries=None, round_number=2):
        return [f"round {round_number}"]

    monkeypatch.setattr(web_research_module, "_generate_followup_queries", fake_followups)
    monkeypatch.setattr(web_research_module, "_synthesize_answer", lambda question, results, model, progress, history=None, answer_mode="web_research", intent=None: "answer")

    def fake_search(query, max_results=50):
        searched_queries.append(query)
        return [
            {"title": f"Result {query}", "url": f"https://example.com/{query.replace(' ', '-')}", "snippet": "snippet", "engine": "test"}
        ]

    monkeypatch.setattr(web_research_module, "_search_web", fake_search)

    result = web_research_module.web_research("question", "model", lambda *args: None, source_limit=5)

    assert searched_queries == ["initial", "question", "round 2", "round 3", "round 4"]
    assert len(result["sources"]) == 5


def test_chat_job_continues_and_can_be_marked_ready():
    with TestClient(app) as client:
        created = client.post("/api/chat/jobs", json={"question": "Explain background work"})
        assert created.status_code == 202
        job = created.json()
        assert job["conversation_id"]
        for _ in range(100):
            job = next(item for item in client.get("/api/chat/jobs").json() if item["id"] == job["id"])
            if job["status"] in ("completed", "failed"):
                break
            time.sleep(0.02)
        assert job["status"] == "completed"
        assert job["result"]["answer"] == "Test answer"
        assert not any(event["stage"] == "verifying" for event in job["events"])
        seen = client.patch(f"/api/chat/jobs/{job['id']}/seen").json()
        assert seen["seen"] is True


def test_chat_job_retries_three_times_before_succeeding(monkeypatch):
    attempts = []
    updates = []
    model_requests = []

    class FakeLiteLLM:
        @staticmethod
        def completion(**kwargs):
            model_requests.append(kwargs["model"])
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="Completed checkpoint"))])

    class Result:
        def model_dump(self, mode="json"):
            return {"answer": "Recovered"}

    def flaky_process(payload, db, notify):
        attempts.append(payload.question)
        assert _chat("Checkpoint system", "Checkpoint prompt", "llama3.2:latest") == "Completed checkpoint"
        if len(attempts) <= 3:
            raise RuntimeError("Temporary Ollama failure")
        return Result()

    monkeypatch.setattr("backend.app.llm._load_litellm", lambda: FakeLiteLLM)
    monkeypatch.setattr(main_module, "_process_chat", flaky_process)
    monkeypatch.setattr(main_module, "_update_chat_job", lambda job_id, **changes: updates.append(changes))
    monkeypatch.setattr(main_module, "CHAT_JOB_MAX_RETRIES", 3)
    monkeypatch.setattr(main_module, "CHAT_JOB_RETRY_DELAY_SECONDS", 0)
    main_module._run_chat_job("job-id", main_module.ChatRequest(question="Retry this"))

    assert len(attempts) == 4
    assert len(model_requests) == 1
    assert len([update for update in updates if "Retrying" in update.get("detail", "")]) == 3
    assert all("preserving 1 completed model step" in update["detail"] for update in updates if "Retrying" in update.get("detail", ""))
    assert updates[-1]["status"] == "completed"


def test_chat_job_retry_count_resets_after_successful_progress(monkeypatch):
    import backend.app.llm as llm_module

    attempts = 0
    completed_steps = 0
    failures_after_progress = 0
    updates = []

    class Result:
        def model_dump(self, mode="json"):
            return {"answer": "Recovered after multiple failure episodes"}

    class FakeLiteLLM:
        @staticmethod
        def completion(**kwargs):
            step = kwargs["messages"][1]["content"].removeprefix("Step ")
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=f"Completed step {step}"))])

    def progressing_process(payload, db, notify):
        nonlocal attempts, completed_steps, failures_after_progress
        attempts += 1
        for step in range(5):
            assert llm_module._chat("System", f"Step {step}", payload.model) == f"Completed step {step}"
            if step == completed_steps:
                completed_steps += 1
                failures_after_progress += 1
                raise RuntimeError(f"Failure episode {failures_after_progress}")
        return Result()

    monkeypatch.setattr("backend.app.llm._load_litellm", lambda: FakeLiteLLM)
    monkeypatch.setattr(main_module, "_process_chat", progressing_process)
    monkeypatch.setattr(main_module, "_update_chat_job", lambda job_id, **changes: updates.append(changes))
    monkeypatch.setattr(main_module, "CHAT_JOB_MAX_RETRIES", 3)
    monkeypatch.setattr(main_module, "CHAT_JOB_RETRY_DELAY_SECONDS", 0)
    main_module._run_chat_job("job-id", main_module.ChatRequest(question="Keep progressing", provider="ollama", model="llama3.2:latest"))

    assert attempts == 6
    assert failures_after_progress == 5
    retry_updates = [update for update in updates if "Retrying" in update.get("detail", "")]
    assert len(retry_updates) == 5
    assert all("Retrying (1/3)" in update["detail"] for update in retry_updates)
    assert all("retry count reset" in update["detail"] for update in retry_updates[1:])
    assert updates[-1]["status"] == "completed"


def test_light_summary_request_uses_only_retrieved_excerpt(monkeypatch):
    captured = {}
    monkeypatch.setattr("backend.app.main.answer_planned_question", lambda question, plan, evidence, *args, **kwargs: captured.update(evidence=evidence) or ("Summary", "test-model"))
    monkeypatch.setattr("backend.app.main.extract_shared_evidence", lambda *args, **kwargs: pytest.fail("Light mode must not inspect all chunks"))
    with TestClient(app) as client:
        store = client.post("/api/collections", json={"title": "Books"}).json()
        full_text = "A distinctivebookterm appears here. " + ("Complete chapter content. " * 1000)
        client.post("/api/files", data={"store_id": store["id"]}, files={"file": ("book.txt", full_text.encode(), "text/plain")})
        chat(client, question="Summarize the distinctivebookterm book")
        assert captured["evidence"][0][0] == "book.txt"
        assert len(captured["evidence"][0][1]) <= 2201


def test_planner_can_request_file_context_without_keyword_routing(monkeypatch):
    captured = {}
    monkeypatch.setattr("backend.app.main.enhance_question", lambda question, history, model: {"enhanced_question": question, "subquestions": [], "answer_format": "Summary", "supporting_details": [], "visualization": "none", "completeness_criteria": [], "use_uploaded_files": True, "requires_full_relevant_files": False, "aggregation_operation": "none", "entity_type": None})
    monkeypatch.setattr("backend.app.main.answer_planned_question", lambda question, plan, evidence, *args, **kwargs: captured.update(evidence=evidence) or ("Answer", "test-model"))
    with TestClient(app) as client:
        store = client.post("/api/collections", json={"title": "Planner context"}).json()
        client.post("/api/files", data={"store_id": store["id"]}, files={"file": ("opaque.txt", b"Content with no lexical overlap to the request.", "text/plain")})
        chat(client, question="Please handle the selected material", file_ids=None)
    assert captured["evidence"]


def test_thinking_mode_inspects_complete_dataset(monkeypatch):
    captured = {}

    def fake_comprehensive(question, requirements, documents, model, notify=lambda detail: None):
        captured["documents"] = documents
        return documents

    monkeypatch.setattr("backend.app.main.extract_shared_evidence", fake_comprehensive)
    with TestClient(app) as client:
        result = chat(client, question="Compare everything", reasoning_mode="thinking")
        assert len(captured["documents"]) == len(client.get("/api/files").json())
        assert all(text for _, text in captured["documents"])


def test_incomplete_draft_is_repaired(monkeypatch):
    monkeypatch.setattr("backend.app.main.enhance_question", lambda question, history, model: {"enhanced_question": question, "subquestions": ["List every company"], "answer_format": "Count followed by a table", "supporting_details": ["roles", "dates"], "visualization": "table", "completeness_criteria": ["Give total", "List company names"], "requires_full_relevant_files": True, "aggregation_operation": "count_unique", "entity_type": "company"})
    monkeypatch.setattr("backend.app.main.verify_response", lambda question, answer, plan, model, sources=None: {"complete": False, "missing": ["Company names"], "quality_score": 55})
    monkeypatch.setattr("backend.app.main.answer_planned_question", lambda *args, **kwargs: ("Sushil worked at six companies.", "test-model"))
    captured = {}

    def fake_repair(question, answer, plan, missing, sources, model, allow_general_knowledge):
        captured.update(missing=missing, sources=sources)
        return "Sushil worked at **six companies**:\n\n| Company |\n|---|\n| Alkem |"

    monkeypatch.setattr("backend.app.main.repair_response", fake_repair)
    with TestClient(app) as client:
        store = client.post("/api/collections", json={"title": "Career records"}).json()
        client.post("/api/files", data={"store_id": store["id"]}, files={"file": ("sushil.txt", b"Sushil worked at Alkem and Zydus among six companies.", "text/plain")})
        result = chat(client, question="In how many companies has Sushil worked?", reasoning_mode="thinking")
        assert "| Company |" in result["answer"]
        assert captured["missing"] == ["Company names"]
        assert captured["sources"]


def test_deep_summary_continues_when_verifier_returns_malformed_json(monkeypatch):
    def fake_deep_summary(documents, model, notify=lambda detail: None):
        manifest = CoverageManifest(
            fileName="book.txt",
            totalPages=1,
            totalChunks=1,
            processedChunks=1,
            detectedSections=["Chapter 1 - One"],
            summarizedSections=["Chapter 1 - One"],
            coverageStatus="complete",
        )
        return "## Chapter 1 - One\nComplete grounded summary.", model, manifest, [("book.txt", "Chapter 1 - One")]

    monkeypatch.setattr("backend.app.main.deep_summarize_documents", fake_deep_summary)
    monkeypatch.setattr("backend.app.main.verify_response", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("The model returned an invalid planning response.")))

    with TestClient(app) as client:
        store = client.post("/api/collections", json={"title": "Verifier fallback"}).json()
        uploaded = client.post("/api/files", data={"store_id": store["id"]}, files={"file": ("book.txt", b"Chapter 1 - One\nAlpha", "text/plain")}).json()
        result = chat(client, question="Summarize book", reasoning_mode="deep_summary", file_ids=[uploaded["id"]])

    assert result["answer"] == "## Chapter 1 - One\nComplete grounded summary."
    assert result["sources"][0]["name"] == "book.txt"


def test_prompt_context_helpers_enforce_model_budgets():
    local_budget = _context_budget("llama3.2:latest")
    cloud_budget = _context_budget("nemotron-3-super:cloud")
    assert local_budget < cloud_budget
    assert cloud_budget < _context_budget("gpt-5.5")
    packed = _pack_sources([("one.txt", "a" * local_budget), ("two.txt", "b" * local_budget)], 3_000)
    assert sum(len(text) for _, text in packed) == 3_000
    history = _trim_history([("user", "x" * 5_000), ("assistant", "y" * 5_000)], 2_000)
    assert sum(len(content) for _, content in history) == 2_000


def test_openai_models_use_litellm_gateway(monkeypatch):
    captured = {}

    class FakeLiteLLM:
        @staticmethod
        def completion(**kwargs):
            captured.update(kwargs)
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="OpenAI answer"))])

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr("backend.app.llm._load_litellm", lambda: FakeLiteLLM)
    assert _chat("System", "Question", "gpt-5.4-mini") == "OpenAI answer"
    assert captured["model"] == "gpt-5.4-mini"
    assert captured["api_key"] == "test-key"
    assert captured["messages"][0]["content"] == "System"


def test_gemini_models_use_litellm_gateway(monkeypatch):
    captured = {}

    class FakeLiteLLM:
        @staticmethod
        def completion(**kwargs):
            captured.update(kwargs)
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="Gemini answer"))])

    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    monkeypatch.setattr("backend.app.llm._load_litellm", lambda: FakeLiteLLM)
    assert _chat("System instruction", "Question", "gemini-2.5-flash") == "Gemini answer"
    assert captured["model"] == "gemini/gemini-2.5-flash"
    assert captured["api_key"] == "test-gemini-key"
    assert captured["messages"][0]["content"] == "System instruction"


def test_summarizer_is_generic_and_uses_all_meaningful_content(monkeypatch):
    questions = []

    def fake_generate(question, sources, history=None, model=None, allow_general_knowledge=True, reasoning_mode="light", guidance=""):
        questions.append(question)
        return "Generic summary", model

    monkeypatch.setattr("backend.app.llm.generate_answer", fake_generate)
    summarize_document("records.csv", "owner: Ada\nrisk: delayed\naction: review\ncontext: no description field", "test-model")
    assert "without assuming a document type" in questions[0]
    assert "decisions, actions, risks" in questions[0]
    assert "fixed fields" in questions[-1]


def test_mode_configuration_separates_light_and_thinking():
    assert MODE_CONFIG["light"].use_initial_retrieval_only
    assert MODE_CONFIG["light"].select_strongest_excerpts_only
    assert not MODE_CONFIG["light"].inspect_all_chunks
    assert not MODE_CONFIG["light"].use_quality_layer
    assert MODE_CONFIG["thinking"].inspect_all_chunks
    assert MODE_CONFIG["thinking"].extract_evidence_from_every_chunk
    assert MODE_CONFIG["thinking"].consolidate_evidence
    assert MODE_CONFIG["thinking"].use_quality_layer
    assert MODE_CONFIG["deep_summary"].inspect_all_chunks
    assert MODE_CONFIG["deep_summary"].use_quality_layer


def test_env_file_matches_example_and_is_ignored():
    def keys(path):
        return {line.split("=", 1)[0] for line in path.read_text().splitlines() if line and not line.startswith("#") and "=" in line}

    assert ENV_PATH.exists()
    assert keys(ENV_PATH) == keys(ENV_PATH.with_name(".env.example"))
    assert os.system(f"git check-ignore -q '{ENV_PATH}'") == 0


def test_missing_required_environment_variable_has_clear_error(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="Missing required environment variable: OPENAI_API_KEY"):
        require_environment_variable("OPENAI_API_KEY")


def test_internal_plan_is_removed_from_final_answer():
    leaked = 'Plan: {"answer_format":"table"}\n\nAnswer: **Six companies**\n\n| Company |\n|---|\n| Alkem |'
    cleaned = clean_final_answer(leaked)
    assert cleaned.startswith("**Six companies**")
    assert "Plan:" not in cleaned


def test_planned_requirements_run_as_separate_calls_before_merge(monkeypatch):
    calls = []

    def fake_generate(question, sources, history=None, model=None, allow_general_knowledge=True, reasoning_mode="light", guidance=""):
        calls.append({"question": question, "sources": sources})
        return f"Finding for {question}", model

    monkeypatch.setattr("backend.app.llm.generate_answer", fake_generate)
    monkeypatch.setattr("backend.app.llm._structured_entities", lambda *args: {"entity_type": "company", "count": 2, "entities": [{"name": "A"}, {"name": "B"}]})
    plan = {"enhanced_question": "Count employers", "subquestions": ["List employers", "Find roles", "Find dates"], "aggregation_operation": "count_unique", "entity_type": "company"}
    answer_planned_question("How many employers?", plan, [("resume.pdf", "evidence")], [], "test-model", False, "Use a table")
    assert [call["question"] for call in calls[:3]] == plan["subquestions"]
    assert calls[-1]["question"] == "How many employers?"
    assert len(calls) == 4


@pytest.mark.parametrize("question", [
    "Summarize this book in detail",
    "I want full context",
    "Give me a complete summary",
    "Help me understand the full document",
    "Provide a chapter wise summary of all chapters",
])
def test_full_summary_intent_detection(question):
    assert is_full_summary_intent(question)


def test_deep_summary_processes_every_chapter_and_builds_manifest(monkeypatch):
    calls = []

    def fake_generate(question, sources, history=None, model=None, allow_general_knowledge=True, reasoning_mode="light", guidance=""):
        calls.append((question, sources))
        if "Required section coverage" in question:
            return "## Chapter 1: Start\nFirst.\n## Chapter 2: Middle\nSecond.\n## Chapter 3: End\nThird.", model
        return f"Summary of {sources[0][1][:80]}", model

    monkeypatch.setattr("backend.app.deep_summary.generate_answer", fake_generate)
    text = "Chapter 1: Start\nAlpha\nChapter 2: Middle\nBeta\nChapter 3: End\nGamma"
    answer, model, manifest, evidence = deep_summarize_documents([("book.txt", text)], "test-model")
    assert manifest.totalChunks == manifest.processedChunks == 3
    assert manifest.detectedSections == ["Chapter 1: Start", "Chapter 2: Middle", "Chapter 3: End"]
    assert manifest.summarizedSections == manifest.detectedSections
    assert manifest.coverageStatus == "complete"
    assert len(evidence) == 3
    assert not missing_sections(answer, manifest)
    assert len([question for question, _ in calls if "Summarize this complete chunk" in question]) == 3


def test_deep_summary_rejects_false_missing_claims_and_appends_every_section(monkeypatch):
    def fake_generate(question, sources, history=None, model=None, allow_general_knowledge=True, reasoning_mode="light", guidance=""):
        if "Required section coverage" in question:
            return "## What's Missing?\nThe source does not contain excerpts from Chapter 2 - Two.", model
        return f"Grounded summary: {sources[0][1][:60]}", model

    monkeypatch.setattr("backend.app.deep_summary.generate_answer", fake_generate)
    text = "Chapter 1 - One\nAlpha content\nChapter 2 - Two\nBeta content"
    answer, _, manifest, _ = deep_summarize_documents([("book.txt", text)], "test-model")
    assert manifest.coverageStatus == "complete"
    assert "What's Missing" not in answer
    assert "## Chapter 1 - One" in answer
    assert "## Chapter 2 - Two" in answer
    assert "Alpha content" in answer
    assert "Beta content" in answer


def test_chunk_document_preserves_page_provenance():
    text = "--- PAGE 1 ---\nChapter 1: One\nFirst page\n--- PAGE 2 ---\nChapter 2: Two\nSecond page"
    chunks, pages, sections = chunk_document("book.pdf", text, 4_000)
    assert pages == 2
    assert [chunk.pages for chunk in chunks] == [[1], [2]]
    assert sections == ["Chapter 1: One", "Chapter 2: Two"]


def test_chunk_document_does_not_treat_table_of_contents_as_section_boundaries():
    text = (
        "--- PAGE 1 ---\nTable of Contents\nChapter 1 - One\nChapter 2 - Two\n"
        "--- PAGE 2 ---\nIntroduction - Welcome\nOpening explanation\n"
        "--- PAGE 3 ---\nChapter 1 - One\nFirst chapter\n"
        "--- PAGE 4 ---\nChapter 2 - Two\nSecond chapter\n"
        "--- PAGE 5 ---\nConclusion - Finish\nClosing text"
    )
    chunks, _, sections = chunk_document("book.pdf", text, 4_000)
    assert [chunk.section for chunk in chunks] == ["Document overview", "Introduction - Welcome", "Chapter 1 - One", "Chapter 2 - Two", "Conclusion - Finish"]
    assert sections == ["Introduction - Welcome", "Chapter 1 - One", "Chapter 2 - Two", "Conclusion - Finish"]


@pytest.mark.parametrize(
    ("reasoning_mode", "question"),
    [("thinking", "Give me a complete summary of this document"), ("deep_summary", "Summarize the selected material")],
)
def test_full_summary_modes_use_deep_pipeline(monkeypatch, reasoning_mode, question):
    captured = {}

    def fake_deep(documents, model, notify=lambda detail: None):
        captured["documents"] = documents
        manifest = CoverageManifest("book.txt", 0, 2, 2, ["Chapter 1", "Chapter 2"], ["Chapter 1", "Chapter 2"], "complete")
        evidence = [("book.txt - Chapter 1", "Chapter 1 summary"), ("book.txt - Chapter 2", "Chapter 2 summary")]
        return "## Chapter 1\nOne\n## Chapter 2\nTwo", model, manifest, evidence

    monkeypatch.setattr("backend.app.main.deep_summarize_documents", fake_deep)
    monkeypatch.setattr("backend.app.main.answer_planned_question", lambda *args, **kwargs: pytest.fail("Deep summaries bypass relevance answer composition"))
    with TestClient(app) as client:
        store = client.post("/api/collections", json={"title": f"Deep pipeline {reasoning_mode}"}).json()
        uploaded = client.post("/api/files", data={"store_id": store["id"]}, files={"file": ("book.txt", b"Chapter 1\nOne\nChapter 2\nTwo", "text/plain")}).json()
        result = chat(client, question=question, reasoning_mode=reasoning_mode, file_ids=[uploaded["id"]])
    assert captured["documents"][0][0] == "book.txt"
    assert "Chapter 2" in result["answer"]
    assert "2/2 chunks" in result["sources"][0]["excerpt"]


def test_deep_summary_factual_question_uses_full_file_evidence_without_coverage_pipeline(monkeypatch):
    called = {"deep": False, "answer": False}

    def fake_answer(question, plan, evidence, *args, **kwargs):
        called["answer"] = True
        assert question == "What has he done so far?"
        assert evidence[0][0] == "resume.txt"
        assert "Built incident automation" in evidence[0][1]
        return "He built incident automation and reporting workflows.", "test-model"

    def fake_deep(*args, **kwargs):
        called["deep"] = True
        pytest.fail("Factual questions should not use the coverage summary pipeline")

    monkeypatch.setattr("backend.app.main.deep_summarize_documents", fake_deep)
    monkeypatch.setattr("backend.app.main.answer_planned_question", fake_answer)
    with TestClient(app) as client:
        store = client.post("/api/collections", json={"title": "Deep factual question"}).json()
        uploaded = client.post("/api/files", data={"store_id": store["id"]}, files={"file": ("resume.txt", b"Built incident automation and reporting workflows.", "text/plain")}).json()
        result = chat(client, question="What has he done so far?", reasoning_mode="deep_summary", file_ids=[uploaded["id"]])
    assert called == {"deep": False, "answer": True}
    assert result["answer"] == "He built incident automation and reporting workflows."
    assert result["sources"][0]["excerpt"] == "Full file inspected and consolidated in Deep Summary mode."


def test_light_full_summary_discloses_partial_coverage(monkeypatch):
    monkeypatch.setattr("backend.app.main.answer_planned_question", lambda *args, **kwargs: ("Excerpt summary", "test-model"))
    with TestClient(app) as client:
        store = client.post("/api/collections", json={"title": "Light disclosure"}).json()
        uploaded = client.post("/api/files", data={"store_id": store["id"]}, files={"file": ("short.txt", b"complete summary marker", "text/plain")}).json()
        result = chat(client, question="Give me a complete summary", reasoning_mode="light", file_ids=[uploaded["id"]])
    assert result["answer"].startswith("This is a partial summary based on retrieved excerpts")
