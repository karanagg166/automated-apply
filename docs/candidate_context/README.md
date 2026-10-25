# Candidate configuration, resume versions and approved project context

Status: **module_complete**, **not production_connected**. These isolated modules
have no registered routes, background workers, implicit settings reads, live
account credentials, model calls or database migrations. They are intended for
review through a draft PR targeting `feat/phase1-local-connections`.

The integration owner must review and deliberately integrate the branch. This
workstream does not modify PR #18/#17, Chrome, Telegram, Gmail, launchd, MCP,
shared settings or an active `.env`. The Phase 1 AGY limitation remains in force.

## Configuration and empty templates

`configuration.CandidateConfiguration` contains typed profile links, an optional
authorized Drive source and up to 30 ranked projects. Blank values remain
missing. Three empty project slots default to priorities 1, 2 and 3. Duplicate
IDs/priorities, unsafe links, unsupported sharing URLs, credential-bearing URLs
and unsafe context paths are rejected. Names, descriptions and personal facts
are never invented.

`configuration_from_environment(mapping)` accepts an explicitly supplied mapping,
using the existing `CANDIDATE_*` link/resume names and
`RESUME_DRIVE_SYNC_INTERVAL_HOURS`. It never reads a shared environment file.
`seed_missing_environment(existing, defaults)` returns a copy and preserves every
nonempty existing value. Saving intentional changes is a separate owner action
with optimistic version checks and hash-only configuration audits.

The placeholder file is
`candidate_context/templates/candidate-profile.env.example`. It has no populated
credentials or personal identifiers. No actual private configuration file is
created by this isolated workstream, because the integration owner controls that
file. A configured resume requires a separate opaque `RESUME_DRIVE_ACCOUNT_REF`;
having a Drive URL or Gmail OAuth does not prove Drive authorization.

Editable, initially unapproved templates are under `candidate_context/templates/`:

- `profile.yaml`
- `project_registry.yaml`
- `projects/project-01.md` through `project-03.md`
- `generated/compact-contexts/` (empty scaffolding only)

The YAML registry supports additional projects. Each project template contains
fields for purpose/business use, architecture/HLD, frontend/backend, database,
cache, messaging, security, infrastructure, APIs, challenges, actual contribution,
features, design decisions, supported measurements, interview points and evidence
references. File text claiming `approved` grants no approval. Approval exists only
as a version-bound owner action in the service. Private personal template copies
should be kept outside Git or in the existing ignored private storage.

## Resume synchronization

`ResumeSyncEngine(drive, records, blobs, cipher, clock=..., validator=...)` accepts
injected dependencies. `check(source, scheduled=True)` respects owner opt-in and
a 60-minute to seven-day interval; six hours is the default. A failed first check
also observes that interval. Nothing schedules or starts a poll automatically.

The engine verifies source/account/file identity, Drive version/revision,
ETag/modified time when provided, file size and SHA-256. Reliable unchanged
metadata skips downloading. Changed metadata whose supplied SHA-256 still matches
the previously verified bytes also skips a download. If only weaker metadata is
available, a byte check occurs at least every 24 hours. Missing change metadata
causes a download on each due check. Downloads are rechecked against metadata
after transfer to reject races and are validated structurally in a subprocess.

Only PDFs of at most 5 MiB and 100 pages are accepted. Truncated/invalid PDFs,
encrypted PDFs, embedded files, JavaScript/open actions and unsupported active
annotations are rejected. PDF contents never enter logs. A bounded subprocess
deadline kills and reaps a stalled parser. Linux also uses CPU/address-space
limits; macOS uses the process deadline and size/page limits.

