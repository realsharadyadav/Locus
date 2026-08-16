"""100-step conversation stress test — tests history trimming, summarization, context budget."""
import json

import pytest

from fastapi.testclient import TestClient

from backend.app.database import SessionLocal
from backend.app.main import app
import backend.app.main as main_module
from backend.app.models import ChatJob


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
        lambda question, plan, evidence, history, model, allow_general_knowledge, guidance, notify=lambda d: None, on_token=None: ("Test answer", model),
    )
    monkeypatch.setattr(
        "backend.app.main.extract_shared_evidence",
        lambda question, requirements, documents, model, notify=lambda d: None: documents,
    )
    monkeypatch.setattr(
        "backend.app.main.generate_answer",
        lambda question, sources, history=None, model=None, allow_general_knowledge=True, reasoning_mode="light", guidance="", system_override=None: ("Test answer", model or "test-model"),
    )
    # Mock stream_answer for direct-stream
    monkeypatch.setattr(
        "backend.app.main.stream_answer",
        lambda *a, **k: (iter(["Test answer"]), "test-model"),
    )
    # Mock web_research
    monkeypatch.setattr(
        "backend.app.main.web_research",
        lambda *a, **k: {"answer": "Web answer", "sources": [], "model": "test-model"},
    )


# =====================================================================
# 100-STEP CONVERSATION TESTS
# =====================================================================

class Test100StepLightConversation:
    """100-step conversation in light mode without files."""

    def test_100_messages_all_persisted(self, monkeypatch):
        """All 100 user+assistant message pairs should be stored in DB."""
        with TestClient(app) as c:
            r1 = chat(c, question="Step 1: What is Python?", reasoning_mode="light", file_ids=[])
            cid = r1["conversation_id"]

            for i in range(2, 101):
                r = chat(c, question=f"Step {i}: follow-up question", conversation_id=cid, reasoning_mode="light", file_ids=[])
                assert r["conversation_id"] == cid, f"Step {i}: conversation_id changed!"

            msgs = c.get(f"/api/chats/{cid}/messages").json()
            assert len(msgs) == 200, f"Expected 200 messages (100 user + 100 assistant), got {len(msgs)}"

            user_msgs = [m for m in msgs if m["role"] == "user"]
            assistant_msgs = [m for m in msgs if m["role"] == "assistant"]
            assert len(user_msgs) == 100
            assert len(assistant_msgs) == 100

            # Verify ordering
            for i in range(len(msgs) - 1):
                assert msgs[i]["id"] < msgs[i+1]["id"], "Messages not in ascending ID order"

    def test_100_steps_chat_session_updated_at_changes(self, monkeypatch):
        """updated_at should change with each message."""
        with TestClient(app) as c:
            r1 = chat(c, question="timestamp test 1", reasoning_mode="light", file_ids=[])
            cid = r1["conversation_id"]

            timestamps = []
            for i in range(1, 21):
                chat(c, question=f"timestamp {i}", conversation_id=cid, reasoning_mode="light", file_ids=[])
                chats = c.get("/api/chats").json()
                session = next(ch for ch in chats if ch["id"] == cid)
                timestamps.append(session["updated_at"])

            # Timestamps should be non-decreasing
            for i in range(1, len(timestamps)):
                assert timestamps[i] >= timestamps[i-1], f"Timestamp decreased at step {i}"

    def test_100_steps_title_preserved(self, monkeypatch):
        """Chat title should be set from first message and never change."""
        with TestClient(app) as c:
            r1 = chat(c, question="My unique title here 42", reasoning_mode="light", file_ids=[])
            cid = r1["conversation_id"]

            for i in range(2, 51):
                chat(c, question=f"msg {i}", conversation_id=cid, reasoning_mode="light", file_ids=[])

            chats = c.get("/api/chats").json()
            session = next(ch for ch in chats if ch["id"] == cid)
            assert session["title"] == "My unique title here 42"

    def test_100_steps_each_message_has_model(self, monkeypatch):
        """Every assistant message should have model and provider stored."""
        with TestClient(app) as c:
            r1 = chat(c, question="model check 1", reasoning_mode="light", file_ids=[], provider="groq", model="test-model")
            cid = r1["conversation_id"]

            for i in range(2, 21):
                chat(c, question=f"model check {i}", conversation_id=cid, reasoning_mode="light", file_ids=[], provider="groq", model="test-model")

            msgs = c.get(f"/api/chats/{cid}/messages").json()
            for msg in msgs:
                if msg["role"] == "assistant":
                    assert msg["model"] == "test-model", f"Message {msg['id']} missing model"
                    assert msg["provider"] == "groq", f"Message {msg['id']} missing provider"


