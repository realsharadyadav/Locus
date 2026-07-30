"""Deep intent detection test suite — 60+ test cases.

Tests: LLM classifier, keyword fallback, context persistence, Hinglish,
       edge cases, output validation, auto-web-search routing.
"""
import pytest
from backend.app.intent import classify_and_enhance, _fallback_classify, validate_search_output, QueryIntent
from backend.app.main import should_auto_web_search


# ---------------------------------------------------------------------------
# 1. WEATHER (10)
# ---------------------------------------------------------------------------

class TestWeather:
    def test_hinglish_weather_deoria(self):
        intent, q = classify_and_enhance("lar deoria me barish hoga aaj?")
        assert intent.intent == "weather"
        assert "deoria" in q.lower()

    def test_hinglish_weather_delhi(self):
        intent, q = classify_and_enhance("aaj delhi me mausam kaisa hai")
        assert intent.intent == "weather"
        assert "delhi" in q.lower()

    def test_english_weather_mumbai(self):
        intent, q = classify_and_enhance("weather in Mumbai today")
        assert intent.intent == "weather"
        assert "mumbai" in q.lower()

    def test_hinglish_kal_barish(self):
        intent, q = classify_and_enhance("kal barish hogi kya?")
        assert intent.intent == "weather"

    def test_hinglish_temperature(self):
        intent, _ = classify_and_enhance("temperatur kya hai aaj")
        assert intent.intent == "weather"

    def test_hinglish_mumbai_mausam(self):
        intent, _ = classify_and_enhance("mumbai ka mausam")
        assert intent.intent == "weather"

    def test_english_chennai_forecast(self):
        intent, _ = classify_and_enhance("chennai weather forecast")
        assert intent.intent == "weather"

    def test_english_rain_bangalore(self):
        intent, _ = classify_and_enhance("bangalore rain today")
        assert intent.intent == "weather"

    def test_english_weekend_goa(self):
        intent, _ = classify_and_enhance("goa weather this weekend")
        assert intent.intent == "weather"

    def test_english_tomorrow_lucknow(self):
        intent, _ = classify_and_enhance("will it rain tomorrow in lucknow")
        assert intent.intent == "weather"


# ---------------------------------------------------------------------------
# 2. SPORTS (8)
# ---------------------------------------------------------------------------

class TestSports:
    def test_cricket_score(self):
        intent, q = classify_and_enhance("cricket score india vs australia")
        assert intent.intent == "sports"
        assert "score" in q.lower() or "cricket" in q.lower()

    def test_ipl_points_table(self):
        intent, _ = classify_and_enhance("ipl 2024 points table")
        assert intent.intent == "sports"

    def test_football_match(self):
        intent, _ = classify_and_enhance("manchester united vs liverpool score")
        assert intent.intent == "sports"

    def test_nba_scores(self):
        intent, _ = classify_and_enhance("nba scores today")
        assert intent.intent == "sports"

    def test_tennis(self):
        intent, _ = classify_and_enhance("tennis grand slam results")
        assert intent.intent == "sports"

    def test_f1_standings(self):
        intent, _ = classify_and_enhance("formula 1 standings 2024")
        assert intent.intent == "sports"

    def test_india_cricket_live(self):
        intent, _ = classify_and_enhance("india cricket match live")
        assert intent.intent == "sports"

    def test_football_world_cup(self):
        intent, _ = classify_and_enhance("football world cup schedule")
        assert intent.intent == "sports"


# ---------------------------------------------------------------------------
# 3. STOCK (7)
# ---------------------------------------------------------------------------