`AuthorizedDriveClient` uses only the fixed official Google Drive v3 file API.
The caller supplies an account-bound token callback containing the exact allowed
file IDs and a Drive read/file scope. Gmail-only scopes are rejected. The adapter
does not discover credentials, expand access, refresh tokens, follow redirects,
use sharing-page URLs, change sharing permissions or make files public. Its
production HTTP client retains TLS certificate/hostname checks, disables
environment proxies, rejects redirects and bounds response sizes/deadlines.
The field/metadata contract follows Google's
[files.get reference](https://developers.google.com/workspace/drive/api/reference/rest/v3/files/get)
and [file resource reference](https://developers.google.com/workspace/drive/api/reference/rest/v3/files).

Each downloaded replacement is encrypted and recorded as `pending_review` with
source provenance, version/checksum, metadata and timestamp. The previous approved
version and its encrypted bytes remain available. `approve(...)` requires explicit
owner confirmation, the current ledger revision and source generation, and the
latest version ID. It rechecks encrypted blob integrity before promotion.
Duplicate approvals do not invalidate twice. Stale source generations, stale Drive
versions, changed-but-inaccessible sources, expired permission, transient failures,
partial downloads and concurrent state changes have fixed safe diagnostic codes.

Resume update/approval/fact-invalidation/failure events are persisted in the same
atomic record as state. Stable event IDs allow the integration owner to build a
deduplicated notification outbox. `acknowledge_event(id)` removes an event only
after delivery is durably recorded. The module never sends a notification itself.
Consumers must persist event IDs to prevent redelivery after crash recovery.

Fact invalidation advances `fact_generation` only when an approved version is
promoted. Future retrieved resume facts must match the current canonical version
and generation. Detection of a pending PDF does not silently replace reviewed
facts. Historical facts, packets and approved bytes are retained.

## Evidence-bound project precomputation

`AuthorizedCheckoutReader({exact_repository_url: local_checkout})` reads committed
blobs from explicitly authorized local checkouts. It verifies the repository's
origin and commit SHA, excludes symlinks/secrets/tests/unrelated paths, and uses
fixed Git arguments without a shell. No repository code, hook, install script or
documentation instruction is executed. No GitHub token is obtained or sent.
Another existing authorized GitHub integration can implement `RepositoryReader`;
its snapshot must preserve the same bounds and origin checks.

Extraction is bounded to 24 selected files, 128 KiB per file, 768 KiB total and a
30-second local checkout deadline. It reads manifests, README prose and relevant
source imports; retained file paths and hashes identify technical evidence. This
is a conservative static extractor, not a complete codebase or architecture audit.
Architecture/contribution/outcome details can be supplied in the owner template
and need separate human approval. The extractor supports common JavaScript and
Python dependency/import declarations; unsupported stacks are reported as
unverified rather than inferred.

Technical declarations such as “the repository declares Redis as a dependency”
remain distinct from claims about the owner's experience. README prose is
`inferred`, never approved personal experience. Suspicious repository instructions
are excluded; repository text has no execution path even when the heuristic does
not recognize it. Inferred or unevidenced facts cannot be approved. Unsupported
configured technology claims are reported and excluded from extracted facts.

`CandidateContextService.build(...)` stores a `pending_review` snapshot with source
commit, relevant-source hash, fact IDs, evidence and compact variants. An unrelated
commit that leaves selected files unchanged updates the last-check commit without
regenerating summaries. Changed relevant files or owner context produce a new
review revision. Previous approvals remain in history, but stale approval facts
are excluded from current answer selection until the new revision is approved.

Precomputed variants contain a 50-word overview, 100-word explanation,
architecture, technologies, challenges, interview explanation and resume bullet
candidates. They are extractive; missing subjects produce blank variants. No
achievements, scale, statistics, employers, responsibilities or causal impact are
invented. Candidate variants are explicitly unapproved. Approved variants are
recomputed using only the facts the owner selected for that revision.

`answer(...)` selects current approved facts by relevance, using priority to break
ties. An explicit project rank selects that ranked approved project. It respects
word/character limits and preserves source references. `ApprovedRewriter` defines
a future provider-independent interface, but no model implementation is invoked.
Generated answers remain drafts requiring review.

## Persistence and operational boundaries

`MemoryRecordStore`/`MemoryBlobStore` are explicit fictional/test adapters.
`SQLRecordStore(session)` reuses private `owner_preferences` JSONB with atomic
compare-and-swap revisions. `SQLResumeBlobStore(session)` reuses `private_resumes`
with encrypted immutable bytes. They do not create tables, initialize a database,
change privileges, obtain credentials or commit. The caller owns the transaction,
target/TLS/RLS checks and owner authentication. No new migration is required.

Do not run this engine alongside the old resume engine against the same source.
Before activation the integration owner must deliberately map existing approved
resume pointers/history to the new ledger, or adapt the domain contracts to the
existing resume repository. No historical approvals are inferred or imported by
this module. The prototype ledger is not a second automatically active canonical
source.

Bounded history/outbox limits fail closed with archive/backlog diagnostic codes;
records are never silently discarded. Configuration/project audits retain hashes
and actor/time metadata rather than duplicating private descriptions. Personal
project and source records remain in the server-side private storage boundary.
