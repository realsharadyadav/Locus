"""Single source of truth for which LLM providers Locus knows about.

Adding a new OpenAI-compatible provider (another aggregator/gateway, a new
vendor) should only require a new entry here — `config.py`, `llm.py`, and
`main.py`'s `/api/llm/config` all read from `PROVIDERS` instead of hardcoding
provider names.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderSpec:
    id: str
    label: str
    icon: str
    blurb: str
    # "ollama" and "gemini" get bespoke handling (different list-models shape,
    # different auth). "groq" and "openai" already speak the OpenAI-compatible
    # shape natively. "gateway" is any other OpenAI-compatible endpoint reached
    # through LiteLLM's generic `openai/<model>` + custom api_base mechanism.
    kind: str
    api_key_env: str | None
    base_url: str | None
    model_env: str | None
    default_model: str | None
    docs_url: str | None
    env_hint: str
    # Gateway-only escape hatch: when set, this env var overrides `base_url` at runtime, so a
    # provider that moves or renames its endpoint can be corrected from .env without a release.
    base_url_env: str | None = None


PROVIDERS: dict[str, ProviderSpec] = {
    "ollama": ProviderSpec(
        id="ollama",
        label="Ollama",
        icon="🦙",
        blurb="Local models, no API key needed",
        kind="ollama",
        api_key_env=None,
        base_url=None,
        model_env="OLLAMA_MODEL",
        default_model="llama3.2:latest",
        docs_url="https://ollama.com",
        env_hint="Runs against OLLAMA_URL — start Ollama and pull a model.",
    ),
    "groq": ProviderSpec(
        id="groq",
        label="Groq",
        icon="⚡",
        blurb="Fast cloud inference",
        kind="groq",
        api_key_env="GROQ_API_KEY",
        base_url="https://api.groq.com/openai/v1",
        model_env="GROQ_MODEL",
        default_model=None,
        docs_url="https://console.groq.com/docs",
        env_hint="Set GROQ_API_KEY in your .env file.",
    ),
    "openai": ProviderSpec(
        id="openai",
        label="OpenAI",
        icon="🤖",
        blurb="OpenAI models",
        kind="openai",
        api_key_env="OPENAI_API_KEY",
        base_url="https://api.openai.com/v1",
        model_env="OPENAI_MODEL",
        default_model="gpt-5.4-mini",
        docs_url="https://platform.openai.com/docs",
        env_hint="Set OPENAI_API_KEY in your .env file.",
    ),
    "gemini": ProviderSpec(
        id="gemini",
        label="Gemini",
        icon="✨",
        blurb="Google Gemini models",
        kind="gemini",
        api_key_env="GEMINI_API_KEY",
        base_url="https://generativelanguage.googleapis.com/v1beta",
        model_env="GEMINI_MODEL",
        default_model="gemini-2.5-flash",
        docs_url="https://ai.google.dev/gemini-api/docs",
        env_hint="Set GEMINI_API_KEY in your .env file.",
    ),
    "openrouter": ProviderSpec(
        id="openrouter",
        label="OpenRouter",
        icon="🌐",
        blurb="One API for many model providers",
        kind="gateway",
        api_key_env="OPENROUTER_API_KEY",
        base_url="https://openrouter.ai/api/v1",
        model_env="OPENROUTER_MODEL",
        default_model="openrouter/auto",
        docs_url="https://openrouter.ai/docs",
        env_hint="Set OPENROUTER_API_KEY in your .env file.",
    ),
    "tokenrouter": ProviderSpec(
        id="tokenrouter",
        label="TokenRouter",
        icon="🔀",
        blurb="Unified gateway across text, image, video, and audio models",
        kind="gateway",
        api_key_env="TOKENROUTER_API_KEY",
        base_url="https://api.tokenrouter.com/v1",
        model_env="TOKENROUTER_MODEL",
        default_model=None,
        docs_url="https://tokenrouter.com/docs",
        env_hint="Set TOKENROUTER_API_KEY in your .env file.",
    ),
    "opencode": ProviderSpec(
        id="opencode",
        label="OpenCode Go",
        icon="🐹",
        blurb="Curated coding models on one key",
        kind="gateway",
        api_key_env="OPENCODE_API_KEY",
        base_url="https://opencode.ai/zen/go/v1",
        model_env="OPENCODE_MODEL",
        default_model=None,
        docs_url="https://opencode.ai/docs/zen/",
        env_hint="Set OPENCODE_API_KEY in your .env file.",
        base_url_env="OPENCODE_BASE_URL",
    ),
    "cerebras": ProviderSpec(
        id="cerebras",
        label="Cerebras",
        icon="🧠",
        blurb="Cerebras inference API",
        kind="cerebras",
        api_key_env="CEREBRAS_API_KEY",
        base_url="https://api.cerebras.ai/v1",
        model_env="CEREBRAS_MODEL",
        default_model="llama-3.3-70b",
        docs_url="https://docs.cerebras.ai",
        env_hint="Set CEREBRAS_API_KEY in your .env file.",
    ),
}

PROVIDER_ORDER = ["ollama", "groq", "openai", "gemini", "cerebras", "openrouter", "tokenrouter", "opencode"]


def provider_spec(provider_id: str) -> ProviderSpec:
    spec = PROVIDERS.get(provider_id)
    if not spec:
        raise RuntimeError(f"Unknown LLM provider '{provider_id}'. Known providers: {', '.join(PROVIDER_ORDER)}.")
    return spec
