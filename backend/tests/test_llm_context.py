"""Context-window plumbing: history trimming, history summarization, source packing,
per-provider character budgets.

These are pure unit tests over `backend.app.llm` helpers with no app or database
involved. They used to be copy-pasted into test_100step_conversation.py,
test_comprehensive_chat.py and test_deep_stress.py — three near-identical sets that
drifted apart and disagreed about the Groq budget. This module is the single home.
"""

from contextlib import contextmanager

import pytest

import backend.app.llm as llm_module
from backend.app.llm import _context_budget, _pack_sources, _summarize_history, _trim_history


@contextmanager
def active_provider(provider_name):
    token = llm_module._ACTIVE_PROVIDER.set(provider_name)
    try:
        yield
    finally:
        llm_module._ACTIVE_PROVIDER.reset(token)


def interleaved_history(pairs):
    history = []
    for i in range(pairs):
        history.append(("user", f"question {i}"))
        history.append(("assistant", f"answer {i}"))
    return history


class TestTrimHistory:
    def test_empty_history(self):
        assert _trim_history([], 1000) == []

    def test_within_budget_is_untouched(self):
        history = [("user", "hello"), ("assistant", "hi")]
        assert _trim_history(history, 10_000) == history

    def test_large_budget_keeps_every_message(self):
        history = [("user", f"msg {i}") for i in range(100)]
        assert len(_trim_history(history, 1_000_000)) == 100

    def test_small_budget_drops_older_messages(self):
        history = [(f"role{i}", f"Message {i}: " + "x" * 50) for i in range(100)]
        result = _trim_history(history, 2000)
        assert sum(len(content) for _, content in result) <= 2000
        assert len(result) < 100

    def test_fills_the_budget_exactly(self):
        history = [(f"role{i}", "a" * 100) for i in range(200)]
        result = _trim_history(history, 5000)
        assert sum(len(content) for _, content in result) == 5000

    def test_keeps_the_most_recent_message(self):
        history = [
            ("user", "old message"),
            ("assistant", "old response"),
            ("user", "recent message"),
            ("assistant", "recent response"),
        ]
        assert _trim_history(history, 200)[-1] == ("assistant", "recent response")

    def test_preserves_role_order(self):
        history = interleaved_history(25)
        result = _trim_history(history, 200)
        assert [role for role, _ in result] == [role for role, _ in history[-len(result):]]

    def test_single_message_longer_than_budget_is_truncated(self):
        result = _trim_history([("user", "a" * 10_000)], 500)
        assert len(result) == 1
        assert len(result[0][1]) == 500

    def test_long_assistant_response_is_truncated_not_dropped(self):
        history = [("user", "short question"), ("assistant", "b" * 9000)]
        result = _trim_history(history, 3000)
        assert result[-1][0] == "assistant"
        assert sum(len(content) for _, content in result) <= 3000

    def test_never_exceeds_the_groq_budget(self):
        with active_provider("groq"):
            budget = _context_budget("test-model")
        history = [(f"role{i}", "x" * 200) for i in range(50)]
        assert sum(len(content) for _, content in _trim_history(history, budget)) <= budget


class TestSummarizeHistory:
    def test_empty_history(self):
        assert _summarize_history([], "m") == ""

    def test_four_or_fewer_messages_skip_the_llm(self, monkeypatch):
        monkeypatch.setattr("backend.app.llm._chat", lambda *args, **kwargs: pytest.fail("should not call the LLM"))
        result = _summarize_history([("user", "q1"), ("assistant", "a1"), ("user", "q2"), ("assistant", "a2")], "m")
        assert "user: q1" in result
        assert "assistant: a2" in result
        assert "Earlier context:" not in result

    def test_longer_history_summarizes_older_messages_once(self, monkeypatch):
        prompts = []

        def fake_chat(system, prompt, model, temperature=0.1, max_tokens=800):
            prompts.append(prompt)
            return "Summary of old messages"

        monkeypatch.setattr("backend.app.llm._chat", fake_chat)
        result = _summarize_history(interleaved_history(20), "m")
        assert "Earlier context:" in result
        assert "Recent messages:" in result
        assert len(prompts) == 1

    def test_recent_messages_survive_verbatim(self, monkeypatch):
        monkeypatch.setattr("backend.app.llm._chat", lambda *args, **kwargs: "Summary")
        history = interleaved_history(20)
        result = _summarize_history(history, "m")
        for role, content in history[-4:]:
            assert f"{role}: {content}" in result

    def test_llm_failure_falls_back_to_truncation(self, monkeypatch):
        def failing_chat(*args, **kwargs):
            raise RuntimeError("LLM unavailable")

        monkeypatch.setattr("backend.app.llm._chat", failing_chat)
        result = _summarize_history(interleaved_history(20), "m", max_chars=3000)
        assert result
        assert "Recent messages:" in result


class TestPackSources:
    def test_no_sources(self):
        assert _pack_sources([], 1000) == []

    def test_within_budget_is_untouched(self):
        assert _pack_sources([("a.txt", "short text")], 1000) == [("a.txt", "short text")]

    def test_large_budget_keeps_every_source(self):
        sources = [(f"file{i}.txt", f"content {i}") for i in range(100)]
        assert len(_pack_sources(sources, 1_000_000)) == 100

    def test_small_budget_drops_sources(self):
        sources = [(f"file{i}.txt", f"content {i} " * 50) for i in range(100)]
        result = _pack_sources(sources, 1000)
        assert sum(len(text) for _, text in result) <= 1000
        assert len(result) < 100

    def test_single_huge_source_is_truncated(self):
        result = _pack_sources([("huge.txt", "x" * 50_000)], 5000)
        assert len(result) == 1
        assert len(result[0][1]) == 5000

    @pytest.mark.parametrize("budget", [1000, 5000, 10_000, 80_000])
    def test_never_exceeds_the_budget(self, budget):
        sources = [(f"file{i}.txt", "x" * 500) for i in range(50)]
        assert sum(len(text) for _, text in _pack_sources(sources, budget)) <= budget


class TestContextBudget:
    def test_groq_uses_its_own_budget_regardless_of_model_name(self):
        with active_provider("groq"):
            # Groq's budget is provider-wide, so an Ollama-looking model name must not
            # fall through to the Ollama branch.
            assert _context_budget("llama3.2:latest") == _context_budget("openai/gpt-oss-20b")

    def test_groq_budget_is_env_overridable(self, monkeypatch):
        monkeypatch.setenv("GROQ_CONTEXT_CHAR_BUDGET", "15000")
        with active_provider("groq"):
            assert _context_budget("test-model") == 15000

    def test_groq_budget_has_a_floor(self, monkeypatch):
        monkeypatch.setenv("GROQ_CONTEXT_CHAR_BUDGET", "10")
        with active_provider("groq"):
            assert _context_budget("test-model") == 8000

    @pytest.mark.parametrize("model", ["gpt-4o", "gpt-4-turbo", "gpt-5.5", "gpt-5.5-mini"])
    def test_openai_models(self, model):
        assert _context_budget(model) == 80_000

    @pytest.mark.parametrize("model", ["gemini-2.5-flash", "gemini-1.5-pro", "gemini-2.0-flash"])
    def test_gemini_models(self, model):
        assert _context_budget(model) == 80_000

    def test_ollama_local_has_a_floor(self):
        with active_provider("ollama"):
            assert _context_budget("llama3.2:latest") >= 10_000

    def test_ollama_cloud_models(self):
        with active_provider("ollama"):
            assert _context_budget("nemotron:cloud") == 40_000
