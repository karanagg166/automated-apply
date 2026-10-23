# Phase execution specifications and ordered engineering backlog

Baseline/research date **2026-10-21**. [Audit](automated-apply-master-roadmap.md),
[environment](phase0-environment-setup.md), [permissions](free-platform-capability-matrix.md)
and [shared architecture](zero-cost-architecture.md) are normative inputs. This is one backlog;
phase-specific runbooks already in the repo remain authoritative for existing implementation.
Do not generate duplicate scheduler, answer, status, account or recovery systems.

## Acceptance conventions for every phase

Each phase records A objective; B reuse; C dependencies; D owner setup; E tasks by layer;
F data flow; G cost; H constraints; I tests; J done; K activation; L recovery; M evidence.

Test abbreviations: **U** unit, **I** service/API integration with controlled transport, **PG**
real disposable PostgreSQL17 migrations/constraints/roles, **C** concurrency/crash/restart,
**S** security/permission/secret/SSRF checks, **E** end-to-end browser/backend and later actual
owner operation. “Existing tests unchanged/pass” is mandatory; do not invent tests that simply
repeat documentation. PG tests run serially on a dedicated cluster; SQLite mocks cannot prove
locking/RLS/TLS. Feature changes require appropriate lint/security, frontend type/build/API parity
and existing workflows on the exact reviewed commit. Every live acceptance receipt stays ignored
and redacted when summarized in GitHub. Never close live gates with fixtures.

Estimates below are single-engineer effort, exclude owner/access/approval wait and assume reuse
survives review. Every phase has **implementation done** and **operationally accepted** states.
A conditional integration can be implemented honestly with manual fallback; do not call it live.
Future migration numbers are assigned only after reconciling existing 012/013 branches.

## Phase 0 — environment preparation (0.5–1 day)

**A. Objective:** reproducible safe local development and precise owner prerequisites.
**B. Reuse:** current venv, Node24, cached Docker PG17/Supabase images, existing CI/Playwright,
`check_environment.py`, `check_workspace.py`, private Phase 9 helper and runbooks.
**C. Dependencies:** none; real data remains subject to Phase 9.
**D. Owner setup:** private administrative connection/CA, independently retrievable existing
recovery identity; existing encryption keys preserved. No optional API account required.

**E. Engineering tasks:** P0-01 inventories versions/config-presence without values; P0-02
reproduces synthetic PG17 fixtures without touching host PG14 or shared DB; P0-03 privately
completes prerequisites. Backend: use 3.11/import/dependency checks. Frontend: use installed
Node24/pnpm lockfile/tests. DB: distinguish A/B/C and recovery scratch. Integrations: none live.
Security: permission/ignore checks and no generated key replacement. Documentation: runbook
with exact supported commands; optional persistent B remains synthetic and unprovisioned until needed.

**F. Architecture:** local isolated fixture services exercise existing modules; owner config is
separate from test config; no runtime mutation on checks. **G. Cost:** installed OSS/no card;
no unnecessary download. **H. Constraints:** templates do not equal readiness; Ollama installation
is not provider implementation; no reset/relink.

**I. Tests:** U/I existing readiness/safety; PG/C dedicated PG17/verifier child DBs; S wrong-target
rejection/ignore checks; E fictional owner UI only. **J. Done:** reproducible versions/commands,
synthetic tests pass with PG skips resolved where claimed, missing optional capabilities visibly
blocked and actual private prerequisites verified before dependent operations.
**K. Activation:** no account/remote SQL/worker. **L. Recovery:** remove only run-owned temporary
containers; retain existing env/services/keys; failed setup leaves existing files unchanged.
**M. Evidence:** tool inventory, check exits, exact test counts/skip reasons and ignored local
receipt. This task delivers inventory/runbooks, not completed missing owner setup.

## Phase 9 — safe database activation (1–3 days plus owner wait)

**A. Objective:** real persistent data without harming the older shared application.
**B. Reuse:** `docs/phase9-live-activation-review.md`, shared assessment, `docs/sql/phase9-*`,
`operations/{migrations,runtime_security,health}.py`, `verify_phase9_runtime.py`; ignored
`secrets/phase9/OWNER-SETUP.md` and exact R1 scope/recovery evidence.
**C. Dependencies:** P0-03. R1 recovery must pass before any R2 request/execution.
**D. Owner setup:** existing admin password/official endpoint/CA/provenance; independent age
recovery copy; actual plan/backup entitlement, existing-app health baseline and bounded window.
Current request confirms prior R1 authorization; **R2 remains unauthorized**.

**E. Engineering tasks:** P9-01 verifies prerequisites/TLS/project/read-only inventory; P9-02
streams authorized whole-DB and password-free roles exports directly into age, restores in the
existing pinned isolated network-none/tmpfs Supabase PG17 design, reconciles source-snapshot
counts/digests/ACLs/extensions. P9-03 prepares an exact reviewable R2 SQL/hash/privilege/impact
bundle; after separate approval applies reviewed 001–011/roles only as needed. P9-04 verifies
restricted runtime and an explicitly authorized probe/restart. Frontend: honest blocked/readiness
states, no onboarding yet. DB/security: preserve `public` and other app roles/data; do not rewrite
migrations. Integrations: none; no automatic backup wrappers replacing the reviewed procedure.

**F. Architecture:** admin read-only snapshot → encrypted stream → isolated local restore →
verification receipt → separate R2 administrator activation → restricted API role. Runtime never
runs DDL. **G. Cost:** existing PG17/age/Docker; shared free-plan eligibility must be confirmed,
no paid backup/PITR/add-on. **H. Constraints:** empty historical Vault does not prove a future
populated Vault recoverable; no external Storage/key/service export included by inference.

