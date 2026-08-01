from backend.app import agentic_pipeline as pipeline


def test_agentic_small_talk_skips_llm(monkeypatch):
    monkeypatch.setattr(pipeline, "_chat", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("LLM should not run")))

    result = pipeline.run_agentic_pipeline("hi", "test-model", lambda *args: None)

    assert result["plan"]["route"] == "small_talk"
    assert "Hi" in result["answer"]
    assert result["sources"] == []


def test_agentic_currency_uses_direct_executor(monkeypatch):
    def fake_get_json(url, timeout):
        assert "USD" in url
        return {"rates": {"INR": 83.25}, "time_last_update_utc": "Fri, 03 Jul 2026 00:00:00 +0000"}

    monkeypatch.setattr(pipeline, "_get_json", fake_get_json)

    result = pipeline.run_agentic_pipeline("1 usd to inr", "test-model", lambda *args: None)

    assert result["plan"]["route"] == "currency"
    assert "1 USD = 83.25 INR" in result["answer"]
    assert result["sources"][0]["engine"] == "currency-api"


def test_agentic_stock_uses_entity_specific_quote(monkeypatch):
    def fake_get_json(url, timeout):
        assert "RELIANCE.NS" in url
        return {
            "chart": {
                "result": [{
                    "meta": {
                        "regularMarketPrice": 1420.5,
                        "previousClose": 1400.0,
                        "currency": "INR",
                        "exchangeName": "NSE",
                        "regularMarketTime": 1783040400,
                    }
                }]
            }
        }

    monkeypatch.setattr(pipeline, "_get_json", fake_get_json)

    result = pipeline.run_agentic_pipeline("reliance ka stock price kya hai", "test-model", lambda *args: None)

    assert result["plan"]["route"] == "stock"
    assert result["plan"]["entities"]["ticker"] == "RELIANCE.NS"
    assert "Reliance" in result["answer"]
    assert "INR 1,420.50" in result["answer"]


def test_agentic_weather_extracts_lar_deoria(monkeypatch):
    def fake_get_json(url, timeout):
        assert "Lar%2C%20Deoria%2C%20Uttar%20Pradesh" in url
        return {
            "current_condition": [{
                "weatherDesc": [{"value": "Light rain"}],
                "temp_C": "29",
                "humidity": "84",
                "windspeedKmph": "10",
            }],
            "weather": [{"hourly": [{"chanceofrain": "80"}]}],
        }

    monkeypatch.setattr(pipeline, "_get_json", fake_get_json)

    result = pipeline.run_agentic_pipeline("lar deoria me barish hoga aaj?", "test-model", lambda *args: None)

    assert result["plan"]["route"] == "weather"
    assert result["plan"]["entities"]["location"] == "Lar, Deoria, Uttar Pradesh"
    assert "Rain chance today: 80%" in result["answer"]


def test_agentic_complex_plan_uses_planning_agent(monkeypatch):
    captured = {}

    def fake_chat(system, prompt, model, temperature=0.2, max_tokens=2048):
        captured["system"] = system
        captured["prompt"] = prompt
        return "30-day C# roadmap with phases, projects, and checkpoints."

    monkeypatch.setattr(pipeline, "_chat", fake_chat)

    result = pipeline.run_agentic_pipeline("plan how to complete c# learning in 30 days", "test-model", lambda *args: None)

    assert result["plan"]["route"] == "complex_plan"
    assert result["plan"]["entities"]["time_window"] == "30 days"
    assert "30-day C# roadmap" in result["answer"]
    assert "planning agent" in captured["system"].lower()


def test_agentic_web_fallback_keeps_broad_research(monkeypatch):
    def fake_web_research(question, model, progress, source_limit=5, history=None, answer_mode="web_research"):
        return {
            "answer": "Broad research answer",
            "sources": [{"title": "Source", "url": "https://example.com", "snippet": "Evidence", "engine": "test"}],
            "model": model,
        }

    monkeypatch.setattr(pipeline, "web_research", fake_web_research)

    result = pipeline.run_agentic_pipeline("research latest React updates", "test-model", lambda *args: None, force_web=True)

    assert result["plan"]["route"] == "web_research"
    assert result["answer"] == "Broad research answer"
    assert result["sources"][0]["url"] == "https://example.com"


def test_agentic_product_followup_uses_llm_resolved_request(monkeypatch):
    calls = {"chat": 0, "queries": []}

    def fake_chat(system, prompt, model, temperature=0.2, max_tokens=None, **kwargs):
        calls["chat"] += 1
        if calls["chat"] == 1:
            return """
            {
              "route": "product_recommendation",
              "resolved_request": "Recommend better phones in India above the previous under ₹20k range, around ₹25k-₹30k",
              "complexity": "medium",
              "needs_external_data": true,
              "entities": {"product": "phone", "market": "India"},
              "constraints": {"previous_budget": 20000, "new_budget_range": [25000, 30000]},
              "search_queries": ["best phones under 30000 India 2026 price", "best smartphones 25000 to 30000 India latest"],
              "answer_format": "comparison table",
              "evidence_rules": ["must be about smartphones", "must mention India pricing"],
              "steps": ["resolve follow-up budget", "search current phone recommendations", "compare accepted evidence"]
            }
            """
        if calls["chat"] == 2:
            return '{"accepted_indices":[1],"reason":"phone source with India price"}'
        return "Here are stronger phones around ₹25k-₹30k: Phone A [1]."

    def fake_web_research(question, model, progress, source_limit=5, history=None, answer_mode="web_research"):
        calls["queries"].append(question)
        return {
            "answer": "ignored",
            "sources": [
                {"title": "Best phones under 30000 India", "url": "https://example.com/phones", "snippet": "Phone A price ₹28,999 with AMOLED and 5G.", "engine": "test"},
                {"title": "BT brinjal", "url": "https://example.com/brinjal", "snippet": "Agriculture unrelated result.", "engine": "test"},
            ],
            "model": model,
        }

    monkeypatch.setattr(pipeline, "_chat", fake_chat)

    result = pipeline.run_agentic_pipeline(
        "go bit more higher range",
        "test-model",
        lambda *args: None,
        history=[("user", "best phone under 20k"), ("assistant", "Here are phones under ₹20,000")],
        web_research_fn=fake_web_research,
    )

    assert result["plan"]["route"] == "product_recommendation"
    assert calls["queries"][0] == "best phones under 30000 India 2026 price"
    assert "go bit more higher range" not in calls["queries"][0]
    assert result["sources"][0]["url"] == "https://example.com/phones"
    assert "Phone A" in result["answer"]


