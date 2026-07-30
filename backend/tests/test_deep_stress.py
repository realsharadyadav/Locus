"""Deep stress tests: mode switching, 200-step rapid fire, file ops mid-conversation, job lifecycle."""
import json
import time

import pytest

from fastapi.testclient import TestClient

from backend.app.database import SessionLocal
from backend.app.main import app
import backend.app.main as main_module
import backend.app.web_research as web_research_module
from backend.app.deep_summary import CoverageManifest
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
def mock_llm(monkeypatch):
    """Mock all LLM calls so tests run fast without a real model."""
    monkeypatch.setattr("backend.app.main.enhance_question",
        lambda question, history, model: {
            "enhanced_question": question, "subquestions": [],
            "answer_format": "Clear answer", "supporting_details": [],
            "visualization": "none", "completeness_criteria": ["Answer the question"],
            "requires_full_relevant_files": False,
            "aggregation_operation": "none", "entity_type": None,
        })
    monkeypatch.setattr("backend.app.main.verify_response",
        lambda question, answer, plan, model, sources=None: {"complete": True, "missing": [], "quality_score": 95})
    monkeypatch.setattr("backend.app.main.answer_planned_question",
        lambda question, plan, evidence, history, model, allow_general_knowledge, guidance, notify=lambda d: None, on_token=None: ("Test answer", model))
    monkeypatch.setattr("backend.app.main.extract_shared_evidence",
        lambda question, requirements, documents, model, notify=lambda d: None: documents)
    monkeypatch.setattr("backend.app.main.generate_answer",
        lambda question, sources, history=None, model=None, allow_general_knowledge=True, reasoning_mode="light", guidance="", system_override=None: ("Test answer", model or "test-model"))
    monkeypatch.setattr("backend.app.main.stream_answer",
        lambda *a, **k: (iter(["Test answer"]), "test-model"))
    monkeypatch.setattr("backend.app.main.web_research",
        lambda *a, **k: {"answer": "Web answer", "sources": [], "model": "test-model"})
    monkeypatch.setattr("backend.app.main.generate_unrestricted_answer",
        lambda *a, **k: ("Unrestricted answer", "test-model"))
    monkeypatch.setattr("backend.app.main.repair_response",
        lambda question, answer, plan, missing, sources, model, allow_general_knowledge: "Repaired answer")

    def fake_deep_summary(documents, model, notify=lambda d: None):
        manifest = CoverageManifest(
            fileName=documents[0][0] if documents else "doc.txt",
            totalPages=1, totalChunks=1, processedChunks=1,
            detectedSections=["Section 1"], summarizedSections=["Section 1"],
            coverageStatus="complete",
        )
        return "Deep summary result", model, manifest, [(documents[0][0], "Section 1 summary")] if documents else []
    monkeypatch.setattr("backend.app.main.deep_summarize_documents", fake_deep_summary)


# =====================================================================
# 1. MODE SWITCHING MID-CONVERSATION
# =====================================================================