class Test100StepWithFiles:
    """100-step conversation with file context."""

    def test_100_steps_with_files_uses_planner(self, monkeypatch):
        """File-based conversation should use planner throughout."""
        planner_calls = []
        def track_enhance(question, history, model):
            planner_calls.append(len(history) if history else 0)
            return {
                "enhanced_question": question, "subquestions": [],
                "answer_format": "Clear answer", "supporting_details": [],
                "visualization": "none", "completeness_criteria": ["Answer"],
                "requires_full_relevant_files": False,
                "aggregation_operation": "none", "entity_type": None,
            }
        monkeypatch.setattr("backend.app.main.enhance_question", track_enhance)

        with TestClient(app) as c:
            s = c.post("/api/collections", json={"title": "100step files"}).json()
            f = _upload_text(c, s["id"], "doc.txt", "Important content about algorithms and data structures")

            r1 = chat(c, question="Tell me about algorithms", reasoning_mode="light", file_ids=[f["id"]])
            cid = r1["conversation_id"]

            for i in range(2, 101):
                r = chat(c, question=f"Follow-up {i}", conversation_id=cid, reasoning_mode="light", file_ids=[f["id"]])
                assert r["conversation_id"] == cid

            msgs = c.get(f"/api/chats/{cid}/messages").json()
            assert len(msgs) == 200

            # Planner was called for every step
            assert len(planner_calls) == 100

            # History starts empty, grows one user+assistant pair per step, then flattens
            # at the loader's message cap.
            assert planner_calls[0] == 0
            assert planner_calls[9] == 18  # step 10: 9 prior pairs, still under the cap
            assert planner_calls[49] == main_module.CHAT_HISTORY_LOAD_LIMIT
            assert planner_calls[99] == main_module.CHAT_HISTORY_LOAD_LIMIT

    def test_100_steps_truncation_mid_conversation(self, monkeypatch):
        """Truncating at step 50 should leave only first 50 messages."""
        monkeypatch.setattr("backend.app.main.generate_answer", lambda *a, **k: ("ok", "m"))
        with TestClient(app) as c:
            s = c.post("/api/collections", json={"title": "trunc test"}).json()
            f = _upload_text(c, s["id"], "doc.txt", "Some content about testing")

            r1 = chat(c, question="msg 1", reasoning_mode="light", file_ids=[f["id"]])
            cid = r1["conversation_id"]

            for i in range(2, 101):
                chat(c, question=f"msg {i}", conversation_id=cid, reasoning_mode="light", file_ids=[f["id"]])

            msgs = c.get(f"/api/chats/{cid}/messages").json()
            assert len(msgs) == 200

            # Truncate from message 51 (user message at position 50)
            edit_msg_id = msgs[100]["id"]  # 50th user message (0-indexed: 0=user1, 1=asst1, ... 98=user50, 99=asst50, 100=user51)
            resp = c.delete(f"/api/chats/{cid}/messages/{edit_msg_id}/from")
            assert resp.status_code == 200
            remaining = resp.json()
            assert len(remaining) == 100  # 50 user + 50 assistant


class Test100StepWebSearch:
    """100-step conversation with web search triggered."""

    def test_100_steps_with_auto_web_search(self, monkeypatch):
        """Web search should work with long conversation history."""
        # Asserted on the agentic pipeline, not on the nested web_research() calls:
        # main.py hands history to the pipeline, which deliberately keeps it out of the
        # search queries themselves, so a fake web_research always sees history=None.
        history_lengths = []

        def track_pipeline(question, model, progress, source_limit=5, history=None, answer_mode="light", force_web=False, web_research_fn=None, direct_answer_fn=None):
            history_lengths.append(len(history or []))
            return {"answer": "Web answer", "sources": [], "model": model, "plan": {}}

        monkeypatch.setattr("backend.app.main.run_agentic_pipeline", track_pipeline)

        with TestClient(app) as c:
            r1 = chat(c, question="Search for Python tutorials", reasoning_mode="web_research")
            cid = r1["conversation_id"]

            for i in range(2, 51):
                chat(c, question=f"Search for more topic {i}", conversation_id=cid, reasoning_mode="web_research")

            assert len(history_lengths) == 50
            assert history_lengths[0] == 0  # first turn has no prior messages
            assert history_lengths[1] == 2  # one user+assistant pair
            assert history_lengths[49] == main_module.CHAT_HISTORY_LOAD_LIMIT


