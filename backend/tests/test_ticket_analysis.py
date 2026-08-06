import json
from types import SimpleNamespace

from backend.app.main import _pipeline_event_metadata, _ticket_analysis_for_file
from backend.app.ticket_analysis import analyze_ticket_rows, clean_tickets, normalize_ticket
from backend.app.ticket_taxonomy import DEFAULT_TAXONOMY, classify_ticket_v2
from backend.app.ticket_taxonomy import TaxonomyRule


def test_normalization_prioritizes_known_fields_and_preserves_metadata():
    ticket = normalize_ticket({
        "number": "INC001", "short_description": "VPN login fails",
        "description": "Authentication fails after reset", "priority": "P2",
    })
    assert ticket.ticket_id == "INC001"
    assert ticket.title == "VPN login fails"
    assert ticket.description == "Authentication fails after reset"
    assert ticket.primary_text == "VPN login fails\nAuthentication fails after reset"
    assert ticket.metadata == {"priority": "P2"}


def test_normalization_aliases_description_only_and_fallback():
    assert normalize_ticket({"summary": "Email is delayed"}).title == "Email is delayed"
    assert normalize_ticket({"details": "Mailbox cannot sync"}).description == "Mailbox cannot sync"
    fallback = normalize_ticket({"record": "R-1", "customer_message": "Printer shows offline"})
    assert "Printer shows offline" in fallback.primary_text


def test_cleaning_keeps_repeated_descriptions_with_distinct_ids():
    tickets, empty, duplicates = clean_tickets([
        {"title": "VPN login fails", "number": "1"},
        {"title": "  VPN   login fails ", "number": "2"},
        {"title": "A different description", "number": "2"},
        {"title": ""},
    ])
    assert len(tickets) == 2
    assert empty == 1
    assert duplicates == 1
    assert [ticket.ticket_id for ticket in tickets] == ["1", "2"]


def test_cleaning_uses_full_row_when_identifiers_are_missing():
    tickets, _, duplicates = clean_tickets([
        {"title": "VPN login fails", "location": "Pune"},
        {"title": "VPN login fails", "location": "Mumbai"},
        {"title": "VPN login fails", "location": "Pune"},
    ])
    assert len(tickets) == 2
    assert duplicates == 1


def test_grouping_counts_percentages_sorting_and_coverage():
    rows = [
        {"number": "1", "title": "VPN connection timeout", "description": "VPN connection times out during login"},
        {"number": "2", "title": "VPN connection timeout", "description": "VPN connection times out after login"},
        {"number": "3", "title": "Email delivery delayed", "description": "Outbound email delivery is delayed"},
    ]
    result = analyze_ticket_rows(rows, similarity_threshold=0.55)
    assert [group["incidentCount"] for group in result["groups"]] == [2, 1]
    assert sum(group["percentage"] for group in result["groups"]) == 100.0
    assert all(group["groupName"] and group["description"] for group in result["groups"])
    assert result["manifest"] == {
        "totalRows": 3, "validTickets": 3, "emptyTicketsRemoved": 0,
        "duplicatesRemoved": 0, "processedTickets": 3, "problemGroups": 2,
        "coverageStatus": "complete", "taxonomyRules": len(DEFAULT_TAXONOMY),
        "llmFallbackStatus": "disabled",
        "llmLabelStatus": "disabled", "llmGroupsRenamed": 0,
        "taxonomySuggestionStatus": "disabled",
        "embeddingMethod": "tfidf", "clusteringMethod": "taxonomy_semantic",
    }


def test_ticket_analysis_endpoint_handler_for_csv(tmp_path, monkeypatch):
    monkeypatch.setattr("backend.app.main.UPLOAD_DIR", tmp_path)
    path = tmp_path / "stored.csv"
    path.write_text("number,title,description\n1,VPN timeout,VPN connection timeout\n2,VPN timeout,VPN connection timeout again\n3,Email delayed,Email delivery delayed\n")
    result = _ticket_analysis_for_file(SimpleNamespace(stored_name=path.name))
    assert result["manifest"]["processedTickets"] == 3
    assert result["manifest"]["coverageStatus"] == "complete"
    assert "rootCause" not in json.dumps(result)


