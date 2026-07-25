"""LLM-based intent detection with conversation context persistence.

Architecture:
  - ONE lightweight LLM call classifies intent, normalizes language, extracts
    entities, and generates optimized search queries — for ANY domain.
  - Conversation history is passed so short follow-ups inherit the
    previous topic/location/context.
  - Keyword-based fallback if LLM call fails (zero API cost).
"""

import json
import re
from dataclasses import dataclass


# ---------------------------------------------------------------------------
# DATA CLASS
# ---------------------------------------------------------------------------

@dataclass
class QueryIntent:
    intent: str          # weather, sports, stock, currency, flight, food, health, entertainment, product, code, math, translate, news, general
    language: str        # detected input language, normalized to en for answers
    search_query: str    # Optimized English search query ready for DuckDuckGo
    original: str        # Original user question
    translated: str      # English translation (if needed)
    entities: dict       # Extracted entities (location, team, company, etc.)
    needs_web_search: bool  # Whether this query requires web search


# ---------------------------------------------------------------------------
# LLM-BASED INTENT CLASSIFIER
# ---------------------------------------------------------------------------

_INTENT_SYSTEM_PROMPT = (
    "Classify the user question into one intent: "
    "weather, sports, stock, currency, flight, food, health, entertainment, product, code, math, translate, news, general. "
    "For short follow-ups, use conversation history to inherit the previous topic. "
    "Normalize non-English or mixed-language questions into English for translated_query and search_query. "
    "Return JSON only: "
    '{"intent":"...","language":"en|other","translated_query":"english version","search_query":"optimized English search engine query","needs_web_search":true|"false","entities":{"location":"","team":"","company":"","ticker":"","currency_from":"","currency_to":"","time":""}}'
)


def classify_query_llm(question: str, history: list[tuple[str, str]] | None = None, model: str | None = None) -> QueryIntent:
    """Classify query intent using LLM. Handles ANY domain + context persistence."""
    if not model:
        from .config import configured_model
        model = configured_model()

    # Build prompt with conversation history
    history_text = ""
    if history:
        recent = history[-6:]  # Last 3 exchanges
        history_text = "Conversation so far:\n" + "\n".join(
            f"{'User' if role == 'user' else 'Assistant'}: {content[:300]}"
            for role, content in recent
        ) + "\n\n"

    user_prompt = f"{history_text}Current user question: {question}"

    try:
        from .llm import _chat
        raw = _chat(_INTENT_SYSTEM_PROMPT, user_prompt, model, temperature=0.0, max_tokens=500)
        result = _parse_json(raw)
        if result and isinstance(result, dict):
            return QueryIntent(
                intent=result.get("intent", "general"),
                language=result.get("language", "en"),
                search_query=result.get("search_query", question),
                original=question,
                translated=result.get("translated_query", question),
                entities=result.get("entities", {}),
                needs_web_search=result.get("needs_web_search", True),
            )
    except Exception:
        pass

    # Fallback: keyword-based (zero API cost)
    return _fallback_classify(question, history)


# ---------------------------------------------------------------------------
# KEYWORD FALLBACK (if LLM fails)
# ---------------------------------------------------------------------------

_FOLLOWUP_PATTERNS = re.compile(
    r"\b(kal|aaj|abhi|aur|bhi|what\s+about|how\s+about|and|then|next|previous|last|uske\s+baad)\b",
    re.IGNORECASE,
)

_SHORT_QUERY = re.compile(r"^[\w\s?]{1,15}$")