**I. Tests:** U/I config/TLS diagnostic handling; PG exact pinned migration/security verifiers;
C bounded locks/source-snapshot drift/abort handling and runtime restart; S hostname/CA/wrong-target
rejection, role escalation/shared-role/other-app denial; E actual encrypted source restore and
separately authorized persistent probe plus older-app before/after health. Synthetic recovery
proves harness only. **J. Done:** 9A actual-source encrypted recovery and independent decryption
fully reconciled; 9B separately approved activation, real verified TLS/runtime restrictions,
persistence/restart and older-app health pass. Until 9B, Phase 9 remains incomplete.
**K. Activation:** 9A within existing R1 scope after gates; 9B exact R2 separately authorized;
012/addendum excluded. **L. Recovery:** stop on trust/rights/Vault/drift/error; failed ciphertext
quarantined partial, no plaintext archive retained; never restore shared production as rollback
without explicit recovery authorization. Halt writes/worker before incident response.
**M. Evidence:** pinned commit/checksums, encrypted artifact hashes, source/restore reconciliations,
owner-held identity retrieval result, sanitized health/role/runtime receipts and actual R2 decision.

## Phase 10 — finalize existing automation (1–3 days)

**A. Objective:** reconcile and review durable discovery controls already implemented.
**B. Reuse:** PR #15 `automation/{models,schemas,store,worker,router}.py`,
`run_discovery_worker.py`, migration 012, `docs/sql/phase10-runtime-addendum.sql`, frontend
`automation.tsx`, tests; local completion `ccc66c5`/`2cd672e`, private-resume fix and release branch.
**C. Dependencies:** code review can proceed after P0; live activation depends on 9B and exact
012/addendum review. **D. Owner setup:** selected source/board rights, approved profile UUID/version,
in-app preferences; later explicit schedule/source/worker opt-in.

**E. Engineering tasks:** P10-01 compares published head/CI and local branch deltas, reconciles
private-resume fix once, matching unknowns/freshness/weights, source pacing and UI controls.
P10-02 reruns exact final-head regressions/PG17/security, updates PR for review; merge is a later
reviewed action, not this plan. P10-03 produces separate SQL/catalog/role impact bundle and
activation checklist. Backend: preserve fencing/leases/two-consumer admission. Frontend: truthful
preview/run/history and profile approval. DB: 012 unchanged unless independently reviewed bug;
no mixing Phase9-only binary/catalog. Integrations: allow only reviewed free sources.
Security: keep disabled deployment and saved schedule gates, paid/send/submission exclusions.

**F. Architecture:** existing PG schedule/execution queue → shared pacing → bounded provider
HTTP → fenced ingestion/matches/audit → existing notification rows. **G. Cost:** existing process
and PG, no broker/host subscription. **H. Constraints:** CI at ac265d3 says nothing about local
completion commits; no merge assumption. Migration 012 alone leaves legacy grants; addendum
must apply as reviewed with no premature exposure.

**I. Tests:** U/I source/config/profile controls; PG/C duplicate run keys, claim/lease/fence,
restart/disable race, stale profile, worker timeout, cooldown/429; S restricted grants/RLS,
BFF/CSRF, paid-source denial; E authenticated fictional controls and explicitly authorized
bounded live run later. **J. Done:** reconciled reviewed commit with green exact-head CI,
no duplicated engine and verified default-disabled entrypoint; activation additionally needs
012/addendum/runtime validation and one real source result with heartbeat/history.
**K. Activation:** review/merge, remote SQL and worker enabling are three different gates.
**L. Recovery:** pending undispatched claims may be reclaimed; dispatched unknown outcomes
blocked, not replayed; disable schedule/fence completions and preserve history on rollback.
**M. Evidence:** PR diff/review/final SHA and workflows; migration hashes; real worker/source
receipt only after approval. The current #15 local and CI results stay attributed to ac265d3.

## Phase 11 — real environment and owner onboarding (1–2 days)

**A. Objective:** approved actual profile/resume in the authenticated persistent workspace.
**B. Reuse:** `dashboard/resumes.py`, `resume_sync/`, profile/resources/evidence APIs,
`frontend/src/features/{profile,resume-sync,resume-review,resume-facts-editor}.tsx`,
local Phase11 release Compose/runbooks and private-resume reference fix.
**C. Dependencies:** Phase9B; reconciled release matching deployed catalog (012 if selected).
**D. Owner setup:** stable PDF/OAuth keys, API/session/passphrase material, approved origins,
real PDF/selected source and import authorization; actual fact confirmation follows extraction.

**E. Engineering tasks:** P11-01 review/adopt existing release artifacts and dependency updates,
verify startup/readiness/auth with paid gates off. P11-02 one private encrypted resume import,
owner-reviewed version/profile/resource activation and restart proof. P11-03 review projects,
GitHub URLs/contributions/preferences/notice/compensation fields, persist only known facts.
Backend: preserve encrypted history and version checks; frontend: show conflicts/missing facts,
review original evidence. DB: no fixture seed or SQLite genuine writes. Integrations: public-link
Drive optional; private upload default. Security: anonymous download/CSRF/client-secret checks.

**F. Architecture:** authenticated upload → isolated parser → encrypted DB version/proposals →
owner confirmation → versioned facts/resource; reads through BFF. **G. Cost:** local parsing/upload,
existing DB; no Drive paid storage or model call. **H. Constraints:** existing public sync is not
private Drive OAuth; do not regenerate key or silently approve extracted facts.

