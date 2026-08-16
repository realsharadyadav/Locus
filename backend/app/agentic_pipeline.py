import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable
from urllib.parse import quote

import httpx

from .brand import BRAND_NAME, USER_AGENT
from .diagnostics import diagnostic_event
from .intent import QueryIntent, classify_and_enhance
from .llm import ANSWER_LANGUAGE_INSTRUCTION, LLMProviderError, _chat, ensure_english_answer
from .web_research import web_research


def _today_for_prompt() -> str:
    # Every planning/search prompt needs this: without it, the model falls back on its training
    # data's idea of "current", which drifts further from reality every month and shows up as
    # search queries quietly padded with a stale year the user never asked for (e.g. "best hindi
    # songs" turning into "best hindi songs 2024" on a model trained through late 2024, regardless
    # of how long ago that actually was).
    return datetime.now(timezone.utc).strftime("%A, %Y-%m-%d")


Progress = Callable[[str, str], None]
WebResearchFn = Callable[[str, str, Progress, int, list[tuple[str, str]] | None, str], dict]
DirectAnswerFn = Callable[[str, list[tuple[str, str]], list[tuple[str, str]] | None, str], tuple[str, str]]


@dataclass
class AgentStep:
    agent: str
    action: str
    status: str = "pending"
    detail: str = ""


@dataclass
class EvidenceItem:
    title: str
    url: str
    snippet: str
    engine: str
    entity: str = ""
    fresh: bool = True


@dataclass
class AgentPlan:
    route: str
    user_goal: str
    entities: dict = field(default_factory=dict)
    constraints: dict = field(default_factory=dict)
    search_queries: list[str] = field(default_factory=list)
    evidence_rules: list[str] = field(default_factory=list)
    answer_format: str = "direct"
    requires_live_data: bool = False
    complexity: str = "small"
    source_limit: int = 5
    steps: list[AgentStep] = field(default_factory=list)


@dataclass
class AgentResult:
    answer: str
    sources: list[EvidenceItem]
    model: str
    plan: AgentPlan


SMALL_TALK_PATTERN = re.compile(
    r"^\s*(hi|hello|hey|yo|namaste|namaskar|hii|hiii|sup|thanks|thank you|ok|okay)\s*[!.?]*\s*$",
    re.IGNORECASE,
)

COMPLEX_PLAN_PATTERN = re.compile(
    r"\b(plan|roadmap|learn|complete|schedule|strategy|curriculum|prepare|master|study)\b",
    re.IGNORECASE,
)

TIME_WINDOW_PATTERN = re.compile(r"\b(\d+)\s*(day|days|week|weeks|month|months)\b", re.IGNORECASE)

EXPLICIT_BUDGET_PATTERN = re.compile(
    r"(?:under|below|within|upto|up\s+to|budget(?:\s+of)?|less\s+than)\s*"
    r"(?:rs\.?|inr|₹)?\s*([0-9]+(?:\.[0-9]+)?)\s*(k|thousand|lakh|lac)?\b|"
    r"(?:rs\.?|inr|₹)\s*([0-9]+(?:\.[0-9]+)?)\s*(k|thousand|lakh|lac)?\b",
    re.IGNORECASE,
)

QUERY_BUDGET_PATTERN = re.compile(
    r"\b(under|below|within|upto|up\s+to|less\s+than)\s*"
    r"(?:rs\.?|inr|₹)?\s*([0-9]+(?:\.[0-9]+)?)\s*(k|thousand|lakh|lac)?\b",
    re.IGNORECASE,
)

COMPANY_TICKERS = {
    "reliance": "RELIANCE.NS",
    "reliance industries": "RELIANCE.NS",
    "tcs": "TCS.NS",
    "infosys": "INFY.NS",
    "hdfc bank": "HDFCBANK.NS",
    "icici bank": "ICICIBANK.NS",
    "sbi": "SBIN.NS",
    "state bank": "SBIN.NS",
    "itc": "ITC.NS",
    "wipro": "WIPRO.NS",
    "adani": "ADANIENT.NS",
    "tata motors": "TATAMOTORS.NS",
}


def run_agentic_pipeline(
    question: str,
    model: str,
    progress: Progress,
    source_limit: int = 5,
    history: list[tuple[str, str]] | None = None,
    answer_mode: str = "light",
    force_web: bool = False,
    web_research_fn: WebResearchFn | None = None,
    direct_answer_fn: DirectAnswerFn | None = None,
) -> dict:
    progress("understanding", f"Calling {model} to resolve intent, context, constraints, evidence needs, and answer shape")
    plan = _plan_with_llm(question, model, history, answer_mode, force_web)
    _emit_plan(plan, progress)
    effective_limit = min(plan.source_limit, source_limit)

    try:
        result = _execute_plan(plan, question, model, progress, effective_limit, history, answer_mode, web_research_fn, direct_answer_fn)
    except (LLMProviderError, RuntimeError):
        raise
    except Exception as exception:
        diagnostic_event("agentic_pipeline.failed", route=plan.route, error=str(exception))
        progress("repairing", "Agent fallback: primary executor failed, switching to general web research")
        result = _web_fallback(question, model, progress, effective_limit, history, answer_mode, web_research_fn=web_research_fn)

    return {
        "answer": result.answer,
        "sources": [item.__dict__ for item in result.sources],
        "model": result.model,
        "plan": {
            "route": result.plan.route,
            "complexity": result.plan.complexity,
            "answer_format": result.plan.answer_format,
            "entities": result.plan.entities,
            "constraints": result.plan.constraints,
            "search_queries": result.plan.search_queries,
            "source_limit": result.plan.source_limit,
            "evidence_rules": result.plan.evidence_rules,
            "steps": [step.__dict__ for step in result.plan.steps],
        },
    }


