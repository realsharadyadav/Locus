from pathlib import Path

import httpx
import pytest
from backend.app.config import GROQ_MODEL_PRESETS, GroqSettings, llm_provider
from backend.app.llm import LLM_REQUEST_TIMEOUT_SECONDS, GroqClient, OllamaClient, get_llm_client, list_groq_models, llm_provider_context
from backend.app.main import llm_config


def settings(**changes):
    values = {
        "api_key": "test-secret-key",
        "base_url": "https://groq.test/openai/v1",
        "model": "openai/gpt-oss-20b",
        "temperature": 0.15,
        "max_tokens": 4096,
        "timeout_seconds": 120,
        "max_retries": 2,
        "retry_backoff_seconds": 0,
    }
    values.update(changes)
    return GroqSettings(**values)


class FakeResponse:
    def __init__(self, status_code=200, payload=None, headers=None):
        self.status_code = status_code
        self._payload = payload or {"choices": [{"message": {"content": "Groq answer"}}]}
        self.headers = headers or {}

    @property
    def is_error(self):
        return self.status_code >= 400

    def raise_for_status(self):
        if self.is_error:
            request = httpx.Request("GET", "https://groq.test")
            raise httpx.HTTPStatusError("failed", request=request, response=httpx.Response(self.status_code, request=request))

    def json(self):
        return self._payload


class FakeClient:
    responses = []
    calls = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs, self.kwargs))
        return self.responses.pop(0)

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs, self.kwargs))
        return self.responses.pop(0)