**I. Tests:** U/I bounds/fact differences; PG/C concurrent approval/stale source generation,
private-resume packet approval and restart; S encrypted-at-rest/download auth/SSRF/key preservation;
E actual owner upload/review/download and saved profile after restart. **J. Done:** one real
approved profile/version and resume, exact facts/links reviewed, persistent encrypted bytes verified,
owner UI authenticated and missing optional account cards truthful. **K. Activation:** actual
import/profile writes and chosen local host setup need explicit scope; no periodic Drive worker.
**L. Recovery:** failed parse/import rolls back; prior approved version active; lost approval response
idempotent; key loss blocks decryption and requires tested recovery, not new key generation.
**M. Evidence:** reviewed source/release SHA, actual import/version/resource/profile IDs, encrypted
storage/read/restart receipt, owner review, auth/readiness tests; private contents stay ignored.

## Phase 12 — free real jobs and account intake (12A 0.5–1; 12B 3–5 days)

**A. Objective:** persisted real opportunities and accurate source/destination/duplicate evidence.
**B. Reuse:** existing four direct feeds/registry, `job_ingestion.py`, `job_deduplication.py`,
normalization/observations, matcher, #15 source windows; local account branch's job intake,
capability registry, MIME/OAuth changes and tests, rather than enabling main's legacy parser.
**C. Dependencies:** offline adapter work after P0; genuine writes after 11; scheduling after 10
activation. **D. Owner setup:** verified company boards and bounded read/save authorization;
optional secondary Gmail client/scopes/label, separate 013 authorization after reconciliation.

**E. Engineering tasks:** P12-01 (12A) selects one existing source/known employer, performs bounded
actual discovery/match/packet preview with owner-approved facts, verifies destination and stores
unknowns. P12-02 adds missing Lever global/EU and Ashby GET adapters via existing factory,
normalization/source observations and reviewed board configs; Greenhouse already exists—extend,
do not rebuild. P12-03 reviews/reuses account branch for manual saved references and separate
Gmail read consent, scoped token storage/MIME ingestion/paging/retention/watermarks. P12-04 adds
expiry/dedup review and evidence filters. Frontend: show source and application destinations,
last seen/published/unknown geography, manual intake and honest connection state. DB: reuse
observations/identities; additive migration only for genuinely missing ingestion cursor/consent
state, reconcile proposed 013. Security: fixed hosts/slugs/no arbitrary feed URLs; HTML as data.

**F. Architecture:** public GET or separately consented bounded mailbox read → normalized jobs
with per-record provenance → canonical candidate identity/possible duplicate → transactional
observations/match. Gmail checkpoints commit with ingestion; replay doesn't duplicate. No LLM
necessary for core discovery. **G. Cost:** public free endpoints, no actor/search key; Gmail
only with no-billing entitlement/policy confirmed; manual import fallback. **H. Constraints:**
regional coverage limited; unknown “remote” not India eligibility; absent-from-one-page doesn't
mean closed; Remotive max four reads/day; closed portals never scraped.

**I. Tests:** U/I all missing fields, source association, HTML/MIME/spoof/redirect limits, global/EU,
Ashby unlisted/compensation, partial results; PG/C same-source replay and cross-source duplicate,
checkpoint crash/paging, worker shared quotas and approval preservation; S SSRF/scopes/CSRF/token
redaction/read-only API; E actual persisted listing/source HTTP receipt, match explanation and
reviewed packet; Gmail one actual alert only if consented. **J. Done:** 12A ≥1 genuine current
job in real DB, accurate geography/unknown eligibility, owner-reviewed packet; 12B both new
adapters tested/one selected board verified each, stale/duplicate handling, optional unavailable
accounts explicitly manual. No arbitrary minimum “matching” job count if none exists.
**K. Activation:** free read/save pilot independently authorized; Gmail consent and any new SQL
separate; no automatic expansion of enabled schedule sources. **L. Recovery:** 429/cooldown,
partial statuses, expiry/revoke stop, transaction rollback preserves checkpoint; never delete
application history on feed disappearance; email-link failures become manual references.
**M. Evidence:** adapter commits/exact CI, official board-ownership/rights record, source HTTP
status/time/counts, actual observation/job/match/packet IDs and replay receipt; no email bodies.

## Phase 13 — local factual application answers (3–5 days)

**A. Objective:** useful grounded narratives without paid AI or fabricated career facts.
**B. Reuse:** `ai/{base,provider_factory,schemas,validation,usage}.py`,
`application_answer_service.py`, `candidate_evidence_retrieval.py`, packet `answer_builder.py`,
existing answer drafts/review/staleness and `test_application_answer*`, `test_llm_provider.py`.
**C. Dependencies:** P0 for synthetic work; Phase11 facts for personal evaluation; not needed for
12A packet. **D. Owner setup:** native Ollama/single selected small model; owner-approved fact/Q&A
entries and permission for local use, no paid model key.

**E. Engineering tasks:** P13-01 extends provider/model Settings validation/factory for fixed
loopback Ollama without breaking Gemini compatibility; add native HTTP client, structured schema,
bounded input/output/time and serial inference. P13-02 approved answer bank with question/variant/
constraints/provenance/profile/evidence-version keys and explicit approval; exact sensitive facts
resolve structurally, never inferred from similarity. P13-03 deterministic evidence retrieval →
context-limited model proposal → server claim/schema/length validation → mandatory narrative review;
P13-04 synthetic and owner-reviewed benchmark. Frontend: facts/Q&A review, citations/unknowns/
validation failures and stale approvals. DB: reuse drafts/resources/evidence/usage; new answer-bank
storage only if existing models cannot express approval/version linkage. Security: no model tool
execution, URL-controlled endpoint or prompt logging. No remote/cloud fallback.

**F. Architecture:** facts → approved exact Q&A → selected verified evidence → optional loopback
proposal → factual validation → existing packet field/draft/review. Cache keys include normalized
question/options/limits/style and complete profile/evidence/resume/model/prompt versions; similar
questions cannot override changed notice/CTC. **G. Cost:** local inference/OSS retrieval; no embeddings
subscription. **H. Constraints:** 8 GiB limits; valid JSON is not factual correctness; model confidence
not eligibility. Unsupported or unknown answers remain needs_input/provider_unavailable.

