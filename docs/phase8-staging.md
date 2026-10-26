# Private workspace staging procedure

This prepares the existing Phase 7 Next.js workspace and FastAPI services. It does not select a
host, authorize database operations, prove a backup, or claim a deployed pilot. Phase 7 PR #11
merged at `48bd924018893c439de5b0aad890c16ed731b697`; both post-merge main workflows passed before
the Phase 8 branch was created.

## Select and authorize a target

Record exact hosting account/project IDs, Supabase project reference, database host/name, region,
owner, isolation evidence and intended HTTPS origins privately. A similar name is insufficient.
Restore CLI authentication privately; never put access tokens in task messages. Obtain explicit
owner authorization for that isolated target and the reviewed commit/migrations before deployment
or DDL. Production needs separate approval.

Review all SQL 001–010, including legacy RLS, policies, effective client grants, runtime DML rights
and append-only history restrictions. Follow the [backup/restore procedure](staging-setup.md) and
record the successful restore test, backup timestamp, encryption-key recovery and recovery window.
Run the existing Phase 6B offline plan and pinned read-only catalog preflight before and after an
authorized migration. Empty and partially migrated schemas require different DBA actions; never
blindly replay SQL to repair drift. Catalog presence is not historical migration proof.

## Configure both services

Use `backend/.env.staging.example` as the incomplete template for an ignored mode-0600 operator
file. The existing `configure_frontend_owner.py` prompts for the owner passphrase and creates
private login/key material. Preserve existing encryption keys. Never replace a resume key to
repair a deployment containing encrypted resumes. Live backend startup now requires a valid
dedicated resume key; OAuth retains its independent key ring.

```sh
backend/venv/bin/python backend/scripts/check_workspace.py --env-file staging.private.env
backend/venv/bin/python backend/scripts/migration_preflight.py
backend/venv/bin/python backend/scripts/migration_preflight.py \
  --env-file staging.private.env --inspect --confirm-staging-target "$STAGING_DATABASE_ID"
```

`check_workspace` performs no network/database operations. It checks password-hash shape,
independent session secret, HTTPS origins, backend host allowlisting, resume-key validity and
Gmail callback origin alongside backend checks. Passing means `configured_not_verified`; actual
login, key recovery, routing, grants and backups remain unverified. A target fingerprint prevents
substitution but does not prove isolation or authorization.

Inject only necessary server variables into each service. Frontend: owner password hash, session
secret, frontend/backend origins and backend owner bearer. Backend: database, owner bearer,
encryption keys and individually authorized providers. Never expose credentials through browser
bundles or `NEXT_PUBLIC_*`; never mount a developer `.env` into staging.

## Build and route

```sh
docker build --build-arg SOURCE_REVISION=REVIEWED_SHA -t automated-apply:staging .
docker build -f frontend/Dockerfile -t automated-apply-frontend:staging frontend
```

Both images run without root. The frontend uses pinned Node 22, pnpm@12.15.0, the committed pnpm lockfile and
Next.js standalone output. Its allowlisted build context excludes environment files, PDFs,
reports, node_modules and the backend. Supply secrets at runtime. It starts `node server.js` on
port 3000. Use one Node instance and one FastAPI worker until shared login throttling, session
revocation and concurrency budgets are deliberately implemented.

An approved TLS ingress must preserve exact Host, overwrite forwarding headers and route:

| Public path | Destination | Boundary |
| --- | --- | --- |
| Workspace, `/api/auth`, `/api/backend/*`, `/_next/*` | Next.js | Owner session, exact Origin, CSRF, bounded proxy allowlist |
| `/api/v1/integrations/gmail/oauth/callback` | FastAPI on the **frontend hostname** | Existing state, PKCE and browser-binding cookie; no injected owner bearer |
| Other `/api/v1/*`, if using one public hostname | FastAPI | Existing owner bearer, exact Host, TLS and request limits |
| `/health`, `/ready` | FastAPI or internal probes | Liveness versus database readiness |

