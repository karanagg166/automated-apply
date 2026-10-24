# Operational blockers, decisions and next execution

Checked **2026-10-21**. No production access or state change occurred in this planning run.
The [master audit](automated-apply-master-roadmap.md) records source/test/merge distinctions;
[this backlog](phase-by-phase-implementation.md#one-ordered-actionable-backlog) is the one task list.

## Authorization ledger and precedence

| Action | Current authority / decision |
| --- | --- |
| Inspection/research/local harmless validation/planning docs/branch/commit/planning PR | Authorized by this request |
| R1 encrypted recovery | **Prior authorization explicitly reaffirmed in current request**; don't ask again. Execute only within existing reviewed R1 scope after private prerequisites, in a later recovery task |
| R2 schema/roles/runtime activation | **Not authorized**. Prepare exact reviewable bundle only after R1 evidence; separate owner decision required |
| Migration 012/runtime addendum | **Separately unauthorized**, not covered by R1, R2-by-inference, PR merge or configuration |
| Proposed migration 013/account branch | **Separately unreviewed/unactivated**; reconcile source/manifest/roles first |
| Real account consent/private resume/mail import or real persistent pilot writes | Not authorized by planning; owner actions/operation scope needed later |
| Notifications/recruiter outreach/applications | No external send/submission authority from this request. Even one Telegram test needs explicit permission |
| Production schedules, paid providers, hosting account/card/billing activation | Disabled/outside scope; default remains ₹0 |
| Merge #15/force push/shared password reset | Not authorized as a side effect; review before any later merge; no force push/reset |

Ignored `secrets/phase9/OWNER-SETUP.md` and private execution/release reports contain older text
saying current R1 approval is missing. The current user request supersedes that approval claim.
Their actual unresolved prerequisites remain: official endpoint/user/port and CA/provenance,
existing admin password entry, independent recovery identity retrieval, project plan/backup
entitlement, capacity and existing-app health. Do not edit these historical private reports to
make them appear newly verified. Recovery outputs are absent from the earlier production run;
synthetic `.age` files are not production backups.

## Blocker register

| ID | Blocker and evidence | Resolution / impact |
| --- | --- | --- |
| B01 | Both actual env files still select SQLite; no runtime DSN/API/owner auth | Configure private restricted PG/TLS after R2 and owner auth for Phase11; synthetic testing works now |
| B02 | Private helper `--check` exits blocked before connecting | Owner completes exact official Connect/CA/provenance/passfile setup; no admin password reset |
| B03 | Working age identity exists, independent recoverable copy unverified | Owner privately retrieves independent copy and harmless challenge passes; never regenerate existing identity |
| B04 | Actual R1 source export/full isolated restore not verified | Run P9-01/P9-02 under existing authorization after gates; Vault/ACL/digest failures are blockers |
| B05 | R2 not authorized; last actual catalog assessment says `job_agent` absent | Separate exact SQL approval after R1; preserve old public schema, no remote SQL in planning |
| B06 | Shared project plan/backups/headroom and older-app current health/window unverified | Owner dashboard evidence/health probe; no assumption Free or paid entitlement; stop rather than upgrade |
| B07 | #15 open/ac265d3; local fixes/release and separate account branch diverge | P10-01 reconcile once, keep latest CI attached to final head. Pinned manifest/binary compatibility required |
| B08 | Private-resume approval fix edb59c5/3eb59f5 not on main; account branch dependency updates unmerged | Review/cherry-pick relevant fix once in implementation task; audit actual dependency pins/advisories before live resume parsing |
| B09 | 012/addendum activation not approved; local 013 proposed separately | Independent review/authorization/catalog/role updates; don't deploy 012-only legacy grants or reserve duplicate migration IDs |
| B10 | No actual approved online owner profile/resume; existing private local artifacts not interrogated | Phase11 explicit real import/review/persistence; historical encrypted local PDF is not online readiness |
| B11 | No configured Greenhouse boards or current genuine persisted candidate match | Owner verifies employer-board identity; authorized bounded existing-source pilot after 11; don't invent India eligibility |
| B12 | Main accepts Gemini only; Ollama absent; 8 GiB/14 GiB disk budget | Phase13 small native model and settings/provider work; no cloud spend; manual narratives unblock first packet |
| B13 | Gmail client/keyring/consent absent; metadata doesn't authorize body intake | Optional separate readonly consent and reviewed account branch; Testing expiry/revocation/retention handled; manual import fallback |
| B14 | Telegram delivery adapter/recipient/config absent | Extend existing outbox, owner bot/recipient verification and explicit one-send test; in-app remains functional |
| B15 | No verified personal applicant submission API across required ATS/closed portals | Default official manual handoff; conditional Phase15B only after documented permission, no private APIs/bypass |
| B16 | LinkedIn secondary personal-account design conflicts with one-account terms | Remove secondary account from default architecture; keep primary manual messages/connections and permitted reference workflow |
| B17 | No selected external free always-running app/worker/LLM host | Default Mac app/local AI plus approved online DB; later host review only if needed; no 24×7 promise |
| B18 | Provider-specific contact/search free API/retention entitlement unverified | Disabled; no enrichment before first complete workflow; use published sources/manual research |

## Decisions made for this roadmap

1. Reuse current modular architecture, PostgreSQL queue/outbox, profile/evidence/packet domains and
   existing tests. No duplicate scheduler/status system or compulsory microservice/broker.
2. Keep requested Phase9–17 labels, with explicit 9A/9B, 12A/12B and 15A/15B slices. Minimal
   Telegram follows the first existing-source packet before optional AI/contact/adapter expansion.
3. Native Mac development and personal application processes are the default; actual data stays
   in the selected approved Supabase namespace under current policy. Local persistent PG is
   synthetic-only unless a future explicit policy review changes this.
4. Private upload is the first resume path; no forced public Drive sharing or broad OAuth.
5. Manual official application is a valid complete first workflow with truthful self-report.
   Provider confirmation remains separately evidenced; no fabricated auto-submit capability.
6. Only documented recurring free/no-card services qualify for default activation. Unverified
   free API access is excluded. Local caps do not prove provider account credit balances.
7. New setup must preserve existing secrets/key material and all uncommitted/private artifacts.
   No broad git staging or destructive environment cleanup. Review release manifests/SQL hashes
   on the selected branch, not another worktree's newer catalog.

## Consolidated owner checklist

- [ ] Privately complete official Connect direct/session host/port/admin user and actual CA/provenance
  for `jyzjgoniuwexvipbbpwa` in the existing `secrets/phase9/` files.
- [ ] Enter existing password through hidden helper; never reset the shared password or paste it here.
- [ ] Independently retrieve the existing age identity and verify harmless decrypt/tamper challenge.
- [ ] Confirm actual no-upgrade project plan/backup entitlement, free capacity and shared-app health/window.
- [ ] Let Phase9A execute the already-authorized exact encrypted recovery once prerequisites pass.
- [ ] Review actual recovery report, then decide R2 for a concrete exact SQL/privilege bundle.
- [ ] Later review 012/addendum and final release source/catalog together; approve no worker implicitly.
- [ ] Configure owner API/session/passphrase material privately, preserving resume/OAuth keys.
- [ ] Authorize one actual private resume import; review extracted facts/links/preferences separately.
- [ ] Select existing free job source/employer board and authorize one bounded read/save pilot.
- [ ] Create/verify Telegram bot/private recipient and explicitly approve one redacted test notification.
- [ ] Review actual packet and complete the official form manually, then report only what happened.
- [ ] Optional later: secondary Gmail readonly alert consent, local model and permitted public contacts.

Return completion statuses or private path/method only; never transmit secrets, private PDFs,
mail bodies, decrypted backups or recovery keys through chat/PRs.

## Next Codex prompt

Copy this as the **single next phase**, after completing the private owner inputs where possible:

> Continue Automated Apply in `/Users/karanagg/Desktop/Projects/automated-apply`. Execute only
> **Phase9A: verify private recovery prerequisites and complete the already-authorized R1 encrypted
> whole-database backup and isolated restore rehearsal** for Supabase `jyzjgoniuwexvipbbpwa`.
>
> First read `docs/plans/operational-blockers-and-decisions.md`, `docs/plans/phase0-environment-setup.md`,
> `docs/phase9-live-activation-review.md`, ignored `secrets/phase9/OWNER-SETUP.md` and the existing
> ignored exact R1 scope at
> `reports/phase9-shared-supabase/readiness-20261021/R1-EXECUTION-SCOPE.md`.
> My current instruction reaffirms prior R1 authorization: do not ask for duplicate R1 approval
> because historical notes say authorization is missing. Technical prerequisites and recovery
> scope/limitations still apply. Preserve every other worktree, local/private report, env file,
> encryption identity/key, migration checksum and untracked `supabase/.temp/`.
>
> Use existing PG17 clients `/opt/homebrew/opt/libpq@17/bin/` and `/opt/homebrew/bin/age`.
> Inspect private setup without displaying values. Validate official target mapping, selected
> direct/session endpoint (no transaction pooler), `sslmode=verify-full` chain/hostname, existing
> admin credential, independent identity retrieval/decryptability, actual plan/backup entitlement,
> free disk/tmpfs capacity and shared-app read-only health/window. Do not invent/reset credentials.
> If any prerequisite is absent, complete every independent safe check and give one exact private
> owner-action list; do not weaken TLS or substitute a same-disk key copy for independent recovery.
>
> When all gates pass, follow the existing reviewed R1 procedure: consistent read-only snapshot,
> entire dumpable database without schema/table exclusions plus separately encrypted roles without
> password hashes; stream directly into age with producer/encryptor exit checks, 0600 exclusive
> outputs and partial quarantine. No plaintext production archives/SQL/diagnostics on disk.
> Restore only in the already-pinned Supabase PG17 image under the exact network-none/no-port/
> no-production-mount/read-only-root/tmpfs/unprivileged procedure. Verify owners/ACLs/RLS/extensions/
> indexes/constraints/sequences and exact snapshot counts/full-row digests. Stop on populated Vault
> without independently reviewed key recovery or any inconsistency. Record external Storage/key/
> platform-service exclusions honestly; this is logical database recovery, not whole-service DR.
>
> Keep receipts/ciphertext in the existing ignored recovery/report paths, redact output, and remove
> only run-owned scratch containers. Report actual artifact hashes and reconciliation, not a
> synthetic success. Then prepare the concrete exact R2 review bundle without executing it.
> **R2, 012/addendum, 013, remote writes/roles/migrations/password changes, account logins/consent,
> resume/mail imports, provider pilot, notifications/sends/submissions, production schedulers,
> merging PR15 and paid/billing changes remain outside this task.** No new features are required.

## Planning delivery evidence

This plan creates seven requested documents on `docs/zero-cost-master-plan-20261021`, based on
main `e7ec1dd`; no implementation/migration/private configuration changes. Initial local tree had
only untracked `supabase/.temp/`, preserved. Fresh local validation: 134 backend passed/one
PG-dependent skip, 33 frontend passed, TypeScript and pip consistency passed. Documentation links,
whitespace and tracked secret checks are required before publication. The final planning commit,
PR URL and CI state are reported in the completion message; they are not inferred in advance.