**I. Tests:** U/I exact facts/options/sensitive abstention/provenance/constraint/stale-cache/prompt
injection; PG/C duplicate approval/cache writes and profile-edit race; S endpoint allowlist/no cloud
requests/no sensitive logging; E 40-case synthetic benchmark plus actual local owner-reviewed draft
with source citations, real model tag/digest and measured memory/latency. **J. Done:** provider
supported/tested, all accepted outputs schema valid, zero unsupported accepted benchmark claims,
100% sensitive-unknown abstention, local-only traffic and usable serial operation on this Mac;
manual answer fallback always works. Review is required even when benchmark passes.
**K. Activation:** installing/downloading is separate from using owner evidence; manual model warmup
only, no startup generation. **L. Recovery:** timeout/OOM/missing model => explicit unavailable,
release local concurrency slot, preserve approved answers, never auto-download larger/cloud model.
**M. Evidence:** exact commit/CI, model license/digest, private benchmark expected/actual and resource
metrics, reviewed actual draft IDs, no prompt/resume publication.

## Phase 14 — Telegram notifications (2–3 days; minimal slice first)

**A. Objective:** actionable redacted alerts while owner controls external delivery.
**B. Reuse:** `dashboard/notifications.py`, `NotificationDelivery`/`OwnerPreference` in
`dashboard/models.py`, frontend settings/notifications, #15 notification synchronizer.
**C. Dependencies:** P0 for implementation, 11/12A for real event; does not require Ollama or
optional Gmail intake. **D. Owner setup:** official bot/private chat/challenge, private token,
verified numeric recipient, opt-in and explicit one-test-send permission.

**E. Engineering tasks:** P14-01 defines reviewed backend-only bot configuration and owner recipient
enrollment, masks/omits secret responses and forbids paid broadcast. P14-02 extends same delivery
outbox with leased claims, event/channel unique key, recipient/config version, attempt/receipt/
unknown status and conservative retry classifications. P14-03 renders high-match/manual-required/
confirmed/unknown/provider-failure messages and daily digest, timezone/quiet hours/pause and deep
links. Frontend: test-send preview, recipient verification, delivery evidence/history and pause.
DB: reuse outbox; additive lease/receipt fields only as needed with restricted runtime grants.
Integrations/security: official Bot API only, private-chat allowlist, redact token-bearing paths,
no actions triggered by inbound bot text. P14-04 real authorized event/send/restart verification.

**F. Architecture:** committed existing event → existing outbox → explicit worker process →
rate-limited Bot API → message ID or failure/unknown record. Poll inbound challenge outbound-only;
no public webhook host. **G. Cost:** ordinary Bot API no card/Premium/Stars; in-app fallback.
**H. Constraints:** API acceptance is not reading; private bots are not encrypted secret chats;
localhost links only usable on Mac; no external sends from saving preferences.

**I. Tests:** U/I formatting/redaction/DST/digest/event mapping/429 and safe pre-dispatch retries;
PG/C multiworker single claim, configuration change, quiet-hour deferral, crash after send vs before
commit, repeated event coalescing; S token URL/exception/client leakage, wrong chat, spoof challenge,
CSRF; E one owner-authorized received test and actual job/handoff alert with persisted receipt.
**J. Done:** recipient verification + actual accepted/received redacted event, no duplicate local
outbox on re-evaluation, pause/quiet/digest work, no automatic retry of unknown transmission;
other alert categories tested and genuinely verified as they occur. **K. Activation:** explicit
token/recipient/opt-in/process start plus separately authorized first send; no approval inferred.
**L. Recovery:** 429 honors retry_after, definitive rejection recorded, uncertain network outcome
blocked for review; Telegram has no general idempotency key for sendMessage so exactly-once
external delivery isn't promised. Show its own failures in-app; rotate token if compromised.
**M. Evidence:** exact CI/commit, recipient verification receipt, actual message ID/time and owner
receipt confirmation, outbox/dedup/restart/unknown tests; no token or private chat data in PR.

## Phase 15 — manual workflow then conditional execution (15A 0.5–1; 15B 4–8 days)

**A. Objective:** complete genuine application workflow with honest outcomes, maximize execution
only where documented permissions support it. **B. Reuse:** packet/platform registry, resume
selector, answer builder, eligibility/review/tracker, submission evidence/events, frontend
applications and existing manual-completion APIs; use current domains instead of parallel status.
**C. Dependencies:** 11/12A and minimal 14 for first requested workflow; local AI optional;
15B after exact capability review and any required new SQL approved. **D. Owner setup:** correct
resume, actual required questions/consents, exact-content approval; 15B platform/employer permission
and documented credentials—not jobseeker login cookies.

**E. Engineering tasks:** P15-01 (15A) validates current destination, packet revision/questions,
resume download/upload instructions, performs manual handoff and owner-reported actual completion
or leaves outstanding. P15-02 reviews target-specific inspect/fill/upload/submit/receipt permissions
and writes supported/manual decision. P15-03 only for a qualifying free permitted target adds
adapter field mapping, correct resume bytes/version and safe validation; consents/unknowns handoff.
P15-04 adds durable submission attempt and guarded in-progress/unknown/current lifecycle transitions,
canonical candidate/job/destination/idempotency protection and receipt reconciliation. Frontend:
preview exact attempt, explicit approval, stop/manual action and immutable evidence. DB: extend
existing domain/triggers; current 008 forbids provider confirmation, so don't bypass it. Security:
sandbox any separately reviewed browser execution, explicit domain/navigation policy, no imported
session, CAPTCHA/MFA bypass, arbitrary JS/URLs, private ATS key extraction or mass apply.

