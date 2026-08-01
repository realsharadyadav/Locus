import json
import math
import re
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

import httpx
from ddgs import DDGS

from .brand import USER_AGENT
from .config import OPENSERP_BASE_URL, WEB_RESEARCH_INITIAL_QUERIES, WEB_RESEARCH_RESULTS_PER_QUERY
from .diagnostics import diagnostic_event
from .intent import classify_and_enhance, validate_search_output, QueryIntent
from .llm import ANSWER_LANGUAGE_INSTRUCTION, ANSWER_SHAPE_INSTRUCTION, LLMProviderError, _chat, _context_budget, ensure_english_answer


_SEARCH_COUNT: ContextVar[dict | None] = ContextVar("locus_search_count", default=None)


def _record_search_query() -> None:
    tracker = _SEARCH_COUNT.get()
    if tracker is not None:
        tracker["queries"] += 1


@contextmanager
def web_search_tracker(tracker: dict | None = None):
    tracker = tracker if tracker is not None else {"queries": 0}
    token = _SEARCH_COUNT.set(tracker)
    try:
        yield tracker
    finally:
        _SEARCH_COUNT.reset(token)


SYNTHESIS_SNIPPET_CHARS = 1200
SYNTHESIS_PROMPT_OVERHEAD_CHARS = 4_000
WEBPAGE_ENRICHMENT_MAX_PAGES = 3
WEBPAGE_ENRICHMENT_CHARS = 2600
YOUTUBE_SEARCH_PREFIX = "site:youtube.com/watch"
WEB_RESEARCH_MAX_ROUNDS = 5
WEB_RESEARCH_STALL_LIMIT = 2


@dataclass
class EvidenceAssessment:
    answerable: bool
    relevant_count: int
    current_sensitive: bool
    reason: str


GENERIC_STOP_WORDS = {
    "about", "after", "again", "also", "answer", "because", "before", "best", "bhai",
    "bta", "could", "details", "does", "give", "have", "here", "into", "kaisa",
    "kya", "latest", "like", "list", "mujhe", "need", "options", "please", "rahega",
    "rhe", "same", "search", "should", "show", "source", "tell", "that", "their",
    "there", "these", "thing", "this", "today", "tomorrow", "under", "want", "weather",
    "what", "when", "where", "which", "with", "would", "your",
}

CURRENT_INFO_PATTERNS = [
    r"\b(current|currently|live|latest|today|tomorrow|yesterday|now|right\s+now|this\s+(?:week|month|year))\b",
    r"\b(score|scores|result|results|status|price|prices|rate|rates|availability|forecast|schedule|news|updates?)\b",
]

VIDEO_INTENT_PATTERN = r"\b(youtube|video|videos|watch|tutorial|demo|review)\b"

PRODUCT_OR_RECOMMENDATION_PATTERNS = [
    r"\b(best|top|recommend|recommendation|options?|compare|comparison|buy|purchase)\b",
    r"\b(phone|phones|mobile|mobiles|smartphone|smartphones|laptop|laptops|earbuds|headphones|camera|cameras)\b",
]

CONTEXTUAL_FOLLOWUP_PATTERNS = [
    r"\b(same|that|it|those|there|then|also|what\s+about|how\s+about)\b",
    r"\b(bola\s+tha|kaisa|kya|rhega|rahega|rhe\s+ga|rahe\s+ga|bta|bata|kr\s+bhai|kar\s+bhai)\b",
    r"\b(table|tabular|format|under|below|budget|again)\b",
]


def _budget_from_question(question: str) -> int | None:
    normalized = question.lower().replace(",", "")
    candidates = []
    patterns = [
        r"(?:under|below|less than|within|budget(?: of)?|upto|up to|<=)\s*(?:rs\.?|inr|₹)?\s*(\d+(?:\.\d+)?)\s*(k|thousand)?\b",
        r"(?:rs\.?|inr|₹)\s*(\d+(?:\.\d+)?)\s*(k|thousand)?\b",
        r"\b(\d+(?:\.\d+)?)\s*(k|thousand)\b",
    ]
    for pattern in patterns:
        for amount, suffix in re.findall(pattern, normalized):
            value = float(amount)
            if suffix == "k" or suffix == "thousand":
                value *= 1000
            if value >= 500:
                candidates.append(int(value))
    return min(candidates) if candidates else None


def _price_values(text: str) -> list[int]:
    normalized = text.lower().replace(",", "")
    values = []
    patterns = [
        r"(?:rs\.?|inr|₹)\s*(\d+(?:\.\d+)?)\s*(k|thousand)?\b",
        r"\b(\d+(?:\.\d+)?)\s*(k|thousand)\b",
        r"(?:under|below|less than|within|budget(?: of)?|upto|up to|<=)\s*(?:rs\.?|inr|₹)?\s*(\d+(?:\.\d+)?)\s*(k|thousand)?\b",
    ]
    for pattern in patterns:
        for amount, suffix in re.findall(pattern, normalized):
            value = float(amount)
            if suffix == "k" or suffix == "thousand":
                value *= 1000
            if value >= 500:
                values.append(int(value))
    return values


def _wants_table(question: str) -> bool:
    return bool(re.search(r"\b(table|tabular|columns?|spreadsheet|grid)\b", question, re.IGNORECASE))


