import re

BRAND_NAME = "Locus"
BRAND_ASSISTANT = "Locus AI"
BRAND_TAGLINE = "Your knowledge, one question away."
BRAND_CREATOR = "Sharad Yadav"

# These questions are answered deterministically in main.py (see CREATOR_QUESTION_PATTERN /
# CAPABILITY_QUESTION_PATTERN below), bypassing the normal LLM routing entirely. A soft
# instruction folded into a system prompt turned out to be unreliable in production: web-search
# auto-trigger pulled in evidence about an unrelated real company also named "Locus" and the
# model grounded its answer in that instead, and some reasoning modes (e.g. "Thinking") route
# through code paths that never see the system prompt with the note at all. Deterministic
# pattern matching guarantees the joke actually shows up every time, in every mode.
CREATOR_QUESTION_PATTERN = re.compile(
    r"\bwho'?s?\s+(your|the)\s+(creator|maker|developer|dev|founder|builder)\b"
    r"|\b(who|which\s+company|what\s+company)\b[^?.!]{0,25}"
    r"\b(built|build|made|make|creat(?:e|ed)|develop(?:ed)?|design(?:ed)?|coded|code|wrote|write|behind)\b"
    r"[^?.!]{0,20}\b(you|u|locus|this\s+app|this\s+site|this\s+thing)\b",
    re.IGNORECASE,
)
CAPABILITY_QUESTION_PATTERN = re.compile(
    r"\bwhat\s+can\s+(you|locus|it)\s+do\b"
    r"|\byour\s+capabilit(?:y|ies)\b"
    r"|\bwhat\s+are\s+you\s+capable\s+of\b"
    r"|\bwhat\s+features\s+do\s+you\s+have\b"
    r"|\bwhat\s+do\s+you\s+do\b",
    re.IGNORECASE,
)
CREATOR_JOKE_ANSWERS = [
    f"I was built solo by {BRAND_CREATOR} — a guy who apparently thinks 3am is prime working hours and 'sleep' is a suggestion, not a requirement. 😅",
    f"One person: {BRAND_CREATOR}. Zero co-founders. Several sleepless nights. That's the whole origin story.",
    f"{BRAND_CREATOR} built me, solo, fueled by caffeine and some genuinely questionable sleep decisions.",
    f"Built end-to-end by {BRAND_CREATOR}, who coded me instead of sleeping — a very indie-developer move.",
]
CAPABILITY_ANSWER_INTRO = (
    "Here's what I can do:\n\n"
    "- **Ask** — chat with your own uploaded files (or general knowledge too), with Light, "
    "Unrestricted, Thinking (deep multi-step reasoning), and Deep Summary modes.\n"
    "- **Patterns** — turn a ticket/incident export into ranked, explainable problem groups "
    "with a live pipeline view of what's happening.\n"
    "- **Private Chat** — spin up a separate, shareable, ephemeral chat outside your main workspace.\n"
    "- **Library** — organize and search across everything you've uploaded, across multiple LLM "
    "providers (Ollama, Groq, OpenAI, Gemini)."
)
CAPABILITY_JOKE_CLOSERS = [
    f"— all built solo by {BRAND_CREATOR}, who clearly needed a hobby other than sleep. 😄",
    f"— the work of one person, {BRAND_CREATOR}, powered by an unreasonable amount of coffee.",
    f"— {BRAND_CREATOR} built this whole thing alone, which explains a few of the 3am commit timestamps.",
    f"— brought to you by {BRAND_CREATOR}, solo developer and part-time insomniac.",
]
USER_AGENT = "Locus/1.0"
CHROMA_COLLECTION = "locus_chunks"
LEGACY_CHROMA_COLLECTION = "mindmap_chunks"
VECTOR_INDEX_FILENAME = "locus_vector_index.sqlite3"
LEGACY_VECTOR_INDEX_FILENAME = "mindmap_vector_index.sqlite3"