**F. Architecture:** approved current packet → canonical duplicate guard → durable attempt commit
before side effect → permitted adapter → evidence/unknown reconciliation → current tracker and
notifications. Manual path uses existing self-report, separate from provider-confirmed. **G. Cost:**
manual official forms always free baseline; no paid browser service/captcha/enrichment. **H. Constraints:**
Greenhouse/Lever/Ashby employer submit APIs need employer credentials/permission; no default
personal applicant API. If no target qualifies, 15B remains conditional/manual; do not manufacture
an auto-submit acceptance criterion. Closed portals remain manual.

**I. Tests:** U/I exact mappings/options/consents/resume/version/receipt classifiers; PG/C duplicate
cross-source attempt, two approval clicks, crash before/after dispatch, lost response, stale profile
and immutable events; S restricted SQL guard transitions/approval scope/SSRF/no cookies; E 15A one
real manual handoff and, if actually completed, owner-reported submission; 15B controlled authorized
submission only with actual receipt plus rejected/unknown tests. **J. Done:** 15A accurate saved
outstanding/completed state and no duplicate; 15B only closes live supported capability with genuine
receipt. Unsupported automated platforms are explicitly documented with working manual fallback.
**K. Activation:** field inspection/fill/upload/submission permissions distinct; exact external
attempt separately authorized. **L. Recovery:** unknown stays unknown, no blind resubmit; reconcile
manually or documented receipt lookup; approval invalidated by material change; failed adapter
retains prior resume/packet/history. **M. Evidence:** capability source/permission, reviewed SHA/CI,
actual packet/attempt/receipt IDs, owner action record, unknown/duplicate/restart probes, no private
application content in Git.

## Phase 16 — startup and recruiter intelligence (3–5 days)

**A. Objective:** relevant small-company hiring/contact evidence and factual outreach drafts.
**B. Reuse:** `startup_discovery/` normalizer/intelligence/ranking/company identity/retention,
`people_discovery/`, `contact_enrichment/`, email candidates/suppression, outreach draft/review,
frontend startups/people/company/outreach. **C. Dependencies:** 12 evidence and first workflow
15A; can research public permission records earlier without enrichment builds. **D. Owner setup:**
reviewed official company sources/hiring signals and optional contact references; no contact key.

**E. Engineering tasks:** P16-01 extends official career/about/team/public professional evidence
allowlists/manual imports and freshness; P16-02 composes geography/industry/technology/hiring and
numeric 2–10 filters, conflicts/unknowns and headcount snapshot date; P16-03 finds relevant founder/
engineering/recruiter links or published professional email and distinguishes guessed candidates;
P16-04 produces owner-reviewed grounded outreach drafts. Frontend: source evidence and freshness,
suppression/corrections and review queue. DB: reuse evidence/contact identities and TTL; no duplicate
people schema. Security: personal data minimization, rights-reviewed collection/retention, no hidden
email verification SMTP or unsolicited sends. Optional providers kept off by default.

**F. Architecture:** jobs/official source facts → existing company identity/evidence → bounded
filters/relevance → contact evidence → existing approved draft workflow. **G. Cost:** manual/official
public sources/local drafts; Apollo/SignalHire only if independently proven free/legitimate later,
never needed here. **H. Constraints:** directory presence is not API permission; website tech hints
not proven stack; “1–10” band does not prove “2–10”; public email not mailbox verification/consent.

**I. Tests:** U/I headcount intervals/conflicts/provenance/role/email classifications, stale/source
withdrawal; PG/C identity reconciliation/suppression races/retention preserving audit refs; S source
allowlist/PII/logging/outbound gate; E actual company with evidenced hiring and relevant role,
headcount unknown unless evidenced, reviewed contact reference/draft without sending. **J. Done:**
one genuine complete research trail, exact 2–10 query returns only evidenced matches (possibly
zero), source dates and unknowns visible, suppression honored; no fabricated contact coverage.
**K. Activation:** source collection rights/owner review separate; sending still separately controlled.
**L. Recovery:** evidence expiry marks stale/unknown without deleting submission history; provider
failure stops enrichment, uses saved links/manual research; guesses never auto-promoted.
**M. Evidence:** reviewed source permission/commit/CI, actual company/job/contact-evidence/draft IDs,
freshness/retention receipt and no-send proof.

## Phase 17 — reliability and full personal pilot (3–5 engineering days + 7–14 observation days)

**A. Objective:** trustworthy repeated personal use, cost containment and recoverability.
**B. Reuse:** operations/readiness/health/report scripts, #15 leases/quotas, resume worker,
existing notifications/outbox/tracker and Phase9 backup/runbooks; local release Compose if reviewed.
**C. Dependencies:** activated workflow 11/12A/14/15A; test optional 13/15B/16 only if selected,
not as prerequisites that force unavailable services. **D. Owner setup:** operating hours, approved
source budgets/retention, backup destination, known incident/health channel, pilot scope and safe
owner completion; host decision only if B selected.

**E. Engineering tasks:** P17-01 adds visible last-success/heartbeat/stale/unknown/backlog/quota/
disk health and provider failure alerts; P17-02 exercises connection-budget/429/outage/sleep/crash/
restart and retention/cost startup checks; P17-03 schedules only selected operations with explicit
opt-in and runs the pilot; P17-04 verifies encrypted backup/isolated restoration and incident
handoff. Frontend: dashboard counts match authoritative evidence, no phantom applied status.
DB: capped growth/log retention, least privilege, no destructive “repair.” Integrations/security:
revocation/expired credentials/secret leak probes and free-gate checks on every dispatch.