def test_hierarchical_analysis_preserves_all_150_incidents():
    distribution = {
        "Security": (28, ["Malware Alert", "Policy Violation", "Access Review", "Suspicious Login", "Phishing"]),
        "Access": (22, ["Account Lockout", "Role Mapping", "SSO", "MFA", "Password Reset"]),
        "Cloud": (19, ["Compute", "Secrets", "Storage", "Load Balancer", "Kubernetes"]),
        "Database": (18, ["Replication Lag", "Connection Failure", "Storage", "Query Timeout", "Deadlock"]),
        "Integration": (18, ["API Failure", "Webhook Failure", "Authentication", "Queue Delay", "Payload Error"]),
        "Software": (17, ["Application Error", "Data Mismatch", "Login Issue", "UI Issue", "Performance"]),
        "Hardware": (15, ["Laptop", "Scanner", "Monitor", "Peripheral"]),
        "Network": (13, ["WiFi", "Firewall", "DNS", "Latency", "VPN"]),
    }
    rows = []
    index = 0
    for category, (count, subcategories) in distribution.items():
        for category_index in range(count):
            index += 1
            subcategory = subcategories[category_index % len(subcategories)]
            rows.append({
                "number": f"INC{index:07d}",
                "sys_id": f"sys-{index}",
                "category": category,
                "subcategory": subcategory,
                "short_description": f"{subcategory} reported",
                "description": "User reports issue. Initial triage captured from self-service channel.",
            })

    result = analyze_ticket_rows(rows)

    assert result["manifest"] == {
        "totalRows": 150, "validTickets": 150, "emptyTicketsRemoved": 0,
        "duplicatesRemoved": 0, "processedTickets": 150, "problemGroups": 11,
        "coverageStatus": "complete", "taxonomyRules": len(DEFAULT_TAXONOMY),
        "llmFallbackStatus": "disabled",
        "llmLabelStatus": "disabled", "llmGroupsRenamed": 0,
        "taxonomySuggestionStatus": "disabled",
        "embeddingMethod": "tfidf", "clusteringMethod": "taxonomy_semantic",
    }
    assert sum(group["incidentCount"] for group in result["groups"]) == 150
    names = {group["groupName"] for group in result["groups"]}
    assert {
        "Login, SSO & Session Authentication Failures",
        "Access Provisioning, Authorization & Licensing Issues",
        "Password Reset & Account Recovery Issues",
        "Security Alerts, Threats & Compliance Violations",
        "Cloud, Compute & Container Platform Stability",
        "Database Reliability & Performance",
        "Integration, API & Middleware Failures",
        "Application Errors, Workflow & Functional Breakage",
        "Endpoint, Hardware & Peripheral Issues",
        "Network, VPN, DNS & Firewall Issues",
        "Data Quality, Reporting & Analytics Issues",
    } == names
    rendered = json.dumps(result).lower()
    assert "title description reports" not in rendered
    assert not any(group["groupName"].startswith("Title") for group in result["groups"])
    assert "tickets describing" not in rendered


def test_related_child_patterns_roll_up_across_multiple_domains():
    examples = {
        "Login, SSO & Session Authentication Failures": [
            "OIDC assertion error", "MFA enrollment issue", "SSO redirect failure",
            "Invalid credentials error despite correct password", "Session expires immediately",
        ],
        "Access Provisioning, Authorization & Licensing Issues": [
            "Permission denied", "Role provisioning delayed", "Incorrect group membership",
        ],
        "Password Reset & Account Recovery Issues": ["Reset link expired", "Reset email not received"],
        "Database Reliability & Performance": ["Replica not catching up", "Connection pool exhausted"],
        "Integration, API & Middleware Failures": ["Webhook retries exhausted", "JSON schema validation failed"],
        "Network, VPN, DNS & Firewall Issues": ["DNS resolution failure", "VPN latency high"],
        "Cloud, Compute & Container Platform Stability": ["Kubernetes node pressure"],
        "Storage, Backup & File Transfer Issues": ["Storage account throttling"],
    }
    rows = []
    index = 0
    for titles in examples.values():
        for title in titles:
            index += 1
            rows.append({"number": f"INC{index:04d}", "short_description": title, "description": f"{title}. Service impact confirmed."})

    result = analyze_ticket_rows(rows)
    counts = {group["groupName"]: group["incidentCount"] for group in result["groups"]}

    assert counts == {name: len(titles) for name, titles in examples.items()}
    assert sum(counts.values()) == len(rows)
    banned = {"OIDC Assertion Error", "MFA Enrollment Issue", "Permission Denied"}
    assert banned.isdisjoint(counts)
    auth = next(group for group in result["groups"] if group["groupName"] == "Login, SSO & Session Authentication Failures")
    assert {ticket["title"] for ticket in auth["representativeTickets"]} <= set(examples["Login, SSO & Session Authentication Failures"])


def test_taxonomy_can_be_extended_without_changing_grouping_code():
    custom = (
        TaxonomyRule(
            "Print & Document Delivery Issues",
            "Employees cannot print, scan, or deliver business documents.",
            ("printer", "print queue", "document delivery"),
        ),
    )
    result = analyze_ticket_rows([
        {"number": "1", "short_description": "Printer offline"},
        {"number": "2", "short_description": "Print queue stalled"},
    ], taxonomy=custom)
    assert result["groups"][0]["groupName"] == "Print & Document Delivery Issues"
    assert result["groups"][0]["incidentCount"] == 2


def test_strategy_taxonomy_then_cluster_uses_taxonomy_and_fallback():
    result = analyze_ticket_rows([
        {"number": "1", "short_description": "VPN login failed", "description": "SSO redirect failure"},
        {"number": "2", "short_description": "Office elevator maintenance delayed"},
        {"number": "3", "short_description": "Office elevator service unavailable"},
    ], min_group_size=2, strategy="taxonomy_then_cluster")
    names = {group["groupName"] for group in result["groups"]}
    assert "Login, SSO & Session Authentication Failures" in names
    assert "Facilities, Badge & Physical Access Issues" in names


