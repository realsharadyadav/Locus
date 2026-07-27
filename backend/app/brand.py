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
# Broad "ask anything about Locus" self-help coverage. This one DOES call the LLM (open-ended
# phrasing needs it), but it's grounded strictly in LOCUS_KNOWLEDGE_DOC below via
# generate_answer(..., system_override=...), which skips web search and the model's own
# "knowledge" entirely — both of which get confused with an unrelated real company also named
# Locus (see the "who built locus" incident this replaced). If it's not in the doc, the model is
# told to say so rather than fill the gap from outside knowledge.
_LOCUS_FEATURE_NAMES = (
    r"upload|ask(?:\s+module|\s+page)?|store|stores|library|patterns|private\s+chat|ticket(?:s|\s+analysis)?"
    r"|reasoning\s+modes?|hub|share|command\s+palette|light\s+mode|thinking\s+mode|unrestricted\s+mode|deep\s?summary"
)
ABOUT_LOCUS_QUESTION_PATTERN = re.compile(
    r"\blocus\b[^?.!]{0,40}\b(is|do|does|work|works|use|used|feature|features|help|guide|about|mean|means|for)\b"
    r"|\b(tell me about|what\s+is|what'?s|explain|describe)\b[^?.!]{0,15}\blocus\b"
    r"|\bhow\s+(do|can|does|is|are)\s+(the\s+|a\s+)?(i|you|locus|" + _LOCUS_FEATURE_NAMES + r")\b[^?.!]{0,60}"
    r"\b(upload|ask|store|stores|library|patterns|private\s+chat|ticket|reasoning\s+modes?|hub|share|work|works)\b"
    r"|\bwhat\s+(is|are)\b[^?.!]{0,25}\b(" + _LOCUS_FEATURE_NAMES + r")\b"
    r"|\b(user\s+guide|self.?help|getting\s+started|how\s+does\s+locus\s+work)\b",
    re.IGNORECASE,
)
LOCUS_KNOWLEDGE_DOC = f"""
{BRAND_NAME} — "{BRAND_TAGLINE}" — is a personal "second brain" app. Upload your own files, then
ask questions grounded in them, either strictly from those files or blended with general knowledge.
Built solo by {BRAND_CREATOR}.

Sections (left sidebar):
- Home: dashboard with stats (stores, files, chats) and quick actions (create a store, upload
  files, ask a question).
- Library: where uploaded files live, organized into "stores" (collections).
- Ask: the main chat. Type a question, optionally scope it to specific files, and pick a
  reasoning mode via slash command:
  - /light (default): fast, direct answers.
  - /unrestricted: expert mode, maximum detail, minimal hand-holding.
  - /thinking: deep, multi-step reasoning over everything selected.
  - /deepsummary: thorough, section-by-section coverage of a document.
  - /ticketanalysis: jumps into the Patterns pipeline for ticket exports.
  There's an "LLM Knowledge" toggle: on blends general knowledge in with your files; off means
  strictly file-only, no outside facts. You can pick the LLM provider/model (Ollama for
  local/private, or Groq/OpenAI/Gemini).
- Patterns: upload a ticket/incident export (CSV/TSV/XLSX/JSON/TXT/MD) and turn it into ranked
  "problem groups" — a pipeline of taxonomy matching, clustering, and optional LLM fallback, with
  a live console showing what's happening stage by stage, confidence scores, evidence, and run
  history you can compare.
- Private: a separate, ephemeral, shareable chat — generate a link, anyone who opens it can chat
  in real time, no account needed. Good for a quick throwaway conversation outside your main
  history.
- Settings: theme (light/dark) and default LLM provider/model.
- Command palette (Cmd/Ctrl+K): jump to any page, file, store, or chat instantly.

IMPORTANT: there is an unrelated real-world logistics/supply-chain company that also happens to
be called "Locus" (locus.sh). Completely ignore anything you know about that company or any other
product also named Locus — it has nothing to do with this app.
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
CHROMA_COLLECTION = "locus_chunks"
LEGACY_CHROMA_COLLECTION = "mindmap_chunks"
VECTOR_INDEX_FILENAME = "locus_vector_index.sqlite3"
LEGACY_VECTOR_INDEX_FILENAME = "mindmap_vector_index.sqlite3"
