# Owner-approved listing imports

Local branch `feat/rust-agent-runtime`, implementation `60d05a68e165a84d243f34f1cd589cd4301c4a51`.

The dashboard discovery form accepts a listing URL, title and optional employer for configured manual sources, including Internshala and HiringCafe. Preview validates the supplied record and reports its result before the owner approves saving. The local import reuses normalized listing validation, explicit filters, canonical deduplication and optional ranking. New listings require review. Existing jobs and observations retain their original evidence when an import matches them. A provider posting retained in the source observation remains available for packet handoff when an employer ATS URL is the canonical deduplication key.

The listing, observations, rankings and terminal receipt commit together under the owner request UUID. A matching request returns the same result. Changes to a retained request produce a conflict. The import performs zero provider requests and records no application authorization.

| Gate | Status | Evidence |
| --- | --- | --- |
| Source and formatting | PASS | Rust formatting, standalone fixture formatting, dashboard Prettier formatting and Git whitespace checks passed. |
| Disposable PostgreSQL | NOT TESTED | Two additions cover zero-write preview, manual provenance, replay, preserving duplicate rows, portal handoff from retained evidence and rollback after receipt trigger drift. |
| Dashboard interaction | NOT TESTED | One addition covers preview, owner approval, approved PUT and private browser attempt storage. The existing source contract fixture includes the manual namespace and paid-input refusal. |
| Current build and combined gate | NOT TESTED | Zero tests executed for this checkpoint. The last validated baseline remains `9c4ace570535a5856184775f8045ee89eafdd05f` with 193 standard Rust and 262 disposable PostgreSQL passes. |
| Live provider discovery, account and application | NOT TESTED | No installed service, provider or application queue action. Manual intake may be exercised locally after combined validation. |

Include `uv run --no-project python rust/scripts/run_postgres_tests.py`, the Rust owner discovery contract fixture and the frontend job discovery suite in the combined local gate. The estimate remains 58% complete and 42% remaining. Continue platform account evidence and authorized discovery adapter work before local acceptance.