def test_strategy_cluster_only_skips_taxonomy_matching():
    result = analyze_ticket_rows([
        {"number": "1", "short_description": "VPN login failed", "description": "SSO redirect failure"},
        {"number": "2", "short_description": "VPN login failed", "description": "SSO redirect failure again"},
    ], min_group_size=2, strategy="cluster_only")
    assert result["manifest"]["taxonomyRules"] == 0
    assert {group["groupName"] for group in result["groups"]} != {"Login, SSO & Session Authentication Failures"}


def test_strategy_taxonomy_only_keeps_unmatched_for_review():
    result = analyze_ticket_rows([
        {"number": "1", "short_description": "Research workspace calibration profile failed"},
        {"number": "2", "short_description": "Research workspace calibration cannot load"},
    ], min_group_size=2, strategy="taxonomy_only")
    assert result["groups"][0]["groupName"] == "Other Service Issues"
    assert result["groups"][0]["matched_reason"] == "taxonomy only: unmatched tickets held for review"


def test_description_only_1000_rows_roll_up_to_parent_pain_points():
    distribution = {
        "Login & Authentication Failures": (180, [
            "Login page fails after valid credentials", "SSO redirect failure", "MFA push not received",
            "OIDC token validation error", "SAML assertion rejected", "Session expires immediately",
        ]),
        "Access Provisioning & Authorization Issues": (150, [
            "License assigned but feature access unavailable", "Permission denied for approved user",
            "Role provisioning delayed", "Incorrect group membership",
        ]),
        "Password Reset & Account Recovery Issues": (120, [
            "Cannot set new password", "Reset password page is unavailable", "Reset link expired",
            "Temporary password rejected", "Account recovery security question failed",
        ]),
        "Security Alerts & Policy Violations": (130, [
            "Suspicious login alert detected by security monitoring", "Multiple failed login alert",
            "Malware quarantine alert", "Phishing message reported", "Security policy violation",
        ]),
        "Database Reliability & Performance": (110, [
            "Report query timing out", "Slow query blocks reporting", "Database connection refused",
            "Replication lag detected", "Connection pool exhausted",
        ]),
        "Integration & API Failures": (100, [
            "Queue consumer not processing messages", "Message queue backlog high", "Webhook retries exhausted",
            "API failure returned 503", "OAuth client credentials rejected",
        ]),
        "Network Connectivity Issues": (90, [
            "DNS resolution failure", "VPN latency high", "Firewall blocks outbound connection",
            "Corporate WiFi disconnects", "Route instability detected",
        ]),
        "Cloud Infrastructure Stability": (70, [
            "VM CPU usage high", "Kubernetes node pressure", "Load balancer health check failed",
            "Secret expiry warning", "Cloud storage blob upload failed",
        ]),
        "End-User Hardware Issues": (50, [
            "Display goes blank intermittently", "Laptop not booting", "Keyboard not working",
            "Scanner feeder jam", "Docking station USB device not detected",
        ]),
    }
    rows = []
    index = 0
    for _, (count, descriptions) in distribution.items():
        for offset in range(count):
            index += 1
            rows.append({"incident_no": f"DESC{index:05d}", "description": descriptions[offset % len(descriptions)]})

    result = analyze_ticket_rows(rows)
    counts = {group["groupName"]: group["incidentCount"] for group in result["groups"]}

    assert result["manifest"]["validTickets"] == 1000
    assert result["manifest"]["duplicatesRemoved"] == 0
    assert counts == {
        "Login, SSO & Session Authentication Failures": 180,
        "Access Provisioning, Authorization & Licensing Issues": 150,
        "Security Alerts, Threats & Compliance Violations": 130,
        "Password Reset & Account Recovery Issues": 120,
        "Database Reliability & Performance": 110,
        "Integration, API & Middleware Failures": 100,
        "Network, VPN, DNS & Firewall Issues": 90,
        "Cloud, Compute & Container Platform Stability": 56,
        "Endpoint, Hardware & Peripheral Issues": 50,
        "Certificate, Secrets & Key Management Issues": 14,
    }
    assert len(counts) == len(result["groups"])
    assert sum(counts.values()) == 1000
    forbidden = {
        "Cannot Set New Issues", "Reset Password Page Issues", "License Assigned Feature Issues",
        "Queue Consumer Not Issues", "Report Query Timing Issues", "Display Goes Blank Issues",
    }
    assert forbidden.isdisjoint(counts)
    assert "Other Service Issues" not in counts
    assert all(0 <= group["confidence"] <= 1 for group in result["groups"])
    assert all(group["matched_reason"] for group in result["groups"])


