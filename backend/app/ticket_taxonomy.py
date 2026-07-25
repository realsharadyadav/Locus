import re
from dataclasses import dataclass
from typing import Any

from .ticket_taxonomy_data import DEFAULT_TAXONOMY, DEFAULT_TAXONOMY_V2, TaxonomyRule, TaxonomyRuleV2


def normalize_signal(value: str | None) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", (value or "").lower()))


GENERIC_ALIAS_SIGNALS = {
    "access", "identity", "software", "platform", "application", "cloud",
    "hardware", "endpoint", "service", "support", "operations",
}
VAGUE_ONLY_SIGNALS = {
    "not working", "please check", "getting error", "same issue again",
    "issue", "error", "problem", "failed", "failure",
}
FAILURE_SIGNALS = (
    "failed", "failure", "down", "error", "outage", "degraded", "not working",
    "unavailable", "timeout", "denied", "not authorized", "unauthorized",
)
REQUEST_SIGNALS = (
    "need", "request", "provide", "create", "please create", "please provide",
    "new hire", "onboarding", "offboarding", "catalog item", "request item",
)
RECORD_TYPE_ALIASES = {
    "incident": ("inc", "incident", "bug"),
    "service_request": ("ritm", "sctask", "sr", "service request", "catalog task", "request item", "catalog item"),
    "change": ("chg", "change", "change request"),
    "problem": ("prb", "problem", "known error"),
    "alert": ("alrt", "ops", "alert"),
}


@dataclass(frozen=True)
class TaxonomyClassification:
    category: str
    confidence: str
    score: float
    matched_reason: str
    evidence: tuple[str, ...]
    alternatives: tuple[dict[str, Any], ...]
    subcategory: str | None = None
    manual_review_recommended: bool = False
    rule: TaxonomyRuleV2 | None = None
    record_type: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "confidence": self.confidence,
            "score": round(self.score, 2),
            "matched_reason": self.matched_reason,
            "evidence": list(self.evidence),
            "alternatives": list(self.alternatives),
            "subcategory": self.subcategory,
            "manual_review_recommended": self.manual_review_recommended,
            "record_type": self.record_type,
        }


@dataclass(frozen=True)
class TaxonomyMatch:
    rule: TaxonomyRule
    confidence: float
    reason: str


def _contains(signal: str, phrase: str) -> bool:
    pattern = normalize_signal(phrase)
    return bool(pattern) and f" {pattern} " in f" {signal} "


def _field(ticket: Any, names: tuple[str, ...]) -> str:
    if isinstance(ticket, dict):
        items = ticket.items()
    else:
        metadata = getattr(ticket, "metadata", {}) or {}
        values = {
            "title": getattr(ticket, "title", None),
            "summary": getattr(ticket, "title", None),
            "short_description": getattr(ticket, "title", None),
            "description": getattr(ticket, "description", None),
            "primary_text": getattr(ticket, "primary_text", None),
            **metadata,
        }
        items = values.items()
    indexed = {normalize_signal(str(key)): str(value or "") for key, value in items}
    for name in names:
        value = indexed.get(normalize_signal(name), "")
        if value.strip():
            return value.strip()
    return ""


def _ticket_parts(ticket: Any) -> tuple[str, str, str]:
    title = _field(ticket, ("short_description", "short description", "summary", "title"))
    description = _field(ticket, ("description", "comments", "work_notes", "work notes", "details", "primary_text"))
    metadata = " ".join(
        _field(ticket, (name,))
        for name in (
            "record_type", "type", "source_system", "number", "ticket_id", "incident_number",
            "assignment_group", "assignment group", "category", "subcategory",
            "business_service", "business service", "cmdb_ci", "component", "labels",
            "application", "service", "ci",
        )
    )
    return normalize_signal(title), normalize_signal(description), normalize_signal(metadata)