**F. Architecture:** existing modular services/PG workers; no new monitoring SaaS/broker. Health
stored as sanitized counters/timestamps. **G. Cost:** local operation/free actual project resources;
no payment method, paid quota bump, keepalive service or third-party always-on promise.
**H. Constraints:** Mac sleep/network affects discovery/alerts; downtime visible and due work
coalesces; remote free DB pause and shared-app headroom remain real limits.

**I. Tests:** U/I health/failure/capacity signals; PG/C two-worker quotas, kill/restart/fence,
notification/submission unknown and backup integrity; S restricted access/revocation/no secrets
and paid dispatch refusal; E repeated real job→match→packet→alert→handoff→tracking, disconnect/restart
and restored state verification in isolation. **J. Done:** 7–14 days of explicitly scoped use,
no duplicate confirmed attempts, unknowns never auto-retried, daily counts reconcile, ₹0 incremental
API/subscription usage evidence, no paid gates, successful recoverable backup, honest uptime and
older-app health/headroom. No minimum number of submissions required when no suitable role exists.
**K. Activation:** process supervision/scheduling/backup cadence approved separately; no paid host
provisioning. **L. Recovery:** pause dispatch, preserve attempts/receipts, degrade to manual/in-app,
use verified restore only under incident authorization; no blind replay/backfill after sleep.
**M. Evidence:** final source/release CI, dated private pilot/incident/quota reports, real entity/
message/receipt IDs, backup hashes/reconciliation and owner acceptance of observed limitations.

## One ordered actionable backlog

Stable IDs below are the task tracking source; do not create a second backlog in each guide.
All tasks inherit the corresponding phase's A–M specification, cost ceiling **₹0 / no card /
paid gates off**, tests and activation boundary. “CI” means exact final implementation SHA,
not old branch checks. For planning/owner-only actions the evidence is the reviewed plan or
private verified receipt; mocked results never close a live task. All future rows are **planned**
unless explicitly marked inventory completed. Priority: P0 essential gate/first workflow; P1
subsequent product/reliability; P2 optional conditional expansion. A depends on completed acceptance,
not merely starting a predecessor. “Offline now” means it can be selected for a later scoped task
without credentials, not authorization to implement all phases during this planning request.