def test_unknown_domains_form_discovered_groups_without_taxonomy_rules():
    domains = {
        "facilities": ["Office elevator maintenance is delayed", "Office elevator service is unavailable"],
        "procurement": ["Purchase order approval is delayed", "Purchase order workflow is blocked"],
        "hr": ["Employee onboarding document verification is delayed", "Employee onboarding checklist is blocked"],
        "finance": ["Invoice reconciliation mismatch requires review", "Invoice reconciliation process is delayed"],
    }
    rows = []
    index = 0
    for descriptions in domains.values():
        for offset in range(12):
            index += 1
            suffix = " User reported this through the service portal." if offset % 3 else ""
            rows.append({"incident_no": f"NEW{index:04d}", "description": descriptions[offset % 2] + suffix})

    result = analyze_ticket_rows(rows, min_group_size=3)

    assert result["manifest"]["problemGroups"] == 5
    assert sum(group["incidentCount"] for group in result["groups"]) == 48
    assert sorted(group["incidentCount"] for group in result["groups"]) == [6, 6, 12, 12, 12]
    assert all(group["confidence"] >= 0.65 for group in result["groups"])
    assert all(group["matched_reason"].startswith("post-processing taxonomy merge:") for group in result["groups"])
    assert "Other Service Issues" not in {group["groupName"] for group in result["groups"]}
    labels = " ".join(group["groupName"].lower() for group in result["groups"])
    assert all(term in labels for term in ("facilities", "procurement", "hr", "finance", "service request"))


def test_only_tiny_unknown_patterns_fall_back_to_other():
    result = analyze_ticket_rows([
        {"incident_no": "1", "description": "One-off unusual office event alpha"},
        {"incident_no": "2", "description": "Completely unrelated isolated event beta"},
    ], min_group_size=3)
    assert result["groups"][0]["groupName"] == "Other Service Issues"
    assert result["groups"][0]["matched_reason"].startswith("fallback:")


def test_llm_fallback_groups_unknown_tickets_and_suggests_taxonomy(monkeypatch):
    def fake_chat(system, prompt, model, temperature=0.0, max_tokens=None, **kwargs):
        payload = json.loads(prompt)
        assert model == "local-test-model"
        assert kwargs["max_retry_after_seconds"] == 2
        assert len(payload["unknownTicketClusters"]) == 2
        return json.dumps({
            "groups": [{
                "groupName": "Research Workspace Calibration Issues",
                "description": "Specialized research workspaces have repeated calibration failures.",
                "ticketIndices": [0, 1],
                "confidence": 0.91,
                "matchedReason": "both tickets mention calibration failure in the same workspace",
                "suggestedIncludes": ["research workspace calibration", "calibration profile failed"],
            }],
            "taxonomySuggestions": [{
                "name": "Research Workspace Calibration Issues",
                "description": "Calibration profile and workspace setup issues for research environments.",
                "patterns": ["research workspace calibration", "calibration profile failed"],
                "contexts": ["research workspace"],
                "reason": "new repeated domain not covered by the default taxonomy",
            }],
        })

    monkeypatch.setattr("backend.app.ticket_analysis._chat", fake_chat)
    progress_events = []

    result = analyze_ticket_rows([
        {"incident_no": "LLM1", "description": "Research workspace calibration profile failed for lab alpha"},
        {"incident_no": "LLM2", "description": "Research workspace calibration cannot load for lab beta"},
    ], min_group_size=3, llm_fallback=True, llm_model="local-test-model", progress=lambda stage, detail: progress_events.append((stage, detail)))

    assert result["manifest"]["llmFallbackStatus"] == "used"
    assert result["groups"][0]["groupName"] == "Research Workspace Calibration Issues"
    assert result["groups"][0]["incidentCount"] == 2
    assert result["groups"][0]["matched_reason"].startswith("llm fallback:")
    assert result["taxonomySuggestions"][0]["patterns"] == ["research workspace calibration", "calibration profile failed"]
    assert progress_events[0] == ("gathering", "Calling local-test-model to classify 2 unknown ticket cluster(s) for taxonomy fallback")
    assert progress_events[-1] == ("gathering", "local-test-model taxonomy fallback returned 1 group(s), 0 unresolved cluster(s)")


def test_taxonomy_fallback_events_are_visible_as_llm_activity():
    call = _pipeline_event_metadata("gathering", "Calling openai/gpt-oss-20b to classify 10 unknown ticket cluster(s) for taxonomy fallback")
    skipped = _pipeline_event_metadata("gathering", "openai/gpt-oss-20b taxonomy fallback skipped: LLMProviderError")

    assert call["type"] == "llm_call"
    assert call["method"] == "ticket_taxonomy_llm_fallback()"
    assert skipped["type"] == "llm_result"
    assert skipped["method"] == "ticket_taxonomy_llm_fallback()"
    assert "skipped" in skipped["tags"]


def test_v2_service_request_access_rolls_to_fulfillment():
    result = classify_ticket_v2({
        "number": "RITM001234",
        "record_type": "Service Request",
        "short_description": "Access chahiye asap for finance portal",
        "description": "Please provide access for new team member",
        "assignment_group": "Service Desk",
    })

    assert result.category == "Service Request Fulfillment"
    assert result.subcategory == "access_request"
    assert result.confidence == "high"
    assert not result.manual_review_recommended


def test_v2_actual_access_denied_stays_access_provisioning():
    result = classify_ticket_v2({
        "number": "INC001234",
        "short_description": "Access denied while opening payroll app",
        "description": "User gets permission denied error after role change",
    })

    assert result.category == "Access Provisioning, Authorization & Licensing Issues"
    assert result.confidence == "high"


def test_v2_api_401_and_queue_do_not_become_login_or_access():
    result = classify_ticket_v2({
        "number": "INC009999",
        "short_description": "API returns HTTP 401 for webhook payload",
        "description": "OAuth client credentials rejected and queue consumer stopped processing messages",
    })

    assert result.category == "Integration, API & Middleware Failures"
    assert result.confidence == "high"