def _plan_with_llm(question: str, model: str, history: list[tuple[str, str]] | None, answer_mode: str, force_web: bool) -> AgentPlan:
    if SMALL_TALK_PATTERN.match(question):
        return _fallback_plan(question, QueryIntent("small_talk", "en", question, question, question, {}, False), question, history, answer_mode, force_web)
    context = "\n".join(f"{role}: {content[:600]}" for role, content in (history or [])[-8:])
    system = (
        f"You are {BRAND_NAME}'s planning agent. Resolve the user's actual request from the current message and conversation context. "
        f"Today's date is {_today_for_prompt()}. Use this as the real current date/year — your training data's notion of "
        "\"current\" or \"latest\" is out of date and must never leak into a search query or resolved request. "
        "Only put a specific year in a search query when the user explicitly named one; for an open-ended \"best/latest/top X\" "
        "with no year mentioned, search without a year rather than guessing one. "
        "Normalize any non-English or mixed-language user wording into English internally. "
        "Return JSON only. Do not answer the user. Prefer flexible reasoning over keyword rules. "
        "For follow-ups, carry forward the previous topic, entities, budget, and answer style. "
        "If the user says higher/lower/more/less, convert that relative constraint into a concrete resolved request. "
        "Choose route from: small_talk, direct_llm, web_research, product_recommendation, complex_plan, weather, stock, currency, sports, news. "
        "DECIDE if web search is needed: set needs_web_search=true when the answer requires current/real-time data, external facts, product prices, comparisons, news, stock prices, weather, or anything not in your training data. "
        "Set needs_web_search=false ONLY for general knowledge, math, code, explanations, opinions, creative writing, or things you can answer from training data. "
        "When in doubt, set needs_web_search=true — it is better to search than to hallucinate. "
        "For deep research (complex multi-source questions), set research_depth='deep'. For simple lookups, set research_depth='basic'. "
        "Web search strategies: use 'quick' for simple current facts, 'research' for deep analysis, 'comprehensive' for multi-step planning, 'webpage' for specific URL-based queries. "
        "Use external data for current prices, products, news, weather, sports, currency, and anything time-sensitive. "
        "DECIDE source_limit: how many total web sources to collect. 3-5 for simple current facts/headlines, 5-10 for news/simple comparisons, 10-25 for detailed comparisons/product research, 25-50 for comprehensive research/competitor analysis, 50-200 for deep multi-faceted research/market analysis."
    )
    prompt = (
        f"Conversation context:\n{context or '(none)'}\n\n"
        f"Current user message:\n{question}\n\n"
        f"Answer mode: {answer_mode}; force_web={force_web}\n\n"
        "Return this JSON shape:\n"
        "{"
        "\"route\":\"...\","
        "\"resolved_request\":\"full standalone user request\","
        "\"complexity\":\"small|medium|complex\","
        "\"needs_external_data\":true,"
        "\"needs_web_search\":true,"
        "\"web_strategy\":\"quick|research|comprehensive|webpage\","
        "\"research_depth\":\"basic|deep\","
        "\"source_limit\":10,"
        "\"entities\":{},"
        "\"constraints\":{},"
        "\"search_queries\":[\"query 1\"],"
        "\"answer_format\":\"natural prose|comparison table|direct value first|step-by-step plan\","
        "\"evidence_rules\":[\"must be about ...\"],"
        "\"steps\":[\"step 1\",\"step 2\"]"
        "}\n"
        "Example: previous user asked 'best phone under 20k', current says 'go bit more higher range'. "
        "Resolve to phones in India around ₹25k-₹30k, with product recommendation route and phone-specific search queries."
    )
    try:
        raw = _chat(system, prompt, model, temperature=0.0, max_tokens=900)
        data = _json_object(raw)
        diagnostic_event("agentic_pipeline.llm_plan", raw=raw, parsed_source_limit=data.get("source_limit"), route=data.get("route"))
        return _plan_from_json(question, data, answer_mode, force_web)
    except Exception as exception:
        diagnostic_event("agentic_pipeline.llm_plan_failed", error=str(exception))
        intent, enhanced_query = _fast_or_llm_classify(question, history, model, force_web)
        return _fallback_plan(question, intent, enhanced_query, history, answer_mode, force_web)


def _json_object(text: str) -> dict:
    cleaned = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start >= 0 and end > start:
            return json.loads(cleaned[start:end + 1])
        raise


