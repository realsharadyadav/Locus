from types import SimpleNamespace

from backend.app import llm as llm_module


def completion_response(text):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])


def stream_chunk(text):
    return SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=text))])


def test_chat_uses_litellm_gateway_for_groq(monkeypatch):
    captured = {}

    class FakeLiteLLM:
        drop_params = False

        @staticmethod
        def completion(**kwargs):
            captured.update(kwargs)
            return completion_response("Gateway answer")

    monkeypatch.setattr(llm_module, "_load_litellm", lambda: FakeLiteLLM)
    monkeypatch.setenv("GROQ_API_KEY", "test-key")

    with llm_module.llm_provider_context("groq"):
        assert llm_module._chat("System", "Question", "openai/gpt-oss-20b") == "Gateway answer"

    assert captured["model"] == "groq/openai/gpt-oss-20b"
    assert captured["messages"][0] == {"role": "system", "content": "System"}
    assert captured["api_key"] == "test-key"


def test_chat_uses_litellm_gateway_for_ollama(monkeypatch):
    captured = {}

    class FakeLiteLLM:
        @staticmethod
        def completion(**kwargs):
            captured.update(kwargs)
            return completion_response("Local answer")

    monkeypatch.setattr(llm_module, "_load_litellm", lambda: FakeLiteLLM)

    with llm_module.llm_provider_context("ollama"):
        assert llm_module._chat("System", "Question", "llama3.2:latest") == "Local answer"

    assert captured["model"] == "ollama_chat/llama3.2:latest"
    assert captured["api_base"] == llm_module.OLLAMA_URL


def test_stream_chat_uses_litellm_stream(monkeypatch):
    captured = {}

    class FakeLiteLLM:
        @staticmethod
        def completion(**kwargs):
            captured.update(kwargs)
            return iter([stream_chunk("hel"), stream_chunk("lo"), stream_chunk(None)])

    monkeypatch.setattr(llm_module, "_load_litellm", lambda: FakeLiteLLM)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    tokens = list(llm_module._stream_chat("System", "Question", "gemini-2.5-flash", provider="gemini"))

    assert tokens == ["hel", "lo"]
    assert captured["stream"] is True
    assert captured["model"] == "gemini/gemini-2.5-flash"