def test_agentic_explicit_budget_overrides_llm_plan(monkeypatch):
    calls = {"chat": 0, "queries": []}

    def fake_chat(system, prompt, model, temperature=0.2, max_tokens=None, **kwargs):
        calls["chat"] += 1
        if calls["chat"] == 1:
            return """
            {
              "route": "product_recommendation",
              "resolved_request": "Recommend the best phones in India under ₹25,000",
              "complexity": "medium",
              "needs_external_data": true,
              "entities": {"product": "phone", "market": "India"},
              "constraints": {"max_budget": 25000},
              "search_queries": ["best phones under 25000 India 2026 price"],
              "answer_format": "comparison table",
              "evidence_rules": ["must be about smartphones", "must mention India pricing"],
              "steps": ["search current phone recommendations", "compare accepted evidence"]
            }
            """
        if calls["chat"] == 2:
            return '{"accepted_indices":[1],"reason":"phone source with India price"}'
        return "Under ₹10,000, Phone B is the best confirmed option [1]."

    def fake_web_research(question, model, progress, source_limit=5, history=None, answer_mode="web_research"):
        calls["queries"].append(question)
        return {
            "answer": "ignored",
            "sources": [
                {
                    "title": "Best phones under 10000 India",
                    "url": "https://example.com/phones-under-10000",
                    "snippet": "Phone B price ₹9,999 with reliable battery life.",
                    "engine": "test",
                }
            ],
            "model": model,
        }

    monkeypatch.setattr(pipeline, "_chat", fake_chat)

    result = pipeline.run_agentic_pipeline(
        "best phone under 10k",
        "test-model",
        lambda *args: None,
        web_research_fn=fake_web_research,
    )

    assert result["plan"]["route"] == "product_recommendation"
    assert result["plan"]["constraints"]["max_budget"] == 10000
    assert result["plan"]["constraints"]["budget_source"] == "current_user_message"
    assert "10000" in result["plan"]["search_queries"][0]
    assert "25000" not in result["plan"]["search_queries"][0]
    assert calls["queries"][0] == "best phones under 10000 India 2026 price"
    assert "Phone B" in result["answer"]


def test_planned_web_answer_retries_broadly_before_giving_up(monkeypatch):
    """Narrow planned queries whose results all get rejected should trigger one broad retry."""
    searched = []

    def fake_web_research(question, model, progress, source_limit=5, history=None, answer_mode="web_research"):
        searched.append(question)
        return {
            "answer": "",
            "sources": [{"title": f"Result for {question}", "url": f"https://example.com/{len(searched)}", "snippet": "Evidence", "engine": "test"}],
            "model": model,
        }

    # Reject everything from the planned queries, accept the broad retry's result.
    def fake_validate(plan, sources, model, progress):
        return [] if len(searched) <= 1 else list(sources)

    monkeypatch.setattr(pipeline, "web_research", fake_web_research)
    monkeypatch.setattr(pipeline, "_validate_evidence_with_llm", fake_validate)
    monkeypatch.setattr(pipeline, "_compose_planned_answer", lambda *args, **kwargs: "Composed from the broad retry")

    plan = pipeline.AgentPlan(route="news", user_goal="latest hiring news at Acme", search_queries=["acme q3 hiring memo leak"])
    result = pipeline._planned_web_answer(plan, "any hiring news at Acme?", "test-model", lambda *args: None, 5, None, "web_research")

    assert len(searched) == 2, "the broad retry should run after the planned query yields nothing usable"
    assert searched[1] == "latest hiring news at Acme"
    assert result.answer == "Composed from the broad retry"


def test_planned_web_answer_still_gives_up_when_retry_also_fails(monkeypatch):
    def fake_web_research(question, model, progress, source_limit=5, history=None, answer_mode="web_research"):
        return {"answer": "", "sources": [{"title": "Irrelevant", "url": "https://example.com/x", "snippet": "No", "engine": "test"}], "model": model}

    monkeypatch.setattr(pipeline, "web_research", fake_web_research)
    monkeypatch.setattr(pipeline, "_validate_evidence_with_llm", lambda *args, **kwargs: [])

    plan = pipeline.AgentPlan(route="news", user_goal="something unfindable", search_queries=["narrow query"])
    result = pipeline._planned_web_answer(plan, "find it", "test-model", lambda *args: None, 5, None, "web_research")

    assert "could not find reliable matching evidence" in result.answer
    assert result.sources == []