def _plan_from_json(question: str, data: dict, answer_mode: str, force_web: bool) -> AgentPlan:
    route = str(data.get("route") or "direct_llm").strip() or "direct_llm"
    if route == "small_talk" and not SMALL_TALK_PATTERN.match(question):
        route = "direct_llm"
    llm_needs_web = bool(data.get("needs_web_search"))
    if force_web and route not in {"web_research", "product_recommendation", "news", "sports", "weather", "stock", "currency"}:
        route = "web_research"
    elif llm_needs_web and route in {"small_talk", "direct_llm", "complex_plan"}:
        route = "web_research"
    resolved = str(data.get("resolved_request") or question).strip() or question
    entities = data.get("entities") if isinstance(data.get("entities"), dict) else {}
    constraints = data.get("constraints") if isinstance(data.get("constraints"), dict) else {}
    search_queries = [str(item).strip() for item in data.get("search_queries", []) if str(item).strip()][:6] if isinstance(data.get("search_queries"), list) else []
    evidence_rules = [str(item).strip() for item in data.get("evidence_rules", []) if str(item).strip()][:8] if isinstance(data.get("evidence_rules"), list) else []
    steps = [str(item).strip() for item in data.get("steps", []) if str(item).strip()][:8] if isinstance(data.get("steps"), list) else []
    llm_source_limit = data.get("source_limit")
    if isinstance(llm_source_limit, str) and llm_source_limit.strip().isdigit():
        llm_source_limit = int(llm_source_limit.strip())
    if isinstance(llm_source_limit, (int, float)) and 3 <= int(llm_source_limit) <= 200:
        source_limit = int(llm_source_limit)
    else:
        source_limit = 10 if route in {"web_research", "product_recommendation"} else 5
    if route in {"product", "recommendation"}:
        route = "product_recommendation"
    if route in {"product_recommendation", "web_research", "news"} and not search_queries:
        search_queries = [resolved]
    resolved, constraints, search_queries = _enforce_explicit_current_constraints(question, resolved, constraints, search_queries)
    plan_steps = [
        AgentStep("LLM Planner", "Resolve intent, context, entities, constraints, and output shape", "done", resolved),
        AgentStep("Execution Planner", "Choose tools and evidence requirements from the structured plan", "done", "; ".join(steps) or route),
    ]
    if route not in {"small_talk", "direct_llm", "complex_plan"}:
        plan_steps.extend([
            AgentStep("Fetch Agent", "Run planned queries/tools instead of raw user text"),
            AgentStep("Evidence Check Agent", "Validate evidence against LLM evidence rules"),
        ])
    plan_steps.append(AgentStep("Answer Agent", "Compose only the final user-facing answer"))
    return AgentPlan(
        route=route,
        user_goal=resolved,
        entities=entities,
        constraints=constraints,
        search_queries=search_queries,
        evidence_rules=evidence_rules,
        answer_format=str(data.get("answer_format") or _answer_format_for(route, question)),
        requires_live_data=bool(data.get("needs_external_data") or force_web or route in {"weather", "stock", "currency", "sports", "news", "product_recommendation"}),
        complexity=str(data.get("complexity") or "complex" if route in {"complex_plan", "product_recommendation", "web_research"} else "small"),
        source_limit=source_limit,
        steps=plan_steps,
    )


def _fallback_plan(question: str, intent: QueryIntent, enhanced_query: str, history: list[tuple[str, str]] | None, answer_mode: str, force_web: bool) -> AgentPlan:
    plan = _build_plan(question, intent, enhanced_query, history, answer_mode, force_web)
    plan.user_goal, plan.constraints, plan.search_queries = _enforce_explicit_current_constraints(
        question,
        plan.user_goal,
        plan.constraints,
        plan.search_queries,
    )
    return plan


def _enforce_explicit_current_constraints(
    question: str,
    resolved: str,
    constraints: dict,
    search_queries: list[str],
) -> tuple[str, dict, list[str]]:
    budget = _explicit_budget_from_text(question)
    if budget is None:
        return resolved, constraints, search_queries

    updated_constraints = dict(constraints or {})
    updated_constraints["max_budget"] = budget
    updated_constraints["budget_source"] = "current_user_message"

    updated_resolved = _rewrite_budget_text(resolved or question, budget)
    updated_queries = [_rewrite_budget_text(query, budget) for query in search_queries]
    if not updated_queries:
        updated_queries = [_rewrite_budget_text(question, budget)]
    return updated_resolved, updated_constraints, updated_queries


def _explicit_budget_from_text(text: str) -> int | None:
    matches = list(EXPLICIT_BUDGET_PATTERN.finditer(text or ""))
    if not matches:
        return None
    match = matches[-1]
    value_text = match.group(1) or match.group(3)
    suffix = match.group(2) or match.group(4) or ""
    try:
        value = float(value_text)
    except (TypeError, ValueError):
        return None
    suffix = suffix.lower()
    if suffix in {"k", "thousand"}:
        value *= 1000
    elif suffix in {"lakh", "lac"}:
        value *= 100000
    return int(value)


def _rewrite_budget_text(text: str, budget: int) -> str:
    text = text or ""
    budget_text = f"{budget}"
    if QUERY_BUDGET_PATTERN.search(text):
        return _normalize_spaces(QUERY_BUDGET_PATTERN.sub(lambda match: f"{match.group(1)} {budget_text} ", text))
    if re.search(r"\b[0-9]+(?:\.[0-9]+)?\s*(k|thousand|lakh|lac)\b", text, re.IGNORECASE):
        return re.sub(r"\b[0-9]+(?:\.[0-9]+)?\s*(k|thousand|lakh|lac)\b", budget_text, text, count=1, flags=re.IGNORECASE)
    if re.search(r"\b[0-9]{4,6}\b", text):
        return re.sub(r"\b[0-9]{4,6}\b", budget_text, text, count=1)
    return f"{text.strip()} under {budget_text}".strip()


