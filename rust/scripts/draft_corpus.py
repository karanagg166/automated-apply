"""Saved-draft DTO oracle for PostgreSQL-shaped fictional records only."""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from backend.app.ai.schemas import DraftRead, DraftReviewUpdate

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    check = parser.parse_args().check
    base = {"id": "10000000-0000-0000-0000-000000000001", "candidate_profile_id": "20000000-0000-0000-0000-000000000001", "job_id": None, "question": " Describe   work ", "answer": " I built   workers.\n I added checks. ", "question_category": "project_explanation", "writing_style": "professional", "provider": None, "model": None, "evidence_references": [{"source_type": "verified_project", "source_id": " project:0 "}], "candidate_profile_version": 4, "review_status": "draft", "created_at": "2026-11-14T00:00:00+00:00", "updated_at": "2026-11-14T00:00:00.000007+00:00"}
    values = [base]
    for key, options in {"question_category": ["profile_link", "personal_details", "short_text", "project_explanation", "technical_experience", "motivation", "startup_interest", "work_authorization", "compensation", "file_upload", "unknown", " unknown ", "other"], "writing_style": ["professional", "conversational", "technical", "concise", "founder_focused", " concise ", "other"], "review_status": ["draft", "reviewed", "discarded", " reviewed ", "submitted"], "candidate_profile_version": [-1, 0, 1, 4, 5, 2147483647], "question": ["", "   ", " A\u001cB ", "é😀", "x" * 2001], "answer": ["", " A   B\nC ", "x" * 10001], "provider": [None, " cohere ", "custom"], "model": [None, " model-name ", ""], "job_id": ["30000000-0000-0000-0000-000000000001"], "evidence_references": [[], [{"source_type": "candidate_profile", "source_id": "x" * 100}], [{"source_type": "candidate_profile", "source_id": "x" * 101}], [{"source_type": "candidate_profile", "source_id": " "}], [{"source_type": "candidate_profile", "source_id": "id", "extra": True}], [{"source_type": "unsupported", "source_id": "id"}], [{"source_type": "opportunity_company", "source_id": "digest:company"}], [{"source_type": "verified_project", "source_id": "é😀"}]], "updated_at": ["2026-11-14T05:30:00+05:30", "2026-11-14T00:00:00.123456Z", "2026-11-14T00:00:00Z"]}.items():
        values.extend({**base, key: value} for value in options)
    values.extend({**base, key: "\u001cX\u001f"} for key in ["question", "answer", "provider", "model"])
    values.append({**base, "evidence_references": [{"source_type": "verified_project", "source_id": "\u001cX\u001f"}]})
    records = []
    for row in values:
        for version in [4, 5]:
            try:
                data = {**row, "stale": row["candidate_profile_version"] != version}
                for key in ["created_at", "updated_at"]:
                    data[key] = datetime.fromisoformat(data[key]).astimezone(timezone.utc)
                parsed = DraftRead.model_validate(data)
                result = {"accepted": True, "output": parsed.model_dump(mode="json")}
            except ValueError:
                result = {"accepted": False}
            records.append({"row": row, "profile_version": version, **result})
    reviews = []
    for value in ["draft", "reviewed", "discarded", " reviewed ", "submitted", None, True, 1]:
        for extra in [False, True]:
            body = {"review_status": value, **({"approve": True} if extra else {})}
            try:
                result = {"accepted": True, "output": DraftReviewUpdate.model_validate(body).model_dump(mode="json")}
            except ValueError:
                result = {"accepted": False}
            reviews.append({"input": body, **result})
    encoded = json.dumps({"records": records, "reviews": reviews}, ensure_ascii=False, indent=2) + "\n"
    path = ROOT / "rust/agent-runtime/tests/fixtures/draft-corpus.json"
    if check:
        if path.read_text() != encoded:
            raise SystemExit("draft_corpus_drift")
    else:
        path.write_text(encoded)
    print(f"fictional_draft_records:{len(records)} review_inputs:{len(reviews)}")


if __name__ == "__main__":
    main()
