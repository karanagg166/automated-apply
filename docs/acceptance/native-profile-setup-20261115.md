# Native profile setup and account gates — 2026-11-15

Implementation [`3744b12bfc2f621f806413e0bc853e9dee9b26dc`](https://github.com/karanagg166/automated-apply/commit/3744b12bfc2f621f806413e0bc853e9dee9b26dc),
branch `feat/rust-agent-runtime`, [PR #50](https://github.com/karanagg166/automated-apply/pull/50),
base `chore/uv-python-tooling`.

The operator helper now accepts only an explicit, approved-account-bound ordinary
Naukri profile setup request. It refuses suspended extension-manager navigation before
loading private configuration and refuses to overwrite a still-pending maintenance
intent. The queue must be stopped, the fixed selected profile online and commands enabled,
and the account binding current. The existing extension creates its own inactive profile
tab and records its receipt; this does not authorize a profile save or job action.

| Check | Result | Actual scope |
| --- | --- | --- |
| Helper/native profile protocol | PASS | Nine isolated Python tests passed in 1.30s: eight existing receipt/context cases plus the new pre-configuration WebUI refusal |
| Ruff/diff | PASS | E9,F,I on both changed Python files; diff whitespace check |
| Existing account evidence | PASS | Retained actual profile UI identity matched the current owner-approved hash; login/contact separation preserved; no identity published |
| Brave Naukri site access | PASS | Actual extension readback allows only the requested Naukri origin; unrelated example.com remains denied |
| Brave login inspection | PASS / limited | Inactive ordinary login/recovery UI inspected; selected tabs and Mac foreground/window order preserved |
| Naukri email verification | FAIL | One ordinary request returned the visible message “Something went wrong. Please try again.” Delivery unconfirmed; no resend or password change |
| Matching local Gmail verification access | BLOCKED | Saved account matches the approved Naukri identity, but actual read/search returned409 `gmail_reauthorization_required`; saved connected status alone was insufficient |
| Approved Chrome live connection | BLOCKED | Fresh status `PROFILE_OFFLINE`; heartbeat older than52hours; target profile absent from saved active-profile list. Persisted `connected=true` was stale |
| Actual native profile request | BLOCKED | Helper returned `PROFILE_OFFLINE` before creating an intent or tab. No successful native profile-open receipt claimed |
| Rust native host registration | PASS / limited | Missing Chrome host registration recreated to the existing immutable Rust executable; exact manifest bytes read back; no binary copy |
| Rust executable to actual API | PASS | One actual Mac framed health invocation returned `ok=true`, `read_only`; this is not an extension reconnection |
| Actual Chrome extension reconnection | NOT TESTED | No fresh heartbeat; awaiting owner opening the approved profile |
| Focus observations | PASS / limited | Actual Chrome metadata/read attempts and registration preserved all selected Chrome tab IDs, OS foreground PID and window ordering at sampled endpoints; no window restored or activated |
| Queue/submissions | PASS | STOP revision162 retained; no Apply, submission, quota reset or uncertain-job replay |
| Full Rust migration / live job acceptance | NOT TESTED / incomplete | Remaining ports, complete installed acceptance and strict worker receipt are still required |

The Chrome native registration was absent when inspected; the cause is unproven.
`com.automated_apply.agent` now points to the same canonical executable already used by
the distinct Brave registration. Implementation
`2e54eec15493f07aba8f112703ca8a4bdb4c3492`, SHA256
`ed335c20d948075372d611cd73d9c6a296047920822abf7d3b974905162a73a1`,
8,226,848 bytes. Allowed extension origin matches the actual Profile8 registration.
The retained extension files exist and report version1.3.40; protected browser preferences
were read only. There was no extension update, Chrome WebUI navigation or browser launch.

The new registration is OS metadata outside the repository; executable, private config,
operational evidence and rollback inventory remain inside ignored canonical `.local/`.
Rollback removes only this newly created manifest after verifying its recorded hash,
restoring the observed absent-registration baseline. No older registration was overwritten,
installed release removed, credentials exported or owner browser process restarted.
The Chrome browser connection remains unaccepted until its own fresh native heartbeat.

The Mac reported screen locked and hid native permission windows from accessibility
inspection. Later ordinary browser permission readback independently confirmed the Naukri
grant; no lock-screen bypass was attempted. The owner authorized autonomous browser setup,
and no terminal/extension-configuration action is now requested from the owner.

Opening another Chrome profile automatically while the owner's other profile is running
is fenced by the existing [profile launcher](../../backend/app/browser/profile_launcher.py),
which explicitly refuses that case to protect focus. The remaining physical step is to
unlock the Mac and open the existing approved Profile8 once, or complete sign-in in the
owned Brave window. Do not silently select another account, infer credentials, replay an
uncertain verification request or activate an owner window to make a check pass.

Reproduce fictional checks:

```sh
uv run --no-project --python .venv/bin/python python -m pytest backend/tests/test_profile_setup_maintenance.py -q
uv run --no-project ruff check --isolated --select E9,F,I backend/scripts/request_naukri_maintenance.py backend/tests/test_profile_setup_maintenance.py
git diff --check
```

An authorized real setup request uses the existing helper with an explicit private env,
`--request-setup --naukri-profile`; do not run it again until the profile is live and any
previous intent has been reconciled. Raw account/DOM/mailbox evidence remains private.
No hosted Actions or employer actions occurred. The preceding Rust baseline remains
[260 passing tests](rust-ollama-20261115.md); those tests were not rerun for this Python
operator-helper change and are not counted as new tests here. No new dependency was added;
there is no paired performance or whole-system resource claim for this milestone.