class TestStock:
    def test_reliance_price(self):
        intent, q = classify_and_enhance("reliance share price today")
        assert intent.intent == "stock"
        assert "reliance" in q.lower() or "share" in q.lower()

    def test_tcs_stock(self):
        intent, _ = classify_and_enhance("tcs stock price")
        assert intent.intent == "stock"

    def test_nifty(self):
        intent, _ = classify_and_enhance("nifty 50 live")
        assert intent.intent == "stock"

    def test_sensex(self):
        intent, _ = classify_and_enhance("sensex today")
        assert intent.intent == "stock"

    def test_hdfc_bank(self):
        intent, _ = classify_and_enhance("hdfc bank share price")
        assert intent.intent == "stock"

    def test_mutual_funds(self):
        intent, _ = classify_and_enhance("best mutual funds to invest")
        assert intent.intent in ("stock", "product")

    def test_infosys(self):
        intent, _ = classify_and_enhance("infosys stock analysis")
        assert intent.intent == "stock"


# ---------------------------------------------------------------------------
# 4. CURRENCY (6)
# ---------------------------------------------------------------------------

class TestCurrency:
    def test_usd_inr(self):
        intent, q = classify_and_enhance("usd to inr")
        assert intent.intent == "currency"
        assert "usd" in q.lower() or "inr" in q.lower()

    def test_dollar_rupee(self):
        intent, _ = classify_and_enhance("dollar to rupee exchange rate")
        assert intent.intent == "currency"

    def test_euro_rupees(self):
        intent, _ = classify_and_enhance("100 euro in indian rupees")
        assert intent.intent == "currency"

    def test_gbp_inr(self):
        intent, _ = classify_and_enhance("gbp to inr")
        assert intent.intent == "currency"

    def test_yen_dollar(self):
        intent, _ = classify_and_enhance("japanese yen to dollar")
        assert intent.intent == "currency"

    def test_aud_exchange(self):
        intent, _ = classify_and_enhance("australian dollar exchange rate")
        assert intent.intent == "currency"


# ---------------------------------------------------------------------------
# 5. FLIGHT (5)
# ---------------------------------------------------------------------------

class TestFlight:
    def test_ai302(self):
        intent, q = classify_and_enhance("ai 302 flight status")
        assert intent.intent == "flight"

    def test_indigo_delay(self):
        intent, _ = classify_and_enhance("indigo flight delay")
        assert intent.intent == "flight"

    def test_emirates(self):
        intent, _ = classify_and_enhance("emirates flight tracking")
        assert intent.intent == "flight"

    def test_mumbai_delhi(self):
        intent, _ = classify_and_enhance("mumbai to delhi flights")
        assert intent.intent == "flight"

    def test_vistara(self):
        intent, _ = classify_and_enhance("vistara flight status today")
        assert intent.intent == "flight"


# ---------------------------------------------------------------------------
# 6. FOOD (5)
# ---------------------------------------------------------------------------

class TestFood:
    def test_biryani(self):
        intent, q = classify_and_enhance("chicken biryani recipe")
        assert intent.intent == "food"

    def test_pasta(self):
        intent, _ = classify_and_enhance("how to make pasta at home")
        assert intent.intent == "food"

    def test_restaurants(self):
        intent, _ = classify_and_enhance("best pizza restaurants near me")
        assert intent.intent == "food"

    def test_cake(self):
        intent, _ = classify_and_enhance("chocolate cake recipe easy")
        assert intent.intent == "food"

    def test_vegan(self):
        intent, _ = classify_and_enhance("vegan dinner ideas")
        assert intent.intent == "food"


# ---------------------------------------------------------------------------
# 7. HEALTH (5)
# ---------------------------------------------------------------------------

class TestHealth:
    def test_fever(self):
        intent, _ = classify_and_enhance("fever symptoms and treatment")
        assert intent.intent == "health"

    def test_headache(self):
        intent, _ = classify_and_enhance("headache medicine")
        assert intent.intent == "health"

    def test_blood_pressure(self):
        intent, _ = classify_and_enhance("how to reduce blood pressure")
        assert intent.intent == "health"

    def test_diabetes(self):
        intent, _ = classify_and_enhance("diabetes symptoms")
        assert intent.intent == "health"

    def test_yoga_pain(self):
        intent, _ = classify_and_enhance("yoga for back pain")
        assert intent.intent == "health"


