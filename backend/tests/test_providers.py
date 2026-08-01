from backend.app.providers import PROVIDER_ORDER, PROVIDERS, provider_spec
from backend.app.llm import _litellm_model, get_llm_client


def test_registry_includes_new_gateway_providers():
    assert "openrouter" in PROVIDERS
    assert "tokenrouter" in PROVIDERS
    assert PROVIDERS["openrouter"].kind == "gateway"
    assert PROVIDERS["tokenrouter"].kind == "gateway"
    assert set(PROVIDER_ORDER) == set(PROVIDERS)


def test_provider_spec_rejects_unknown_provider():
    try:
        provider_spec("not-a-real-provider")
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "Unknown LLM provider" in str(exc)


def test_gateway_models_route_through_openai_prefix():
    assert _litellm_model("openrouter", "anthropic/claude-fable-5") == "openai/anthropic/claude-fable-5"
    assert _litellm_model("tokenrouter", "openai/some-model") == "openai/some-model"


def test_get_llm_client_rejects_unsupported_provider():
    try:
        get_llm_client(model="whatever", provider="not-a-real-provider")
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "not-a-real-provider" in str(exc) or "Unknown LLM provider" in str(exc)