def _detect_record_type_from_signals(title: str, description: str, metadata: str) -> str | None:
    combined = " ".join((metadata, title, description))
    raw_id = " ".join(re.findall(r"\b[A-Z]{2,8}[-_]?\d+\b", " ".join((metadata, title, description)).upper()))
    if re.search(r"\b(INC|BUG)[-_]?\d+\b", raw_id) or any(_contains(combined, phrase) for phrase in ("incident", "issue", "error", "down", "failed", "not working", "outage")):
        detected = "incident"
    else:
        detected = None
    if re.search(r"\b(RITM|SCTASK|SR|REQ)[-_]?\d+\b", raw_id) or any(_contains(combined, phrase) for phrase in ("service request", "catalog task", "request item", "catalog item")):
        detected = "service_request"
    if re.search(r"\bCHG[-_]?\d+\b", raw_id) or any(_contains(combined, phrase) for phrase in ("deployment", "release", "upgrade", "maintenance", "change request")):
        detected = "change"
    if re.search(r"\bPRB[-_]?\d+\b", raw_id) or any(_contains(combined, phrase) for phrase in ("rca", "recurring issue", "known error", "permanent fix")):
        detected = "problem"
    if re.search(r"\b(ALRT|OPS)[-_]?\d+\b", raw_id) or any(_contains(combined, phrase) for phrase in ("monitoring", "threshold", "siem", "edr", "health check")):
        detected = "alert"
    explicit = next((record for record, aliases in RECORD_TYPE_ALIASES.items() if any(_contains(metadata, alias) for alias in aliases)), None)
    return explicit or detected


def _best_subcategory(rule: TaxonomyRuleV2, evidence: list[str]) -> str | None:
    joined = normalize_signal(" ".join(evidence))
    for subcategory in rule.subcategories:
        terms = normalize_signal(subcategory)
        if any(term and term in joined for term in terms.split()):
            return subcategory
    return rule.subcategories[0] if rule.subcategories else None


def _rule_by_name(name: str, taxonomy: tuple[TaxonomyRuleV2, ...]) -> TaxonomyRuleV2:
    normalized = normalize_signal(name)
    return next(rule for rule in taxonomy if normalize_signal(rule.name) == normalized)


def _classification(
    rule: TaxonomyRuleV2,
    score: float,
    reason: str,
    evidence: list[str],
    alternatives: list[dict[str, Any]] | None = None,
    *,
    record_type: str | None,
    confidence: str | None = None,
    manual_review: bool = False,
    subcategory: str | None = None,
) -> TaxonomyClassification:
    if confidence is None:
        confidence = "high" if score >= 8 and not manual_review else "medium" if score >= 4.5 else "low"
    return TaxonomyClassification(
        category=rule.name,
        confidence=confidence,
        score=score,
        matched_reason=reason,
        evidence=tuple(evidence[:8]),
        alternatives=tuple((alternatives or [])[:3]),
        subcategory=subcategory or _best_subcategory(rule, evidence),
        manual_review_recommended=manual_review or confidence == "low",
        rule=rule,
        record_type=record_type,
    )


