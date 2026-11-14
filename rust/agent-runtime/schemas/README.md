# Public profile DTO snapshots

Generated from `backend/app/schemas/candidate_profile.py` without settings, candidate data,
provider access or database connections. These files contain structural constraints for
create, partial update and read contracts. They preserve local `$defs` references and
reject unknown fields.

```sh
uv run --no-project --python .venv/bin/python python -m rust.scripts.export_profile_schema
uv run --no-project --python .venv/bin/python python -m rust.scripts.export_profile_schema --check
```

These snapshots are preparation for the Rust profile API port. They do not implement the
Python model's complete semantic behavior: whitespace normalization, Unicode list deduplication,
email/URL canonicalization, numeric/date coercion, Decimal serialization, chronological dates,
unique authorization countries and the complete serialized-size bound need explicit Rust
implementations and differential tests. Default-null partial fields still reject supplied
null where the complete type is nonnullable. Empty PATCH must also be rejected.

No existing profile API route is replaced by checking these files in. Owner profile writes
must retain authentication before body parsing, 64KiB bounds, exact If-Match/ETag/version
semantics, unchanged-value handling, transactional commit before acknowledgment, existing
facts/resume association and live placeholder rejection. The migration remains incomplete.
