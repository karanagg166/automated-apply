# Public profile contracts

The structural snapshots come from `backend/app/schemas/candidate_profile.py`, importing
public DTOs only. No settings, candidate data, provider or database is loaded by exporters.
They retain local `$defs`, constraints and forbidden extra fields. Runtime JSON Schema
validation disables remote/file retrieval and uses cached compiled validators.

`src/profile_contract.rs` adds explicit create/partial-update normalization, root ORM read
semantics, Unicode whitespace and casefold deduplication, email/URL canonicalization,
numeric/date coercion, exact Decimal serialization and cent bounds, chronological dates,
complete-profile authorization uniqueness and serialized UTF-8 size bounds. Missing partial
fields remain omitted; supplied null follows the complete field type. Partial preferences
merge one level, then the full resulting profile is revalidated. Empty PATCH is rejected.
The live placeholder fence preserves Python's Unicode case and word-boundary behavior.

The fictional corpus currently compares 779 cases with the public Python DTOs, including
root ORM reads and rejected inputs. Python Unicode 14 unsafe/word/digit tables and the
installed IDNA PVALID data are frozen in `profile-unicode.json`; they contain public Unicode
properties only. Export source is Python3.11 / Unicode14.0.0, Pydantic2.14.1/core2.50.1,
email-validator2.3.0 and idna3.20 (IDNA data18.0.0). New versions must pass drift and conformance
checks before changing these snapshots. This is bounded compatibility evidence, not a proof
of equivalence for every possible input.

```sh
uv run --no-project --python .venv/bin/python python -m rust.scripts.export_profile_schema --check
uv run --no-project --python .venv/bin/python python -m rust.scripts.export_profile_unicode --check
uv run --no-project --python .venv/bin/python python -m rust.scripts.profile_corpus --check
cargo test --locked -p automated-apply-agents --test profile_contract
```

The standalone Rust host implements authenticated `GET/PUT/PATCH /api/v1/profile` on its
existing loopback listener. It preserves strong If-Match/ETag versions, raw-versus-normalized
no-op behavior, atomic CAS and commit before acknowledgment. Resume associations, stored
confirmation/history and unrelated columns stay outside profile writes. Production/staging
placeholder checks remain mandatory. No existing owner service/proxy was redirected and no
real profile was saved. Validation errors use sanitized `detail` strings; they do not copy
FastAPI's complete per-input validation-error array. Saved-job matching is also implemented as an owner-only read computation. Profile readiness/
confirmation, resources and rich context endpoints still need ports and live acceptance.