# ---------------------------------------------------------------------------
# 8. ENTERTAINMENT (5)
# ---------------------------------------------------------------------------

class TestEntertainment:
    def test_netflix(self):
        intent, _ = classify_and_enhance("netflix new series 2024")
        assert intent.intent == "entertainment"

    def test_avengers(self):
        intent, _ = classify_and_enhance("avengers movie release date")
        assert intent.intent == "entertainment"

    def test_taylor_swift(self):
        intent, _ = classify_and_enhance("taylor swift concert tickets")
        assert intent.intent == "entertainment"

    def test_anime(self):
        intent, _ = classify_and_enhance("best anime to watch")
        assert intent.intent == "entertainment"

    def test_bollywood(self):
        intent, _ = classify_and_enhance("new bollywood movies this week")
        assert intent.intent == "entertainment"


# ---------------------------------------------------------------------------
# 9. PRODUCT (5)
# ---------------------------------------------------------------------------

class TestProduct:
    def test_phone_budget(self):
        intent, q = classify_and_enhance("best phone under 20000")
        assert intent.intent == "product"
        assert "20000" in q or "phone" in q.lower()

    def test_laptops(self):
        intent, _ = classify_and_enhance("top 10 laptops 2024")
        assert intent.intent == "product"

    def test_earbuds(self):
        intent, _ = classify_and_enhance("best wireless earbuds under 5000")
        assert intent.intent == "product"

    def test_samsung_vs_iphone(self):
        intent, _ = classify_and_enhance("samsung vs iphone comparison")
        assert intent.intent == "product"

    def test_gaming_monitor(self):
        intent, _ = classify_and_enhance("best gaming monitor")
        assert intent.intent == "product"


# ---------------------------------------------------------------------------
# 10. CODE (3)
# ---------------------------------------------------------------------------

class TestCode:
    def test_python_sort(self):
        intent, _ = classify_and_enhance("python sort list by multiple keys")
        assert intent.intent == "code"

    def test_javascript_async(self):
        intent, _ = classify_and_enhance("javascript async await tutorial")
        assert intent.intent == "code"

    def test_fastapi(self):
        intent, _ = classify_and_enhance("how to create a REST API in fastapi")
        assert intent.intent == "code"


# ---------------------------------------------------------------------------
# 11. MATH (2)
# ---------------------------------------------------------------------------

class TestMath:
    def test_calculate(self):
        intent, _ = classify_and_enhance("calculate 15% of 500")
        assert intent.intent == "math"

    def test_square_root(self):
        intent, _ = classify_and_enhance("what is the square root of 144")
        assert intent.intent == "math"


# ---------------------------------------------------------------------------
# 12. NEWS (3)
# ---------------------------------------------------------------------------

class TestNews:
    def test_latest_news_ai(self):
        intent, _ = classify_and_enhance("latest news about AI")
        assert intent.intent == "news"

    def test_today_headlines(self):
        intent, _ = classify_and_enhance("today headlines india")
        assert intent.intent == "news"

    def test_breaking_news(self):
        intent, _ = classify_and_enhance("breaking news about elections")
        assert intent.intent == "news"


# ---------------------------------------------------------------------------
# 13. GENERAL (4)
# ---------------------------------------------------------------------------

class TestGeneral:
    def test_quantum(self):
        intent, _ = classify_and_enhance("what is quantum entanglement")
        assert intent.intent == "general"

    def test_ml(self):
        intent, _ = classify_and_enhance("explain machine learning")
        assert intent.intent == "general"

    def test_photosynthesis(self):
        intent, _ = classify_and_enhance("how does photosynthesis work")
        assert intent.intent == "general"

    def test_haiku(self):
        intent, _ = classify_and_enhance("write a haiku about coding")
        assert intent.intent == "general"


# ---------------------------------------------------------------------------
# 14. HINGLISH SPECIFIC (5)
# ---------------------------------------------------------------------------

