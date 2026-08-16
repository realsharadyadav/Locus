"""Automatic model fallback when the saved default fails on a real chat request.

Opt-in via the `auto_select_model` preference (the toggle on Settings next to the default
model). When the default model fails inside a ChatJob, the worker asks this module for the
healthiest alternative: responding models from the `model_health` tags, ranked by latency,
and kept inside the `enabled_models` allowlist if the user has customized one. Stale tags
are re-probed live, briefly, so a model that stopped answering since Settings last tested
it is not picked on reputation alone. The job retries once with that model; when it
succeeds the switch becomes permanent — the new model is persisted as the `explore_ai`
default and the switch itself is recorded under `auto_select_last_switch` so Settings can
explain what happened.

The default itself is still resolved in exactly one place (`ai_defaults.preferred_ai`);
this module only ever picks a *replacement* for a failed run, never the everyday default.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from .llm import probe_model
from .models import UserPreference

AUTO_SELECT_PREFERENCE_KEY = "auto_select_model"
MODEL_HEALTH_PREFERENCE_KEY = "model_health"
ENABLED_MODELS_PREFERENCE_KEY = "enabled_models"
LAST_SWITCH_PREFERENCE_KEY = "auto_select_last_switch"

# A health tag older than this is not trustworthy enough to choose a fallback on its own —
# the model may have started or stopped answering since Settings last probed it.
HEALTH_STALE_SECONDS = 10 * 60
# How many alternatives to consider. Every candidate tried is one full pipeline retry, so
# this stays small: the point is a quick recovery, not a tour of the catalogue.
FALLBACK_CANDIDATE_LIMIT = 3
# Live re-probes of stale tags run concurrently and are bounded, so a hanging provider
# cannot hold the failing job open for the full per-request timeout.
FALLBACK_PROBE_TIMEOUT_SECONDS = 5.0


def enabled(db: Session) -> bool:
    """Whether the auto-select toggle is on. Absent = off."""
    preference = db.get(UserPreference, AUTO_SELECT_PREFERENCE_KEY)
    value = preference.value if preference else None
    if isinstance(value, dict):
        return bool(value.get("enabled"))
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "on", "yes"}
    return False


def choose_fallback(db: Session, provider: str, model: str) -> list[tuple[str, str]]:
    """Ranked alternatives to the failed `(provider, model)`, or an empty list.

    Candidates come from the `model_health` tags: only `ok: true`, lowest `latency_ms`
    first, and only models the `enabled_models` allowlist still permits (a provider with
    no allowlist entry means every model is enabled). Health tags that are stale — missing
    a `checked_at` or older than 10 minutes — are re-probed once, concurrently, inside a
    short timeout, and the fresh answers are folded back into `model_health` so the next
    failure does not re-probe the same models. Returns up to `FALLBACK_CANDIDATE_LIMIT`
    candidates; the caller tries them in order and stops at the first success.
    """
    if not enabled(db):
        return []
    health = _preference_value(db, MODEL_HEALTH_PREFERENCE_KEY)
    if not health:
        return []
    allowlist = _preference_value(db, ENABLED_MODELS_PREFERENCE_KEY) or {}
    blocked = {(provider, model)}
    candidates = []
    for provider_id, models in health.items():
        if not isinstance(models, dict):
            continue
        allowed = allowlist.get(provider_id) if isinstance(allowlist, dict) else None
        for model_id, entry in models.items():
            if not isinstance(entry, dict) or not entry.get("ok"):
                continue
            if (provider_id, model_id) in blocked:
                continue
            if allowed is not None and model_id not in allowed:
                continue
            candidates.append({
                "provider": provider_id,
                "model": model_id,
                "latency_ms": int(entry.get("latency_ms") or 0),
                "entry": entry,
            })
    if not candidates:
        return []
    candidates.sort(key=lambda candidate: candidate["latency_ms"])
    top = candidates[:FALLBACK_CANDIDATE_LIMIT]
    stale = [candidate for candidate in top if _health_is_stale(candidate["entry"])]
    if stale:
        _refresh_stale(db, stale)
    ranked = [candidate for candidate in top if candidate["entry"].get("ok")]
    ranked.sort(key=lambda candidate: candidate["latency_ms"])
    return [(candidate["provider"], candidate["model"]) for candidate in ranked]


def record_switch(db: Session, previous_provider: str, previous_model: str, provider: str, model: str, reason: str, job_id: str | None = None) -> None:
    """Persist a fallback as the new `explore_ai` default and log what happened.

    Only the provider/model halves of the saved preference are replaced — the reasoning
    mode and web-source limit the user picked alongside the old default survive. The switch
    record under `auto_select_last_switch` is what the Settings page reads to explain the
    change, and keeps the previous model so the user can switch back if they want.
    """
    saved = _preference_value(db, "explore_ai") or {}
    updated = dict(saved)
    updated["provider"] = provider
    updated["model"] = model
    _set_preference(db, "explore_ai", updated)
    _set_preference(db, LAST_SWITCH_PREFERENCE_KEY, {
        "previous_provider": previous_provider,
        "previous_model": previous_model,
        "provider": provider,
        "model": model,
        "reason": (reason or "")[:500],
        "job_id": job_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })


def _refresh_stale(db: Session, candidates: list[dict]) -> None:
    """Re-probe stale candidates concurrently and fold the answers into `model_health`."""
    fresh: dict[str, dict] = {}
    checked_at = datetime.now(timezone.utc).isoformat()
    with ThreadPoolExecutor(max_workers=len(candidates)) as pool:
        futures = {
            pool.submit(probe_model, candidate["provider"], candidate["model"]): candidate
            for candidate in candidates
        }
        for future, candidate in futures.items():
            try:
                result = future.result(timeout=FALLBACK_PROBE_TIMEOUT_SECONDS)
            except Exception:  # noqa: BLE001 - a timed-out probe counts as "did not answer"
                result = {"ok": False, "latency_ms": 0, "error": "Fallback probe timed out"}
            candidate["entry"].update({**result, "checked_at": checked_at})
            fresh.setdefault(candidate["provider"], {})[candidate["model"]] = candidate["entry"]
    if not fresh:
        return
    preference = db.get(UserPreference, MODEL_HEALTH_PREFERENCE_KEY)
    stored = dict(preference.value) if preference and isinstance(preference.value, dict) else {}
    for provider_id, models in fresh.items():
        provider_health = dict(stored.get(provider_id) or {})
        provider_health.update(models)
        stored[provider_id] = provider_health
    if preference:
        preference.value = stored
    else:
        db.add(UserPreference(key=MODEL_HEALTH_PREFERENCE_KEY, value=stored))
    db.commit()


def _health_is_stale(entry: dict) -> bool:
    checked_at = (entry.get("checked_at") or "").strip()
    if not checked_at:
        return True
    try:
        parsed = datetime.fromisoformat(checked_at.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return True
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - parsed > timedelta(seconds=HEALTH_STALE_SECONDS)


def _preference_value(db: Session, key: str) -> dict | None:
    preference = db.get(UserPreference, key)
    if preference and isinstance(preference.value, dict):
        return preference.value
    return None


def _set_preference(db: Session, key: str, value) -> None:
    preference = db.get(UserPreference, key)
    if preference:
        preference.value = value
    else:
        db.add(UserPreference(key=key, value=value))
    db.commit()
