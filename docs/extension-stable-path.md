# Stable extension path and background-only boundary

The selected Chrome Profile 8 still persists extension ID
`gdjbmkffcpicbpiikcohlmokkmcpipgp` at the historical `b069092…/extension/dist`
directory. Read-only disk verification on 2026-10-30 found 15 of the 18 expected
candidate files identical; `background.js` and `task-coordinator.js` differ and
`tab-audit.js` is missing. The approved90 build and the separately prepared989
artifact each match all 18 files. This establishes a saved-path mismatch, not
its cause. No Chrome preference file was written and no desktop action occurred.

Chrome documents [Load unpacked and Reload](https://developer.chrome.com/docs/extensions/get-started/tutorial/hello-world)
for personal development. A persistent extension directory avoids selecting a new
release folder each time. It does not make the initial Chrome installation
background-only. [Chrome's runtime reload API](https://developer.chrome.com/docs/extensions/reference/api/runtime#method-reload)
reloads the extension that calls it; it does not migrate an installation to a
different directory. The current extension exposes no reviewed native reload
command. Do not inject one into the running historical release.

## Supported owner-operated cutover

After approval of an exact extension source SHA, use one dedicated real directory:

```text
~/Library/Application Support/Automated Apply/chrome-extension
```

This is a proposed deployment path, **not created or installed by this task**.
Keep it outside development worktrees and immutable historical releases. Retain
the public manifest key, extension ID, native allowed origin, existing permissions
and private profile binding. Do not use a mutable dependency/build symlink into a
release. Stage and verify the exact build privately first; preserve a rollback
inventory before an approved deployment copies it to this dedicated directory.
Do not update files while an application command is active.

1. The owner chooses a convenient time and uses the already selected Profile 8.
   Verify its profile path in `chrome://version` without switching profiles.
2. The owner opens `chrome://extensions`, enables Developer mode if desired and
   uses **Load unpacked** to select the dedicated directory. Preserve the same
   public key/ID. If Chrome refuses the same-ID relocation, stop and inspect the
   displayed error. Do not remove the old extension or lose its storage/grants
   to force installation; removal needs a separately reviewed recovery plan.
3. Verify the same extension ID and Chrome's displayed source path. Run the
   read-only verifier below against the dedicated directory and Profile 8.
   A disk/path match is necessary, but alone does not prove which code is running.
4. The owner uses Chrome's **Reload** control once, observes that the service
   worker loads without errors, and checks a fresh heartbeat for the same
   selected binding. In its own service-worker DevTools, the owner can inspect
   `background.js` imports for `./tab-audit.js` and compare the loaded source
   with the approved file. Do not read profile credentials/storage secrets.
   No application command, Apply action or browser restart is needed to check
   extension identity/source and heartbeat.
5. Repeat the saved-path/disk check after the owner's next *normal* Chrome
   restart. Do not restart Chrome to produce acceptance evidence. A persisted
   source-path change remains a failure until explained; this guide does not
   claim to have reproduced or fixed the prior reversion.

For subsequent approved updates, stage the complete reviewed inventory, preserve
the previous dedicated-directory inventory, replace only this deployment's files
while execution is stopped, and have the owner use Reload. Do not overwrite any
immutable release. Background preparation remains possible afterwards where the
site/permissions allow it; all GUI gestures in this procedure belong to the owner.
If the requirement excludes even owner-operated setup/reload, **cutover is
blocked**: no supported silent relocation route has been established here.

```sh
backend/venv/bin/python backend/scripts/verify_extension_cutover.py \
  --sha 98965f7607a4714371599fef0143d5e1f8eed25b \
  --extension-dir "$HOME/Library/Application Support/Automated Apply/chrome-extension" \
  --profile-dir "$HOME/Library/Application Support/Google/Chrome/Profile 8"
```

Exit 0 means exact disk inventory and saved path match; exit 1 means mismatch;
exit 2 means audit failure. It emits file hashes and path-equality booleans,
never profile contents, account identities, credentials or absolute paths.
`runtime_reload_verified` deliberately remains false: runtime observation is
separate evidence. No preferences are patched; no permissions or protections are
changed; no Chrome process is launched, attached, closed or focused.

## Distribution alternatives

[Chrome's distribution guidance](https://developer.chrome.com/docs/extensions/how-to/distribute)
supports Web Store distribution and managed enterprise self-hosting. External
installation on macOS [requires a Web Store update URL and user confirmation](https://developer.chrome.com/docs/extensions/how-to/distribute/install-extensions).
This project has neither a reviewed published Web Store item nor an authorized
managed deployment. Introducing enterprise policy, a different browser/profile,
debugging flags or protected-preference edits is not a cutover solution for this
session. Web Store publishing is a separate release project and does not need to
delay the first owner-operated Naukri application.