def test_provider_selection(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    assert isinstance(get_llm_client("llama3.2:latest"), OllamaClient)
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    assert isinstance(get_llm_client(), GroqClient)
    monkeypatch.setenv("LLM_PROVIDER", "unknown")
    with pytest.raises(RuntimeError, match="ollama.*groq"):
        llm_provider()


def test_missing_groq_key_is_actionable(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="GROQ_API_KEY"):
        GroqClient()


def test_groq_sends_openai_messages_and_config(monkeypatch):
    FakeClient.responses = [FakeResponse()]
    FakeClient.calls = []
    monkeypatch.setattr("backend.app.llm.httpx.Client", FakeClient)
    messages = [{"role": "system", "content": "System"}, {"role": "user", "content": "Question"}]
    assert GroqClient(settings()).generate(messages, temperature=0.3, max_tokens=123) == "Groq answer"
    url, request, client = FakeClient.calls[0]
    assert url == "https://groq.test/openai/v1/chat/completions"
    assert request["json"] == {"model": "openai/gpt-oss-20b", "messages": messages, "temperature": 0.3, "max_tokens": 123}
    assert request["headers"]["Authorization"] == "Bearer test-secret-key"
    # The per-provider timeout is clamped by the global LLM request ceiling, so a
    # generous GroqSettings value never lets one call hang past that ceiling.
    assert client["timeout"] == min(120, LLM_REQUEST_TIMEOUT_SECONDS)


def test_groq_timeout_below_global_ceiling_is_used_as_is(monkeypatch):
    FakeClient.responses = [FakeResponse()]
    FakeClient.calls = []
    monkeypatch.setattr("backend.app.llm.httpx.Client", FakeClient)
    lower = LLM_REQUEST_TIMEOUT_SECONDS - 10
    GroqClient(settings(timeout_seconds=lower)).generate([{"role": "user", "content": "Question"}])
    _, _, client = FakeClient.calls[0]
    assert client["timeout"] == lower


def test_groq_retries_rate_limit_then_succeeds(monkeypatch):
    FakeClient.responses = [FakeResponse(429), FakeResponse()]
    FakeClient.calls = []
    monkeypatch.setattr("backend.app.llm.httpx.Client", FakeClient)
    assert GroqClient(settings()).generate([{"role": "user", "content": "Hi"}]) == "Groq answer"
    assert len(FakeClient.calls) == 2


def test_groq_honors_bounded_retry_after(monkeypatch):
    sleeps = []
    FakeClient.responses = [FakeResponse(429, headers={"Retry-After": "35"}), FakeResponse()]
    FakeClient.calls = []
    monkeypatch.setattr("backend.app.llm.httpx.Client", FakeClient)
    monkeypatch.setattr("backend.app.llm.time.sleep", sleeps.append)
    assert GroqClient(settings()).generate([{"role": "user", "content": "Hi"}]) == "Groq answer"
    assert sleeps == [35]


def test_groq_waits_for_token_reset_when_longer_than_retry_after(monkeypatch):
    sleeps = []
    FakeClient.responses = [FakeResponse(429, headers={"Retry-After": "13", "x-ratelimit-reset-tokens": "44.5s"}), FakeResponse()]
    FakeClient.calls = []
    monkeypatch.setattr("backend.app.llm.httpx.Client", FakeClient)
    monkeypatch.setattr("backend.app.llm.time.sleep", sleeps.append)
    assert GroqClient(settings()).generate([{"role": "user", "content": "Hi"}]) == "Groq answer"
    assert sleeps == [44.5]


def test_groq_honors_long_retry_after_without_a_hardcoded_cap(monkeypatch):
    sleeps = []
    FakeClient.responses = [FakeResponse(429, headers={"Retry-After": "120"}), FakeResponse()]
    FakeClient.calls = []
    monkeypatch.setattr("backend.app.llm.httpx.Client", FakeClient)
    monkeypatch.setattr("backend.app.llm.time.sleep", sleeps.append)
    assert GroqClient(settings()).generate([{"role": "user", "content": "Hi"}]) == "Groq answer"
    assert sleeps == [120]
    assert len(FakeClient.calls) == 2


@pytest.mark.parametrize(("status", "message"), [(401, "authentication"), (404, "model is unavailable"), (413, "too large")])
def test_groq_non_success_errors_are_safe(monkeypatch, status, message):
    FakeClient.responses = [FakeResponse(status)] * 3
    FakeClient.calls = []
    monkeypatch.setattr("backend.app.llm.httpx.Client", FakeClient)
    with pytest.raises(RuntimeError, match=message) as raised:
        GroqClient(settings()).generate([{"role": "user", "content": "Hi"}])
    assert "test-secret-key" not in str(raised.value)
    assert len(FakeClient.calls) == 1


def test_groq_proactively_waits_when_next_call_exceeds_remaining_tokens(monkeypatch):
    sleeps = []
    FakeClient.responses = [
        FakeResponse(headers={"x-ratelimit-remaining-tokens": "100", "x-ratelimit-reset-tokens": "5s"}),
        FakeResponse(),
    ]
    FakeClient.calls = []
    monkeypatch.setattr("backend.app.llm.httpx.Client", FakeClient)
    monkeypatch.setattr("backend.app.llm.time.sleep", sleeps.append)
    with llm_provider_context("groq"):
        client = GroqClient(settings())
        assert client.generate([{"role": "user", "content": "First"}], max_tokens=1000) == "Groq answer"
        assert client.generate([{"role": "user", "content": "Second"}], max_tokens=1000) == "Groq answer"
    assert len(sleeps) == 1
    assert 0 < sleeps[0] <= 5


def test_model_listing_fetches_and_falls_back(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    FakeClient.responses = [FakeResponse(payload={"data": [{"id": "model-b"}, {"id": "model-a"}]})]
    FakeClient.calls = []
    monkeypatch.setattr("backend.app.llm.httpx.Client", FakeClient)
    assert list_groq_models() == (["model-a", "model-b"], False)
    FakeClient.responses = [FakeResponse(503)]
    assert list_groq_models() == (GROQ_MODEL_PRESETS, True)


def test_llm_config_endpoint_and_env_example(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    payload = llm_config()
    assert payload["provider"] == "groq"
    assert payload["model"] == "openai/gpt-oss-20b"
    assert payload["models"] == GROQ_MODEL_PRESETS
    example = Path(__file__).resolve().parents[2] / ".env.example"
    text = example.read_text()
    assert "GROQ_API_KEY=" in text
    assert "GROQ_MODEL=openai/gpt-oss-20b" in text
