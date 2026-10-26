# Conversational command execution

The authenticated dashboard at `/agent` and the paired private Telegram owner use
one durable queue and `CommandPlanner` → `CommandExecutor` → fixed tool registry.
This is an implementation for the existing single-owner deployment, not a new
multi-user authorization system. Chrome and AGY identities cannot enqueue commands.
The extension remains v1.2.1. Submission and email sending are disabled.

## Running

Run the backend and dashboard using the existing private configuration. The existing
Telegram polling worker now drains this queue. For dashboard-only operation run:

```sh
python backend/scripts/run_command_worker.py
```

Use the existing backend environment loader/operator configuration. Start only the
reviewed release against the owner-approved online PostgreSQL database. This change
does not install or restart the owner's running services, change launchd, run
production DDL, deploy hosting, or enable any source/account automatically. API
startup does not start a command worker. The dashboard reports an absent/stale
worker as pending, based on a persisted heartbeat, rather than implying execution.

`POST /api/v1/agent/commands` accepts only `Message(text, request_id)`. Reuse the
request ID after a lost response; different text with that ID returns a conflict.
`GET /agent/campaigns`, `/agent/campaigns/{id}`, and `/agent/status` expose the
persisted outcomes. Authenticated owner controls are `/agent/campaigns/{id}/cancel`
and `/agent/campaigns/{id}/approve`. Approval is revision/nonce bound and supports
`prepare` only. The BFF retains its session, CSRF, and fixed-route restrictions.

## Commands

These commands run without a cloud model:

- `Find backend jobs in India.`
- `Find backend jobs in India from Arbeitnow.`
- `Only show startups.`
- `Exclude internships.`
- `Only companies with 2–10 employees.`
- `Show the best five.`
- `Prepare applications for the first three.`
- `Use Quick-Clinic as my main project.`
- `What happened to my previous search?`
- `Which applications still need information?`
- `Cancel that campaign.`
- `Find 10 Python backend jobs in Indian startups with 2–10 employees, exclude jobs I've already applied to, rank them and prepare applications for the best five.`

A new search defaults to cached saved data; say `from Arbeitnow`, `from Remotive`,
`from Greenhouse`, or `from Hacker News` for a free-source fetch. Greenhouse needs
configured boards. Paid portal adapters are unavailable to this executor even when
configured elsewhere. Naukri, Wellfound, Instahyre, YC and Internshala account/session
observations never establish an automated application connection. LinkedIn remains
discovery only. Missing or failed discovery is persisted as unavailable/manual work;
no fixture or invented listing is substituted. Free discovery sends search filters,
not candidate profile data (`use_profile=false`, `allow_paid=false`).

The bounded per-owner context expires after 24 hours. It retains filters, up to ten
ranked result IDs, up to 100 scanned candidate IDs, approved project selection, and
pending/previous campaign references. Follow-ups reuse this saved result list;
filtering does not repeat external discovery. Model filter patches cannot reset
unmentioned dimensions. A new wider search is necessary to go beyond the stored
100-job scan. Unknown size, employment type, location, work arrangement, salary
comparison or experience are explicitly recorded and excluded from the confirmed
match/positional list when that dimension is required. A `1–10` band cannot prove
`2–10`. Existing applied jobs and submitted packets exclude the whole saved company.

Explicit preparation language authorizes local drafts for the actual selected
results. `Apply to the first three` pauses for clarification/approval of the exact
local draft scope. `yes` does not authorize submission. Preparation requires the
current reviewed profile and uses the existing packet builder, confirmed resume
selection and approved project context. Missing facts produce `needs_input`, with
actual packet IDs only when a packet was saved. Review blockers are distinguished
from missing facts; resume upload remains manual. Project selection requires an
exact approved project name/ID; removed approval causes abstention on later use.

## Permissions and recovery

The registry exposes only `search_jobs`, `filter_jobs`, `rank_jobs`,
`get_candidate_profile`, `get_approved_project_context`, `get_canonical_resume`,
`get_application_history`, `prepare_application`, `generate_grounded_answer`,
`get_campaign_status`, and `cancel_campaign`. Every proposal is checked against a
strict argument schema, authenticated owner, exact server-generated plan step,
saved selection, running state, and budgets. Preparation additionally checks the
nonce/revision/application cap, platform policy, existing submission evidence and
reviewed candidate data. `fill_application` and `submit_application` always return
`capability_not_enabled`. No tool exposes shell, SQL, files, arbitrary navigation,
email sending, or arbitrary HTTP execution. Cohere tool-call parsing produces
proposals only; the production planner uses structured Understanding JSON and the
backend generates the executable plan.

