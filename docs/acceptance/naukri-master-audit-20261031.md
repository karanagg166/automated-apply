# Naukri continuation audit — Stage A

Phase **OPEN**. Audit source: `fix/live-prepare-discovery-20261030` at
[`4fb982693a251b095f3a426e164ae2da5595f4a0`](https://github.com/karanagg166/automated-apply/commit/4fb982693a251b095f3a426e164ae2da5595f4a0).
[PR #48](https://github.com/karanagg166/automated-apply/pull/48) is OPEN against `main`,
with that exact head. Its implementation candidate is `81a678cdce4ac9fd7b1761e0f43d67f7fa6a1cd2`.
The canonical checkout was clean; its resumable ownership registry was read and
updated for this continuation. No other checkout or installed release was edited.

| Area | Verdict | Evidence / gap |
| --- | --- | --- |
| Repository, PR, ownership | PASS audit | Current branch/head agrees with GitHub; one open PR; manual-only workflow triggers retained |
| Durable discovery / preparation | PASS source inspection; NOT TESTED live | PostgreSQL owner fencing, queue leases, bounded capacity, observation and actual packet/PDF preparation already exist |
| Automatic application execution | FAIL requirement | `naukri_native.READS` and extension consumer allow only job/search observation; preparation ends waiting with `submission_executor_pending` |
| Admission / no replay | PASS source inspection | Existing write gate checks matching, policy, receipt, packet, local PDF, fresh prior status and provider resume digest; writes lack a delivered consumer |
| QTrino history | PASS retained evidence; NOT REVERIFIED | Original genuine owner-authorized receipt and no-replay fence preserved; no repeat submission or provider visit in this audit |
| Installed API/execution/Telegram/frontend | PASS inventory; FAIL version consistency | Four LaunchAgent definitions reference `90f2f2ade50a1c31b26ca85cc7fdf5e93bb67c20`; API/frontend listening on loopback; `/health` HTTP 200 |
| Installed native host | PASS inventory | Wrapper references exact `90f2f2a…`; manifest restricts origin to stable extension ID `gdjbmkffcpicbpiikcohlmokkmcpipgp` |
| Selected Chrome extension | FAIL version consistency | Profile 8 Secure Preferences references preserved `b06909293b1866e8191277d17fc284c398b4307b/extension/dist`; 10/18 compared source JS/manifest files match current source (not a complete build inventory) |
| Profile synchronization | NOT IMPLEMENTED in recurring queue | Verified canonical facts and selected resume exist; comparison, scoped updates and versioned sync receipts still needed |
| Questions / AI / Telegram | PARTIAL source | Existing revisioned questions, authenticated replies and answer services; recurring browser integration missing |
| Gmail | PARTIAL requirement | Read/draft integrations preserved; legacy owner-confirmed sending service remains feature-gated and needs a product-wide read/draft fence |
| Awake locked Mac / repeated genuine cycles | NOT TESTED | No screen lock, GUI operation, provider interaction, new application or installed restart performed |

Existing tests are historical evidence in the linked
[queue report](naukri-background-queue-20261031.md), not tests rerun by this audit.
**New test count: 0.** Inventory involved filesystem reads, GitHub reads and local
HTTP/process inspection only. Two guessed health routes returned HTTP errors;
neither is represented as a readiness failure. No secrets, mailbox content, resume
bytes, raw private logs or screenshots are included. No migration or provider
network operation ran. No timing/resource improvement is claimed by an audit.

Reproduce from the repository: `git status --short --branch`,
`git rev-parse HEAD`, `gh pr view 48 --repo karanagg166/automated-apply`,
`git worktree list --porcelain`; inspect only sanitized release references in
the four `com.automated-apply.*` LaunchAgent definitions, native wrapper and
Profile 8 Secure Preferences. Do not print private configuration or entire browser
preferences. Existing installation and rollback remain in
[the queue report](naukri-background-queue-20261031.md) and
[approved90 inventory](approved90-installation-20261030.md).

Next: durable application execution/reconciliation and regression tests, extension
consumer/recovery, verified profile reconciliation, dashboard/Telegram contracts,
then exact-version release preparation. Production installation and genuine locked
acceptance require owner review/approval of the resulting exact SHA under
`AGENTS.md`; audit and fixture success do not authorize replacing production.