class TestHinglish:
    def test_barish_kya(self):
        intent, _ = classify_and_enhance("barish hogi kya aaj?")
        assert intent.intent == "weather"

    def test_india_score(self):
        intent, _ = classify_and_enhance("india ka score kya hai")
        assert intent.intent == "sports"

    def test_reliance_price(self):
        intent, _ = classify_and_enhance("reliance ka price kitna hai")
        assert intent.intent == "stock"

    def test_biryani_kaise(self):
        intent, _ = classify_and_enhance("biryani kaise banaye")
        assert intent.intent == "food"

    def test_bukhar_kya_karu(self):
        intent, _ = classify_and_enhance("bukhar hai kya karu")
        assert intent.intent == "health"


# ---------------------------------------------------------------------------
# 15. FOLLOW-UP CONTEXT PERSISTENCE (6)
# ---------------------------------------------------------------------------

class TestContextPersistence:
    def test_kal_after_weather(self):
        history = [("user", "lar deoria me barish hoga aaj?"), ("assistant", "Deoria me aaj 32°C hai")]
        intent, q = classify_and_enhance("kal?", history=history)
        assert intent.intent == "weather"
        assert "deoria" in q.lower() or "deoria" in str(intent.entities).lower()

    def test_aur_after_cricket(self):
        history = [("user", "india cricket score kya hai"), ("assistant", "India ka score 285/6 hai")]
        intent, _ = classify_and_enhance("aur?", history=history)
        assert intent.intent == "sports"

    def test_aur_after_stock(self):
        history = [("user", "reliance share price batao"), ("assistant", "Reliance ka price ₹2,450 hai")]
        intent, _ = classify_and_enhance("aur?", history=history)
        assert intent.intent == "stock"

    def test_kal_after_currency(self):
        history = [("user", "usd to inr kya hai"), ("assistant", "1 USD = ₹83.2 hai")]
        intent, _ = classify_and_enhance("kal ka rate?", history=history)
        assert intent.intent == "currency"

    def test_mumbai_after_delhi_weather(self):
        history = [("user", "weather in delhi today"), ("assistant", "Delhi me aaj 35°C hai")]
        intent, q = classify_and_enhance("what about mumbai?", history=history)
        assert intent.intent == "weather"
        assert "mumbai" in q.lower()

    def test_aur_after_product(self):
        history = [("user", "best phone under 20000"), ("assistant", "Realme Narzo 70X best hai")]
        intent, _ = classify_and_enhance("aur koi option?", history=history)
        assert intent.intent in ("product", "general")


# ---------------------------------------------------------------------------
# 16. KEYWORD FALLBACK (7)
# ---------------------------------------------------------------------------

class TestKeywordFallback:
    def test_fallback_weather_hinglish(self):
        intent = _fallback_classify("lar deoria me barish hoga aaj?")
        assert intent.intent == "weather"

    def test_fallback_weather_english(self):
        intent = _fallback_classify("what is the weather in delhi")
        assert intent.intent == "weather"

    def test_fallback_sports(self):
        intent = _fallback_classify("cricket score india")
        assert intent.intent == "sports"

    def test_fallback_stock(self):
        intent = _fallback_classify("reliance share price")
        assert intent.intent == "stock"

    def test_fallback_currency(self):
        intent = _fallback_classify("usd to inr")
        assert intent.intent == "currency"

    def test_fallback_general(self):
        intent = _fallback_classify("explain quantum computing")
        assert intent.intent == "general"

    def test_fallback_followup_kal(self):
        history = [("user", "lar deoria me barish hoga aaj?"), ("assistant", "Deoria me 32°C")]
        intent = _fallback_classify("kal?", history=history)
        assert intent.intent == "weather"


