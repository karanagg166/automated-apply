# Owner-operated upgrade and acceptance

This procedure upgrades the existing services. It does not install another bot,
executor, browser implementation or submission engine. Running it requires separate
owner authorization to change/restart the installed services. No upgrade, service
restart, owner-form fill or submission was performed during the readiness audit.

## Freeze and prepare the reviewed release

Use the exact accepted integration commit recorded in `live-readiness.md`, not a
moving branch name. Keep the occupied original checkout and its untracked files.
The installed checkout has local modifications: its Git SHA alone is not a backup.

After upgrade authorization, run from the integration checkout:

```sh
umask 077
support="$HOME/Library/Application Support/Automated Apply"
reviewed_sha="$(git rev-parse HEAD)"
release="$support/releases/$reviewed_sha"
backup="$support/upgrade-backups/$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$backup" "$support/releases"
chmod 700 "$backup" "$support/releases"
git diff --exit-code
git diff --cached --exit-code
git worktree add --detach "$release" "$reviewed_sha"
uv venv --python 3.11 "$release/.venv"
uv pip install --python "$release/.venv/bin/python" -c "$release/backend/requirements.lock" -r "$release/backend/requirements.txt"
pnpm --version
pnpm -C "$release/frontend" install --frozen-lockfile
pnpm -C "$release/frontend" build
pnpm -C "$release/frontend" exec playwright install chromium
pnpm -C "$release/extension" build
```

Require pnpm **12.15.0** before installing. Do not change system npm, replace the
lockfile, copy another worktree's dependencies or regenerate credentials. A release
venv stays at its original absolute path. Existing requirements are constrained by
the reviewed Python lockfile. Save `uv pip freeze --python "$release/.venv/bin/python"` and tool versions privately for the
release inventory; the unversioned pytest tooling is for acceptance, not runtime.

Keep the complete old `phase1-runtime` directory **in place**, including dirty and
untracked files, venv, extension and `.next` artifacts. Record its status, binary
diff and SHA privately. Before cutover, snapshot the launchd plists, native manifest,
native wrapper, `start-frontend.py`, external private env files and existing Chrome
profile metadata into `$backup` using `cp -p`; keep the directory mode 0700 and all
secret files mode 0600. Do not print their contents, put them in a PR or rotate the
resume encryption key. Check for file changes again before cutover; abort if another
writer has changed the release or installation. Do not prune old worktrees.

Run the existing **read-only** preflight against the unchanged private settings:

```sh
"$release/.venv/bin/python" "$release/backend/scripts/phase1/local_service.py" preflight --env-file "$support/phase1.private.env"
"$release/.venv/bin/python" "$release/backend/scripts/phase1/install_local.py" launchd-plan --service api --env-file "$support/phase1.private.env" > "$backup/api.new.plist"
"$release/.venv/bin/python" "$release/backend/scripts/phase1/install_local.py" launchd-plan --service telegram --env-file "$support/phase1.private.env" > "$backup/telegram.new.plist"
"$release/.venv/bin/python" "$release/backend/scripts/phase1/install_local.py" native-plan --env-file "$support/phase1.private.env" --extension-id gdjbmkffcpicbpiikcohlmokkmcpipgp > "$backup/native.new.json"
plutil -lint "$backup/api.new.plist" "$backup/telegram.new.plist"
```

These plan commands do not install or restart anything. The native manifest retains
the existing stable wrapper path and sole allowed extension origin. Review a new
wrapper that changes only its checkout and Python paths to this immutable release.
Prepare a private copy of the existing frontend launcher that changes only its
working directory to `$release/frontend`; retain its private env loading and loopback
binding. Prepare the frontend plist with that launcher's absolute path and the new
venv. Validate all paths and file modes before changing the installed definitions.
The existing install commands refuse occupied paths; do not remove files merely to
bypass that protection.

## Authorized cutover and rollback

Review the prepared files and backup inventory first. Stop the existing Telegram,
frontend and API services with `launchctl bootout gui/$(id -u)/com.automated-apply.<service>`.
Confirm each old PID exited; do not start a second poller. Install the reviewed
plists at their existing paths with mode 0600, install the reviewed native wrapper
at its existing path with mode 0700, and retain its single-origin manifest. Start
the API, then frontend, then Telegram with
`launchctl bootstrap gui/$(id -u) "$HOME/Library/LaunchAgents/com.automated-apply.<service>.plist"`.
Check `/health`, `/ready`, dashboard login, `/api/v1/agent/status`, Telegram poll age
and `last_error`. Verify the new API's OpenAPI includes command and browser routes.
The Telegram worker already drains the shared command executor; a second command
worker is unnecessary for this setup.

