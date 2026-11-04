# Chrome DevTools MCP on this Mac

The owner's Codex configuration registers `chrome-devtools` using the official
`chrome-devtools-mcp@1.12.0` package through pnpm. This is a developer tool beside
Automated Apply; it does not replace the stable Naukri extension or its queue.

Registration used this command, with the installed pnpm executable:

```sh
codex mcp add chrome-devtools \
  --env CHROME_DEVTOOLS_MCP_NO_USAGE_STATISTICS=1 -- \
  /opt/homebrew/bin/pnpm --silent dlx chrome-devtools-mcp@1.12.0 \
  --headless \
  --executablePath="<installed Playwright Google Chrome for Testing executable>" \
  --userDataDir="$HOME/Library/Application Support/Automated Apply/developer-tools/chrome-devtools-mcp/browser-profile" \
  --no-usage-statistics --no-performance-crux
codex mcp get chrome-devtools --json
```

The actual private configuration is in `~/.codex/config.toml`, with an exact
access-restricted backup retained before editing. Existing Codex settings and the
Supabase MCP configuration were compared and preserved. Do not commit that file,
authentication stores, browser profiles or the private backup.

Use the existing Playwright testing executable with bundle ID
`com.google.chrome.for.testing`, as well as the private user-data directory.
Launching another headless system Google Chrome can take over macOS AppleScript's
`Google Chrome` application-name lookup, even with a separate profile. The verifier
now rejects that configuration before it launches a browser. The exact cached
testing executable path is registered privately; it is not a portable literal.

The separate browser identity and headless profile preserve the owner's focus and
signed-in Chrome profiles. No `autoConnect`, `browserUrl`, `wsEndpoint` or Profile8 user-data path is
configured. Usage statistics and performance CrUX lookups are disabled. Connecting
to an authenticated existing browser would be a separate setup operation subject
to existing account, permission and focus requirements. This setup does not log
into Naukri, authorize a database migration or enable application submission.

Configured servers are loaded by Codex clients when they initialize their MCP
connections. The native tools became available and a real `list_pages` call worked;
it exposed the system-browser identity conflict above. The corrected connection subsequently passed a direct native `list_pages` call
on November4, showing the separate owned `about:blank` browser. The earlier stale
transport is resolved. Direct protocol verification below also works without
restarting the owner's Chrome.

Run the actual registered server and browser check from this repository:

```sh
.venv/bin/python backend/scripts/verify_chrome_devtools_mcp.py
```

This uses the installed MCP client SDK and registered command. It requires the
separate headless profile, rejects personal-profile aliases and existing-browser
attachment options, and only creates/modifies/closes a new owned `about:blank`
page. It discovers tools, evaluates a DOM marker, reads the accessibility snapshot
and records whether the owner's frontmost application/window active-tab IDs are
equal before/after. Metadata reads do not launch a closed personal Chrome instance.
No personal URL, title, cookie, account, application environment or provider page
is inspected. A successful tool check is not Naukri application acceptance.

To undo registration, run `codex mcp remove chrome-devtools`. Preserve the private
backup and profile unless their deletion is separately approved. Restore the whole
config only after comparing any newer settings, rather than overwriting them.

Official sources: [Chrome DevTools MCP](https://github.com/ChromeDevTools/chrome-devtools-mcp),
[configuration](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/docs/configuration.md).