def test_v2_common_override_confusions():
    examples = [
        ({"short_description": "Port blocked by firewall", "description": "Traffic denied from app subnet"}, "Network, VPN, DNS & Firewall Issues"),
        ({"short_description": "Pipeline failed during release", "description": "Artifact missing and rollback failed"}, "DevOps, CI/CD & Release Deployment Issues"),
        ({"short_description": "Database login failed", "description": "DB connection and query timeout observed"}, "Database Reliability & Performance"),
        ({"number": "SCTASK001", "short_description": "Need laptop for new joiner", "description": "Request new laptop and monitor"}, "Service Request Fulfillment"),
    ]

    for row, expected in examples:
        assert classify_ticket_v2(row).category == expected


def test_v2_vague_ticket_does_not_get_high_confidence():
    result = classify_ticket_v2({
        "number": "INC000001",
        "short_description": "Getting error",
        "description": "Same issue again please check",
        "category": "Application",
    })

    assert result.confidence != "high"
    assert result.manual_review_recommended


def test_noisy_access_chahiye_group_merges_into_service_request_fulfillment():
    rows = [
        {"number": f"RITM{i}", "record_type": "Service Request", "short_description": "Access chahiye asap", "description": "Please provide access for reporting app"}
        for i in range(5)
    ]

    result = analyze_ticket_rows(rows, min_group_size=3)
    counts = {group["groupName"]: group["incidentCount"] for group in result["groups"]}

    assert counts == {"Service Request Fulfillment": 5}
    assert "Access Chahiye Asap Issues" not in counts


def test_llm_fallback_failure_keeps_classification_pipeline_alive(monkeypatch):
    def failing_chat(*args, **kwargs):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr("backend.app.ticket_analysis._chat", failing_chat)
    result = analyze_ticket_rows([
        {"incident_no": "U1", "description": "Unusual isolated alpha pattern"},
        {"incident_no": "U2", "description": "Different isolated beta pattern"},
    ], min_group_size=3, llm_fallback=True, llm_model="local-test-model")

    assert result["manifest"]["llmFallbackStatus"].startswith("failed:")
    assert result["groups"][0]["groupName"] == "Other Service Issues"


LOGIN_ROWS = [
    {"incident_no": f"N{index}", "short_description": text}
    for index, text in enumerate([
        "SSO login failure for portal", "MFA prompt not received at login",
        "SAML assertion rejected on sign in", "Session expires immediately after login",
    ])
]
# Novel domain the default taxonomy does not cover, so grouping produces a
# generated label — the only kind LLM naming is allowed to rewrite.
NOVEL_ROWS = [
    {"incident_no": f"C{index}", "short_description": "Research workspace calibration profile failed"}
    for index in range(4)
]


def test_llm_naming_rewrites_generated_group_labels_and_reports_real_count(monkeypatch):
    captured = {}

    def fake_chat(system, prompt, model, temperature=0.0, max_tokens=None, **kwargs):
        captured["payload"] = json.loads(prompt)
        assert model == "local-test-model"
        return json.dumps({"groups": [{
            "index": 0,
            "name": "Workforce Sign-In Breakdowns",
            "description": "Staff cannot complete sign-in across SSO, MFA and session handling.",
        }]})

    monkeypatch.setattr("backend.app.ticket_analysis._chat", fake_chat)
    progress_events = []
    result = analyze_ticket_rows(
        NOVEL_ROWS,
        pause_okf_taxonomy=True,
        llm_labels=True,
        llm_model="local-test-model",
        progress=lambda stage, detail: progress_events.append((stage, detail)),
    )

    group = result["groups"][0]
    assert group["groupName"] == "Workforce Sign-In Breakdowns"
    assert group["description"].startswith("Staff cannot complete sign-in")
    assert group["llm_named"] is True
    assert group["llm_original_name"] and group["llm_original_name"] != group["groupName"]
    assert group["incidentCount"] == 4  # membership untouched by naming
    assert result["manifest"]["llmLabelStatus"] == "used"
    assert result["manifest"]["llmGroupsRenamed"] == 1
    assert captured["payload"]["problemGroups"][0]["exampleTickets"]
    assert progress_events[-1] == ("llm_labels", "local-test-model rewrote 1 of 1 problem group label(s)")


def test_llm_naming_rewrites_curated_taxonomy_labels_but_keeps_the_rule_name(monkeypatch):
    captured = {}

    def fake_chat(system, prompt, model, temperature=0.0, max_tokens=None, **kwargs):
        captured["payload"] = json.loads(prompt)["problemGroups"]
        current = captured["payload"][0]["currentName"]
        return json.dumps({"groups": [{"index": 0, "currentName": current, "name": "Workforce Sign-In Breakdowns"}]})

    monkeypatch.setattr("backend.app.ticket_analysis._chat", fake_chat)
    result = analyze_ticket_rows(LOGIN_ROWS, llm_labels=True, llm_model="local-test-model")

    group = result["groups"][0]
    assert group["groupName"] == "Workforce Sign-In Breakdowns"
    # The reviewed vocabulary stays recoverable after the rewrite.
    assert group["taxonomy_rule_name"] == "Login, SSO & Session Authentication Failures"
    assert group["llm_original_name"] == "Login, SSO & Session Authentication Failures"
    # The prompt tells the model which labels are curated so it can be conservative.
    assert captured["payload"][0]["isCuratedTaxonomyLabel"] is True
    assert result["manifest"]["llmGroupsRenamed"] == 1