class TestEdgeCases100Step:
    """Edge cases at step 100."""

    def test_delete_at_step_100(self, monkeypatch):
        """Deleting chat at step 100 removes everything."""
        monkeypatch.setattr("backend.app.main.generate_answer", lambda *a, **k: ("ok", "m"))
        with TestClient(app) as c:
            r1 = chat(c, question="delete test 1", reasoning_mode="light", file_ids=[])
            cid = r1["conversation_id"]

            for i in range(2, 101):
                chat(c, question=f"msg {i}", conversation_id=cid, reasoning_mode="light", file_ids=[])

            msgs = c.get(f"/api/chats/{cid}/messages").json()
            assert len(msgs) == 200

            resp = c.delete(f"/api/chats/{cid}")
            assert resp.status_code == 204
            # After deletion, session is gone — messages endpoint returns 404
            msg_resp = c.get(f"/api/chats/{cid}/messages")
            assert msg_resp.status_code == 404
            # Chat no longer in listing
            assert not any(ch["id"] == cid for ch in c.get("/api/chats").json())

    def test_truncate_at_step_75(self, monkeypatch):
        """Truncating at step 75 leaves first 75 messages."""
        monkeypatch.setattr("backend.app.main.generate_answer", lambda *a, **k: ("ok", "m"))
        with TestClient(app) as c:
            r1 = chat(c, question="trunc 1", reasoning_mode="light", file_ids=[])
            cid = r1["conversation_id"]

            for i in range(2, 101):
                chat(c, question=f"msg {i}", conversation_id=cid, reasoning_mode="light", file_ids=[])

            msgs = c.get(f"/api/chats/{cid}/messages").json()
            # Message 76 (user) = index 150
            edit_from = msgs[150]["id"]
            resp = c.delete(f"/api/chats/{cid}/messages/{edit_from}/from")
            assert resp.status_code == 200
            remaining = resp.json()
            assert len(remaining) == 150  # 75 pairs

    def test_job_cancel_at_step_50(self, monkeypatch):
        """Cancel a running job in a long conversation."""
        with TestClient(app) as c:
            r1 = chat(c, question="job cancel test 1", reasoning_mode="light", file_ids=[])
            cid = r1["conversation_id"]

            for i in range(2, 51):
                chat(c, question=f"msg {i}", conversation_id=cid, reasoning_mode="light", file_ids=[])

            with SessionLocal() as db:
                job = ChatJob(
                    id="cancel_at_50", status="running", stage="drafting",
                    detail="Running", question="cancel me",
                    conversation_id=cid, model="test-model",
                )
                db.add(job)
                db.commit()

            event = main_module._chat_job_cancel_event("cancel_at_50")
            assert not event.is_set()
            resp = c.post("/api/chat/jobs/cancel_at_50/cancel")
            assert resp.status_code == 200
            assert resp.json()["status"] == "cancelled"
            assert event.is_set()
            main_module._forget_chat_job_cancel_event("cancel_at_50")

    def test_concurrent_100_step_chats(self, monkeypatch):
        """Two chats running concurrently to 100 steps."""
        monkeypatch.setattr("backend.app.main.generate_answer", lambda *a, **k: ("ok", "m"))
        with TestClient(app) as c:
            r1 = chat(c, question="concurrent A", reasoning_mode="light", file_ids=[])
            r2 = chat(c, question="concurrent B", reasoning_mode="light", file_ids=[])
            cid_a = r1["conversation_id"]
            cid_b = r2["conversation_id"]

            for i in range(2, 51):
                chat(c, question=f"A-{i}", conversation_id=cid_a, reasoning_mode="light", file_ids=[])
                chat(c, question=f"B-{i}", conversation_id=cid_b, reasoning_mode="light", file_ids=[])

            msgs_a = c.get(f"/api/chats/{cid_a}/messages").json()
            msgs_b = c.get(f"/api/chats/{cid_b}/messages").json()
            assert len(msgs_a) == 100
            assert len(msgs_b) == 100


# Helper context manager for patching provider
from contextlib import contextmanager

@contextmanager
def patch_active_provider(provider_name):
    """Temporarily patch the active LLM provider."""
    import backend.app.llm as llm_mod
    token = llm_mod._ACTIVE_PROVIDER.set(provider_name)
    try:
        yield
    finally:
        llm_mod._ACTIVE_PROVIDER.reset(token)
