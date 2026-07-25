#!/usr/bin/env python3
"""Evaluate V2 ITSM taxonomy classification against expected_taxonomy CSV data."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.ticket_analysis import read_ticket_rows  # noqa: E402
from backend.app.ticket_taxonomy import classify_ticket_v2  # noqa: E402


def _key(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().replace("_", " ").split())


def _first(row: dict[str, Any], names: tuple[str, ...]) -> str:
    indexed = {_key(name): value for name, value in row.items()}
    return next((str(indexed[_key(name)]).strip() for name in names if str(indexed.get(_key(name), "")).strip()), "")


def evaluate(path: Path) -> dict[str, Any]:
    rows = read_ticket_rows(path)
    expected_rows = [row for row in rows if _first(row, ("expected_taxonomy",))]
    total = len(expected_rows)
    correct = 0
    expected_counts: Counter[str] = Counter()
    predicted_counts: Counter[str] = Counter()
    true_positive: Counter[str] = Counter()
    confusion: Counter[tuple[str, str]] = Counter()
    wrong: list[dict[str, Any]] = []
    low_confidence = manual_review = 0

    for row in expected_rows:
        expected = _first(row, ("expected_taxonomy",))
        result = classify_ticket_v2(row)
        predicted = result.category
        expected_counts[expected] += 1
        predicted_counts[predicted] += 1
        confusion[(expected, predicted)] += 1
        low_confidence += result.confidence == "low"
        manual_review += result.manual_review_recommended
        if _key(expected) == _key(predicted):
            correct += 1
            true_positive[expected] += 1
        else:
            wrong.append({
                "ticket_id": _first(row, ("ticket_id", "number", "sys_id", "incident_number")),
                "expected": expected,
                "predicted": predicted,
                "confidence": result.confidence,
                "score": round(result.score, 2),
                "matched_reason": result.matched_reason,
                "short_description": _first(row, ("short_description", "summary", "title")),
            })

    categories = sorted(set(expected_counts) | set(predicted_counts))
    per_category = {}
    for category in categories:
        tp = true_positive[category]
        predicted_total = predicted_counts[category]
        expected_total = expected_counts[category]
        per_category[category] = {
            "precision": round(tp / predicted_total, 4) if predicted_total else 0.0,
            "recall": round(tp / expected_total, 4) if expected_total else 0.0,
            "expected": expected_total,
            "predicted": predicted_total,
        }

    return {
        "total_records": total,
        "accuracy": round(correct / total, 4) if total else 0.0,
        "correct": correct,
        "per_category": per_category,
        "confusion_matrix": [
            {"expected": expected, "predicted": predicted, "count": count}
            for (expected, predicted), count in confusion.most_common()
        ],
        "top_25_wrong_classifications": wrong[:25],
        "predicted_distribution": dict(predicted_counts.most_common()),
        "low_confidence_count": low_confidence,
        "manual_review_count": manual_review,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate ITSM taxonomy predictions against expected_taxonomy.")
    parser.add_argument("csv_path", type=Path)
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    args = parser.parse_args()
    result = evaluate(args.csv_path)
    if args.json:
        print(json.dumps(result, indent=2))
        return
    print(f"Total records: {result['total_records']}")
    print(f"Accuracy: {result['accuracy']:.2%} ({result['correct']}/{result['total_records']})")
    print(f"Low confidence: {result['low_confidence_count']}")
    print(f"Manual review: {result['manual_review_count']}")
    print("\nPredicted distribution:")
    for category, count in result["predicted_distribution"].items():
        print(f"- {category}: {count}")
    print("\nPer-category precision/recall:")
    for category, metrics in result["per_category"].items():
        print(f"- {category}: precision={metrics['precision']:.2%}, recall={metrics['recall']:.2%}, expected={metrics['expected']}, predicted={metrics['predicted']}")
    print("\nTop wrong classifications:")
    for item in result["top_25_wrong_classifications"]:
        print(f"- {item['ticket_id']}: expected={item['expected']} predicted={item['predicted']} score={item['score']} reason={item['matched_reason']}")


if __name__ == "__main__":
    main()