Campaigns and leases reuse private `owner_preferences` records; immutable intake
receipts and tool outcomes use insert-only `agent_operations`. Existing forced RLS
and runtime grants suffice. No migration or grant expansion is needed. State
transitions, source/run IDs, evidence URLs/status, rankings, selections, packet IDs,
missing information and profile/resume/project provenance persist. Row locking and
`SKIP LOCKED` claims serialize the single owner. Leases last 120 seconds, heartbeat
every 25 seconds, at most three claims, 16 steps/tool calls, 4,000 observed planning
tokens, 180 seconds per attempt and 45 seconds per local tool. A stale fence cannot
commit progress. Local preparation writes and progress are in one transaction.
Cancellation fences subsequent steps; a step already atomically committed remains
visible. Intake allows at most ten nonterminal campaigns.

Discovery reuses the existing independently idempotent `DiscoveryRun` and ingestion
service. A running/uncertain discovery after a crash requires investigation; it is
never treated as success or blindly reissued. An AI understanding attempt is marked
before sending; a lost response cannot silently authorize another cloud request.
Unknown token usage stops model-driven execution. Telegram acceptance and update
offset commit together. A failed/ambiguous send remains `sending`; automatic replay
could duplicate a message and is deliberately avoided. A completed campaign either
updates its unsent reply or creates a separate unique completion-outbox entry.

## Cohere

See [the provider contract and private configuration](cohere.md). Official V2
structured JSON objects (including nested filters) need a required property.
Unsupported remote bounds are removed; Pydantic still enforces them locally.
The V2 tool parser validates JSON-encoded function arguments, tool identity and
allowlist against the actual official `TOOL_CALL` envelope. JSON/tools are separate
modes; A+ thinking is disabled. There is no provider fallback, billing change or
Cohere retry. Local usage status is not the remaining provider-account quota.

No evaluation key was present in either private backend configuration inspected at
preflight. Live acceptance and account/model access are blocked; mock HTTP tests
are explicitly fictional. Activating live understanding requires an owner-verified
free evaluation key, `COHERE_ENABLED`, `COHERE_EVALUATION_KEY_CONFIRMED`, and explicit
`COHERE_OWNER_TEXT_AUTHORIZED`. Candidate profile/resume/project facts require the
separate `COHERE_CANDIDATE_DATA_AUTHORIZED` consent. Without it, a conservative job-only vocabulary gate also blocks unfamiliar free text that could contain private facts. Deterministic handling consumes
no cloud requests. Never enable a paid fallback or send candidate facts to validate
a key; first use a small fictional-data evaluation.

## Laptop boundaries

| Situation | Actual behavior |
|---|---|
| Mac awake, screen locked | Requests can execute while the processes and network stay available; no screen unlock is required by this backend worker. |
| Mac asleep | Local processes and Chrome tasks pause. Cloud Cohere does not wake or replace the Mac. |
| Mac offline | No safe database/provider/Telegram connectivity is assumed. Already committed work remains durable; the dashboard/transport may be unavailable and worker heartbeat expires. |
| Backend/worker restart | Committed queue/results survive. Expired leases recover with fencing and bounded claims; atomic preparation and idempotent discovery prevent duplicate successful writes. |

Tests model worker absence, network failure, restart, expired leases, cancellation
and duplicate delivery. They do not physically sleep/lock the owner's Mac or prove
continuous live operation. No 24/7 claim is made. Always-on cloud hosting remains
separately deferred.

## Validation

`backend/tests/test_agent_execution.py` exercises existing services with fictional
saved/HTTP fixture jobs, Telegram transport, dashboard auth, approvals, injection,
unknown evidence, missing profile, positional context and crash rollback.
`verify_command_postgres.py` creates and drops its own localhost PostgreSQL 17
database, applies the existing public bootstrap with isolated test role names,
and executes under its restricted grants. It verifies atomic competing claims,
heartbeat, stale fencing, expired-lease recovery, real packet writes, restart,
Telegram replay prevention, and source adapter → ingestion → persistent results.
It refuses non-local/non-disposable targets. The full regression also retains all
existing migration/security tests. Browser E2E uses the actual FastAPI/BFF/worker
with fictional SQLite fixtures only; this is not live portal or Supabase acceptance.

All heavy local tests use `fcntl.flock` on the existing
`/tmp/automated-apply-heavy-tests.lock` without deleting the lock inode. No Ollama
generation or local model loading is used. See the accompanying verification report
for exact final counts and links.
