from backend.app.config import gateway_settings
from backend.app.providers import PROVIDER_ORDER, PROVIDERS, provider_spec
from backend.app.llm import _litellm_model, build_model_meta, extract_param_size, get_llm_client


def test_registry_includes_new_gateway_providers():
    assert "openrouter" in PROVIDERS
    assert "tokenrouter" in PROVIDERS
    assert "opencode" in PROVIDERS
    assert PROVIDERS["openrouter"].kind == "gateway"
    assert PROVIDERS["tokenrouter"].kind == "gateway"
    assert PROVIDERS["opencode"].kind == "gateway"
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
    assert _litellm_model("opencode", "grok-code") == "openai/grok-code"


def test_opencode_settings_read_key_and_model_from_env(monkeypatch):
    monkeypatch.setenv("OPENCODE_API_KEY", "sk-opencode-test")
    monkeypatch.setenv("OPENCODE_MODEL", "kimi-k2.7-code")
    monkeypatch.delenv("OPENCODE_BASE_URL", raising=False)
    settings = gateway_settings("opencode")
    assert settings.api_key == "sk-opencode-test"
    assert settings.model == "kimi-k2.7-code"
    assert settings.base_url == "https://opencode.ai/zen/go/v1"


def test_gateway_base_url_env_overrides_registry_default(monkeypatch):
    monkeypatch.setenv("OPENCODE_API_KEY", "sk-opencode-test")
    monkeypatch.setenv("OPENCODE_BASE_URL", "https://opencode.ai/zen/v1")
    assert gateway_settings("opencode").base_url == "https://opencode.ai/zen/v1"


def test_gateway_without_base_url_env_ignores_overrides(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-openrouter-test")
    assert gateway_settings("openrouter").base_url == "https://openrouter.ai/api/v1"


def test_get_llm_client_rejects_unsupported_provider():
    try:
        get_llm_client(model="whatever", provider="not-a-real-provider")
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "not-a-real-provider" in str(exc) or "Unknown LLM provider" in str(exc)


def test_extract_param_size_matches_open_weight_ids():
    assert extract_param_size("llama-3.3-70b-versatile") == "70B"
    assert extract_param_size("llama-3.1-8b-instant") == "8B"
    assert extract_param_size("openai/gpt-oss-20b") == "20B"
    assert extract_param_size("allam-2-7b") == "7B"


def test_extract_param_size_returns_none_for_proprietary_ids():
    assert extract_param_size("x-ai/grok-4.5") is None
    assert extract_param_size("gpt-4o") is None
    assert extract_param_size("gemini-2.5-flash") is None
    assert extract_param_size("claude-fable-5") is None


def test_build_model_meta_prefers_live_metadata_over_litellm_fallback():
    provider_models = {"openrouter": ["x-ai/grok-4.5"]}
    provider_metadata = {
        "openrouter": {
            "x-ai/grok-4.5": {
                "name": "xAI: Grok 4.5",
                "context_length": 500000,
                "pricing": {"prompt": "0.000002", "completion": "0.000006"},
            },
        },
    }
    meta = build_model_meta(provider_models, provider_metadata)
    entry = meta["x-ai/grok-4.5"]
    assert entry["name"] == "xAI: Grok 4.5"
    assert entry["context_length"] == 500000
    assert entry["pricing"] == {"prompt": "0.000002", "completion": "0.000006"}
    assert entry["param_size"] is None