def _override_classification(title: str, description: str, metadata: str, record_type: str | None, taxonomy: tuple[TaxonomyRuleV2, ...]) -> TaxonomyClassification | None:
    combined = " ".join((title, description, metadata))
    strong_failure = any(_contains(combined, phrase) for phrase in FAILURE_SIGNALS)
    service_requestish = record_type == "service_request" and any(_contains(combined, phrase) for phrase in REQUEST_SIGNALS + ("access", "laptop", "software"))
    overrides = [
        (("port needs to be allowed", "firewall", "traffic denied", "port blocked"), "Network, VPN, DNS & Firewall Issues", "firewall_proxy"),
        (("api 401", "api 403", "http 401", "http 403", "oauth", "client credentials", "payload", "webhook", "queue"), "Integration, API & Middleware Failures", None),
        (("database login", "db connection", "database connection", "query timeout", "deadlock", "replication"), "Database Reliability & Performance", None),
    ]
    for phrases, name, subcategory in overrides:
        matched = next((phrase for phrase in phrases if _contains(combined, phrase)), None)
        if matched:
            rule = _rule_by_name(name, taxonomy)
            return _classification(rule, 12, f'override: matched "{matched}"', [matched], record_type=record_type, confidence="high", subcategory=subcategory)
    cloud_evidence = any(_contains(combined, phrase) for phrase in ("kubernetes", "k8s", "pod", "node", "cluster", "crashloopbackoff"))
    devops_phrase = next((phrase for phrase in ("deployment failed", "pipeline failed", "terraform", "helm upgrade failed", "artifact missing", "rollback failed") if _contains(combined, phrase)), None)
    if devops_phrase and not cloud_evidence:
        rule = _rule_by_name("DevOps, CI/CD & Release Deployment Issues", taxonomy)
        return _classification(rule, 12, f'override: matched "{devops_phrase}"', [devops_phrase], record_type=record_type, confidence="high")
    request_phrase = next((phrase for phrase in ("request new laptop", "need laptop", "request monitor", "new joiner laptop") if _contains(combined, phrase)), None)
    if request_phrase:
        rule = _rule_by_name("Service Request Fulfillment", taxonomy)
        return _classification(rule, 12, f'override: matched "{request_phrase}"', [request_phrase], record_type=record_type, confidence="high", subcategory="hardware_request")
    lifecycle_phrase = next((phrase for phrase in ("offboarding request", "new hire", "create account", "onboarding checklist") if _contains(combined, phrase)), None)
    if lifecycle_phrase:
        lifecycle_evidence = any(_contains(combined, phrase) for phrase in ("hr feed", "sync", "scim", "identity lifecycle", "account lifecycle", "jml"))
        name = "Identity Directory Sync & Account Lifecycle Issues" if lifecycle_evidence and strong_failure else "Service Request Fulfillment"
        rule = _rule_by_name(name, taxonomy)
        return _classification(rule, 11, f'override: matched "{lifecycle_phrase}"', [lifecycle_phrase], record_type=record_type, confidence="high" if service_requestish else "medium", subcategory="onboarding_offboarding")
    access_request = next((phrase for phrase in ("access chahiye", "need access", "request access", "provide access") if _contains(combined, phrase)), None)
    if access_request and record_type == "service_request":
        rule = _rule_by_name("Service Request Fulfillment", taxonomy)
        return _classification(rule, 12, f'override: service request matched "{access_request}"', [access_request], record_type=record_type, confidence="high", subcategory="access_request")
    access_failure = next((phrase for phrase in ("access denied", "permission denied", "not authorized", "unauthorized") if _contains(combined, phrase)), None)
    if access_failure and strong_failure:
        rule = _rule_by_name("Access Provisioning, Authorization & Licensing Issues", taxonomy)
        return _classification(rule, 11, f'override: failure matched "{access_failure}"', [access_failure], record_type=record_type, confidence="high")
    if service_requestish and not strong_failure:
        rule = _rule_by_name("Service Request Fulfillment", taxonomy)
        return _classification(rule, 9, "override: request-style service request without strong failure evidence", ["service request", "request intent"], record_type=record_type, confidence="high")
    return None


def classify_ticket_v2(ticket: Any, taxonomy: tuple[TaxonomyRuleV2, ...] = DEFAULT_TAXONOMY_V2) -> TaxonomyClassification:
    title_signal, description_signal, metadata_signal = _ticket_parts(ticket)
    combined_signal = " ".join((title_signal, description_signal, metadata_signal))
    record_type = _detect_record_type_from_signals(title_signal, description_signal, metadata_signal)
    override = _override_classification(title_signal, description_signal, metadata_signal, record_type, taxonomy)
    if override:
        return override

    candidates: list[tuple[float, int, TaxonomyRuleV2, list[str], list[str]]] = []
    for order, rule in enumerate(taxonomy):
        if any(_contains(combined_signal, phrase) for phrase in rule.excludes):
            continue
        score = 0.0
        evidence: list[str] = []
        reasons: list[str] = []
        for phrase in rule.includes:
            phrase_signal = normalize_signal(phrase)
            if phrase_signal in GENERIC_ALIAS_SIGNALS:
                continue
            if _contains(title_signal, phrase):
                score += 5 + min(2, len(phrase_signal.split()) * 0.15)
                evidence.append(phrase)
                reasons.append(f'title matched "{phrase}"')
            elif _contains(description_signal, phrase):
                score += 3 + min(1.5, len(phrase_signal.split()) * 0.1)
                evidence.append(phrase)
                reasons.append(f'description matched "{phrase}"')
            elif _contains(metadata_signal, phrase):
                score += 2
                evidence.append(phrase)
                reasons.append(f'metadata matched "{phrase}"')
        for context in rule.contexts:
            if normalize_signal(context) not in GENERIC_ALIAS_SIGNALS and _contains(combined_signal, context):
                score += 1
                evidence.append(context)
                reasons.append(f'context matched "{context}"')
                break
        for hint in rule.assignment_hints:
            if _contains(metadata_signal, hint):
                score += 2.5
                evidence.append(hint)
                reasons.append(f'assignment hint matched "{hint}"')
                break
        if record_type and rule.record_types:
            if record_type in rule.record_types:
                score += 2
                reasons.append(f"record type matched {record_type}")
            else:
                score -= 3
                reasons.append(f"record type mismatch {record_type}")
        if score > 0:
            candidates.append((score, -order, rule, evidence, reasons))
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    if not candidates:
        return TaxonomyClassification("Unclassified / Needs Review", "low", 0, "no taxonomy evidence matched", (), (), None, True, None, record_type)
    score, _, rule, evidence, reasons = candidates[0]
    alternatives = [
        {"category": candidate.name, "score": round(candidate_score, 2)}
        for candidate_score, __, candidate, ___, ____ in candidates[1:4]
    ]
    vague_only = any(_contains(combined_signal, phrase) for phrase in VAGUE_ONLY_SIGNALS) and not any(len(normalize_signal(item).split()) > 1 for item in evidence)
    manual_review = vague_only or score < 4.5 or (len(candidates) > 1 and score - candidates[1][0] < 1.5)
    confidence = "high" if score >= 8 and not vague_only and not manual_review else "medium" if score >= 4.5 else "low"
    return _classification(rule, score, "; ".join(reasons[:4]), evidence, alternatives, record_type=record_type, confidence=confidence, manual_review=manual_review)