Use the approved HTTPS API origin as `BACKEND_ORIGIN`. Plain HTTP to non-loopback names such as
`http://backend:8000` is rejected. With one hostname, route `/api/v1/*` to FastAPI to avoid a proxy
loop. With two origins, explicitly route the Gmail callback on the frontend hostname to FastAPI.
Vercel plus Render does not automatically supply this route or trusted forwarding. Verify the
selected ingress before consent; no arbitrary dynamic callback rewrite is added.

Restrict direct upstream access; trust only the actual ingress network in uvicorn. Disable query
logging for OAuth callbacks and caching for private responses. Allow up to 5 MiB on the exact
resume upload, 64 KiB on profile/packet mutations and 1 MiB on other mutations, retaining server
timeouts/rate limits. Verify login/logout, Secure/HttpOnly/SameSite cookies, CSRF, rejected
Host/Origin, API reads, encrypted PDF round-trip and notifications using fictional staging facts
first. Never use fixture credentials for the owner.

## Owner and provider activation

Upload the actual PDF through `/profile`; review extracted text and every career fact, project
contribution and preference before saving. Confirm proposed public links individually, resolve
the conflicting GFG proposals and decide optional projects. Repository existence does not confirm
the owner's contribution. Do not infer a resume destination from its short URL. Only confirmed
candidate data can support a genuine match or packet.

Follow [provider validation](real-provider-validation.md). Configured keys are not verified
access. Gemini needs separate potentially billable authorization, initially with fictional
evidence. Professional research/enrichment needs verified access, data rights and explicit cost
authorization. No LinkedIn fetching/account automation is permitted. Gmail connection is not send
authorization: verify expected sender, encrypted refresh envelope, exact scopes and timestamp.
Keep `GMAIL_SENDING_ENABLED=false`. No external application is submitted by these procedures.

## Local public discovery when staging is unavailable

```sh
backend/venv/bin/python backend/scripts/local_public_pilot.py \
  --authorize-public-read --source hacker_news --idempotency-key OWNER_RUN_ID
```

Supported local sources: HN, Arbeitnow and Remotive, one per invocation, at most 20 listings.
This mode loads no environment file, ignores provider credentials, uses no owner profile, and
cannot prepare packets or send anything. It reuses existing adapters/discovery services. Keep
the **same** mode-0700 state directory: SQLite, source windows, run IDs and mode-0600 reports
persist in ignored `reports/phase8-public/`. A process lock prevents concurrent runs. Same-key
retries reuse a run; new keys still respect pacing, including Remotive's six-hour window. Do not
delete/change state directories to bypass limits. This is not PostgreSQL verification and does
not populate a staging dashboard. Restrict/retain the state according to owner policy; never
commit it.

The pilot distinguishes supported listing geography from unknown/restricted remote locations.
US-only/residency-restricted and ambiguous locations remain in a review list and do not count as
relevant jobs. Worldwide availability is not proof of personal experience or work authorization.
Company size stays unknown without source evidence. Partial feeds, missing profile/destination
and zero suitable results remain shortfalls. Use the [staging pilot](end-to-end-pilot.md) after
authorized onboarding for database-backed packet preparation. Review is revision-specific;
opening handoff never marks applied.

## External notification prerequisites

Existing in-app preferences/activity/history remain available. Telegram needs an official Bot
API token, owner chat opt-in/ID, secret storage, budget and tested delivery/retry/deduplication.
Browser push needs HTTPS, permission opt-in, a service worker, subscription lifecycle, VAPID keys
and unsubscribe support. WhatsApp needs the official Cloud API, verified business setup,
recipient opt-in, applicable templates and current pricing/cost approval. Each channel needs
separate authorization and implementation verification. No external delivery is enabled here.
# Online persistence correction

The former local live SQLite pilot described below is retired. All genuine jobs
and workflow state now require approved online Supabase PostgreSQL. Use
`run_startup_pilot.py` with its existing staging approval gates; see
[online database setup](online-postgresql.md). Historical local results do not
establish online persistence.