# ---------------------------------------------------------------------------
# 17. EDGE CASES (6)
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_empty_string(self):
        intent = _fallback_classify("")
        assert intent.intent == "general"

    def test_single_question_mark(self):
        intent = _fallback_classify("?")
        assert intent.intent == "general"

    def test_greeting(self):
        intent = _fallback_classify("hi")
        assert intent.intent == "general"

    def test_numbers_only(self):
        intent = _fallback_classify("12345")
        assert intent.intent == "general"

    def test_random_words(self):
        intent = _fallback_classify("abc xyz pqr")
        assert intent.intent == "general"

    def test_no_crash_on_llm_call(self):
        intent, q = classify_and_enhance("test query that should not crash")
        assert isinstance(intent, QueryIntent)
        assert isinstance(q, str)


# ---------------------------------------------------------------------------
# 18. OUTPUT VALIDATION (10)
# ---------------------------------------------------------------------------

class TestOutputValidation:
    def _mock_intent(self, name):
        return QueryIntent(intent=name, language="en", search_query="test",
                           original="test", translated="test", entities={}, needs_web_search=True)

    def test_weather_shayari_invalid(self):
        results = [{"title": "Barish Shayari", "snippet": "Aaj mausam bhi lagta hai", "url": "http://x"}]
        v = validate_search_output(self._mock_intent("weather"), results)
        assert v.valid is False

    def test_weather_forecast_valid(self):
        results = [{"title": "Weather in Deoria", "snippet": "Temperature 32°C, Rain expected", "url": "http://x"}]
        v = validate_search_output(self._mock_intent("weather"), results)
        assert v.valid is True

    def test_sports_score_valid(self):
        results = [{"title": "India vs Australia Score", "snippet": "Live score: India 285/6", "url": "http://x"}]
        v = validate_search_output(self._mock_intent("sports"), results)
        assert v.valid is True

    def test_sports_no_data_invalid(self):
        results = [{"title": "Random Blog", "snippet": "Just a random blog", "url": "http://x"}]
        v = validate_search_output(self._mock_intent("sports"), results)
        assert v.valid is False

    def test_stock_price_valid(self):
        results = [{"title": "Reliance Stock", "snippet": "NSE: ₹2,450", "url": "http://x"}]
        v = validate_search_output(self._mock_intent("stock"), results)
        assert v.valid is True

    def test_stock_recipe_invalid(self):
        results = [{"title": "Biryani Recipe", "snippet": "How to make", "url": "http://x"}]
        v = validate_search_output(self._mock_intent("stock"), results)
        assert v.valid is False

    def test_currency_rate_valid(self):
        results = [{"title": "USD to INR", "snippet": "1 USD = ₹83.20", "url": "http://x"}]
        v = validate_search_output(self._mock_intent("currency"), results)
        assert v.valid is True

    def test_currency_weather_invalid(self):
        results = [{"title": "Weather Today", "snippet": "Sunny", "url": "http://x"}]
        v = validate_search_output(self._mock_intent("currency"), results)
        assert v.valid is False

    def test_flight_status_valid(self):
        results = [{"title": "AI 302 Status", "snippet": "On time", "url": "http://x"}]
        v = validate_search_output(self._mock_intent("flight"), results)
        assert v.valid is True

    def test_empty_results_invalid(self):
        v = validate_search_output(self._mock_intent("weather"), [])
        assert v.valid is False


# ---------------------------------------------------------------------------
# 19. AUTO-WEB-SEARCH ROUTING (12)
# ---------------------------------------------------------------------------

class TestAutoWebSearchRouting:
    @pytest.mark.parametrize("question", [
        "lar deoria me barish hoga aaj?",
        "cricket score india",
        "reliance share price",
        "usd to inr",
        "best phone under 20000",
        "weather in delhi",
        "barish hogi kya",
        "aaj ka mausam",
        "india ka score",
        "latest news about AI",
        "today headlines india",
        "stock market today",
    ])
    def test_should_trigger(self, question):
        assert should_auto_web_search(question) is True

    @pytest.mark.parametrize("question", [
        "explain quantum computing",
        "what is photosynthesis",
        "write a python function",
        "In how many companies has Sushil worked?",
    ])
    def test_should_not_trigger(self, question):
        assert should_auto_web_search(question) is False
