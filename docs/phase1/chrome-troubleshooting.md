# Chrome / Google Forms preview diagnostics

Phase 1 supports URL preview and connection checks. It never fills or submits a
Google Form. “Check this portal session” applies only to the five supported job
portals; using that action on Google Forms is unsupported.

The reported owner failure remains open until its exact action/error is confirmed
or the failing owner workflow is retested. A separately reproduced installation
fault is fixed: the old native manifest authorized the ID derived from the
`/private/tmp` checkout, while another installation path produced a different ID.
Real Chrome for Testing rejected the relocated origin with “Access to the
specified native messaging host is forbidden.” An isolated profile without its
host manifest produced “Specified native messaging host not found.”

The committed manifest now has a public RSA key, making the extension ID
`gdjbmkffcpicbpiikcohlmokkmcpipgp` independent of installation directory. This is
public identity material, not a credential or a substitute for the backend bearer.
The native host accepts exactly this origin; API authentication, explicit command
allowlists, frame bounds and preview-only results remain enforced. A reviewed
exact-key false positive is recorded in `.secrets.baseline`; scanner rules were
not disabled. See Chrome's official [native messaging documentation](https://developer.chrome.com/docs/extensions/develop/concepts/native-messaging).

The stable runtime and owned native manifest were updated without changing keys,
OAuth credentials, database credentials or Telegram pairing. The repair script
changes only `CHROME_EXTENSION_ID` in the private env, preserves a mode-0600 backup,
checks installation ownership and refuses a mismatched runtime manifest. The
project API and worker were explicitly restarted. No personal Chrome profile was
read or changed.

Owner retest:

1. In `chrome://extensions`, enable Developer mode and load unpacked from
   `~/Library/Application Support/Automated Apply/phase1-runtime/extension`.
2. Confirm the displayed stable ID above. A previously loaded temporary checkout
   needs reload/replacement; its old origin is intentionally no longer accepted.
3. Open the failing Form and use **Preview this application URL** or
   **Preview with Automated Apply** in the context menu. No field interaction is
   necessary. Report the exact action and visible error/result.
4. Check the matching backend correlation ID. A preview does not authenticate a
   portal identity or authorize form filling.

Actual isolated Chrome for Testing 156 passed ordinary HTTPS, a previously
owner-authorized real Google Form, Google redirect into that Form, refresh,
extension reload through Chrome's Extensions UI, browser restart, relocated
installation, stale native origin rejection, duplicate gesture coalescing,
unsupported page rejection and rendered popup success. Offline fault injection
uses an actual refused loopback endpoint in a private probe config; the popup
shows `backend_offline`, and restoring the endpoint recovers. The separate
lifecycle probe actually stops/restarts FastAPI with restricted PostgreSQL and
verifies persisted state. The owner backend was not stopped for offline injection.

The same Chrome checks reached the actual online API and seven corresponding
Supabase audit records under the stable extension ID. No Form fields were read,
filled or submitted. The test invokes the extension's own preview module in an
extension page, and reads the popup result. It is not proof of a new owner-profile
toolbar/context-menu gesture; that distinction is retained in live evidence.

Run from `frontend/`, with absolute private probe paths:

```sh
node scripts/verify-phase1-chrome.mjs /path/to/python /path/to/probe.private.env /path/to/approved-form.private.json
```

The optional form file contains only the previously authorized `form_url`. The
script creates a separate private profile/host manifest and never exports cookies,
passwords or session tokens. Do not substitute a personal Chrome data directory.