def _fallback_classify(question: str, history: list[tuple[str, str]] | None = None) -> QueryIntent:
    """Keyword-based fallback when LLM call fails. Covers ALL domains."""
    normalized = " ".join(question.lower().split())

    # Detect if this is a short follow-up
    is_followup = bool(_FOLLOWUP_PATTERNS.search(normalized)) or _SHORT_QUERY.match(normalized)

    # If follow-up and has history, inherit context
    if is_followup and history:
        last_user_msg = next(
            (content for role, content in reversed(history) if role == "user"),
            "",
        )
        last_normalized = " ".join(last_user_msg.lower().split())

        domain_keywords = {
            "weather": ("weather", "rain", "temperature", "mausam", "barish", "forecast", "cloudy", "sunny"),
            "sports": ("cricket", "football", "score", "match", "ipl", "nba", "tennis", "f1"),
            "stock": ("stock", "share", "price", "nse", "bse", "nifty", "sensex", "mutual fund"),
            "currency": ("dollar", "euro", "rupee", "usd", "eur", "inr", "exchange"),
            "flight": ("flight", "airline", "pnr", "boarding", "airport"),
            "food": ("recipe", "cook", "restaurant", "food", "biryani", "pizza", "pasta"),
            "health": ("fever", "headache", "medicine", "symptom", "treatment", "doctor"),
            "entertainment": ("movie", "netflix", "series", "concert", "anime", "song"),
            "product": ("phone", "laptop", "earbuds", "camera", "speaker", "monitor"),
            "news": ("news", "headlines", "breaking", "latest"),
        }

        for domain, keywords in domain_keywords.items():
            if any(w in last_normalized for w in keywords):
                return _build_inherited_intent(question, last_normalized, domain, "en")

    # Direct keyword matching — ALL domains (order matters: most specific first)
    # Build combined keyword lists
    _weather_kw = ("weather", "rain", "raining", "temperature", "temperatur", "forecast", "cloudy", "sunny", "humidity", "storm", "drizzle", "fog", "mausam", "barish", "barsaat", "tapman", "garmi", "thand", "sardi", "toofan", "aandhi", "kohra", "dhund", "pani")
    _food_kw = ("recipe", "cook", "cooking", "restaurant", "food", "pizza", "pasta", "ingredient", "cuisine", "diet", "vegan", "vegetarian", "dinner", "lunch", "breakfast", "snack", "dessert", "cake", "burger", "biryani", "pakwan", "khaana", "khana")
    _health_kw = ("fever", "headache", "medicine", "symptom", "treatment", "diabetes", "blood pressure", "yoga", "exercise", "workout", "fitness", "pain", "infection", "allergy", "bukhar", "khasi", "dard", "bimari", "dawa", "ilaj")
    _entertainment_kw = ("movie", "netflix", "series", "concert", "anime", "song", "film", "cinema", "album", "podcast", "spotify", "hotstar", "disney")
    _code_kw = ("code", "function", "class", "api", "debug", "script", "program", "syntax", "database", "sql", "git", "docker", "tutorial", "python", "javascript", "java", "typescript", "fastapi", "django", "flask", "react", "node")
    _math_kw = ("calculate", "compute", "formula", "equation", "solve", "square root", "integral", "derivative", "probability", "statistics", "percentage")
    _sports_kw = ("cricket", "football", "score", "match", "ipl", "nba", "tennis", "f1", "formula 1", "soccer", "hockey", "olympics", "world cup", "championship", "standings")
    _stock_kw = ("stock", "share", "nse", "bse", "sensex", "nifty", "mutual fund", "dividend", "trading", "portfolio", "investment", "invest", "bazaar", "bhav", "kimat", "nivesh", "reliance", "tcs", "infosys", "hdfc", "icici", "sbi", "wipro", "itc", "tata", "adani", "bajaj")
    _currency_kw = ("dollar", "euro", "rupee", "usd", "eur", "inr", "gbp", "yen", "exchange rate", "currency", "convert", "rupaye")
    _flight_kw = ("flight", "airline", "pnr", "boarding", "airport", "departure", "arrival")
    _news_kw = ("news", "headlines", "breaking", "latest")
    _product_kw = ("phone", "laptop", "earbuds", "camera", "speaker", "monitor", "tablet", "headphones")

    all_kw = [
        ("weather", _weather_kw), ("food", _food_kw), ("health", _health_kw),
        ("entertainment", _entertainment_kw), ("code", _code_kw), ("math", _math_kw),
        ("sports", _sports_kw), ("stock", _stock_kw), ("currency", _currency_kw),
        ("flight", _flight_kw), ("news", _news_kw), ("product", _product_kw),
    ]
    for domain, keywords in all_kw:
        if any(re.search(rf"\b{re.escape(kw)}\b", normalized) for kw in keywords):
            query_map = {
                "weather": f"{question} weather forecast temperature",
                "food": f"{question} recipe easy quick",
                "health": f"{question} symptoms treatment medicine",
                "entertainment": f"{question} watch stream online",
                "code": f"{question} code tutorial documentation",
                "math": f"{question} calculation formula",
                "sports": f"{question} live score result today",
                "stock": f"{question} stock price today NSE BSE",
                "currency": f"{question} exchange rate today",
                "flight": f"{question} flight status today",
                "news": f"{question} latest news today",
                "product": f"{question} best price comparison India",
            }
            return QueryIntent(domain, "en", query_map[domain], question, question, {}, True)

    return QueryIntent("general", "en", question, question, question, {}, True)


def _build_inherited_intent(question: str, previous_context: str, intent: str, language: str) -> QueryIntent:
    """Build intent for a follow-up by inheriting context from previous query."""
    # Combine previous context with current question for search
    search_query = f"{previous_context} {question} latest"

    # Extract location from previous context if present
    location_match = re.search(r"\bin\s+([A-Za-z]+)", previous_context)
    location = location_match.group(1) if location_match else ""

    entities = {}
    if location:
        entities["location"] = location

    return QueryIntent(
        intent=intent,
        language=language,
        search_query=search_query,
        original=question,
        translated=question,
        entities=entities,
        needs_web_search=True,
    )


# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------

def _parse_json(text: str) -> dict | None:
    """Extract JSON from LLM response, handling markdown code blocks."""
    # Try to find JSON object
    match = re.search(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except (json.JSONDecodeError, ValueError):
            pass
    # Try parsing the whole text
    try:
        return json.loads(text.strip())
    except (json.JSONDecodeError, ValueError):
        pass
    return None


# ---------------------------------------------------------------------------
# PUBLIC API — called by web_research.py
# ---------------------------------------------------------------------------

def classify_and_enhance(question: str, history: list[tuple[str, str]] | None = None, model: str | None = None) -> tuple[QueryIntent, str]:
    """Classify intent (LLM-based) and return enhanced search query.

    Args:
        question: User's question
        history: Conversation history [(role, content), ...]
        model: LLM model to use for classification

    Returns:
        (QueryIntent, enhanced_search_query)
    """
    intent = classify_query_llm(question, history=history, model=model)
    return intent, intent.search_query


def validate_search_output(intent: QueryIntent, search_results: list[dict]):
    """Validate that search results match the detected intent."""
    from dataclasses import dataclass as _dc

    @_dc
    class OutputValidation:
        valid: bool
        reason: str
        suggestion: str = ""

    if not search_results:
        return OutputValidation(False, "no search results returned")

    # Domain-specific validation
    validators = {
        "weather": _validate_weather,
        "sports": _validate_sports,
        "stock": _validate_stock,
        "currency": _validate_currency,
        "flight": _validate_flight,
    }
    validator = validators.get(intent.intent)
    if validator:
        return validator(search_results)
    return OutputValidation(True, "no specific validation")


def _validate_weather(results):
    from dataclasses import dataclass as _dc
    @_dc
    class V:
        valid: bool; reason: str; suggestion: str = ""
    weather_words = {"weather", "forecast", "temperature", "rain", "sunny", "cloudy", "humidity", "celsius", "fahrenheit", "accuweather", "windy"}
    shayari_words = {"shayari", "poetry", "poem", "ghazal", "sher", "premiyo", "intzaar", "yaadon", "dil", "pyaar", "ishq"}
    w_count = sum(1 for r in results if any(w in f"{r.get('title','')} {r.get('snippet','')}".lower() for w in weather_words))
    s_count = sum(1 for r in results if any(w in f"{r.get('title','')} {r.get('snippet','')}".lower() for w in shayari_words))
    if w_count == 0 and len(results) > 0:
        return V(False, f"no weather data found in {len(results)} results — likely poetry/shayari")
    return V(True, "weather results look relevant")


def _validate_sports(results):
    from dataclasses import dataclass as _dc
    @_dc
    class V:
        valid: bool; reason: str; suggestion: str = ""
    sports_words = {"score", "live", "match", "result", "innings", "goal", "wicket", "espn", "cricbuzz", "flashscore"}
    count = sum(1 for r in results if any(w in f"{r.get('title','')} {r.get('snippet','')}".lower() for w in sports_words))
    if count == 0 and len(results) > 0:
        return V(False, "no sports data found in search results")
    return V(True, "sports results look relevant")


def _validate_stock(results):
    from dataclasses import dataclass as _dc
    @_dc
    class V:
        valid: bool; reason: str; suggestion: str = ""
    stock_words = {"stock", "share", "price", "nse", "bse", "sensex", "nifty", "moneycontrol", "trading"}
    count = sum(1 for r in results if any(w in f"{r.get('title','')} {r.get('snippet','')}".lower() for w in stock_words))
    if count == 0 and len(results) > 0:
        return V(False, "no stock data found in search results")
    return V(True, "stock results look relevant")


def _validate_currency(results):
    from dataclasses import dataclass as _dc
    @_dc
    class V:
        valid: bool; reason: str; suggestion: str = ""
    currency_words = {"exchange", "rate", "currency", "convert", "usd", "eur", "gbp", "inr", "dollar", "xe.com"}
    count = sum(1 for r in results if any(w in f"{r.get('title','')} {r.get('snippet','')}".lower() for w in currency_words))
    if count == 0 and len(results) > 0:
        return V(False, "no currency data found in search results")
    return V(True, "currency results look relevant")


def _validate_flight(results):
    from dataclasses import dataclass as _dc
    @_dc
    class V:
        valid: bool; reason: str; suggestion: str = ""
    flight_words = {"flight", "airline", "status", "departure", "arrival", "delayed", "flightradar"}
    count = sum(1 for r in results if any(w in f"{r.get('title','')} {r.get('snippet','')}".lower() for w in flight_words))
    if count == 0 and len(results) > 0:
        return V(False, "no flight data found in search results")
    return V(True, "flight results look relevant")