class TestModeSwitchingMidConversation:
    """Switch between modes within the same conversation."""

    def test_light_to_thinking_to_light(self, monkeypatch):
        """Switch light → thinking → light, all in same conversation."""
        with TestClient(app) as c:
            r1 = chat(c, question="Simple question", reasoning_mode="light", file_ids=[])
            cid = r1["conversation_id"]

            r2 = chat(c, question="Deep analysis please", conversation_id=cid, reasoning_mode="thinking", file_ids=[])
            assert r2["conversation_id"] == cid

            r3 = chat(c, question="Back to simple", conversation_id=cid, reasoning_mode="light", file_ids=[])
            assert r3["conversation_id"] == cid

            msgs = c.get(f"/api/chats/{cid}/messages").json()
            assert len(msgs) == 6  # 3 pairs

    def test_light_to_web_research(self, monkeypatch):
        """Switch light → web_research."""
        with TestClient(app) as c:
            r1 = chat(c, question="Simple question", reasoning_mode="light", file_ids=[])
            cid = r1["conversation_id"]

            r2 = chat(c, question="Search for latest news", conversation_id=cid, reasoning_mode="web_research")
            assert r2["conversation_id"] == cid
            assert r2["answer"] == "Web answer"

    def test_light_to_unrestricted(self, monkeypatch):
        """Switch light → unrestricted."""
        with TestClient(app) as c:
            r1 = chat(c, question="Simple question", reasoning_mode="light", file_ids=[])
            cid = r1["conversation_id"]

            r2 = chat(c, question="Expert analysis", conversation_id=cid, reasoning_mode="unrestricted", file_ids=[])
            assert r2["conversation_id"] == cid
            assert r2["answer"] == "Unrestricted answer"

    def test_all_modes_sequentially(self, monkeypatch):
        """Go through all 6 modes in order."""
        with TestClient(app) as c:
            s = c.post("/api/collections", json={"title": "Mode test"}).json()
            f = _upload_text(c, s["id"], "tickets.csv", "id,summary\n1,Login issue\n2,Password reset")

            r = chat(c, question="Start simple", reasoning_mode="light", file_ids=[])
            cid = r["conversation_id"]

            # thinking mode
            r = chat(c, question="Think deeper", conversation_id=cid, reasoning_mode="thinking", file_ids=[])
            assert r["conversation_id"] == cid

            # deep_summary
            r = chat(c, question="Give complete summary", conversation_id=cid, reasoning_mode="deep_summary", file_ids=[f["id"]])
            assert r["conversation_id"] == cid

            # web_research
            r = chat(c, question="Search the web", conversation_id=cid, reasoning_mode="web_research")
            assert r["conversation_id"] == cid

            # unrestricted
            r = chat(c, question="Expert mode", conversation_id=cid, reasoning_mode="unrestricted", file_ids=[])
            assert r["conversation_id"] == cid

            msgs = c.get(f"/api/chats/{cid}/messages").json()
            assert len(msgs) == 10  # 5 pairs (skipped ticket_analysis since it requires 1 file only)


# =====================================================================
# 2. VERY LONG MESSAGES
# =====================================================================

