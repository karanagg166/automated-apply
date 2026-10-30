# Narrow history fix ready for exact-SHA review

Candidate: [`98965f7607a4714371599fef0143d5e1f8eed25b`](https://github.com/karanagg166/automated-apply/commit/98965f7607a4714371599fef0143d5e1f8eed25b),
branch `fix/live-prepare-discovery-20261030`, base `main`,
[PR #48](https://github.com/karanagg166/automated-apply/pull/48).
**Prepared for review, NOT INSTALLED.** Approval of that SHA has not been recorded.
Current service source remains approved
[`90f2f2ade50a1c31b26ca85cc7fdf5e93bb67c20`](https://github.com/karanagg166/automated-apply/commit/90f2f2ade50a1c31b26ca85cc7fdf5e93bb67c20).

The implementation delta between90 and989 is limited to command/receipt sorting
in `backend/app/browser/chrome_profiles.py`: order each fresh snapshot by
`(created_at, key)` before retaining the last30. The other runtime sources and
extension bytes are identical. Tests and intervening acceptance documentation
also differ. No API contract, migration, matching rule, permission, timeout,
provider budget, Gmail gate or submission behavior changes.

The original defect omitted a completed command from37 durable records. Its four
regressions failed before correction; the original focused run passed47 tests.
See [the original counts, genuine snapshot and timing evidence](approved90-installation-20261030.md).
The new workflow report records the current combined local test run separately.
Existing history stays unchanged and no command is replayed to demonstrate this fix.

A private **non-installed** artifact of this SHA's extension inventory was prepared
and independently compared: **18/18 identical**, zero extra files, same public
key/ID and permissions. The installed90 extension build also matches18/18; the
profile's persisted historical build matches15/18. These are disk comparisons,
not runtime acceptance. See [the supported stable-path cutover](../extension-stable-path.md).

## Exact approval scope and installation plan

The reviewable installation target is **98965f7607a4714371599fef0143d5e1f8eed25b**,
not the moving PR head or the newer notification implementation. Installing989
will fix bounded history selection; it will not install the newer ready notices,
relocate the Chrome extension, discover a form or submit an application.

Only after owner authorization of that SHA:

1. Recheck service references, current commands, Stop/Pause state and owner/private
   configuration hashes. Preserve verified backups of all installation references,
   native identity, secrets and the exact currently installed90 release.
2. Produce a separate immutable release from989, build its Python environment and
   frontend/extension with pnpm, and verify exact source/inventory. Do not patch
   the running90 release, replace an existing release or share mutable dependencies.
3. Review the existing installer plans for API/frontend/execution/Telegram and
   native references against the backed-up90 plans. Keep all environment settings,
   profile selection and manual-only CI unchanged. No DDL or Gmail activation.
4. Quiesce only the known services, switch the reviewed references to989, restart
   those services and perform one bounded health/status verification. Compare
   command IDs to existing durable records; issue no Open/Prepare/Apply to test
   ordering. Preserve and report any original error rather than adding retries.
5. Roll back references to the verified90 plans if startup or status fails; keep
   both releases and private backups. Preserve terminal command evidence and stop
   unknown outcomes. Extension reload remains the separately owner-operated step
   described in the stable-path guide.

No installation command was executed, no LaunchAgent/native file changed, no
production service restarted and no hosted Action dispatched in this task.
There is no installation approval question blocking a manual first application.

| Check | Verdict | Evidence |
| --- | --- | --- |
| Exact SHA and narrow implementation review | PASS | One runtime file, creation-time/stable-key sorting |
| Original defect/regression reproduction | PASS | Original four failures;47 focused passes; genuine37-record snapshot |
| Exact989 extension artifact | PASS disk only |18/18 files; zero extras |
| Exact989 install authority | BLOCKED | Owner has not authorized this SHA |
| Exact989 live installed history | NOT TESTED | Services remain90 |
| Extension runtime cutover | BLOCKED | Persisted historical path; owner-operated setup/reload needed |
| Real application submission | NOT TESTED | Independent owner-operated Naukri action remains next |