def find_taxonomy_match(
    category: str | None,
    subcategory: str | None,
    titles: list[str],
    descriptions: list[str],
    taxonomy: tuple[TaxonomyRule, ...] = DEFAULT_TAXONOMY,
) -> TaxonomyMatch | None:
    """Return the strongest explainable parent match using structured fields first."""

    category_signal = normalize_signal(category)
    subcategory_signal = normalize_signal(subcategory)
    title_signal = normalize_signal(" ".join(titles))
    description_signal = normalize_signal(" ".join(descriptions))
    def contains(signal: str, pattern: str) -> bool:
        return bool(pattern) and f" {pattern} " in f" {signal} "

    best: tuple[int, int, TaxonomyRule, str, str] | None = None
    for order, rule in enumerate(taxonomy):
        patterns = tuple(normalize_signal(pattern) for pattern in rule.patterns)
        exclude_patterns = tuple(normalize_signal(pattern) for pattern in getattr(rule, "excludes", ()))
        combined_signal = " ".join((category_signal, subcategory_signal, title_signal, description_signal))
        if any(contains(combined_signal, pattern) for pattern in exclude_patterns):
            continue
        field_matches: list[tuple[int, str, str]] = []
        # Longer child phrases beat generic fragments (for example,
        # "suspicious login" should outrank the generic child "login").
        # Use the strongest child phrase per field. Summing overlapping synonyms
        # (for example "privileged access" + "access review") would let broad
        # rules overpower a more specific parent phrase.
        subcategory_matches = [(12 + len(pattern.split()), "subcategory", pattern) for pattern in patterns if contains(subcategory_signal, pattern)]
        title_matches = [(7 + len(pattern.split()), "title", pattern) for pattern in patterns if contains(title_signal, pattern)]
        description_matches = [(2 + len(pattern.split()), "description", pattern) for pattern in patterns if contains(description_signal, pattern)]
        for matches in (subcategory_matches, title_matches, description_matches):
            if matches:
                field_matches.append(max(matches))
        aliases = {normalize_signal(alias) for alias in rule.category_aliases}
        if category_signal in aliases:
            field_matches.append((8, "category", category_signal))
        score = sum(match[0] for match in field_matches)
        strongest = max(field_matches, default=(0, "", ""))
        candidate = (score, -order, rule, strongest[1], strongest[2])
        if score and (best is None or candidate[:2] > best[:2]):
            best = candidate
    if not best:
        return None
    _, _, rule, field, phrase = best
    base_confidence = {"subcategory": 0.96, "title": 0.92, "description": 0.87, "category": 0.84}[field]
    return TaxonomyMatch(rule, base_confidence, f'taxonomy: {field} matched "{phrase}"')


def match_taxonomy_rule(
    category: str | None,
    subcategory: str | None,
    titles: list[str],
    descriptions: list[str],
    taxonomy: tuple[TaxonomyRule, ...] = DEFAULT_TAXONOMY,
) -> TaxonomyRule | None:
    """Compatibility wrapper for callers that need only the matched rule."""
    match = find_taxonomy_match(category, subcategory, titles, descriptions, taxonomy)
    return match.rule if match else None