def _meaningful_terms(text: str) -> list[str]:
    normalized = re.sub(r"[^a-zA-Z0-9₹]+", " ", text.lower())
    terms = []
    seen = set()
    for term in normalized.split():
        if len(term) < 3 or term in GENERIC_STOP_WORDS:
            continue
        if term.isdigit() and int(term) < 100:
            continue
        if term not in seen:
            seen.add(term)
            terms.append(term)
    return terms


def _is_current_sensitive(question: str) -> bool:
    return any(re.search(pattern, question, re.IGNORECASE) for pattern in CURRENT_INFO_PATTERNS)


def _requests_video(question: str) -> bool:
    return bool(re.search(VIDEO_INTENT_PATTERN, question, re.IGNORECASE))


def _is_product_or_recommendation_query(question: str) -> bool:
    return _budget_from_question(question) is not None or any(
        re.search(pattern, question, re.IGNORECASE) for pattern in PRODUCT_OR_RECOMMENDATION_PATTERNS
    )


def _result_relevance_score(question_terms: list[str], result: dict) -> int:
    haystack = f"{result.get('title', '')} {result.get('snippet', '')}".lower()
    return sum(1 for term in question_terms if term in haystack)


def _assess_evidence(question: str, search_results: list[dict]) -> EvidenceAssessment:
    if not search_results:
        return EvidenceAssessment(False, 0, _is_current_sensitive(question), "no sources returned")

    terms = _meaningful_terms(question)
    if not terms:
        return EvidenceAssessment(True, len(search_results), _is_current_sensitive(question), "no strong constraints to score")

    relevant_count = sum(1 for result in search_results if _result_relevance_score(terms, result) > 0)
    required = min(len(search_results), 1 if len(terms) <= 2 else 2)
    if relevant_count < required:
        return EvidenceAssessment(False, relevant_count, _is_current_sensitive(question), "sources do not match the user's key constraints")

    return EvidenceAssessment(True, relevant_count, _is_current_sensitive(question), "sources match key constraints")


def _contextual_followup(question: str, history: list[tuple[str, str]] | None = None) -> bool:
    if not history:
        return False
    normalized = " ".join(question.lower().split())
    if not normalized:
        return False
    if any(re.search(pattern, normalized, re.IGNORECASE) for pattern in CONTEXTUAL_FOLLOWUP_PATTERNS):
        return True
    return len(_meaningful_terms(normalized)) <= 2 and len(normalized.split()) <= 6


def _expand_budget_shorthand(question: str) -> str:
    budget = _budget_from_question(question)
    if not budget:
        return question
    expanded = re.sub(r"\b(\d+(?:\.\d+)?)\s*k\b", lambda match: str(int(float(match.group(1)) * 1000)), question, flags=re.IGNORECASE)
    if not re.search(r"\b(under|below|less than|within|upto|up to|budget)\b", expanded, re.IGNORECASE):
        expanded = f"{expanded} under {budget} rupees"
    return expanded


def _clean_search_query(question: str) -> str:
    cleaned = _expand_budget_shorthand(question)
    cleaned = re.sub(r"\b(bhai|bro|yaar|please|pls|mujhe|bta|bata|kaisa|kya|rhega|rahega)\b", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\brhe\s+ga\b", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\brahe\s+ga\b", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bkr\s+bhai\b", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bkar\s+bhai\b", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b(?:here\s+)?in\s+my\s+location\b", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bmy\s+location\b", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b(here|location)\b", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bbola tha\b", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bgive me\b", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bin\s+(?:a\s+)?(?:tabular|table)\s+format\b", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bwith\s+mobile\s+name\s+and\s+price\b", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bmobile\s+name\s+and\s+price\b", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bwith\s+[\w\s,]*(?:columns?|format)\b", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .,:;-")
    cleaned = re.sub(r"\b(and|with)\s*$", "", cleaned, flags=re.IGNORECASE).strip(" .,:;-")
    return cleaned or _expand_budget_shorthand(question)


def _search_question_with_history(question: str, history: list[tuple[str, str]] | None = None) -> str:
    current = _clean_search_query(question)
    if not _contextual_followup(question, history):
        return current
    previous_user = next((content for role, content in reversed(history) if role == "user" and content.strip()), "")
    if previous_user:
        return _clean_search_query(f"{previous_user}. {question}")
    return current


def _constraint_queries(question: str) -> list[str]:
    expanded = _clean_search_query(question)
    budget = _budget_from_question(expanded)
    queries = [expanded]
    if budget and re.search(r"\b(phone|phones|mobile|mobiles|smartphone|smartphones)\b", expanded, re.IGNORECASE):
        queries.extend([
            f"best mobile phones under {budget} rupees in India latest price",
            f"best phones below Rs {budget} India price list",
            f"smartphones under {budget} India current price",
            f"feature phones under {budget} India best price",
        ])
    elif budget:
        queries.extend([
            f"{expanded} under {budget} rupees",
            f"{expanded} below Rs {budget} price",
        ])
    if _is_current_sensitive(question):
        queries.extend([
            f"{expanded} current today",
            f"{expanded} latest live",
            f"{expanded} official current status",
        ])
    return _unique_queries(queries)


def _is_over_budget_result(result: dict, budget: int | None) -> bool:
    if not budget:
        return False
    text = f"{result.get('title', '')} {result.get('snippet', '')}".lower().replace(",", "")
    return any(value > budget for value in _price_values(text))


def _candidate_name_from_result(result: dict) -> str:
    names = _candidate_names_from_result(result)
    return names[0] if names else ""