def _normalize_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _fast_or_llm_classify(question: str, history: list[tuple[str, str]] | None, model: str, force_web: bool = False) -> tuple[QueryIntent, str]:
    fast_route = _fast_route(question)
    if fast_route:
        return QueryIntent(fast_route, "en", question, question, question, {}, True), question
    if force_web:
        return QueryIntent("web_research", "en", question, question, question, {}, True), question
    return _classify(question, history, model)


def _classify(question: str, history: list[tuple[str, str]] | None, model: str) -> tuple[QueryIntent, str]:
    try:
        return classify_and_enhance(question, history=history, model=model)
    except Exception as exception:
        diagnostic_event("agentic_pipeline.classifier_failed", error=str(exception))
        return QueryIntent("general", "en", question, question, question, {}, True), question


def _fast_route(question: str) -> str | None:
    if SMALL_TALK_PATTERN.match(question):
        return "small_talk"
    if _looks_like_currency(question):
        return "currency"
    if _looks_like_stock(question):
        return "stock"
    if _looks_like_weather(question, QueryIntent("general", "en", question, question, question, {}, True)):
        return "weather"
    if _looks_like_sports(question):
        return "sports"
    if _looks_like_complex_plan(question):
        return "complex_plan"
    return None


def _build_plan(
    question: str,
    intent: QueryIntent,
    enhanced_query: str,
    history: list[tuple[str, str]] | None,
    answer_mode: str,
    force_web: bool,
) -> AgentPlan:
    normalized = " ".join(question.lower().split())
    route = intent.intent
    if SMALL_TALK_PATTERN.match(question):
        route = "small_talk"
    elif _looks_like_currency(question):
        route = "currency"
    elif _looks_like_stock(question):
        route = "stock"
    elif _looks_like_weather(question, intent):
        route = "weather"
    elif _looks_like_sports(question):
        route = "sports"
    elif _looks_like_complex_plan(question):
        route = "complex_plan"
    elif force_web or answer_mode == "web_research":
        route = "web_research"
    elif route not in {"weather", "sports", "stock", "currency", "product", "news"}:
        route = "direct_llm"

    complexity = "small" if route in {"small_talk", "currency", "stock", "weather"} else "complex"
    if len(normalized.split()) > 18 or _looks_like_complex_plan(question):
        complexity = "complex"

    entities = dict(intent.entities or {})
    entities.update(_extract_entities(question, enhanced_query, route, history))
    search_queries = [enhanced_query or question] if route in {"web_research", "product", "news"} else []
    answer_format = _answer_format_for(route, question)
    requires_live = route in {"weather", "sports", "stock", "currency", "news"} or "latest" in normalized or "live" in normalized
    steps = [
        AgentStep("Router Agent", "Classify the request and choose a route", "done", route),
        AgentStep("Entity Agent", "Extract target entities, date/time, and constraints", "done", json.dumps(entities, ensure_ascii=False)),
        AgentStep("Plan Agent", "Pick executor, evidence requirements, and final answer shape", "done", answer_format),
    ]
    if route not in {"small_talk", "direct_llm"}:
        steps.append(AgentStep("Fetch Agent", f"Use {route} executor before generic search"))
        steps.append(AgentStep("Evidence Check Agent", "Reject stale, mismatched, or entity-wrong evidence"))
    steps.append(AgentStep("Answer Agent", "Compose only the user-facing answer"))
    fallback_source_limit = 5 if complexity != "complex" else 15
    if route in {"product_recommendation", "web_research"}:
        fallback_source_limit = 20
    return AgentPlan(
        route, intent.translated or question, entities, {}, search_queries, [],
        answer_format, requires_live, complexity, fallback_source_limit, steps
    )


def _emit_plan(plan: AgentPlan, progress: Progress) -> None:
    progress("understanding", f"Agent plan: {plan.route} route, {plan.complexity} depth, {plan.answer_format} output, {plan.source_limit} sources")
    diagnostic_event(
        "agentic_pipeline.plan",
        route=plan.route,
        complexity=plan.complexity,
        answer_format=plan.answer_format,
        entities=plan.entities,
        requires_live_data=plan.requires_live_data,
    )


def _execute_plan(
    plan: AgentPlan,
    question: str,
    model: str,
    progress: Progress,
    source_limit: int,
    history: list[tuple[str, str]] | None,
    answer_mode: str,
    web_research_fn: WebResearchFn | None = None,
    direct_answer_fn: DirectAnswerFn | None = None,
) -> AgentResult:
    effective_limit = min(plan.source_limit, source_limit)
    if plan.route == "small_talk":
        return _small_talk(plan, model)
    if plan.route == "currency":
        return _currency_answer(plan, question, model, progress)
    if plan.route == "stock":
        return _stock_answer(plan, question, model, progress)
    if plan.route == "weather":
        return _weather_answer(plan, question, model, progress)
    if plan.route == "complex_plan":
        return _complex_plan_answer(plan, question, model, progress, history)
    if plan.route == "direct_llm":
        return _direct_llm_answer(plan, question, model, progress, history, direct_answer_fn)
    if plan.route in {"product_recommendation", "news", "sports"}:
        return _planned_web_answer(plan, question, model, progress, effective_limit, history, answer_mode, web_research_fn)
    return _web_fallback(question, model, progress, effective_limit, history, answer_mode, plan, web_research_fn)