| Order / ID | Phase / priority / task | Depends on | Target modules/artifacts | Account/setup required | Cost guard | Tests | Acceptance criteria | Blocker / current availability | Completion evidence |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 P0-01 | 0 P0 inventory and readiness plan | — | Existing setup/check scripts, Phase0 guide | None | Reuse installed tools | Offline readiness, frontend, secret/link checks | Versions/paths, missing config and DB A/B/C documented | Inventory completed in this plan | Planning commit + fresh check results |
| 2 P0-02 | 0 P0 reproducible synthetic PG17 environment | P0-01 | Existing PG verifiers/CI/Playwright | Docker only | Local cached image | PG/C/S/E fixtures | All claimed PG checks executed on isolated 17; no genuine-data mounts | Offline now; memory/disk bounds | Run-owned receipt, PG version/test log/cleanup |
| 3 P0-03 | 0 P0 owner recovery inputs | P0-01 | Ignored secrets/phase9 files/helper | Existing admin/CA/age copy/plan | No password reset/add-on | Offline syntax + independent decrypt challenge | Correct-target private inputs and independent key retrieval pass | Owner inputs missing | Private readiness/challenge/provenance receipt |
| 4 P9-01 | 9A P0 read-only trust and baseline | P0-03 | Existing R1 runbook/config | Existing admin + selected CA | No upgrade | Actual TLS/project/rights/Vault checks | Verified hostname/tenant/source privileges and recovery dependencies | Owner inputs; no duplicate R1 approval | Sanitized actual baseline/TLS receipt |
| 5 P9-02 | 9A P0 encrypted whole-DB export/isolated restore | P9-01 | Pinned recovery procedure/PG17+age | Independent identity and storage capacity | Existing local resources | Snapshot/restore/digest/ACL/extension E | Entire reviewed logical scope restored/reconciled; no plaintext host artifact | Recovery inputs/integrity; R1 already authorized | Ciphertext hashes + actual-source restore receipt |
| 6 P9-03 | 9B P0 exact R2 review and activation | P9-02 | 001–011, phase9 SQL, manifest | Separate exact R2 decision/runtime credential | No paid host/DB | PG/S + actual preservation/health | Reviewed schema/grants applied only after R2; old app intact | **R2 unauthorized** | Reviewed hash bundle + authorization + activation receipt |
| 7 P9-04 | 9B P0 restricted persistent runtime | P9-03 | health/runtime_security/check_database | Private runtime DSN/TLS; probe scope | Small pool/no billing | PG/C/S/E real restart | Authorized probe persists/reloads; runtime cannot cross app boundary | R2 and separate real probe scope | Redacted runtime/probe/restart/old-app health |
| 8 P10-01 | 10 P0 reconcile existing branches | P0-01 | #15, edb59c5, ccc66c5/2cd672e, a339188 | No account | No provider requests | Diff/ancestry + affected regressions | One private-resume fix; matching/controls/source fixes reconciled; 013 conflict documented | Offline now | Reconciliation decision + reviewed diff/commit |
| 9 P10-02 | 10 P0 final-head review/CI/merge readiness | P10-01 | Existing feature PR/tests/UI | GitHub review access | Existing Actions entitlement | Full U/I/PG/C/S/E + images | Exact final head green and reviewable; merge only after review in separately scoped work | No review yet; #15 remains open | PR reviews/head/CI URLs; merge SHA only if actually merged |
| 10 P10-03 | 10 P0 separate 012/addendum/runtime gate | P10-02,P9-04 | 012, runtime addendum/catalog/worker | Exact SQL approval; later source/schedule opt-in | Public free sources only | PG/C/S + real bounded run if enabled | Correct binary/catalog/grants; default off, real heartbeat only when authorized | 012/addendum/activation unauthorized | SQL hashes/decision + actual runtime/run receipt |
| 11 P11-01 | 11 P0 secure actual local app environment | P9-04,P10-02; P10-03 if using 012 binary | Existing release branch Compose, backend/Next BFF | Owner auth/origins; stable keys | Local host/default disabled gates | Auth/readiness/build/S | Correct release runs against compatible approved DB; no fake readiness | DB/auth; dependency security review | Release SHA/CI + actual health/login checks |
| 12 P11-02 | 11 P0 actual encrypted resume and approved facts | P11-01 | dashboard/resumes, resume_sync, profile UI | Import permission, real PDF, owner fact review | Private upload/no paid API | PG/C/S/E actual import/restart | Confirmed encrypted version/profile/resource; original key preserved | Real import/review not authorized here | Actual private version/profile IDs + owner approval |
| 13 P11-03 | 11 P0 review project evidence/preferences | P11-02 | candidate_knowledge/profile/resources/project UI | Owner-known facts/repo URLs | No enrichment/model required | U/I/E fact retrieval/matching | Notice/location/CTC/skills known or explicit unknown; contributions attributable | Owner fact review | Approved version/evidence IDs, no facts in Git |
| 14 P12-01 | 12A P0 first actual job/match/packet | P11-03 | Existing direct feeds/ingestion/matcher/packets | Board/source selection and bounded read/save scope | Free source only | U/I/PG/E real HTTP/replay | ≥1 genuine opportunity and reviewed packet with correct destination/unknown eligibility | Real runtime/facts/provider permission | HTTP/count + job/observation/match/packet IDs |
| 15 P14-01 | 14 P0 bot/recipient enrollment minimal slice | P0-01 for build; P11-01 for live config | Connection UI/config, existing token patterns | BotFather/private chat/challenge | No Stars/Premium | U/I/S wrong recipient/token leak | Verified bot/private numeric chat + explicit opt-in; no implicit send | Offline now; owner bot for live | Exact CI + private enrollment receipt |
| 16 P14-02 | 14 P0 extend notification outbox/dispatcher | P14-01; P10-01 reconciliation | NotificationDelivery/preferences + worker | Recipient/config; schema approval if needed | Ordinary API only | PG/C/S unknown/crash/429 | Single local delivery record/claim; safe definitive failures; unknown not replayed | Offline now; future schema/activation | CI/PG races + reviewed additive SQL if needed |
| 17 P14-03 | 14 P0 alerts, digest, quiet hours and links | P14-02 | Existing notification generator/settings/UI | Owner timezone/quiet prefs | ≤local cap/free rate | U/I/E message redaction/DST | Categories/digest obey pause/quiet; no sensitive text; Mac-only links labeled | Offline now | CI + redacted message fixtures |
| 18 P14-04 | 14 P0 authorized actual alert | P14-03,P12-01 | Outbox/Bot API/notification UI | Explicit one-send approval | No paid broadcast | E actual API receipt + owner receipt | Actual job/handoff alert received and persisted; repeated evaluation deduped | **No send authorized by planning** | Actual message/time/outbox IDs + receipt confirmation |
| 19 P15-01 | 15A P0 first manual handoff/tracking | P12-01,P14-04 | Existing review/handoff/tracker/UI | Exact packet review; owner official completion | Free manual official form | PG/S/E real owner workflow | Handoff remains outstanding unless actually completed; self-report clearly labeled | Owner action, no auto-submit permission | Actual packet/event + optional true self-report evidence |
| 20 P12-02 | 12B P1 Lever/Ashby public GET adapters | P10-01 | direct_api/factory/registry/normalization tests | Verified employer board slugs for live test | Credential-free GET | U/I/PG/C/S/E | Both adapters robust; source/region/unlisted/compensation handled; one actual approved board check each | Offline now; rights/boards for live | Commit/CI + actual source receipts |
| 21 P12-03 | 12B P1 reconcile saved-job/Gmail intake branch | P10-01; P11-01 for live | a339188 job_intake/MIME/OAuth/013/tests/UI | Optional secondary OAuth readonly/label; 013 approval | No-billing API or manual import | U/I/PG/C/S/E scopes/replay/revoke | No legacy raw-token path; least-privilege body consent; checkpoint/idempotency | Optional owner scope/platform content rights | Reviewed branch integration/CI + live alert receipt if selected |
| 22 P12-04 | 12B P1 evidence freshness/dedup review | P12-01,P12-02 | Existing dedup/observations/search/UI | Owner ambiguous-identity review | No search API | U/I/PG/C/E duplicate/expiry | Source replay preserves human state; ambiguity blocks duplicate attempt; not closed from missing page | Offline now | Regression/PG/actual duplicate decision evidence |
| 23 P13-01 | 13 P1 local provider/settings/client | P0-02 | ai/base/factory/provider/config | Native Ollama, one model download | Local-only/no cloud fallback | U/I/S schema/timeout/host | Ollama supported by Settings/factory; Gemini safety intact; bounded local request | Offline synthetic work now; model missing | Exact SHA/CI + local model handshake |
| 24 P13-02 | 13 P1 approved fact/Q&A bank | P11-03,P13-01 | Knowledge/evidence/answers/packet review/UI | Owner approvals; additive SQL review if needed | Existing DB | U/I/PG/C/S exact facts/staleness | Safe exact reuse keyed to evidence/options/revision; unknown sensitive facts abstain | Owner Q&A review | CI + approved bank/revision receipt |
| 25 P13-03 | 13 P1 grounded generation/packet integration | P13-02 | retrieval/answer_service/validation/answer_builder | Approved evidence | No paid SDK calls | U/I/PG/C/S adversarial facts | Claims cited/validated; narratives require review; stale draft blocked | Local model/facts | CI + grounded draft/negative-case receipt |
| 26 P13-04 | 13 P1 correctness and resource benchmark | P13-03 | Evaluation fixture/report; existing APIs | Later real local-evidence evaluation scope | No model shopping downloads | 40-case E + RAM/latency | Zero unsupported accepted claims, full sensitive abstention, valid accepted schemas, 8 GiB feasibility | Model missing; quality not assumed | Model digest/license + private benchmark and owner-reviewed sample |
| 27 P15-02 | 15B P1 target-specific execution feasibility | P15-01 | Platform capability registry/provider matrix | Actual employer/platform permission evidence | Free permitted target only | Capability/contract review | Each inspect/fill/upload/submit/confirm stage supported or manual | Default ATS submit APIs require employer access | Reviewed permission decision + manual fallback |
| 28 P15-03 | 15B P2 permitted form adapter | P15-02 qualifying target; P13-03 only for model answers | Existing application adapter boundary | Documented access, exact packet/resume/consents | No browser SaaS/captcha service | U/I/S/E controlled target | Correct fields/upload; stops at MFA/captcha/unknown consent; no generic portal bot | **Conditional**; may remain unsupported | Code/CI + controlled authorized field/upload evidence |
| 29 P15-04 | 15B P1 attempt/receipt/unknown state | P15-02; P15-03 for real dispatch | Existing packet/evidence/events/SQL guards/tracker | Exact new SQL + external attempt approval | No retries that create duplicate applications | PG/C/S/E lost response/two-click | Durable attempt before network; real receipt only confirmation; unknown blocks replay | New SQL/action unauthorized; no default target | Migration/CI/race probes + actual receipt only if qualified |
| 30 P16-01 | 16 P1 official startup/hiring sources | P15-01,P12-04 | startup_discovery/source_registry/evidence | Owner source/retention rights | Published free evidence only | U/I/S/E source allowlist | Actual hiring source/time/company links; no directory scraper | Offline source review now | Rights record/CI + real company/evidence IDs |
| 31 P16-02 | 16 P1 accurate size/geo/stack filters | P16-01 | Existing intelligence/ranking/startup UI | Owner evidence/conflict review | No paid company dataset | U/I/PG/C/E interval/conflict | 2–10 only numerically evidenced; unknown/conflict visible; zero results acceptable | Source evidence may be unavailable | CI + actual query/evidence reconciliation |
| 32 P16-03 | 16 P1 founder/recruiter contact evidence | P16-01 | people/contact identity/suppression/retention | Public professional refs/owner review | Apollo/SignalHire disabled | U/I/PG/C/S/E suppression | Published/provider/guessed distinct; stale/suppressed not actionable | No proven enrichment entitlement needed | CI + real published evidence/correction receipt |
| 33 P16-04 | 16 P1 factual outreach drafts | P16-02,P16-03 | Existing outreach_drafting/review/UI | Owner recipient/content review | Local text/manual send | U/I/S/E factual draft | Grounded draft with source references, sending stays gated | Missing evidence needs_input | Draft/revision/approval IDs; no-send boundary |
| 34 P17-01 | 17 P1 health, quotas and cost startup checks | P10-03,P14-02 | operations/status/health/worker/UI | Actual free-plan quotas/operating prefs | Hard stop/no upgrade | U/I/PG/S/E failure signals | Stale worker/unknown backlog/DB capacity visible, paid dispatch refused | Offline build now; actual environment for closure | CI + redacted actual dashboard/cost receipt |
| 35 P17-02 | 17 P1 crash/outage/sleep recovery | P17-01 | Existing scheduler/outbox/tracker | Scoped fault window | Local bounded runs | PG/C/S/E kill/restart/429 | No duplicate external replay; due reads coalesce; dashboard accurate | Actual pilot scope/owner time | Dated fault/restart/counter reconciliation |
| 36 P17-03 | 17 P0 full personal pilot | P15-01,P17-02; optional features only if selected | Existing application/notification workflow | Explicit pilot/scheduling scope | ₹0 actual usage/no paid gates | Repeated real E + 7–14 days | Real evidence chain, honest downtime/status, costs zero, old app healthy | Activation/owner participation | Private dated pilot + actual entity/receipt/usage refs |
| 37 P17-04 | 17 P0 backup/restore and incident runbook | P9-02,P17-03 | Existing R1 procedure/retention/health | Approved cadence/destination/incident scope | Existing storage/egress headroom | Actual isolated restore/C/S | Recoverable current state and key retrieval, retention/unknown history preserved | Separate future backup cadence scope | Encrypted hashes/integrity receipt + incident walkthrough |

## Work that may overlap and work that must serialize

Owner completion of P0-03 can overlap read-only P10-01 review, offline provider/capability work,
notification message design and synthetic local-AI implementation when separately selected.
Independent frontend work can accompany backend contracts after contract agreement. Do not run
multiple heavyweight PG suites/model/builds concurrently on this 8 GiB Mac; this is a capacity
constraint, not a dependency requiring a new server.

P9-01 → P9-02 → R2 review/approval → P9-03 → P9-04 must serialize. Phase9-only release cannot
start against the Phase10 manifest or vice versa. 012/addendum and proposed 013 activation must
follow final branch/catalog reconciliation and their own approval. Real resume import precedes
fact confirmation; approved facts precede personalized-match claims; exact current packet
approval precedes external attempt. Submission dispatch and its persisted attempt cannot reorder.

Shortest delivery path is backlog **1–19**, using the existing feeds and manual handoff. It does
not require tasks 20–33. Reliability controls already needed for safe first dispatch are included
in 10/14/15; Phase17 broadens observation and operations, not permission to defer those controls.
P17-04 backup rehearsal is reused from Phase9 and repeated after meaningful pilot changes, not
an excuse to operate without a recoverable backup meanwhile.