def test_llm_naming_disabled_by_default_never_calls_the_model(monkeypatch):
    def unexpected_chat(*args, **kwargs):
        raise AssertionError("naming must not call the LLM when the toggle is off")

    monkeypatch.setattr("backend.app.ticket_analysis._chat", unexpected_chat)
    result = analyze_ticket_rows(LOGIN_ROWS)

    assert result["manifest"]["llmLabelStatus"] == "disabled"
    assert result["manifest"]["llmGroupsRenamed"] == 0
    assert all("llm_named" not in group for group in result["groups"])


def test_llm_naming_rejects_empty_and_colliding_labels(monkeypatch):
    rows = NOVEL_ROWS + [
        {"incident_no": f"D{index}", "short_description": text}
        for index, text in enumerate([
            "Telescope array alignment drift detected", "Telescope array alignment drift detected",
            "Telescope array alignment drift detected", "Telescope array alignment drift detected",
        ])
    ]

    def fake_chat(system, prompt, model, temperature=0.0, max_tokens=None, **kwargs):
        payload = json.loads(prompt)
        names = [entry["currentName"] for entry in payload["problemGroups"]]
        return json.dumps({"groups": [
            {"index": 0, "name": "  "},
            {"index": 1, "name": names[0]},
            {"index": 99, "name": "Ignored Out Of Range Group"},
        ]})

    monkeypatch.setattr("backend.app.ticket_analysis._chat", fake_chat)
    result = analyze_ticket_rows(rows, pause_okf_taxonomy=True, llm_labels=True, llm_model="local-test-model")

    names = [group["groupName"] for group in result["groups"]]
    assert len(names) == len(set(names))  # collision rejected, groups stay distinct
    assert result["manifest"]["llmGroupsRenamed"] == 0
    assert result["manifest"]["llmLabelStatus"] == "no_changes"


def test_llm_naming_failure_keeps_deterministic_labels(monkeypatch):
    def failing_chat(*args, **kwargs):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr("backend.app.ticket_analysis._chat", failing_chat)
    result = analyze_ticket_rows(NOVEL_ROWS, pause_okf_taxonomy=True, llm_labels=True, llm_model="local-test-model")

    assert result["manifest"]["llmLabelStatus"].startswith("failed:")
    assert result["manifest"]["llmGroupsRenamed"] == 0
    assert result["groups"][0]["groupName"]


CLUSTER_ROWS = [
    {"incident_no": f"K{index}", "short_description": text}
    for index, text in enumerate([
        "Payment gateway timeout on checkout", "Payment gateway timeout at checkout page",
        "Payment gateway declined without reason", "Payment gateway settlement delayed",
        "Warehouse scanner will not pair", "Warehouse scanner battery drains fast",
        "Warehouse scanner drops wifi mid shift", "Warehouse scanner firmware update failed",
        "Kiosk display frozen in lobby", "Kiosk display shows black screen",
        "Kiosk display touch not responding", "Kiosk display reboots randomly",
    ])
]


def test_every_clustering_method_produces_groups_and_records_itself():
    seen = {}
    for method in ("taxonomy_semantic", "agglomerative", "kmeans", "hdbscan_lite", "google_kwikbucks"):
        result = analyze_ticket_rows(
            CLUSTER_ROWS, pause_okf_taxonomy=True, min_group_size=2,
            clustering_method=method, target_clusters=3,
        )
        assert result["manifest"]["clusteringMethod"] == method
        assert sum(group["incidentCount"] for group in result["groups"]) == len(CLUSTER_ROWS)
        seen[method] = [group["groupName"] for group in result["groups"]]
    # The methods are genuinely different engines, not one engine behind five labels.
    assert len({tuple(names) for names in seen.values()}) > 1


def test_kmeans_honours_the_target_cluster_count():
    result = analyze_ticket_rows(
        CLUSTER_ROWS, pause_okf_taxonomy=True, min_group_size=1,
        clustering_method="kmeans", target_clusters=3,
    )
    assert len(result["groups"]) == 3


def test_hdbscan_min_samples_controls_how_much_becomes_noise():
    def noise(min_samples):
        result = analyze_ticket_rows(
            CLUSTER_ROWS, pause_okf_taxonomy=True, min_group_size=1,
            clustering_method="hdbscan_lite", hdbscan_min_samples=min_samples,
        )
        return sum(g["incidentCount"] for g in result["groups"] if g["groupName"] == "Other Service Issues")

    assert noise(8) > noise(2)


def test_every_embedding_method_runs_and_is_recorded():
    for method in ("tfidf", "neural_hash", "hybrid"):
        result = analyze_ticket_rows(CLUSTER_ROWS, pause_okf_taxonomy=True, min_group_size=2, embedding_method=method)
        assert result["manifest"]["embeddingMethod"] == method
        assert sum(group["incidentCount"] for group in result["groups"]) == len(CLUSTER_ROWS)


