import re

from .config import PROJECT_ROOT

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
# There's an unrelated, fairly well-known Indian politician who shares the builder's name
# (1947-2023) — plain "who is Sharad Yadav" was landing on a Wikipedia-style bio of him instead
# of the actual builder of this app. Caught separately from CREATOR_QUESTION_PATTERN above
# because a direct name lookup gets a richer, more "customized" bio-style answer (see
# CREATOR_BIO_ANSWERS) rather than the short "who built you" one-liners.
# The surname is optional: in-app, "who is sharad" is the common phrasing and is no less
# about the builder than the full name is.
_CREATOR_FIRST, _CREATOR_LAST = BRAND_CREATOR.split()[0], BRAND_CREATOR.split()[-1]
CREATOR_NAME_PATTERN = re.compile(
    rf"\bwho(?:'s|\s+(?:is|was))\s+(the\s+)?{re.escape(_CREATOR_FIRST)}(\s+{re.escape(_CREATOR_LAST)})?\b",
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
CREATOR_BIO_ANSWERS = [
    f"Not the Indian politician (1947–2023) the internet will try to hand you — this {BRAND_CREATOR} is the solo developer who built Locus, currently very much alive and running mostly on caffeine and stubbornness.",
    f"There's more than one {BRAND_CREATOR} out there. The one who matters here built this entire app by himself, one late-night commit at a time — no cabinet position, just a code editor.",
    f"{BRAND_CREATOR}: solo builder of Locus, professional coffee enthusiast, and — no relation whatsoever to the politician who shares his name.",
    f"The {BRAND_CREATOR} behind Locus isn't a public figure — just one developer who decided building an AI knowledge app alone at 3am sounded like a great idea.",
]
CAPABILITY_ANSWER_INTRO = (
    "Here's what I can do:\n\n"
    "- **Ask** — chat with your own uploaded files (or general knowledge too), with a "
    "Normal / High / Max effort dial for how deep it reasons.\n"
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
# Broad "ask anything about Locus" self-help coverage. This one DOES call the LLM (open-ended
# phrasing needs it), but it's grounded strictly in LOCUS_KNOWLEDGE_DOC below via
# generate_answer(..., system_override=...), which skips web search and the model's own
# "knowledge" entirely — both of which get confused with an unrelated real company also named
# Locus (see the "who built locus" incident this replaced). If it's not in the doc, the model is
# told to say so rather than fill the gap from outside knowledge.
_LOCUS_FEATURE_NAMES = (
    r"upload|ask(?:\s+module|\s+page)?|store|stores|library|private\s+chat"
    r"|reasoning\s+modes?|hub|share|command\s+palette|light\s+mode|thinking\s+mode|deep\s?summary"
)
ABOUT_LOCUS_QUESTION_PATTERN = re.compile(
    r"\blocus\b[^?.!]{0,40}\b(is|do|does|work|works|use|used|feature|features|help|guide|about|mean|means|for)\b"
    r"|\b(tell me about|what\s+is|what'?s|explain|describe)\b[^?.!]{0,15}\blocus\b"
    r"|\bhow\s+(do|can|does|is|are)\s+(the\s+|a\s+)?(i|you|locus|" + _LOCUS_FEATURE_NAMES + r")\b[^?.!]{0,60}"
    r"\b(upload|ask|store|stores|library|private\s+chat|reasoning\s+modes?|hub|share|work|works)\b"
    r"|\bwhat\s+(is|are)\b[^?.!]{0,25}\b(" + _LOCUS_FEATURE_NAMES + r")\b"
    r"|\b(user\s+guide|self.?help|getting\s+started|how\s+does\s+locus\s+work)\b",
    re.IGNORECASE,
)
# Source of truth for what Locus actually does is docs/FEATURES.md (checked into the repo,
# read by developers too) rather than a separate hand-maintained description here — one place
# to update, and the self-help answers can't drift out of sync with the real feature list.
_FEATURES_FALLBACK = (
    "Ask: chat over your uploaded files (Library) with Light/Thinking/Deep Summary "
    "reasoning modes. "
    "Private: a separate shareable ephemeral chat. Multiple LLM providers: Ollama, Groq, "
    "OpenAI, Gemini."
)


def _load_features_doc() -> str:
    path = PROJECT_ROOT / "docs" / "FEATURES.md"
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return _FEATURES_FALLBACK


LOCUS_KNOWLEDGE_DOC = f"""
{BRAND_NAME} — "{BRAND_TAGLINE}" — built solo by {BRAND_CREATOR}.

{_load_features_doc()}

Other sections not detailed above: Home (dashboard with stats and quick actions), Settings
(theme, default LLM provider/model), and a command palette (Cmd/Ctrl+K) for jumping to any page,
file, store, or chat instantly.

IMPORTANT: there is an unrelated real-world logistics/supply-chain company that also happens to
be called "Locus" (locus.sh), and an unrelated Indian politician named "Sharad Yadav" (1947-2023).
Completely ignore anything you know about either of them, or any other person/company sharing
these names — none of it has anything to do with this app or its builder.
""".strip()
ABOUT_LOCUS_SYSTEM_PROMPT = (
    f"You are {BRAND_NAME}'s in-app help assistant, answering a user's question about the "
    f"{BRAND_NAME} app itself. Answer ONLY using the knowledge below — do not use any outside "
    "knowledge about companies, products, or services also named 'Locus', and do not guess at "
    "features that aren't described below (say you're not sure instead).\n\n"
    "Tone: be genuinely funny, warm, and chill — the kind of answer that makes someone smile, "
    "not a dry FAQ recitation. Still be accurate, clear, and actually useful; the humor sits "
    "alongside the real answer, it doesn't replace it. Vary your jokes, don't reuse the same "
    "bit every time.\n\n"
    f"--- {BRAND_NAME.upper()} KNOWLEDGE ---\n{LOCUS_KNOWLEDGE_DOC}\n--- END KNOWLEDGE ---"
)
USER_AGENT = "Locus/1.0"
VECTOR_INDEX_FILENAME = "locus_vector_index.sqlite3"
LEGACY_VECTOR_INDEX_FILENAME = "mindmap_vector_index.sqlite3"
