"""The one provider/model default the whole app answers with.

Settings is the only place a provider and model are chosen; it stores the choice under the
`explore_ai` user preference. No other module carries its own picker any more, so every entry
point that needs a provider/model resolves it here — Ask, Ticket Analysis and the private-chat
copilot alike — and falls back to the `.env` defaults when Settings has never been saved.
"""

from sqlalchemy.orm import Session

from .config import configured_model, llm_provider
from .database import SessionLocal
from .models import UserPreference
from .providers import PROVIDERS

AI_PREFERENCE_KEY = "explore_ai"


def preferred_ai(db: Session | None = None) -> tuple[str, str]:
    """Return the saved `(provider, model)` default, or the environment's when none is saved.

    A saved provider that is no longer in the registry (renamed or removed between releases)
    takes its model down with it — that model id means nothing to whichever provider we would
    otherwise fall back to — so both halves revert to the environment together. A preference
    that names only a model is fine, though: it belongs to the environment's own provider.
    """
    if db is None:
        with SessionLocal() as owned_session:
            return preferred_ai(owned_session)
    preference = db.get(UserPreference, AI_PREFERENCE_KEY)
    saved = preference.value if preference and isinstance(preference.value, dict) else {}
    provider = (saved.get("provider") or "").strip()
    model = (saved.get("model") or "").strip()
    if provider and provider not in PROVIDERS:
        return llm_provider(), configured_model()
    return provider or llm_provider(), model or configured_model()