def test_tfidf_downweights_boilerplate_shared_by_every_ticket():
    from backend.app.ticket_analysis import _build_vectors

    texts = [
        "Initial triage captured from self-service channel. Printer jam in finance",
        "Initial triage captured from self-service channel. Payroll export failed",
    ]
    tfidf_vectors, tfidf_similarity = _build_vectors(texts, "tfidf")
    raw_vectors, raw_similarity = _build_vectors(texts, "none")
    assert tfidf_similarity(*tfidf_vectors) < raw_similarity(*raw_vectors)


def test_taxonomy_suggestions_run_without_llm_fallback(monkeypatch):
    def fake_chat(system, prompt, model, temperature=0.0, max_tokens=None, **kwargs):
        assert "unmatchedClusters" in json.loads(prompt)
        return json.dumps({"taxonomySuggestions": [{
            "name": "Research Workspace Calibration",
            "description": "Calibration failures in research workspaces.",
            "patterns": ["workspace calibration", "calibration profile"],
            "reason": "repeated unmatched pattern",
        }]})

    monkeypatch.setattr("backend.app.ticket_analysis._chat", fake_chat)
    result = analyze_ticket_rows(
        NOVEL_ROWS, pause_okf_taxonomy=True, min_group_size=99,
        suggest_taxonomy_rules=True, llm_model="local-test-model",
    )

    assert result["manifest"]["taxonomySuggestionStatus"] == "used"
    assert result["taxonomySuggestions"][0]["patterns"] == ["workspace calibration", "calibration profile"]
    # Suggestions are advisory: they must not invent groups or move tickets.
    assert [group["groupName"] for group in result["groups"]] == ["Other Service Issues"]


def test_taxonomy_suggestions_disabled_by_default_never_calls_the_model(monkeypatch):
    def unexpected_chat(*args, **kwargs):
        raise AssertionError("suggestions must not call the LLM when the toggle is off")

    monkeypatch.setattr("backend.app.ticket_analysis._chat", unexpected_chat)
    result = analyze_ticket_rows(NOVEL_ROWS, pause_okf_taxonomy=True, min_group_size=99)

    assert result["manifest"]["taxonomySuggestionStatus"] == "disabled"
    assert result["taxonomySuggestions"] == []


def test_ticket_analysis_stream_reports_real_stages_before_the_result():
    from fastapi.testclient import TestClient
    from backend.app.main import app

    topics = ["Payment gateway timeout on checkout", "Warehouse scanner will not pair"]
    csv_bytes = b"number,short_description\n" + b"\n".join(
        f"INC{index},{topics[index % 2]} {index}".encode() for index in range(6)
    )
    with TestClient(app) as client:
        upload = client.post(
            "/api/files",
            data={"store_id": 2},
            files={"file": ("stream-tickets.csv", csv_bytes, "text/csv")},
        )
        assert upload.status_code == 201
        file_id = upload.json()["id"]

        stages, result = [], None
        with client.stream("POST", "/api/ticket-analysis/stream", json={
            "fileId": file_id, "clusteringMethod": "kmeans", "targetClusters": 2,
            "pauseOkfTaxonomy": True, "minGroupSize": 1,
        }) as response:
            assert response.status_code == 200
            for line in response.iter_lines():
                if not line.strip():
                    continue
                event = json.loads(line)
                if event["type"] == "stage":
                    stages.append(event["stage"])
                elif event["type"] == "result":
                    result = event["data"]
                else:
                    raise AssertionError(event)

    # Stage names are the pipeline's own, streamed as the work happens.
    assert stages[0] == "ingest"
    assert stages[-1] == "complete"
    assert "cluster" in stages
    assert result["manifest"]["clusteringMethod"] == "kmeans"
    assert len(result["groups"]) == 2


def test_llm_naming_accepts_a_bare_array_response(monkeypatch):
    """Smaller models answer "return {groups: [...]}" with just the array."""
    def fake_chat(system, prompt, model, temperature=0.0, max_tokens=None, **kwargs):
        current = json.loads(prompt)["problemGroups"][0]["currentName"]
        return json.dumps([{"index": 0, "currentName": current, "name": "Lab Calibration Breakdowns"}])

    monkeypatch.setattr("backend.app.ticket_analysis._chat", fake_chat)
    result = analyze_ticket_rows(NOVEL_ROWS, pause_okf_taxonomy=True, llm_labels=True, llm_model="local-test-model")

    assert result["groups"][0]["groupName"] == "Lab Calibration Breakdowns"
    assert result["manifest"]["llmGroupsRenamed"] == 1


def test_llm_naming_accepts_an_unexpected_wrapper_key(monkeypatch):
    def fake_chat(system, prompt, model, temperature=0.0, max_tokens=None, **kwargs):
        current = json.loads(prompt)["problemGroups"][0]["currentName"]
        return json.dumps({"renamedGroups": [{"index": 0, "currentName": current, "name": "Lab Calibration Breakdowns"}]})

    monkeypatch.setattr("backend.app.ticket_analysis._chat", fake_chat)
    result = analyze_ticket_rows(NOVEL_ROWS, pause_okf_taxonomy=True, llm_labels=True, llm_model="local-test-model")

    assert result["groups"][0]["groupName"] == "Lab Calibration Breakdowns"