In Chrome, manually load/reload the reviewed release's unpacked extension build and
verify ID `gdjbmkffcpicbpiikcohlmokkmcpipgp`. Do not attach automation to everyday Chrome.
Keep `BROWSER_AUTOMATION_ENABLED=false`, `BROWSER_SUBMIT_ENABLED=false`,
`APPLICATION_SUBMISSION_ENABLED=false`, `GMAIL_SENDING_ENABLED=false`,
`AUTOMATION_EXECUTION_ENABLED=false`, Cohere consent flags false and local AI off
for the initial search/status acceptance. This release cannot submit to real
employers even if fixture submission flags are changed.

If health, auth, extension or worker checks fail: boot out the new services, restore
the backed-up plists, frontend launcher, wrapper and manifest, manually restore the
old unpacked extension location, then bootstrap the original API/frontend/Telegram.
The unchanged old runtime and its absolute venv paths remain available. Verify the
old health checks and polling. Preserve new release logs privately for diagnosis.
No schema change is part of this upgrade; do not run down migrations or reset the
database. Existing campaign/audit data survives. Do not replay uncertain attempts.

## Profile review in the existing dashboard

Open `http://127.0.0.1:3000/profile` and use the existing five-step wizard. The audit
found **no saved profile**, one decryptable/checksum-valid **unconfirmed** private
PDF, no primary resume resource, and three configured projects with zero built or
approved facts. Existing search preferences have no separate review attestation.

1. Review the actual PDF's contents; select it for final fact review. An upload or
   successful checksum never approves its content.
2. Supply/review name, email, phone, skills, roles, years of experience, education
   and relevant claims. Review GitHub/LinkedIn/portfolio and additional links.
3. Review job titles, locations, work arrangement, compensation, notice period and
   work authorization. Unknown values stay unknown.
4. Use the final review checkbox and save the current profile. Verify the primary
   resume resource refers to the correct encrypted PDF and is owner-confirmed.
5. In Profile's project-context panel, build each explicitly authorized checkout,
   inspect evidence and approve only actual contributions. Select Quick-Clinic
   only after its current revision is approved. Nothing in this audit approves it.

Any profile edit, PDF/resource change, changed project approval or stale job/document
requires refreshing and reviewing prepared packets and browser plans. Existing
version/hash/fence checks enforce this; never copy an old approval forward.

## Real Telegram acceptance, after authorized upgrade

Use the already paired owner's private chat. The audit used only `getMe` and
`getWebhookInfo`: it did not consume updates, simulate the owner or send messages.
Send these commands yourself and compare replies with dashboard Agent history:

1. `Find Python backend jobs in India.` Search defaults to saved/cache data. With
   the currently empty database, an empty result is truthful.
2. `Find Python backend jobs in India from Greenhouse.` First configure explicitly
   reviewed public board-token/company pairs in private `GREENHOUSE_BOARDS`, or use
   `from Arbeitnow`. Source availability does not promise India/Python matches.
3. `Only startups with 2–10 employees.` Confirm prior filters survive and unknown
   startup/employee facts are reported rather than invented.
4. `Show the best five.` Confirm actual stored job IDs, URLs and provenance.
5. `Prepare the first two applications.` Run only with at least two saved matches
   and reviewed owner facts. Otherwise expect needs-input and no invented second ID.
6. `Use my Quick-Clinic project.` Expect needs-input until current context is approved.
7. `What's the status of my applications?` A prepared packet must never count as submitted.

Record command/campaign IDs, saved job/packet IDs, source/retrieval times and worker
heartbeat privately. Do not send submission or generic approval commands. Chrome
filling and upload of owner data still require separate authorization. After that
authorization, opt into the existing dedicated Chrome worker using the documented
[worker procedure](../browser/inspection-and-fill.md), not an everyday profile.
Real portal compatibility limitations in `live-readiness.md` still apply.

## Locked-screen acceptance

Keep the machine powered and network-connected without changing power settings.
After the approved upgrade is healthy, start the existing read-only observer:

```sh
"$release/.venv/bin/python" "$release/backend/scripts/phase1/monitor_locked_worker.py" --help
```

Use its `--env-file` and `--output` options with the external private env and an
ignored private report. Coordinate a bounded observation period. The owner locks
the screen manually and sends a fresh `/ping` from their phone. Require observed
`IOConsoleLocked`, a new poll during that continuous lock interval and a new sent
pong during the same interval. Unlock and inspect the report; absence is unverified.
Do not infer Chrome readiness from a Telegram pong. Separately, with permission,
observe the dedicated worker's heartbeat while locked using a fictional form.
No real form fill is part of this test. Locking generally leaves user processes
running; sleep suspends local workers and network progress. After waking, observe
fresh heartbeats and fenced lease recovery. Physical sleep/lock/recovery has not
been tested on this integrated release. No 24/7 operation is claimed.
