# Portal session evidence for the selected browser

Local branch `feat/rust-agent-runtime`, implementation `51a20ee078baf43ecd7d5015d095905dce75220a`.

The extension sends the portal origin and a fixed indicator after an owner gesture. If the observation comes from the connected ordinary window, native messaging also carries the existing browser binding credential. The native runtime checks that credential against the selected profile, session and window. The saved evidence expires after 30 minutes and loses its current status when the browser goes offline or the saved context changes. Older observations retain their historical status and are marked as unscoped in Connections.

The portal listing and operation receipt expose the evidence classification without the browser identifiers or credential. Historical replay requires the binding credential for scoped observations and leaves the saved portal untouched. Owners can still accept manual handoff or forget the portal observation. Applicant identity and submission require independent evidence. Instahyre describes email and linked logins as candidate signup options. [Instahyre candidate setup](https://help.instahyre.com/en/article/getting-started-nkf98s/)

| Gate | Status | Evidence |
| --- | --- | --- |
| Source formatting and whitespace | PASS | Rust formatting, extension Prettier formatting and Git whitespace checks completed. |
| Disposable PostgreSQL | NOT TESTED | A new fixture covers selection, window matching, the redacted-hash replay challenge, expiry and a selection round trip. The existing fixture checks unscoped compatibility. |
| Extension | NOT TESTED | A new fixture covers redacted origin, connected-window scope, another window and private browsing refusal. |
| Current build and combined gate | NOT TESTED | Zero tests executed for this checkpoint. Prior baseline `9c4ace570535a5856184775f8045ee89eafdd05f` had 193 standard Rust and 262 disposable PostgreSQL passes. |
| Actual account, browser focus and application | NOT TESTED | No provider call, browser activation, application attempt or installation took place. The last recorded Naukri strict worker receipt count remains zero. |

Include `uv run --no-project python rust/scripts/run_postgres_tests.py` and `pnpm -C extension test` in the combined local suite. Engineering estimate remains 58% complete and 42% remaining. Continue the provider-specific discovery and account evidence paths, with Naukri first in actual application acceptance.