def test_llm_naming_anchors_on_the_echoed_name_not_the_index(monkeypatch):
    """A model that drops an entry shifts every index after it. Following the
    index would staple each label onto the wrong group's tickets."""
    rows = NOVEL_ROWS + [
        {"incident_no": f"T{index}", "short_description": "Telescope array alignment drift detected"}
        for index in range(4)
    ]

    def fake_chat(system, prompt, model, temperature=0.0, max_tokens=None, **kwargs):
        groups = json.loads(prompt)["problemGroups"]
        assert len(groups) == 2
        # Both entries claim index 0, but each echoes the group it means.
        return json.dumps({"groups": [
            {"index": 0, "currentName": groups[1]["currentName"], "name": "Telescope Alignment Drift"},
            {"index": 0, "currentName": groups[0]["currentName"], "name": "Lab Calibration Breakdowns"},
        ]})

    monkeypatch.setattr("backend.app.ticket_analysis._chat", fake_chat)
    result = analyze_ticket_rows(rows, pause_okf_taxonomy=True, min_group_size=2, llm_labels=True, llm_model="local-test-model")

    named = {group["llm_original_name"]: group["groupName"] for group in result["groups"] if group.get("llm_named")}
    assert set(named.values()) == {"Telescope Alignment Drift", "Lab Calibration Breakdowns"}
    for original, new in named.items():
        assert ("calibration" in original.lower()) == ("Calibration" in new)


def test_llm_naming_drops_an_entry_echoing_an_unknown_group(monkeypatch):
    def fake_chat(system, prompt, model, temperature=0.0, max_tokens=None, **kwargs):
        return json.dumps({"groups": [{"index": 0, "currentName": "A Group That Was Never Sent", "name": "Should Not Apply"}]})

    monkeypatch.setattr("backend.app.ticket_analysis._chat", fake_chat)
    result = analyze_ticket_rows(NOVEL_ROWS, pause_okf_taxonomy=True, llm_labels=True, llm_model="local-test-model")

    assert result["manifest"]["llmGroupsRenamed"] == 0
    assert all(group["groupName"] != "Should Not Apply" for group in result["groups"])


def test_llm_naming_flags_an_unusable_model_response_separately(monkeypatch):
    """A model answering with the wrong shape is a different signal to the user
    than a model that read the labels and deliberately kept them."""
    def garbled_chat(system, prompt, model, temperature=0.0, max_tokens=None, **kwargs):
        return json.dumps([{"index": 0, "currentName": "Something The Pipeline Never Sent", "description": "no name field"}])

    monkeypatch.setattr("backend.app.ticket_analysis._chat", garbled_chat)
    result = analyze_ticket_rows(NOVEL_ROWS, pause_okf_taxonomy=True, llm_labels=True, llm_model="local-test-model")

    assert result["manifest"]["llmLabelStatus"] == "no_usable_response"
    assert result["manifest"]["llmGroupsRenamed"] == 0


def test_llm_naming_reports_no_changes_when_the_model_keeps_every_label(monkeypatch):
    def keep_chat(system, prompt, model, temperature=0.0, max_tokens=None, **kwargs):
        groups = json.loads(prompt)["problemGroups"]
        return json.dumps({"groups": [
            {"index": entry["index"], "currentName": entry["currentName"], "name": entry["currentName"],
             "description": entry["currentDescription"]}
            for entry in groups
        ]})

    monkeypatch.setattr("backend.app.ticket_analysis._chat", keep_chat)
    result = analyze_ticket_rows(NOVEL_ROWS, pause_okf_taxonomy=True, llm_labels=True, llm_model="local-test-model")

    assert result["manifest"]["llmLabelStatus"] == "no_changes"
    assert result["manifest"]["llmGroupsRenamed"] == 0


def test_an_empty_custom_taxonomy_means_no_rules_rather_than_an_error():
    """Clearing the rule set is a real choice — group by discovery alone — and
    must not fall back to the shipped taxonomy or reject the request."""
    from fastapi.testclient import TestClient
    from backend.app.main import app

    topics = ["Payment gateway timeout on checkout", "Warehouse scanner will not pair"]
    csv_bytes = b"number,short_description\n" + b"\n".join(
        f"INC{index},{topics[index % 2]} {index}".encode() for index in range(8)
    )
    with TestClient(app) as client:
        upload = client.post(
            "/api/files",
            data={"store_id": 2},
            files={"file": ("empty-taxonomy.csv", csv_bytes, "text/csv")},
        )
        response = client.post("/api/ticket-analysis", json={
            "fileId": upload.json()["id"], "taxonomyRules": [], "minGroupSize": 1,
        })

    assert response.status_code == 200
    body = response.json()
    assert body["manifest"]["taxonomyRules"] == 0
    assert sum(group["incidentCount"] for group in body["groups"]) == 8
    assert body["analysisOptions"]["taxonomySource"] == "custom"
