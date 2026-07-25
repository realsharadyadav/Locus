# Locus Diagnostics

Failed background chat jobs retain structured JSONL traces in `jobs/`.
Successful job traces are deleted automatically. Logs contain operational
metadata, timings, retry decisions, safe rate-limit headers, and sanitized
stack traces. API keys, prompts, document text, and generated answers are not
recorded.
