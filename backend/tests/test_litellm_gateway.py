from types import SimpleNamespace

from backend.app import llm as llm_module


def completion_response(text):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])


def stream_chunk(text):
    return SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=text))])


def test_chat_routes_groq_through_groq_client_not_litellm(monkeypatch):
    """Groq must bypass the LiteLLM gateway so calls share GroqClient's proactive
    token-budget throttle and rate-limit-aware backoff (see _GROQ_RATE_STATE).
    LiteLLM's generic num_retries has no idea about Groq's remaining-tokens headers."""
    litellm_called = {"value": False}

    class FakeLiteLLM:
        drop_params = False

        @staticmethod
        def completion(**kwargs):
            litellm_called["value"] = True
            return completion_response("Gateway answer")

    class FakeGroqResponse:
        status_code = 200
        headers = {}
        is_error = False

        def json(self):
            return {"choices": [{"message": {"content": "Groq answer"}}], "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8}}

    class FakeHttpxClient:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def post(self, url, **kwargs):
            captured["url"] = url
            captured["json"] = kwargs["json"]
            return FakeGroqResponse()

    captured = {}
    monkeypatch.setattr(llm_module, "_load_litellm", lambda: FakeLiteLLM)
    monkeypatch.setattr(llm_module.httpx, "Client", FakeHttpxClient)
    monkeypatch.setenv("GROQ_API_KEY", "test-key")

    with llm_module.llm_provider_context("groq"):
        assert llm_module._chat("System", "Question", "openai/gpt-oss-20b") == "Groq answer"

    assert litellm_called["value"] is False
    assert captured["json"]["model"] == "openai/gpt-oss-20b"
    assert captured["json"]["messages"][0] == {"role": "system", "content": "System"}


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