def _small_talk(plan: AgentPlan, model: str) -> AgentResult:
    text = plan.user_goal.strip().lower()
    if text in {"ok", "okay"}:
        answer = "ok"
    else:
        answer = "Hi! How can I help?"
    return AgentResult(answer, [], model, plan)


def _currency_answer(plan: AgentPlan, question: str, model: str, progress: Progress) -> AgentResult:
    amount, base, target = _currency_pair(question, plan.entities)
    progress("gathering", f"Currency Agent: fetching {base} to {target}")
    url = f"https://open.er-api.com/v6/latest/{base}"
    data = _get_json(url, timeout=8)
    rates = data.get("rates") or {}
    rate = rates.get(target)
    if not isinstance(rate, (int, float)):
        raise RuntimeError(f"No {base}/{target} rate returned")
    converted = float(amount) * float(rate)
    stamp = data.get("time_last_update_utc") or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    title = f"{base} to {target} exchange rate"
    answer = f"{amount:g} {base} = {converted:,.2f} {target}. Rate: 1 {base} = {float(rate):,.4f} {target}. Updated: {stamp}."
    source = EvidenceItem(title, url, answer, "currency-api", f"{base}/{target}")
    _mark_done(plan, "Fetch Agent", "Currency API returned a live rate")
    _mark_done(plan, "Evidence Check Agent", f"Matched currency pair {base}/{target}")
    return AgentResult(answer, [source], model, plan)