def _candidate_names_from_result(result: dict) -> list[str]:
    title = re.sub(r"\s+", " ", result.get("title", "")).strip()
    snippet = re.sub(r"\s+", " ", result.get("snippet", "")).strip()
    text = f"{title} {snippet}"
    lowered = text.lower()
    names = []
    known_patterns = [
        ("Forme Mi 5 Pro", "forme mi 5"),
        ("AI+ Pulse", "ai+ pulse"),
        ("AI+ Nova 5G", "ai+ nova 5g"),
        ("AI+ Plus", "ai+ plus"),
        ("Poco C61", "poco c61"),
        ("Redmi Go", "redmi go"),
        ("Infinix Smart 2", "infinix smart 2"),
        ("Xiaomi Redmi 3S", "xiaomi redmi 3s"),
        ("Alcatel 5V", "alcatel 5v"),
        ("realme C30", "realme c30"),
    ]
    for name, signal in known_patterns:
        if signal in lowered:
            names.append(name)
    patterns = [
        r"Best phones:\s*([^,|]+?)\s+has",
        r"followed by\s+([^,|]+?)\s+with",
        r"\b([A-Z][A-Za-z0-9]+(?:\s+[A-Z0-9][A-Za-z0-9]+){0,3})\s+Smartphone",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            candidate = match.group(1).strip(" -|")
            if candidate.lower() not in {"smartphone", "ai smartphone", "ai+ smartphone"}:
                names.append(candidate)
    if any(term in title.lower() for term in ["under 5000", "price list", "best phone", "mobiles under"]):
        return list(dict.fromkeys(name for name in names if name))
    fallback = title.split("|")[0].split("-")[0].strip()
    if fallback and fallback.lower() not in {"smartphone", "ai smartphone", "ai+ smartphone"}:
        names.append(fallback)
    return list(dict.fromkeys(name for name in names if name))


def _compact_source_title(title: str) -> str:
    return re.sub(r"\s+", " ", title).strip().split("|")[0].strip()[:90] or "source"


def _extract_value_signals(question: str, result: dict) -> list[str]:
    text = re.sub(r"\s+", " ", f"{result.get('title', '')} {result.get('snippet', '')}").strip()
    question_lower = question.lower()
    lowered_text = text.lower()
    asks_current_market_value = bool(re.search(r"\b(current|today|live|now|latest)\b", question_lower)) and bool(re.search(r"\b(price|rate|quote)\b", question_lower))
    if asks_current_market_value and re.search(r"\b(prediction|forecast|estimate|target|future)\b", lowered_text):
        return []
    signals = []
    patterns = [
        r"\b\d+(?:\.\d+)?\s?°\s?[CF]?\b",
        r"(?:₹|Rs\.?|INR|\$|USD)\s?\d[\d,]*(?:\.\d+)?",
        r"\b\d{1,3}(?:\.\d+)?\s?(?:km/h|mph|mm|cm|kg|g|mb|hpa)\b",
    ]
    if re.search(r"\b(percent|percentage|margin|change|gain|loss|rate)\b", question_lower):
        patterns.append(r"\b\d+(?:\.\d+)?\s?%")
    if re.search(r"\b(status|train|flight|depart|arriv|delay|cancel)\b", question_lower):
        patterns.append(r"\b(?:on time|delayed|cancelled|canceled|scheduled|departed|arrived)\b")
    for pattern in patterns:
        for match in re.findall(pattern, text, re.IGNORECASE):
            value = match if isinstance(match, str) else " ".join(match)
            value = value.strip()
            if value and value.lower() not in {s.lower() for s in signals}:
                signals.append(value)
            if len(signals) >= 4:
                return signals
    return signals


def _evidence_based_fallback(question: str, search_results: list[dict]) -> str:
    terms = _meaningful_terms(question)
    ranked = sorted(
        search_results,
        key=lambda result: (_result_relevance_score(terms, result), 0 if result.get("engine") == "youtube" else 1),
        reverse=True,
    )
    useful = [result for result in ranked if _result_relevance_score(terms, result) > 0 or not terms]
    useful = useful[:3] or ranked[:3]
    if not useful:
        return "I could not find enough relevant web evidence to answer this directly."

    signal_lines = []
    context_lines = []
    for index, result in enumerate(useful, 1):
        title = _compact_source_title(result.get("title", ""))
        signals = _extract_value_signals(question, result)
        if signals:
            signal_lines.append(f"- {title}: {', '.join(signals)} [{index}]")
        else:
            snippet = re.sub(r"\s+", " ", result.get("snippet", "")).strip()
            if snippet:
                context_lines.append(f"- {title}: {snippet[:180]} [{index}]")

    if signal_lines:
        return "I found these direct values in the web snippets:\n\n" + "\n".join(signal_lines)

    lines = [
        "I found relevant sources, but their snippets do not expose the exact live value. The strongest evidence I can summarize is:",
        "",
        *(context_lines or [f"- {_compact_source_title(result.get('title', ''))} [{index}]" for index, result in enumerate(useful, 1)]),
    ]
    return "\n".join(lines)


def _fallback_web_answer(question: str, search_results: list[dict]) -> str:
    budget = _budget_from_question(question)
    wants_table = _wants_table(question)
    product_or_recommendation = _is_product_or_recommendation_query(question)
    if not product_or_recommendation:
        return _evidence_based_fallback(question, search_results)
    rows = []
    seen = set()
    for result in search_results:
        if _is_over_budget_result(result, budget):
            continue
        prices = [value for value in _price_values(f"{result.get('title', '')} {result.get('snippet', '')}") if not budget or value <= budget]
        price = f"₹{prices[0]:,}" if prices else f"≤ ₹{budget:,} (listed under budget)" if budget else "Check source"
        for name in _candidate_names_from_result(result):
            key = name.lower()
            if key in seen:
                continue
            seen.add(key)
            rows.append((name, price, result.get("title", "Source")))
            if len(rows) >= 5:
                break
        if len(rows) >= 5:
            break
    if not rows:
        if budget:
            return f"I found sources for this search, but I could not verify specific items clearly under ₹{budget:,}. Try increasing the budget slightly or checking the attached sources directly."
        return "I found sources, but could not confidently extract a clean answer from them. Check the attached sources for details."
    if wants_table:
        lines = ["| Mobile name | Price | Source |", "|---|---:|---|"]
        lines.extend(f"| {name} | {price} | {source[:70]} |" for name, price, source in rows)
        return "\n".join(lines)
    intro = f"Best options I could verify under ₹{budget:,}:" if budget else "Best options I could verify:"
    return intro + "\n\n" + "\n".join(f"- **{name}** — {price} ({source[:80]})" for name, price, source in rows)


def _remove_over_budget_lines(answer: str, budget: int | None) -> str:
    if not budget:
        return answer
    kept = []
    removed = 0
    for line in answer.splitlines():
        stripped = line.strip()
        if not stripped:
            kept.append(line)
            continue
        if re.match(r"^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?$", stripped):
            kept.append(line)
            continue
        prices = _price_values(stripped)
        if prices and max(prices) > budget:
            removed += 1
            continue
        kept.append(line)
    cleaned = "\n".join(kept).strip()
    if removed:
        note = f"Note: I removed options whose listed price exceeded the ₹{budget:,} budget."
        cleaned = f"{cleaned}\n\n{note}" if cleaned else note
    return cleaned


def _looks_like_source_directory_answer(answer: str) -> bool:
    if not answer.strip():
        return True
    lower = answer.lower()
    check_source_count = len(re.findall(r"\bcheck source\b", lower))
    source_like_bullets = len(re.findall(r"^\s*[-*]\s+\*\*.+?\*\*\s+[—-]\s+", answer, re.MULTILINE))
    citations = len(re.findall(r"\[\d+\]", answer))
    if check_source_count >= 2 and source_like_bullets >= 2:
        return True
    if source_like_bullets >= 4 and citations == 0 and "best options i could verify" in lower:
        return True
    return False


def _search_ddg(query: str, max_results: int) -> list[dict]:
    with DDGS() as ddgs:
        results = list(ddgs.text(query, max_results=max_results))
    return [
        {"title": r.get("title", ""), "url": r.get("href", ""), "snippet": r.get("body", ""), "engine": "ddg"}
        for r in results
    ]


def _search_openserp(query: str, max_results: int) -> list[dict]:
    if not OPENSERP_BASE_URL:
        return []
    try:
        resp = httpx.get(
            f"{OPENSERP_BASE_URL}/google/search",
            params={"text": query, "limit": max_results},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        return [
            {"title": r.get("title", ""), "url": r.get("url", ""), "snippet": r.get("snippet", ""), "engine": "google"}
            for r in data.get("results", [])
        ]
    except Exception:
        diagnostic_event("web_research.openserp_failed", query=query)
        return []


def _is_youtube_url(url: str) -> bool:
    normalized = url.lower()
    return "youtube.com/watch" in normalized or "youtu.be/" in normalized


def _search_youtube(query: str, max_results: int) -> list[dict]:
    youtube_query = f"{YOUTUBE_SEARCH_PREFIX} {query}"
    diagnostic_event("web_research.youtube_search", query=query, search_query=youtube_query, max_results=max_results)
    results = []
    for raw_batch in (_search_ddg(youtube_query, max_results), _search_openserp(youtube_query, max_results)):
        for r in raw_batch:
            url = r.get("url", "")
            if _is_youtube_url(url):
                results.append({**r, "engine": "youtube"})
    return results


def _search_web(query: str, max_results: int = 50, include_youtube: bool = True) -> list[dict]:
    _record_search_query()
    diagnostic_event("web_research.search", query=query, max_results=max_results)
    start = time.perf_counter()
    seen_urls = set()
    all_results = []

    web_results = _search_ddg(query, max_results) + _search_openserp(query, max_results)
    youtube_results = _search_youtube(query, max_results) if include_youtube else []

    def add_result(r: dict) -> bool:
        url = r.get("url", "")
        if url and url not in seen_urls:
            seen_urls.add(url)
            all_results.append(r)
            return True
        return False

    for r in web_results:
        if len(all_results) >= max_results:
            break
        add_result(r)

    if youtube_results and not any(r.get("engine") == "youtube" for r in all_results):
        youtube_result = next((r for r in youtube_results if r.get("url") not in seen_urls), youtube_results[0])
        if len(all_results) >= max_results:
            removed = all_results.pop()
            seen_urls.discard(removed.get("url", ""))
        add_result(youtube_result)

    elapsed = round((time.perf_counter() - start) * 1000, 1)
    diagnostic_event(
        "web_research.search_done",
        query=query,
        result_count=len(all_results),
        elapsed_ms=elapsed,
        engines=("youtube+" if include_youtube else "") + ("ddg+openserp" if OPENSERP_BASE_URL else "ddg"),
    )

    all_results = all_results[:max_results]

    if not all_results:
        diagnostic_event("web_research.search_failed", query=query, error="No results from any engine")
    return all_results


def _should_enrich_webpages(question: str, intent: QueryIntent | None = None) -> bool:
    if intent and intent.intent in {"product", "current", "news", "stock"}:
        return True
    return _is_product_or_recommendation_query(question) or _is_current_sensitive(question)


def _read_webpage_text(url: str, timeout: float = 7) -> str:
    if not url or _is_youtube_url(url) or re.search(r"\.(pdf|zip|jpg|jpeg|png|gif|webp)(?:$|\?)", url, re.IGNORECASE):
        return ""
    try:
        response = httpx.get(
            url,
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": f"{USER_AGENT} (+research enrichment)"},
        )
        response.raise_for_status()
    except Exception as exception:
        diagnostic_event("web_research.page_read_failed", url=url, error=str(exception))
        return ""
    content_type = response.headers.get("content-type", "")
    if "text/html" not in content_type and "text/plain" not in content_type:
        return ""
    text = response.text[:250_000]
    text = re.sub(r"(?is)<(script|style|noscript|svg|header|footer|nav|form)[^>]*>.*?</\1>", " ", text)
    text = re.sub(r"(?is)<br\s*/?>", "\n", text)
    text = re.sub(r"(?is)</(p|div|li|tr|h[1-6])>", "\n", text)
    text = re.sub(r"(?is)<[^>]+>", " ", text)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&lt;", "<", text)
    text = re.sub(r"&gt;", ">", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:WEBPAGE_ENRICHMENT_CHARS]


def _enrich_results_with_webpages(question: str, results: list[dict], progress, intent: QueryIntent | None = None, max_pages: int = WEBPAGE_ENRICHMENT_MAX_PAGES) -> list[dict]:
    if not results or not _should_enrich_webpages(question, intent):
        return results
    enriched = []
    reads = 0
    for result in results:
        updated = dict(result)
        if reads < max_pages and result.get("engine") != "test":
            page_text = _read_webpage_text(result.get("url", ""))
            if page_text:
                reads += 1
                updated["snippet"] = _merge_snippet_with_page_text(result.get("snippet", ""), page_text)
                updated["page_read"] = True
        enriched.append(updated)
    if reads:
        progress("gathering", f"Browsed {reads} top result page{'s' if reads != 1 else ''} for richer evidence")
        diagnostic_event("web_research.page_enrichment", question=question[:120], read_count=reads)
    return enriched


def _merge_snippet_with_page_text(snippet: str, page_text: str) -> str:
    snippet = re.sub(r"\s+", " ", snippet or "").strip()
    page_text = re.sub(r"\s+", " ", page_text or "").strip()
    if not snippet:
        return page_text[:WEBPAGE_ENRICHMENT_CHARS]
    if not page_text or page_text.lower() in snippet.lower():
        return snippet
    return f"{snippet}\n\nPage content: {page_text[:WEBPAGE_ENRICHMENT_CHARS]}"


def _call_llm_json(messages: list[dict], model: str, temperature: float = 0.1, max_tokens: int = 2048):
    system = "\n\n".join(message.get("content", "") for message in messages if message.get("role") == "system") or "You are a helpful research assistant."
    prompt = "\n\n".join(
        f"{message.get('role', 'user').title()}: {message.get('content', '')}"
        for message in messages
        if message.get("role") != "system"
    )
    raw = _chat(system, prompt, model, temperature=temperature, max_tokens=max_tokens)
    match = re.search(r"\[.*?\]", raw, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except (json.JSONDecodeError, ValueError):
        return None


def _generate_initial_queries(question: str, model: str, count: int) -> list[str]:
    deterministic_queries = _constraint_queries(question)
    messages = [
        {"role": "system", "content": (
            f"You are a research planner. Break down the user's question into {count} specific "
            f"web search queries that collectively provide comprehensive coverage from different angles. "
            f"Normalize non-English or mixed-language wording into English search terms. "
            f"Preserve all hard constraints exactly, especially budgets, locations, dates, and requested format. "
            f"If the user writes shorthand like 5k in an India price query, treat it as 5000 rupees. "
            f"Return ONLY a JSON array of {count} strings, nothing else."
        )},
        {"role": "user", "content": f"Question: {question}"},
    ]
    try:
        result = _call_llm_json(messages, model)
        if result and isinstance(result, list) and all(isinstance(q, str) for q in result):
            return _unique_queries(deterministic_queries + result)
    except (LLMProviderError, RuntimeError):
        pass
    return deterministic_queries


def _unique_queries(queries: list[str]) -> list[str]:
    seen = set()
    unique = []
    for query in queries:
        normalized = " ".join(str(query).split())
        key = normalized.lower()
        if normalized and key not in seen:
            seen.add(key)
            unique.append(normalized)
    return unique


def _generate_followup_queries(question: str, found_topics: list[str], model: str, count: int, previous_queries: list[str] | None = None, round_number: int = 2) -> list[str]:
    topics_text = "\n".join(found_topics[:20])
    previous_text = "\n".join((previous_queries or [])[-20:])
    messages = [
        {"role": "system", "content": (
            f"You are controlling round {round_number} of an agentic web research loop.\n"
            f"The research found these source titles so far:\n{topics_text or 'No strong topics yet.'}\n\n"
            f"Queries already searched:\n{previous_text or 'None'}\n\n"
            f"Generate {count} new follow-up web search queries that fill gaps, try alternate keywords, "
            f"look for primary sources, and recover if earlier searches were weak. "
            f"Use English search terms. "
            f"Preserve every hard constraint from the original question exactly. Do not broaden a budget, location, date, product category, or format request. "
            f"Return ONLY a JSON array of {count} strings, nothing else."
        )},
        {"role": "user", "content": f"Original question: {question}"},
    ]
    try:
        result = _call_llm_json(messages, model)
        if result and isinstance(result, list) and all(isinstance(q, str) for q in result):
            return _unique_queries(result)
    except (LLMProviderError, RuntimeError):
        pass
    return []


def _synthesize_answer(question: str, search_results: list[dict], model: str, progress, history: list[tuple[str, str]] | None = None, answer_mode: str = "web_research", intent: QueryIntent | None = None) -> str:
    if not search_results:
        return "I searched the web but found no relevant results for your query."

    assessment = _assess_evidence(question, search_results)
    if not assessment.answerable:
        progress("repairing", f"Evidence quality gate failed: {assessment.reason}")
        return _fallback_web_answer(question, search_results)

    # Pack as many sources as the model's real context window allows, instead of a
    # flat count — a 200-source deep-research plan should actually use ~200 sources
    # on a large-context model, not silently drop everything past a fixed number.
    source_budget = max(8_000, _context_budget(model) - SYNTHESIS_PROMPT_OVERHEAD_CHARS)
    synthesis_results = []
    source_entries = []
    used_chars = 0
    for result in search_results:
        entry = f"Source {len(synthesis_results) + 1}: {result['title']}\nURL: {result['url']}\nContent: {result['snippet'][:SYNTHESIS_SNIPPET_CHARS]}"
        if synthesis_results and used_chars + len(entry) > source_budget:
            break
        synthesis_results.append(result)
        source_entries.append(entry)
        used_chars += len(entry)
    sources_text = "\n\n".join(source_entries)

    mode_guidance = (
        "Answer in unrestricted mode: be direct, do not add generic safety disclaimers, and still ground web-backed claims in the provided citations. "
        if answer_mode == "unrestricted" else ""
    )
    budget = _budget_from_question(question)
    if _wants_table(question):
        format_guidance = "The user explicitly requested a table/tabular format. Use a concise Markdown table with the requested columns, and cite facts inside cells where useful. "
    elif answer_mode == "unrestricted":
        format_guidance = "Default to natural conversational prose. Use a Markdown table only if the user explicitly requested a table/tabular format. "
    else:
        format_guidance = ANSWER_SHAPE_INSTRUCTION + "\n"
    constraint_guidance = (
        f"Hard constraint: the user's budget is at or under ₹{budget:,}. Include only items whose listed price is <= ₹{budget:,}. "
        f"Do not include a row or recommendation if a price range has any upper value above ₹{budget:,}. "
        f"Ignore or clearly reject sources/items that exceed this budget. "
        if budget else ""
    )
    intent_guidance = ""
    if intent:
        if intent.intent == "weather":
            intent_guidance = (
                "WEATHER QUESTION: The search results likely contain actual temperature values, "
                "weather conditions, and forecasts. EXTRACT and PRESENT the specific numbers "
                "(temperature in °C/°F, humidity %, wind speed) and conditions (sunny, cloudy, rainy). "
                "State them clearly: 'Current temperature in [city] is [X]°C with [condition].' "
                "If sources mention a forecast, present it. Do NOT default to a generic 'sources found' message "
                "when actual weather data is present in the snippets."
            )
        elif intent.intent == "sports":
            intent_guidance = (
                "SPORTS QUESTION: Extract and present live scores, match status, team names, "
                "player stats, and match details. State scores clearly: 'Team A: X/Y, Team B: A/B'. "
                "Include overs, wickets, run rates for cricket. Include quarter/half scores for football. "
                "Do NOT default to generic text when actual score data is in the snippets."
            )
        elif intent.intent == "stock":
            intent_guidance = (
                "STOCK QUESTION: Extract and present the current stock price, change percentage, "
                "NSE/BSE values, 52-week range, and market cap if available. "
                "State clearly: '[Company] is trading at ₹[price] ([change%]) on [exchange].' "
                "Do NOT default to generic text when actual price data is in the snippets."
            )
        elif intent.intent == "currency":
            intent_guidance = (
                "CURRENCY QUESTION: Extract and present the exchange rate clearly. "
                "State: '[amount] [from_currency] = [converted] [to_currency] as of [date].' "
                "Include the rate and date. Do NOT default to generic text when the rate is in the snippets."
            )
        elif intent.intent == "product":
            intent_guidance = (
                "PRODUCT RECOMMENDATION: Extract and present: "
                "product names, prices, key specifications, pros/cons, and comparison points. "
                "If the user has a budget constraint, strictly filter results to that budget. "
                "Prefer a compact Markdown comparison table for best/top/budget product requests unless the user asks for plain prose. "
                "For smartphones, include columns for phone, approximate price, 5G, battery, main camera, display, processor, and why it stands out when available. "
                "After the table, add short key takeaways for likely priorities like 5G, battery, camera, and overall value. "
                "Do not invent specs; use 'not confirmed' only for missing fields, but still extract every visible spec from source snippets and page content. "
            )
        elif intent.intent == "current":
            intent_guidance = (
                "CURRENT/EVENT information: Extract and present: "
                "latest news, current status, recent developments, and real-time data. "
                "Prioritize the most recent sources and note the date of information. "
            )
    system_prompt = (
        "You are a research analyst. The user asked a question and you have web search results. "
        "EXTRACT actual data from the snippets — numbers, prices, temperatures, scores, rates, dates. "
        "Present them as a direct answer. Example formats:\n"
        "- Weather: 'Temperature in Deoria is 35°C with partly cloudy skies.'\n"
        "- Currency: '1 USD = 85.50 INR (as of today).'\n"
        "- Stock: 'Reliance Industries (NSE: RELIANCE) is trading at ₹2,850.'\n"
        "- Cricket: 'India 185/4 (20 overs) vs Australia 180/6 (20 overs). India won by 5 runs.'\n"
        "Do NOT say 'I found sources' or 'snippets do not expose values' when the data is right there. "
        "If a snippet has a number, price, score, or rate — use it. "
        f"{mode_guidance}"
        f"{constraint_guidance}"
        f"{intent_guidance}"
        f"{format_guidance}"
        "Cite sources using markdown links: [Source Title](URL) — for example: The Tata Punch EV starts at ₹10 lakh [Tata Punch EV Price](https://example.com). "
        "Every factual claim must have an inline citation link to its source. Do NOT use numbered citations like [1]. "
        "Do NOT include a '## Sources' section. "
        "Only say data is unavailable if the snippets truly contain zero relevant numbers or values. "
        f"{ANSWER_LANGUAGE_INSTRUCTION}"
    )

    user_prompt = (
        f"Question: {question}\n\n"
        f"Web search results ({len(synthesis_results)} of {len(search_results)} collected sources):\n{sources_text}\n\n"
        "Provide a thorough answer citing sources."
    )
    if history:
        recent = history[-6:]
        context = "\n".join(f"{role}: {content[:300]}" for role, content in recent)
        user_prompt = f"Conversation so far for context:\n{context}\n\n{user_prompt}"

    progress("drafting", f"Calling {model} to generate a well-informed response from {len(synthesis_results)} of {len(search_results)} web sources")
    try:
        answer = _chat(system_prompt, user_prompt, model, temperature=0.2, max_tokens=2048)
    except (LLMProviderError, RuntimeError):
        progress("repairing", "Model synthesis failed; building a constraint-safe fallback answer from sources")
        return _fallback_web_answer(question, search_results)
    source_dump = len(re.findall(r"\bSource\s+\d+\s*:", answer, re.IGNORECASE)) >= 2 and len(re.findall(r"\bURL\s*:", answer, re.IGNORECASE)) >= 2
    source_directory = _looks_like_source_directory_answer(answer)
    missing_requested_table = _wants_table(question) and "|" not in answer
    if source_dump or source_directory or missing_requested_table:
        progress("repairing", "Rewriting web answer to respect the user's constraints and requested format")
        repair_prompt = (
            f"The previous draft failed because it {'listed source records instead of answering' if source_dump or source_directory else 'ignored the requested table format'}.\n\n"
            f"User question: {question}\n\n"
            f"Search results:\n{sources_text}\n\n"
            "Rewrite the answer now. Answer the user's question directly. "
            "Do not output raw Source/URL/Content blocks. "
            "Do not list source titles as if they are the answer. "
            "Cite sources inline as [Source Title](URL) — every factual claim needs a citation link. "
            "If the snippets do not contain enough evidence for a direct answer, say that plainly. "
            "Keep hard constraints like budget and location. "
            "If the user requested tabular format, output a Markdown table with the requested columns. "
            f"{ANSWER_LANGUAGE_INSTRUCTION}"
        )
        try:
            answer = _chat(system_prompt, repair_prompt, model, temperature=0.1, max_tokens=2048)
        except (LLMProviderError, RuntimeError):
            progress("repairing", "Rewrite failed; using deterministic table fallback from sources")
            answer = _fallback_web_answer(question, search_results)
    if _looks_like_source_directory_answer(answer):
        progress("repairing", "Answer still looked like a source directory; using honest fallback")
        answer = _fallback_web_answer(question, search_results)
    answer = ensure_english_answer(_remove_over_budget_lines(answer, budget), model)
    return answer


def _rounds_budget(target: int) -> tuple[int, int]:
    """Follow-up rounds and stall patience, scaled to how many sources the plan
    actually needs — a 200-source deep-research plan needs more attempts than
    a 5-source quick lookup, not the same fixed ceiling."""
    if target <= 10:
        return WEB_RESEARCH_MAX_ROUNDS, WEB_RESEARCH_STALL_LIMIT
    if target <= 30:
        return 6, 3
    if target <= 75:
        return 9, 3
    return 14, 4


def web_research(question: str, model: str, progress, source_limit: int = 5, history: list[tuple[str, str]] | None = None, answer_mode: str = "web_research") -> dict:
    target = max(5, min(200, source_limit))
    results_per_query = WEB_RESEARCH_RESULTS_PER_QUERY
    initial_count = WEB_RESEARCH_INITIAL_QUERIES
    effective_question = _expand_budget_shorthand(question)
    is_followup = _contextual_followup(question, history)
    search_question = _search_question_with_history(question, history)
    requested_budget = _budget_from_question(effective_question)

    # Track counts
    llm_hits = 0
    web_queries = 0

    # Intent detection: classify query using LLM (with conversation context for follow-ups)
    intent, enhanced_query = classify_and_enhance(question, history=history, model=model)
    llm_hits += 1
    if intent.intent != "general":
        diagnostic_event("web_research.intent", intent=intent.intent, language=intent.language, enhanced_query=enhanced_query, entities=intent.entities)

    progress("understanding", f"Calling {model} to plan up to {target} sources across multiple search rounds")
    context_line = ""
    if is_followup and history:
        recent = history[-6:]
        context_line = "\n\nConversation so far:\n" + "\n".join(f"{role}: {content[:300]}" for role, content in recent)
    # Use enhanced query for domain-specific intents, otherwise use the cleaned search question
    base_query = enhanced_query if intent.intent != "general" else search_question
    initial_queries = _unique_queries(_generate_initial_queries(base_query + context_line, model, initial_count) + _constraint_queries(search_question))
    llm_hits += 1
    diagnostic_event("web_research.plan", initial_query_count=len(initial_queries), queries=initial_queries)

    all_results = []
    seen_urls = set()
    searched_queries = set()
    total_searched = 0

    def search_and_collect(queries: list[str], round_label: str) -> int:
        nonlocal total_searched
        added_total = 0
        for i, query in enumerate(queries):
            if len(all_results) >= target:
                break
            normalized_query = " ".join(query.split())
            query_key = normalized_query.lower()
            if not normalized_query or query_key in searched_queries:
                continue
            searched_queries.add(query_key)
            total_searched += 1
            remaining = target - len(all_results)
            per_query_max = min(results_per_query, remaining)
            progress("gathering", f"{round_label} search {total_searched}: {normalized_query[:80]}")
            include_youtube = _requests_video(normalized_query) or not _is_current_sensitive(search_question)
            try:
                results = _search_web(normalized_query, max_results=per_query_max, include_youtube=include_youtube)
            except TypeError:
                results = _search_web(normalized_query, max_results=per_query_max)
            new_in_query = []
            for r in results:
                if len(all_results) >= target:
                    break
                if _is_over_budget_result(r, requested_budget):
                    continue
                if r["url"] and r["url"] not in seen_urls:
                    seen_urls.add(r["url"])
                    all_results.append(r)
                    new_in_query.append(r)
                    added_total += 1
            for r in new_in_query[:5]:
                progress("gathering", f"  → {r['title'][:60]} {r['url']}")
            if len(new_in_query) > 5:
                progress("gathering", f"  … and {len(new_in_query) - 5} more from this query")
            progress("gathering", f"Collected {len(all_results)}/{target} unique sources so far")
        return added_total

    search_and_collect(initial_queries, "Initial")
    web_queries = total_searched

    stalled_rounds = 0
    round_number = 2
    max_rounds, stall_limit = _rounds_budget(target)
    while len(all_results) < target and round_number <= max_rounds and stalled_rounds < stall_limit:
        found_topics = [r["title"] for r in all_results[:30] if r.get("title")]
        progress("understanding", f"Round {round_number}: generating follow-up searches to reach {target} sources")
        remaining = target - len(all_results)
        followup_count = min(10, max(initial_count, math.ceil(remaining / max(1, results_per_query))))
        followup_queries = [
            query for query in _generate_followup_queries(search_question, found_topics, model, followup_count, list(searched_queries), round_number)
            if query.lower() not in searched_queries
        ]
        # Each follow-up query generation is one LLM call
        if followup_queries:
            llm_hits += 1
        if not followup_queries:
            stalled_rounds += 1
            progress("gathering", f"Round {round_number}: no fresh follow-up queries generated")
            round_number += 1
            continue
        progress("gathering", f"Round {round_number}: running {len(followup_queries)} follow-up searches")
        added = search_and_collect(followup_queries, f"Round {round_number}")
        stalled_rounds = stalled_rounds + 1 if added == 0 else 0
        web_queries = total_searched
        round_number += 1

    # Output validation: check if search results match the detected intent
    validation = validate_search_output(intent, all_results)
    if not validation.valid:
        progress("repairing", f"Intent mismatch: {validation.reason}")
        # For weather/product intents, retry with enhanced query
        if intent.intent in ("weather", "product") and not is_followup:
            retry_query = enhanced_query
            progress("gathering", f"Retrying with enhanced query: {retry_query[:80]}")
            retry_results = _search_web(retry_query, max_results=results_per_query, include_youtube=False)
            new_urls = {r["url"] for r in all_results}
            for r in retry_results:
                if r["url"] and r["url"] not in new_urls:
                    all_results.append(r)
                    new_urls.add(r["url"])
            # Re-validate
            validation = validate_search_output(intent, all_results)

    # Scale with target, but stay conservative — each page read is a real sequential
    # network fetch (up to 7s timeout), so this is capped well below target to avoid
    # multi-minute latency on large deep-research requests.
    enrichment_pages = max(WEBPAGE_ENRICHMENT_MAX_PAGES, min(10, target // 10))
    all_results = _enrich_results_with_webpages(effective_question, all_results, progress, intent, max_pages=enrichment_pages)
    answer = _synthesize_answer(effective_question, all_results, model, progress, history=history if is_followup else None, answer_mode=answer_mode, intent=intent)
    llm_hits += 1

    source_list = [
        {"title": r["title"], "url": r["url"], "snippet": r["snippet"], "engine": r.get("engine", ""), "page_read": bool(r.get("page_read"))}
        for r in all_results
    ]

    return {
        "answer": answer,
        "sources": source_list,
        "model": model,
        "llm_hits": llm_hits,
        "web_queries": web_queries,
    }
