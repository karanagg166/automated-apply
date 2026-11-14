"""Freeze public DTO constraints only; never load settings, candidate data or a database."""
import argparse
import json
from pathlib import Path

from backend.app.schemas.candidate_profile import (
    CandidateProfileCreate,
    CandidateProfileRead,
    CandidateProfileUpdate,
)

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args()
    for name, model in (
        ("profile-create", CandidateProfileCreate),
        ("profile-update", CandidateProfileUpdate),
        ("profile-read", CandidateProfileRead),
    ):
        path = ROOT / "rust/agent-runtime/schemas" / f"{name}.json"
        encoded = json.dumps(model.model_json_schema(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        if arguments.check:
            if not path.is_file() or path.read_text() != encoded:
                raise SystemExit(f"public_schema_drift:{name}")
        else:
            path.parent.mkdir(exist_ok=True)
            path.write_text(encoded)
    print("public_profile_schemas_match" if arguments.check else "public_profile_schemas_exported")


if __name__ == "__main__":
    main()