def _stock_answer(plan: AgentPlan, question: str, model: str, progress: Progress) -> AgentResult:
    ticker = _stock_ticker(question, plan.entities)
    progress("gathering", f"Stock Agent: fetching quote for {ticker}")
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range=1d&interval=1m"
    data = _get_json(url, timeout=8)
    result = ((data.get("chart") or {}).get("result") or [None])[0]
    if not result:
        raise RuntimeError(f"No quote returned for {ticker}")
    meta = result.get("meta") or {}
    price = meta.get("regularMarketPrice") or meta.get("previousClose")
    currency = meta.get("currency") or "INR"
    exchange = meta.get("exchangeName") or meta.get("fullExchangeName") or "market"
    name = _stock_name(question, ticker)
    if not isinstance(price, (int, float)):
        raise RuntimeError(f"No live price returned for {ticker}")
    previous = meta.get("previousClose")
    change_text = ""
    if isinstance(previous, (int, float)) and previous:
        change = float(price) - float(previous)
        pct = (change / float(previous)) * 100
        change_text = f" ({change:+.2f}, {pct:+.2f}% vs previous close)"
    updated = datetime.fromtimestamp(meta.get("regularMarketTime", datetime.now().timestamp()), tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    answer = f"{name} is trading at {currency} {float(price):,.2f}{change_text} on {exchange}. Updated: {updated}."
    source = EvidenceItem(f"{name} quote", url, answer, "yahoo-finance", ticker)
    _mark_done(plan, "Fetch Agent", "Finance quote endpoint returned a price")
    _mark_done(plan, "Evidence Check Agent", f"Matched ticker {ticker}")
    return AgentResult(answer, [source], model, plan)


def _weather_answer(plan: AgentPlan, question: str, model: str, progress: Progress) -> AgentResult:
    location = _weather_location(question, plan.entities)
    progress("gathering", f"Weather Agent: fetching forecast for {location}")
    url = f"https://wttr.in/{quote(location)}"
    api_url = f"{url}?format=j1"
    data = _get_json(api_url, timeout=10)
    current = (data.get("current_condition") or [{}])[0]
    weather = (current.get("weatherDesc") or [{}])[0].get("value", "weather data")
    temp = current.get("temp_C")
    humidity = current.get("humidity")
    wind = current.get("windspeedKmph")
    chance = _rain_chance(data, question)
    day_label = "tomorrow" if _asks_tomorrow(question) else "today"
    rain_text = f" Rain chance {day_label}: {chance}%." if chance is not None else ""
    answer = f"{location}: {temp}°C, {weather}, humidity {humidity}%, wind {wind} km/h.{rain_text}"
    source = EvidenceItem(f"{location} weather", url or api_url, answer, "wttr.in", location)
    _mark_done(plan, "Fetch Agent", "Weather endpoint returned current conditions")
    _mark_done(plan, "Evidence Check Agent", f"Matched location {location}")
    return AgentResult(answer, [source], model, plan)


def _complex_plan_answer(
    plan: AgentPlan,
    question: str,
    model: str,
    progress: Progress,
    history: list[tuple[str, str]] | None,
) -> AgentResult:
    progress("drafting", f"Calling {model} to build a systematic multi-step answer")
    prompt = (
        f"User request: {question}\n\n"
        f"Conversation context: {json.dumps((history or [])[-6:], ensure_ascii=False)}\n\n"
        "Build a practical plan. Scale depth to the request. For a learning roadmap, include phases, daily/weekly structure, projects, checkpoints, and how to measure progress. "
        "Do not mention internal agents. Return the final user-facing answer only. "
        + ANSWER_LANGUAGE_INSTRUCTION
    )
    answer = ensure_english_answer(_chat(
        f"You are {BRAND_NAME}'s planning agent. Think systematically, break complex goals into steps and substeps, and produce a polished, actionable answer. "
        + ANSWER_LANGUAGE_INSTRUCTION,
        prompt,
        model,
        temperature=0.2,
        max_tokens=2048,
    ), model)
    _mark_done(plan, "Answer Agent", "Composed complex plan")
    return AgentResult(answer.strip(), [], model, plan)


def _direct_llm_answer(
    plan: AgentPlan,
    question: str,
    model: str,
    progress: Progress,
    history: list[tuple[str, str]] | None,
    direct_answer_fn: DirectAnswerFn | None = None,
) -> AgentResult:
    progress("drafting", f"Calling {model} for direct response")
    if direct_answer_fn:
        answer, used_model = direct_answer_fn(question, [], history, model)
        return AgentResult(answer.strip(), [], used_model, plan)
    prompt = f"Question: {question}\n\nAnswer naturally and concisely. Scale detail to the question. {ANSWER_LANGUAGE_INSTRUCTION}"
    if history:
        prompt = f"Recent context:\n{json.dumps(history[-6:], ensure_ascii=False)}\n\n{prompt}"
    answer = ensure_english_answer(_chat(f"You are {BRAND_NAME}. Be direct, useful, and concise. " + ANSWER_LANGUAGE_INSTRUCTION, prompt, model, temperature=0.2, max_tokens=1024), model)
    return AgentResult(answer.strip(), [], model, plan)


def _web_fallback(
    question: str,
    model: str,
    progress: Progress,
    source_limit: int,
    history: list[tuple[str, str]] | None,
    answer_mode: str,
    plan: AgentPlan | None = None,
    web_research_fn: WebResearchFn | None = None,
) -> AgentResult:
    progress("gathering", "Web Research Agent: using broad search fallback")
    research_question = plan.user_goal if plan else question
    if web_research_fn:
        result = web_research_fn(research_question, model, progress, source_limit, None, answer_mode)
    else:
        result = web_research(research_question, model, progress, source_limit, history=None, answer_mode=answer_mode)
    sources = [
        EvidenceItem(
            title=item.get("title", ""),
            url=item.get("url", ""),
            snippet=item.get("snippet", ""),
            engine=item.get("engine", "web"),
        )
        for item in result.get("sources", [])
    ]
    fallback_plan = plan or AgentPlan("web_research", question)
    _mark_done(fallback_plan, "Fetch Agent", f"Collected {len(sources)} web sources")
    return AgentResult(result.get("answer", ""), sources, result.get("model", model), fallback_plan)


def _planned_web_answer(
    plan: AgentPlan,
    question: str,
    model: str,
    progress: Progress,
    source_limit: int,
    history: list[tuple[str, str]] | None,
    answer_mode: str,
    web_research_fn: WebResearchFn | None = None,
) -> AgentResult:
    queries = plan.search_queries or [plan.user_goal or question]
    collected: list[EvidenceItem] = []
    seen = set()
    # Each query here runs a full nested web_research pipeline (its own search
    # rounds + LLM calls), so this scales with source_limit rather than a flat
    # count — Normal's low ceiling gets a couple of planned queries, Max's full
    # ceiling gets the full dozen, capped well below source_limit to avoid an
    # explosion of nested pipelines.
    max_queries = max(3, min(12, source_limit // 10))
    selected_queries = queries[:max_queries]
    progress("gathering", f"Fetch Agent: running {len(selected_queries)} planned quer{'y' if len(selected_queries) == 1 else 'ies'}")
    for query in selected_queries:
        query_limit = max(3, source_limit // max(1, len(selected_queries)))
        if web_research_fn:
            result = web_research_fn(query, model, progress, query_limit, None, answer_mode)
        else:
            result = web_research(query, model, progress, query_limit, history=None, answer_mode=answer_mode)
        for item in result.get("sources", []):
            url = item.get("url", "")
            key = url or f"{item.get('title', '')}|{item.get('snippet', '')}"
            if key in seen:
                continue
            seen.add(key)
            collected.append(EvidenceItem(
                title=item.get("title", ""),
                url=url,
                snippet=item.get("snippet", ""),
                engine=item.get("engine", "web"),
            ))
    collected = collected[:source_limit]
    _mark_done(plan, "Fetch Agent", f"Collected {len(collected)} candidate sources from planned queries")
    accepted = _validate_evidence_with_llm(plan, collected, model, progress)
    if not accepted:
        # The planned queries can be narrow enough that every result gets rejected. Before giving up,
        # search once more on the resolved request itself — a broader query often returns the same
        # facts in a form the validator accepts.
        broad_query = plan.user_goal or question
        if broad_query not in selected_queries:
            progress("gathering", f"Fetch Agent: planned queries returned no usable evidence, retrying broadly with '{broad_query[:80]}'")
            if web_research_fn:
                retry = web_research_fn(broad_query, model, progress, source_limit, None, answer_mode)
            else:
                retry = web_research(broad_query, model, progress, source_limit, history=None, answer_mode=answer_mode)
            retry_items = []
            for item in retry.get("sources", []):
                url = item.get("url", "")
                key = url or f"{item.get('title', '')}|{item.get('snippet', '')}"
                if key in seen:
                    continue
                seen.add(key)
                retry_items.append(EvidenceItem(
                    title=item.get("title", ""),
                    url=url,
                    snippet=item.get("snippet", ""),
                    engine=item.get("engine", "web"),
                ))
            if retry_items:
                accepted = _validate_evidence_with_llm(plan, retry_items[:source_limit], model, progress)
    if not accepted:
        _mark_done(plan, "Evidence Check Agent", "No evidence matched the structured plan")
        answer = (
            "I could not find reliable matching evidence for that request. "
            f"I was looking for: {plan.user_goal}. The sources returned did not satisfy the evidence rules."
        )
        return AgentResult(answer, [], model, plan)
    _mark_done(plan, "Evidence Check Agent", f"Accepted {len(accepted)} relevant source{'s' if len(accepted) != 1 else ''}")
    answer = _compose_planned_answer(plan, question, accepted, model, progress, history)
    return AgentResult(answer, accepted, model, plan)


def _validate_evidence_with_llm(plan: AgentPlan, sources: list[EvidenceItem], model: str, progress: Progress) -> list[EvidenceItem]:
    if not sources:
        return []
    progress("verifying", f"Calling {model} to validate evidence sources against the plan")
    source_text = "\n\n".join(
        f"[{index}] Title: {source.title}\nURL: {source.url}\nSnippet: {source.snippet[:700]}"
        for index, source in enumerate(sources, 1)
    )
    prompt = (
        f"Resolved request: {plan.user_goal}\n"
        f"Route: {plan.route}\n"
        f"Entities: {json.dumps(plan.entities, ensure_ascii=False)}\n"
        f"Constraints: {json.dumps(plan.constraints, ensure_ascii=False)}\n"
        f"Evidence rules: {json.dumps(plan.evidence_rules, ensure_ascii=False)}\n\n"
        f"Candidate sources:\n{source_text}\n\n"
        "Return JSON only: {\"accepted_indices\":[1,2],\"reason\":\"...\"}. "
        "Accept only sources that directly match the resolved request, entities, and constraints. Reject unrelated snippets."
    )
    try:
        data = _json_object(_chat("You are a strict evidence validator. Never accept unrelated sources.", prompt, model, temperature=0.0, max_tokens=500))
        accepted = []
        for value in data.get("accepted_indices", []):
            try:
                index = int(value) - 1
            except (TypeError, ValueError):
                continue
            if 0 <= index < len(sources):
                accepted.append(sources[index])
        diagnostic_event("agentic_pipeline.evidence_validation", route=plan.route, accepted=len(accepted), total=len(sources), reason=data.get("reason", ""))
        return accepted[:plan.source_limit]
    except Exception as exception:
        diagnostic_event("agentic_pipeline.evidence_validation_failed", route=plan.route, error=str(exception))
        return _fallback_evidence_filter(plan, sources)


def _fallback_evidence_filter(plan: AgentPlan, sources: list[EvidenceItem]) -> list[EvidenceItem]:
    terms = []
    for value in [plan.user_goal, *[str(v) for v in plan.entities.values()], *[str(v) for v in plan.constraints.values()]]:
        terms.extend(re.findall(r"[A-Za-z0-9₹]+", value.lower()))
    terms = [term for term in terms if len(term) >= 3 and term not in {"best", "under", "higher", "range", "latest"}]
    if not terms:
        return sources[:plan.source_limit]
    ranked = []
    for source in sources:
        haystack = f"{source.title} {source.snippet}".lower()
        score = sum(1 for term in terms if term in haystack)
        if score:
            ranked.append((score, source))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return [source for _, source in ranked[:plan.source_limit]]


def _compose_planned_answer(plan: AgentPlan, question: str, sources: list[EvidenceItem], model: str, progress: Progress, history: list[tuple[str, str]] | None) -> str:
    progress("drafting", f"Calling {model} to generate a well-informed response from accepted evidence")
    source_text = "\n\n".join(
        f"[{index}] {source.title}\nURL: {source.url}\nSnippet: {source.snippet[:900]}"
        for index, source in enumerate(sources, 1)
    )
    prompt = (
        f"Original user message: {question}\n"
        f"Resolved request: {plan.user_goal}\n"
        f"Answer format: {plan.answer_format}\n"
        f"Entities: {json.dumps(plan.entities, ensure_ascii=False)}\n"
        f"Constraints: {json.dumps(plan.constraints, ensure_ascii=False)}\n"
        f"Conversation context: {json.dumps((history or [])[-6:], ensure_ascii=False)}\n\n"
        f"Accepted evidence (use these titles and URLs for citations):\n{source_text}\n\n"
        "Write the final answer only. Use the resolved request, not the raw ambiguous follow-up. "
        "CITE sources inline as markdown links: [Title from evidence above](URL from evidence above). "
        "Example: TCS is trading at ₹3,450 [TCS vs Wipro Comparison](https://example.com). "
        "CRITICAL: Do NOT use [1], [2], [Source 1], etc. ONLY use [Exact Title From Evidence](URL). "
        "Every factual claim MUST have a [Title](URL) citation. "
        "If prices/specs are not present, say what could not be confirmed instead of inventing. "
        "For product recommendation requests, prefer a compact Markdown comparison table plus short key takeaways. "
        "For smartphone tables, include phone, approximate price, 5G, battery, main camera, display, processor, and why it stands out when available. "
        "If the user asks for launch dates, answer with a launch-date table for the specific phones already being compared. "
        + ANSWER_LANGUAGE_INSTRUCTION
    )
    answer = _chat(f"You are {BRAND_NAME}'s answer agent. Be direct, useful, and grounded only in accepted evidence. " + ANSWER_LANGUAGE_INSTRUCTION, prompt, model, temperature=0.15, max_tokens=4000)
    return ensure_english_answer(answer, model).strip()


def _get_json(url: str, timeout: float) -> dict:
    response = httpx.get(url, timeout=timeout, follow_redirects=True, headers={"User-Agent": f"{USER_AGENT}/agentic-pipeline"})
    response.raise_for_status()
    return response.json()


def _looks_like_currency(question: str) -> bool:
    return bool(re.search(r"\b(usd|inr|eur|gbp|dollar|rupee|exchange|convert)\b", question, re.IGNORECASE))


def _looks_like_stock(question: str) -> bool:
    return bool(re.search(r"\b(stock|share|nse|bse|trading|reliance|tcs|infosys|hdfc|icici|sbi)\b", question, re.IGNORECASE))


def _looks_like_weather(question: str, intent: QueryIntent) -> bool:
    return intent.intent == "weather" or bool(re.search(r"\b(weather|mausam|barish|rain|temperature|forecast)\b", question, re.IGNORECASE))


def _looks_like_sports(question: str) -> bool:
    return bool(re.search(r"\b(cricket|score|match|ipl|football|tennis|india vs|vs australia)\b", question, re.IGNORECASE))


def _looks_like_complex_plan(question: str) -> bool:
    return bool(COMPLEX_PLAN_PATTERN.search(question) and (TIME_WINDOW_PATTERN.search(question) or len(question.split()) >= 8))


def _extract_entities(question: str, enhanced_query: str, route: str, history: list[tuple[str, str]] | None) -> dict:
    entities: dict[str, str] = {}
    if route == "currency":
        amount, base, target = _currency_pair(question, {})
        entities.update(amount=str(amount), currency_from=base, currency_to=target)
    elif route == "stock":
        entities["ticker"] = _stock_ticker(question, {})
    elif route == "weather":
        entities["location"] = _weather_location(question, {})
    elif route == "complex_plan":
        match = TIME_WINDOW_PATTERN.search(question)
        if match:
            entities["time_window"] = f"{match.group(1)} {match.group(2)}"
    elif route == "sports":
        entities["match"] = enhanced_query or question
    return entities


def _answer_format_for(route: str, question: str) -> str:
    if route in {"currency", "stock", "weather", "sports"}:
        return "direct value first, then timestamp/source"
    if route == "complex_plan":
        return "structured step-by-step plan"
    if "table" in question.lower() or "tabular" in question.lower():
        return "markdown table"
    return "natural concise prose"


def _currency_pair(question: str, entities: dict) -> tuple[float, str, str]:
    amount_match = re.search(r"\b(\d+(?:\.\d+)?)\b", question)
    amount = float(amount_match.group(1)) if amount_match else 1.0
    text = question.lower()
    base = (entities.get("currency_from") or "").upper()
    target = (entities.get("currency_to") or "").upper()
    if not base:
        base = "USD" if re.search(r"\b(usd|dollar)\b", text) else "INR"
    if not target:
        target = "INR" if base != "INR" and re.search(r"\b(inr|rupee)\b", text) else "USD"
    return amount, base, target


def _stock_ticker(question: str, entities: dict) -> str:
    ticker = str(entities.get("ticker") or "").strip().upper()
    if ticker:
        return ticker if "." in ticker else f"{ticker}.NS"
    text = question.lower()
    for name, symbol in COMPANY_TICKERS.items():
        if name in text:
            return symbol
    match = re.search(r"\b([A-Z]{2,12})(?:\.NS|\.BO)?\b", question)
    if match:
        value = match.group(0).upper()
        return value if "." in value else f"{value}.NS"
    raise RuntimeError("Could not identify stock ticker")


def _stock_name(question: str, ticker: str) -> str:
    text = question.lower()
    for name, symbol in COMPANY_TICKERS.items():
        if symbol == ticker and name in text:
            return name.title()
    return ticker


def _weather_location(question: str, entities: dict) -> str:
    location = str(entities.get("location") or "").strip()
    if location:
        return location
    text = re.sub(r"\b(aaj|kal|today|tomorrow|weather|mausam|barish|hoga|hogi|rain|forecast|temperature|kya|hai|me|mein|in)\b", " ", question, flags=re.IGNORECASE)
    text = re.sub(r"[^A-Za-z,\s]", " ", text)
    words = [word for word in text.split() if len(word) > 1]
    if "deoria" in question.lower() and "lar" in question.lower():
        return "Lar, Deoria, Uttar Pradesh"
    if "deoria" in question.lower():
        return "Deoria, Uttar Pradesh"
    return " ".join(words[:4]) or "current location"


def _asks_tomorrow(question: str) -> bool:
    return bool(re.search(r"\b(kal|tomorrow)\b", question, re.IGNORECASE))


def _rain_chance(data: dict, question: str) -> str | None:
    weather_days = data.get("weather") or []
    index = 1 if _asks_tomorrow(question) and len(weather_days) > 1 else 0
    if index >= len(weather_days):
        return None
    hourly = weather_days[index].get("hourly") or []
    chances = []
    for hour in hourly:
        chance = hour.get("chanceofrain")
        if chance is not None and str(chance).isdigit():
            chances.append(int(chance))
    if not chances:
        return None
    return str(max(chances))


def _mark_done(plan: AgentPlan, agent: str, detail: str) -> None:
    for step in plan.steps:
        if step.agent == agent:
            step.status = "done"
            step.detail = detail
            return
    plan.steps.append(AgentStep(agent, detail, "done", detail))
