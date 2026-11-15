"""Export only fictional legacy readiness results; never load owner config or databases."""

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace as S

from backend.app.services.applications.eligibility import readiness


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    check = parser.parse_args().check
    # Freeze the oracle clock at the module boundary; no system time or timezone edits.
    import backend.app.services.applications.eligibility as legacy

    instant = datetime(2026, 1, 1, tzinfo=timezone.utc)

    class Clock:
        @staticmethod
        def now(_zone):
            return instant

    original_clock = legacy.datetime
    legacy.datetime = Clock
    base = dict(
        question="Fictional question — résumé?",
        required=True,
        effective_answer=None,
        validation_status="needs_input",
        requires_review=True,
        review_status="pending",
        answer_expires_at=None,
    )
    variants = [
        [],
        [base],
        [
            {
                **base,
                "effective_answer": "Verified fact",
                "validation_status": "draft_ready",
            }
        ],
        [
            {
                **base,
                "effective_answer": "Verified fact",
                "validation_status": "draft_ready",
                "review_status": "reviewed",
            }
        ],
        [{**base, "required": False}],
        [{**base, "validation_status": "file_upload_required"}],
        [
            {
                **base,
                "effective_answer": "Verified fact",
                "validation_status": "draft_ready",
                "review_status": "reviewed",
                "answer_expires_at": instant,
            }
        ],
        [
            {
                **base,
                "required": False,
                "answer_expires_at": instant - timedelta(seconds=1),
            }
        ],
        [
            {
                **base,
                "effective_answer": "Verified fact",
                "validation_status": "validation_failed",
            }
        ],
        [
            {
                **base,
                "effective_answer": "Verified fact",
                "validation_status": "provider_unavailable",
            }
        ],
        [
            {
                **base,
                "effective_answer": "Verified fact",
                "validation_status": "draft_ready",
                "review_status": "reviewed",
                "answer_expires_at": instant + timedelta(microseconds=1),
            }
        ],
        [
            {
                **base,
                "required": False,
                "effective_answer": "",
                "validation_status": "draft_ready",
            }
        ],
        [
            {
                **base,
                "effective_answer": "Verified fact",
                "validation_status": "draft_ready",
                "requires_review": False,
            }
        ],
        [
            {
                **base,
                "effective_answer": "Verified fact",
                "validation_status": "draft_ready",
                "review_status": "reviewed",
                "answer_expires_at": instant,
            },
            base,
            {
                **base,
                "effective_answer": "Verified fact",
                "validation_status": "draft_ready",
            },
        ],
    ]
    results, indexes, cases = [], {}, []
    try:
        for bits in range(256):
            snapshot = S(
                warnings=["Snapshot warning"],
                candidate=S() if bits & 1 else None,
                preparation_supported=bool(bits & 2),
                destination=S(
                    warnings=["Destination warning"],
                    valid=bool(bits & 4),
                    source_confidence="source_consistent"
                    if bits & 8
                    else "source_conflict",
                ),
                resume=S(
                    selected=S() if bits & 16 else None,
                    reason="Choose a confirmed resume",
                ),
            )
            for variant, values in enumerate(variants):
                fields = [
                    S(
                        **{k: v for k, v in value.items() if k != "answer_expires_at"},
                        provenance=S(answer_expires_at=value["answer_expires_at"]),
                    )
                    for value in values
                ]
                result = readiness(
                    snapshot,
                    fields,
                    stale=bool(bits & 32),
                    approved=bool(bits & 64),
                    submitted=bool(bits & 128),
                ).model_dump(mode="json")
                key = json.dumps(result, sort_keys=True, ensure_ascii=False)
                if key not in indexes:
                    indexes[key] = len(results)
                    results.append(result)
                cases.append([bits, variant, indexes[key]])
    finally:
        legacy.datetime = original_clock
    fields_json = json.loads(json.dumps(variants, default=lambda v: v.isoformat()))
    output = (
        Path(__file__).resolve().parents[1]
        / "agent-runtime/tests/fixtures/packet-readiness-corpus.json"
    )
    encoded = (
        json.dumps(
            {
                "now": instant.isoformat(),
                "fields": fields_json,
                "results": results,
                "cases": cases,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        + "\n"
    )
    if check:
        if output.read_text() != encoded:
            raise SystemExit("packet_readiness_oracle_changed")
    else:
        output.write_text(encoded)
    print(
        json.dumps(
            {
                "fictional_cases": len(cases),
                "deduplicated_results": len(results),
                "bytes": output.stat().st_size,
            }
        )
    )


if __name__ == "__main__":
    main()
