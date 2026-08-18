"""Deterministic brand/self-awareness routing.

These questions bypass the LLM pipeline entirely (see brand.py for why: web search kept
grounding "who is Sharad Yadav" in the unrelated politician, and "Locus" in the unrelated
logistics company). The patterns are the whole guarantee, so they get direct coverage.
"""

import pytest

from backend.app.brand import (
    BRAND_CREATOR,
    CREATOR_NAME_PATTERN,
    CREATOR_QUESTION_PATTERN,
)


@pytest.mark.parametrize("question", [
    "who is sharad",           # first name alone — the common in-app phrasing
    "Who is Sharad",
    "who is sharad yadav",
    "who is Sharad Yadav",
    "who's sharad",
    "who was sharad yadav",
])
def test_creator_name_questions_match(question):
    assert CREATOR_NAME_PATTERN.search(question)


@pytest.mark.parametrize("question", [
    "who is john",
    "summarize the sharad report",       # a name inside a content question
    "what did sharad write in the doc",
])
def test_unrelated_questions_do_not_match_creator_name(question):
    assert not CREATOR_NAME_PATTERN.search(question)


@pytest.mark.parametrize("question", [
    "who built you",
    "who made locus",
    "who's your creator",
    "which company built this app",
    # "who'?s?" alone never allowed the spelled-out verb, so the most natural phrasing of
    # all used to fall through to the LLM and answer with whatever it felt like.
    "who is your developer",
    "who is the founder",
    "who is your owner",
    "who programmed you",
    "who owns locus",
    "made by whom",
    # Asked in Hinglish just as often as English.
    "tumhe kisne banaya",
    "kisne banaya hai tumhe",
])
def test_creator_questions_match(question):
    assert CREATOR_QUESTION_PATTERN.search(question)


@pytest.mark.parametrize("question", [
    # "the <role>" must not swallow questions about an uploaded document or the wider world.
    "who is the author of this PDF",
    "who is the owner of this contract",
    "who is the founder of Tesla",
    "who is the creator of Bitcoin",
    "who is the CEO of Google",
    "who wrote War and Peace",
])
def test_unrelated_questions_do_not_match_creator(question):
    assert not CREATOR_QUESTION_PATTERN.search(question)


def test_creator_name_pattern_tracks_the_brand_creator_constant():
    """The pattern is derived from BRAND_CREATOR, so renaming the constant must not
    silently leave the regex matching the old name."""
    first, last = BRAND_CREATOR.split()[0], BRAND_CREATOR.split()[-1]
    assert CREATOR_NAME_PATTERN.search(f"who is {first}")
    assert CREATOR_NAME_PATTERN.search(f"who is {first} {last}")
