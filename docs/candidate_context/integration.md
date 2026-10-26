# Agent 1 integration contract

This branch is **module_complete**, not production_connected. Review the draft PR
before deliberately integrating it. Do not automatically merge or start a second
resume worker. No file below is changed by this workstream.

## Application adapters

```python
from backend.app.candidate_context.persistence import SQLRecordStore
from backend.app.candidate_context.service import (
    CandidateContextService,
    TelegramKnowledgeAdapter,
)

# Existing owner-authenticated request/worker transaction; no new DB credentials.
service = CandidateContextService(SQLRecordStore(session), reader=authorized_reader)
result = await service.answer(
    "Explain my Redis experience",
    project_rank=None,
    max_words=100,
    max_characters=2000,
)
# result: ContextAnswer(text, sources, generator, status)

knowledge = TelegramKnowledgeAdapter(service)
# knowledge.answer(...) returns a JSON dict matching ApprovedKnowledge.
```

`approved_projects()` returns `(ProjectApproval, configured_priority)` pairs and
excludes unapproved, changed-source and changed-configuration snapshots. A project
rank counts the currently approved projects sorted by priority; missing/unapproved
slots are not silently counted as real projects.

`ContextAnswer.status` is `draft_requires_review` or `missing_approved_context`.
`generator` is always `deterministic_extractive`. `sources` includes project ID,
approved revision, source commit, fact IDs and source references. No AGY or other
model generation is claimed.

`CandidateContextService.configuration()` returns the private typed setup and its
optimistic revision. `save_configuration(config, expected_revision=...,
owner_ref=...)` saves explicit owner edits and hash-only audits. For initial
environment proposals use `configuration_from_environment(mapping)` and
`seed_missing_environment(existing, defaults)`; saving proposals grants no fact
approval. `build(project_id, expected_configuration_revision=..., owner_facts=...)`
reads only authorized repository inputs. `approve(project_id,
expected_revision=<snapshot sha256>, fact_ids=(...), owner_ref=...,
owner_confirmed=True)` binds approval to a current exact revision.

Load bounded owner template claims with
`templates.load_project_facts(owner_selected_root, project)` and the scalable YAML
registry with `templates.load_registry(root, relative=...)`. Registry values
are proposals; the server's saved configuration becomes the active source only
after an explicit owner save. There is no startup reimport/overwrite.

## Resume engine wiring

```python
from backend.app.candidate_context.drive import AuthorizedDriveClient
from backend.app.candidate_context.persistence import FernetCipher, SQLResumeBlobStore
from backend.app.candidate_context.resume import ResumeSyncEngine

engine = ResumeSyncEngine(
    AuthorizedDriveClient(existing_verified_drive_token_callback),
    SQLRecordStore(session),
    SQLResumeBlobStore(session),
    FernetCipher(existing_resume_encryption_key),
)
result = await engine.check(saved_source, scheduled=True)
```

The token callback returns `DriveAuthorization(account_ref, allowed_file_ids,
scopes, access_token)`. It must be derived from separately authorized Drive access
and a verified account binding. Do not reuse Gmail-only scopes, broaden access,
copy a token from chat or rotate existing keys. The module has no OAuth browser
flow or automatic token refresh. An expired token returns a safe reconnect state.

Review/promotion calls require `expected_revision`,
`expected_source_generation`, `owner_ref` and explicit owner confirmation.
The integration owner must bridge the `candidate_facts_invalidated` event into
the existing candidate-profile/packet freshness controls in the same application
transaction. The engine does not silently rewrite the existing candidate profile.
`ApprovedResumeFact` retrieval filters version/generation so stale facts are
excluded. No pending PDF becomes approved simply because it downloaded.

Events use fixed kinds and stable IDs. Recommended user-visible update text:
“Resume update detected. New version downloaded. Review required.”
Route it through the existing dashboard/Telegram outbox after owner/channel policy
checks. Record the event ID and delivery state atomically, then acknowledge it;
never retry an ambiguous external send without the existing delivery policy.

## Minimal shared integration changes for Agent 1

1. Add owner-authenticated dashboard/BFF routes exposing typed configuration,
   project build/review and approved answer retrieval. Reuse the existing CSRF,
   bearer, owner identity and extension/Telegram capability boundaries. Do not give
   Telegram configuration-edit, approval or arbitrary repository/path powers.
2. Add private profile/dashboard fields for links, ranked registry entries,
   missing values, candidate versus approved summaries and pending resume review.
   Do not auto-populate personal facts from the empty templates.
3. Add missing optional settings only if the parent chooses environment proposals.
   Reuse existing `CANDIDATE_*`, Drive URL/ID and hourly interval names. The sample
   documents new `RESUME_DRIVE_ACCOUNT_REF`, `RESUME_SOURCE_TYPE`, missing profile
   names, `OTHER_PROFILE_URLS` and the three `PROJECT_XX_*` groups. No actual env
   file, global config or dependency file was changed here.
4. Inject `TelegramKnowledgeAdapter` into the parent's `ApprovedKnowledge`
   implementation after review. It returns only current approved evidence and
   deterministic output. Parent retains all command/tool authorization.
5. Choose exactly one resume sync implementation. Map existing approved
   source/version/history explicitly before enabling a schedule. Review any
   adapter changes to existing resume repositories; this PR performs no migration
   or live canonical-pointer write. Keep existing encryption keys unchanged.
6. Run the full integration/security suite and separately authorized actual Drive,
   dashboard and notification acceptance. The module tests use fictional data and
   cannot prove a real account connection.

No production DDL or new package is required by the module. It uses dependencies
already pinned in the Phase 1 lockfile (Pydantic, httpx, cryptography, pypdf,
PyYAML and SQLAlchemy). Mypy/Ruff/Bandit used for local checking are developer
tools; dependency files remain unchanged.