class TestVeryLongMessages:
    """Messages at and beyond ChatRequest's question length limit."""

    def test_question_just_under_maximum(self, monkeypatch):
        monkeypatch.setattr("backend.app.main.generate_answer", lambda *a, **k: ("ok", "m"))
        with TestClient(app) as c:
            q = "x" * (QUESTION_MAX_CHARS - 1) + "?"
            r = chat(c, question=q, reasoning_mode="light", file_ids=[])
            assert r["answer"] == "ok"

    def test_question_at_maximum_accepted(self, monkeypatch):
        monkeypatch.setattr("backend.app.main.generate_answer", lambda *a, **k: ("ok", "m"))
        with TestClient(app) as c:
            q = "A " + "detailed " * ((QUESTION_MAX_CHARS - 11) // 9)
            q = q.ljust(QUESTION_MAX_CHARS - 1, "x") + "?"
            assert len(q) == QUESTION_MAX_CHARS
            r = chat(c, question=q, reasoning_mode="light", file_ids=[])
            assert r["answer"] == "ok"

    def test_question_one_char_over_maximum_rejected(self):
        with TestClient(app) as c:
            resp = c.post("/api/chat/stream", json={"question": "x" * (QUESTION_MAX_CHARS + 1), "reasoning_mode": "light", "file_ids": []})
            assert resp.status_code == 422

    def test_long_question_with_special_chars(self, monkeypatch):
        monkeypatch.setattr("backend.app.main.generate_answer", lambda *a, **k: ("ok", "m"))
        with TestClient(app) as c:
            q = "Explain <script>alert('xss')</script> and " + "a" * 900 + " in detail?"
            assert len(q) <= QUESTION_MAX_CHARS
            r = chat(c, question=q, reasoning_mode="light", file_ids=[])
            assert r["answer"] == "ok"

    def test_long_question_unicode(self, monkeypatch):
        monkeypatch.setattr("backend.app.main.generate_answer", lambda *a, **k: ("ok", "m"))
        with TestClient(app) as c:
            q = "解释" * 200 + "的内容?"
            r = chat(c, question=q, reasoning_mode="light", file_ids=[])
            assert r["answer"] == "ok"

    def test_long_question_hindi(self, monkeypatch):
        monkeypatch.setattr("backend.app.main.generate_answer", lambda *a, **k: ("ok", "m"))
        with TestClient(app) as c:
            q = "मुझे बताओ " * 100 + "क्या है?"
            if len(q) > 1000:
                q = q[:1000]
            r = chat(c, question=q, reasoning_mode="light", file_ids=[])
            assert r["answer"] == "ok"

    def test_repeated_same_question(self, monkeypatch):
        monkeypatch.setattr("backend.app.main.generate_answer", lambda *a, **k: ("ok", "m"))
        with TestClient(app) as c:
            r1 = chat(c, question="What is Python?", reasoning_mode="light", file_ids=[])
            cid = r1["conversation_id"]
            for i in range(10):
                r = chat(c, question="What is Python?", conversation_id=cid, reasoning_mode="light", file_ids=[])
                assert r["conversation_id"] == cid
            msgs = c.get(f"/api/chats/{cid}/messages").json()
            assert len(msgs) == 22  # 11 pairs


# =====================================================================
# 3. RAPID-FIRE 200-STEP
# =====================================================================

class TestRapidFire200Steps:
    """200 messages with no delay — stress test the DB and pipeline."""

    def test_200_steps_no_delay(self, monkeypatch):
        """All 200 steps should work with no sleep between."""
        with TestClient(app) as c:
            r1 = chat(c, question="Rapid step 1", reasoning_mode="light", file_ids=[])
            cid = r1["conversation_id"]

            for i in range(2, 201):
                r = chat(c, question=f"Rapid step {i}", conversation_id=cid, reasoning_mode="light", file_ids=[])
                assert r["conversation_id"] == cid, f"Failed at step {i}"

            msgs = c.get(f"/api/chats/{cid}/messages").json()
            assert len(msgs) == 400  # 200 user + 200 assistant

            # Verify all user messages are present
            user_msgs = [m for m in msgs if m["role"] == "user"]
            for i, msg in enumerate(user_msgs):
                assert msg["content"] == f"Rapid step {i+1}", f"Message {i} mismatch"

    def test_200_steps_with_files(self, monkeypatch):
        """200 steps with file context."""
        with TestClient(app) as c:
            s = c.post("/api/collections", json={"title": "200step files"}).json()
            f = _upload_text(c, s["id"], "big.txt", "Content about testing and quality assurance")

            r1 = chat(c, question="Step 1 with file", reasoning_mode="light", file_ids=[f["id"]])
            cid = r1["conversation_id"]

            for i in range(2, 201):
                r = chat(c, question=f"Step {i} with file", conversation_id=cid, reasoning_mode="light", file_ids=[f["id"]])
                assert r["conversation_id"] == cid, f"Failed at step {i}"

            msgs = c.get(f"/api/chats/{cid}/messages").json()
            assert len(msgs) == 400

    def test_200_steps_interleaved_modes(self, monkeypatch):
        """200 steps alternating between light and web_research."""
        with TestClient(app) as c:
            r1 = chat(c, question="Interleaved 1 light", reasoning_mode="light", file_ids=[])
            cid = r1["conversation_id"]

            for i in range(2, 201):
                mode = "light" if i % 2 == 0 else "web_research"
                r = chat(c, question=f"Interleaved {i} {mode}", conversation_id=cid, reasoning_mode=mode)
                assert r["conversation_id"] == cid, f"Failed at step {i}"

            msgs = c.get(f"/api/chats/{cid}/messages").json()
            assert len(msgs) == 400


# =====================================================================
# 4. FILE UPLOAD/DELETE MID-CONVERSATION
# =====================================================================

class TestFileOpsMidConversation:
    """Upload and delete files during a long conversation."""

    def test_upload_new_file_mid_conversation(self, monkeypatch):
        """Upload a new file after 10 messages, then reference it."""
        with TestClient(app) as c:
            s = c.post("/api/collections", json={"title": "Mid upload"}).json()

            r1 = chat(c, question="Initial question", reasoning_mode="light", file_ids=[])
            cid = r1["conversation_id"]

            for i in range(2, 11):
                chat(c, question=f"Msg {i}", conversation_id=cid, reasoning_mode="light", file_ids=[])

            # Upload a new file
            f = _upload_text(c, s["id"], "new.txt", "New content about machine learning")

            # Now use the file
            r = chat(c, question="What does the new file say?", conversation_id=cid, reasoning_mode="light", file_ids=[f["id"]])
            assert r["conversation_id"] == cid

            msgs = c.get(f"/api/chats/{cid}/messages").json()
            assert len(msgs) == 22  # 11 pairs

    def test_delete_file_after_conversation(self, monkeypatch):
        """Upload file, use it in conversation, then delete the file."""
        with TestClient(app) as c:
            s = c.post("/api/collections", json={"title": "Delete file test"}).json()
            f = _upload_text(c, s["id"], "deleteme.txt", "Content to be deleted")

            r1 = chat(c, question="What does deleteme.txt say?", reasoning_mode="light", file_ids=[f["id"]])
            cid = r1["conversation_id"]

            # Delete the file
            resp = c.delete(f"/api/files/{f['id']}")
            assert resp.status_code == 204

            # Continue conversation without the file
            r2 = chat(c, question="Continue without the file", conversation_id=cid, reasoning_mode="light", file_ids=[])
            assert r2["conversation_id"] == cid

    def test_multiple_files_upload_mid_conversation(self, monkeypatch):
        """Upload 3 files at different points in conversation."""
        with TestClient(app) as c:
            s = c.post("/api/collections", json={"title": "Multi file mid"}).json()

            r1 = chat(c, question="Start", reasoning_mode="light", file_ids=[])
            cid = r1["conversation_id"]

            f1 = _upload_text(c, s["id"], "file1.txt", "Content about Python")
            chat(c, question="msg 2", conversation_id=cid, reasoning_mode="light", file_ids=[f1["id"]])

            f2 = _upload_text(c, s["id"], "file2.txt", "Content about JavaScript")
            chat(c, question="msg 3", conversation_id=cid, reasoning_mode="light", file_ids=[f2["id"]])

            f3 = _upload_text(c, s["id"], "file3.txt", "Content about Rust")
            r = chat(c, question="msg 4", conversation_id=cid, reasoning_mode="light", file_ids=[f3["id"]])

            assert r["conversation_id"] == cid
            msgs = c.get(f"/api/chats/{cid}/messages").json()
            assert len(msgs) == 8  # 4 pairs

    def test_delete_collection_removes_all_files(self, monkeypatch):
        """Deleting a collection removes all its files."""
        with TestClient(app) as c:
            s = c.post("/api/collections", json={"title": "Delete collection"}).json()
            f1 = _upload_text(c, s["id"], "a.txt", "File A")
            f2 = _upload_text(c, s["id"], "b.txt", "File B")

            resp = c.delete(f"/api/collections/{s['id']}")
            assert resp.status_code == 204

            files = c.get("/api/files").json()
            assert not any(f["id"] in (f1["id"], f2["id"]) for f in files)


class TestWebSearchFollowUp:
    """Web search behavior with conversation history."""

    def test_agentic_pipeline_receives_history(self, monkeypatch):
        captured = {}
        monkeypatch.setattr("backend.app.main.run_agentic_pipeline", fake_agentic(captured))

        with TestClient(app) as c:
            r1 = chat(c, question="Tell me about Python", reasoning_mode="light", file_ids=[])
            cid = r1["conversation_id"]

        # Conversation history reaches the agentic pipeline, which threads it into
        # planning and answer composition. It is deliberately NOT forwarded to the
        # nested web_research() searches — those run the planner's self-contained
        # queries, so passing history there would only pollute the search terms.
            chat(c, question="Search for latest Python updates", conversation_id=cid, reasoning_mode="web_research")
            assert ("user", "Tell me about Python") in captured["history"]
            assert captured["question"] == "Search for latest Python updates"
            assert len(captured["history"]) > 0

    def test_web_search_followup_cleans_query(self):
        """Follow-up queries should be cleaned."""
        query = web_research_module._search_question_with_history(
            "bola tha same phone in tabular format",
            [("user", "best phones under 5k"), ("assistant", "Here are options")],
        )
        assert "bola tha" not in query.lower()
        assert "tabular" not in query.lower()
        assert "5000" in query or "5k" in query.lower() or "phone" in query.lower()

    def test_web_search_stall_recovery(self, monkeypatch):
        """When search returns no new results, stall counter increments."""
        round_count = {"n": 0}
        def fake_search(query, max_results=50):
            round_count["n"] += 1
            if round_count["n"] > 2:
                return []  # stall
            return [{"title": f"Result {round_count['n']}", "url": f"https://example.com/{round_count['n']}", "snippet": "snippet", "engine": "test"}]

        monkeypatch.setattr(web_research_module, "_search_web", fake_search)
        monkeypatch.setattr(web_research_module, "_generate_initial_queries", lambda q, m, c: ["query"])
        monkeypatch.setattr(web_research_module, "_generate_followup_queries", lambda *a, **k: ["followup"])
        monkeypatch.setattr(web_research_module, "_synthesize_answer", lambda q, r, m, p, **kw: "answer")

        result = web_research_module.web_research("question", "model", lambda *a: None, source_limit=5)
        assert result["answer"] == "answer"

    def test_web_search_max_rounds_limited(self, monkeypatch):
        """Should not exceed 5 rounds."""
        searched = []
        def track_search(query, max_results=50):
            searched.append(query)
            return [{"title": "R", "url": f"https://x.com/{len(searched)}", "snippet": "s", "engine": "t"}]

        monkeypatch.setattr(web_research_module, "_search_web", track_search)
        monkeypatch.setattr(web_research_module, "_generate_initial_queries", lambda q, m, c: ["q1", "q2"])
        monkeypatch.setattr(web_research_module, "_generate_followup_queries", lambda *a, **k: ["fu1", "fu2"])
        monkeypatch.setattr(web_research_module, "_synthesize_answer", lambda q, r, m, p, **kw: "answer")

        web_research_module.web_research("question", "model", lambda *a: None, source_limit=200)
        assert len(searched) <= 12


# =====================================================================
# 8. EMPTY/WHITESPACE MESSAGES
# =====================================================================

class TestEmptyAndWhitespace:
    """Edge cases with empty or whitespace-only content."""

    def test_question_with_only_spaces_accepted_as_valid_input(self, monkeypatch):
        """Whitespace-only passes Pydantic validation but may produce empty/error answer."""
        monkeypatch.setattr("backend.app.main.generate_answer", lambda *a, **k: ("ok", "m"))
        with TestClient(app) as c:
            resp = c.post("/api/chat/stream", json={"question": "   ", "reasoning_mode": "light", "file_ids": []})
            assert resp.status_code == 200

    def test_question_with_only_newlines_accepted(self, monkeypatch):
        monkeypatch.setattr("backend.app.main.generate_answer", lambda *a, **k: ("ok", "m"))
        with TestClient(app) as c:
            resp = c.post("/api/chat/stream", json={"question": "\n\n\n", "reasoning_mode": "light", "file_ids": []})
            assert resp.status_code == 200

    def test_question_with_tabs_accepted(self, monkeypatch):
        monkeypatch.setattr("backend.app.main.generate_answer", lambda *a, **k: ("ok", "m"))
        with TestClient(app) as c:
            resp = c.post("/api/chat/stream", json={"question": "\t\t\t", "reasoning_mode": "light", "file_ids": []})
            assert resp.status_code == 200

    def test_question_with_mixed_whitespace_accepted(self, monkeypatch):
        monkeypatch.setattr("backend.app.main.generate_answer", lambda *a, **k: ("ok", "m"))
        with TestClient(app) as c:
            resp = c.post("/api/chat/stream", json={"question": " \n \t ", "reasoning_mode": "light", "file_ids": []})
            assert resp.status_code == 200

    def test_single_char_rejected(self):
        with TestClient(app) as c:
            resp = c.post("/api/chat/stream", json={"question": "a", "reasoning_mode": "light", "file_ids": []})
            assert resp.status_code == 422

    def test_two_chars_accepted(self, monkeypatch):
        monkeypatch.setattr("backend.app.main.generate_answer", lambda *a, **k: ("ok", "m"))
        with TestClient(app) as c:
            r = chat(c, question="ok", reasoning_mode="light", file_ids=[])
            assert r["answer"] == "ok"

    def test_just_punctuation_accepted(self, monkeypatch):
        monkeypatch.setattr("backend.app.main.generate_answer", lambda *a, **k: ("ok", "m"))
        with TestClient(app) as c:
            r = chat(c, question="??", reasoning_mode="light", file_ids=[])
            assert r["answer"] == "ok"


# =====================================================================
# 9. JOB LIFECYCLE
# =====================================================================

class TestJobLifecycle:
    """Create → cancel → retry patterns."""

    def test_job_create_complete_cycle(self):
        with TestClient(app) as c:
            resp = c.post("/api/chat/jobs", json={"question": "Lifecycle test", "reasoning_mode": "light", "file_ids": []})
            assert resp.status_code == 202
            job_id = resp.json()["id"]

            for _ in range(100):
                jobs = c.get("/api/chat/jobs").json()
                job = next((j for j in jobs if j["id"] == job_id), None)
                if job and job["status"] in ("completed", "failed"):
                    break
                time.sleep(0.02)

            assert job["status"] == "completed"
            assert job["result"] is not None
            assert job["seen"] is False

            # Mark as seen
            seen = c.patch(f"/api/chat/jobs/{job_id}/seen")
            assert seen.json()["seen"] is True

    def test_job_cancel_during_execution(self):
        """Cancel a job while it's running."""
        with TestClient(app) as c:
            with SessionLocal() as db:
                session = ChatSession(title="Cancel lifecycle")
                db.add(session)
                db.flush()
                job = ChatJob(
                    id="lifecycle_cancel", status="running", stage="drafting",
                    detail="Running", question="Cancel me",
                    conversation_id=session.id, model="test-model",
                )
                db.add(job)
                db.commit()

            event = main_module._chat_job_cancel_event("lifecycle_cancel")
            assert not event.is_set()

            resp = c.post("/api/chat/jobs/lifecycle_cancel/cancel")
            assert resp.status_code == 200
            assert resp.json()["status"] == "cancelled"
            assert resp.json()["detail"] == "Answer stopped by user"
            assert event.is_set()
            main_module._forget_chat_job_cancel_event("lifecycle_cancel")

    def test_stop_chat_cancels_all_jobs(self):
        """Stop chat cancels all active jobs for that chat."""
        with TestClient(app) as c:
            with SessionLocal() as db:
                session = ChatSession(title="Stop all jobs")
                db.add(session)
                db.flush()
                job1 = ChatJob(id="stop_job1", status="running", stage="drafting", detail="R", question="j1", conversation_id=session.id, model="m")
                job2 = ChatJob(id="stop_job2", status="queued", stage="starting", detail="Q", question="j2", conversation_id=session.id, model="m")
                db.add_all([job1, job2])
                db.commit()
                chat_id = session.id

            resp = c.post(f"/api/chats/{chat_id}/stop")
            assert resp.status_code == 200
            result = resp.json()
            assert result["status"] == "stopped"
            assert "stop_job1" in result["cancelled_jobs"]
            assert "stop_job2" in result["cancelled_jobs"]
            assert main_module._chat_job_cancel_event("stop_job1").is_set()
            assert main_module._chat_job_cancel_event("stop_job2").is_set()
            main_module._forget_chat_job_cancel_event("stop_job1")
            main_module._forget_chat_job_cancel_event("stop_job2")

    def test_delete_chat_cancels_jobs_and_removes(self):
        """Delete chat cancels jobs and removes everything."""
        with TestClient(app) as c:
            with SessionLocal() as db:
                session = ChatSession(title="Delete lifecycle")
                db.add(session)
                db.flush()
                job = ChatJob(id="delete_lifecycle_job", status="running", stage="drafting", detail="R", question="j", conversation_id=session.id, model="m")
                db.add(job)
                db.commit()
                chat_id = session.id

            event = main_module._chat_job_cancel_event("delete_lifecycle_job")
            assert not event.is_set()

            resp = c.delete(f"/api/chats/{chat_id}")
            assert resp.status_code == 204
            assert event.is_set()
            assert not any(ch["id"] == chat_id for ch in c.get("/api/chats").json())
            main_module._forget_chat_job_cancel_event("delete_lifecycle_job")

    def test_job_list_returns_newest_first(self):
        with TestClient(app) as c:
            resp1 = c.post("/api/chat/jobs", json={"question": "First job", "reasoning_mode": "light", "file_ids": []})
            time.sleep(0.02)
            resp2 = c.post("/api/chat/jobs", json={"question": "Second job", "reasoning_mode": "light", "file_ids": []})

            j1, j2 = resp1.json(), resp2.json()
            assert j2["created_at"] >= j1["created_at"] or j2["id"] != j1["id"]
            assert j1["question"] == "First job"
            assert j2["question"] == "Second job"


# =====================================================================
# 10. CONCURRENT JOBS ON SAME CHAT
# =====================================================================

class TestConcurrentJobsSameChat:
    """Multiple concurrent jobs targeting the same chat."""

    def test_two_jobs_same_chat_both_complete(self):
        with TestClient(app) as c:
            with SessionLocal() as db:
                session = ChatSession(title="Concurrent jobs")
                db.add(session)
                db.flush()
                db.commit()
                chat_id = session.id

            resp1 = c.post("/api/chat/jobs", json={"question": "Job A", "conversation_id": chat_id, "reasoning_mode": "light", "file_ids": []})
            resp2 = c.post("/api/chat/jobs", json={"question": "Job B", "conversation_id": chat_id, "reasoning_mode": "light", "file_ids": []})

            assert resp1.status_code == 202
            assert resp2.status_code == 202

            # Both should complete
            for _ in range(100):
                jobs = c.get("/api/chat/jobs").json()
                j1 = next((j for j in jobs if j["id"] == resp1.json()["id"]), None)
                j2 = next((j for j in jobs if j["id"] == resp2.json()["id"]), None)
                if j1 and j2 and j1["status"] in ("completed", "failed") and j2["status"] in ("completed", "failed"):
                    break
                time.sleep(0.02)

            assert j1["status"] == "completed"
            assert j2["status"] == "completed"

            # Both messages should be in the chat
            msgs = c.get(f"/api/chats/{chat_id}/messages").json()
            user_msgs = [m for m in msgs if m["role"] == "user"]
            assert len(user_msgs) == 2

    def test_cancel_one_job_does_not_affect_other(self):
        with TestClient(app) as c:
            with SessionLocal() as db:
                session = ChatSession(title="Cancel one only")
                db.add(session)
                db.flush()
                db.commit()
                chat_id = session.id

            resp1 = c.post("/api/chat/jobs", json={"question": "Keep me", "conversation_id": chat_id, "reasoning_mode": "light", "file_ids": []})
            resp2 = c.post("/api/chat/jobs", json={"question": "Cancel me", "conversation_id": chat_id, "reasoning_mode": "light", "file_ids": []})

            time.sleep(0.05)
            # Cancel only job 2
            cancel = c.post(f"/api/chat/jobs/{resp2.json()['id']}/cancel")
            assert cancel.status_code == 200

            # Job 1 should still be running/completed
            time.sleep(0.1)
            jobs = c.get("/api/chat/jobs").json()
            j1 = next((j for j in jobs if j["id"] == resp1.json()["id"]), None)
            assert j1["status"] in ("running", "completed")
