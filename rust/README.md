# Rust migration

This workspace replaces Python components incrementally. It is not yet the production
backend. See [the migration plan](../docs/plans/2026-11-14-rust-agent-migration.md).

Develop and build from the canonical repository only. Local runtime data and preserved
private evidence live under ignored `.local/`; the old Library path is a compatibility
symlink. See [storage evidence](../docs/acceptance/storage-cleanup-20261115.md).

```sh
cargo test --locked --workspace
uv run --no-project python rust/scripts/run_postgres_tests.py
cargo clippy --locked --workspace --all-targets -- -D warnings
cargo build --locked --release --workspace
```

`automated-apply-native /absolute/private.env chrome-extension://<stable-extension-id>/`
reads one length-prefixed Chrome frame and returns one frame. It uses the existing
loopback backend contract. It does not open tabs, start local inference or submit jobs.
Browser manifests may also point directly to the Rust executable. In that mode the
browser supplies the extension origin and the executable reads only its adjacent
`automated-apply-native.private.env` file. This file must be owner-owned, regular,
private and contain the existing explicit native endpoint/token/extension settings.
No shell wrapper, ambient environment or current-directory configuration is needed.
Operating-system file permissions still apply to the executable and private file.
The public command schema is generated from current Python contracts; check it with:

```sh
uv venv --python 3.11 .venv
uv pip install --python .venv/bin/python -r backend/requirements-runtime.txt
uv run --no-project --python .venv/bin/python python -m rust.scripts.export_native_schema --check
uv run --no-project --python .venv/bin/python python -m rust.scripts.benchmark_native --iterations 20
```

The Rust host reads only its explicit private env file (no ambient configuration override),
requires a regular owner-owned file with no group/other access, refuses symlinks, and
accepts only a numeric IPv4 loopback HTTP endpoint with a port. Remote proxies,
redirects and network schema retrieval are disabled. JSON schema validation is stricter
than Python coercion; valid typed extension requests are the compatibility target.
Cross-field Python validators remain authoritative until their Rust ports are complete.
Never swap the installed native wrapper without STOP, immutable release/rollback
inventory and account/policy/history/readiness acceptance.

The agent host includes direct factual answers, deterministic grounded extraction,
reviewable saved drafts, signed exact-context owner answers and scoped reusable answers.
Optional Cohere/Gemini generation shares the existing monthly usage ledger and bounded model
concurrency with the graph agents. It makes one request per reservation, releases read
locks before inference, rechecks evidence before saving, and cannot submit applications.
One transient generation connection keeps owner controls responsive; no database pool is
added. Gemini also requires its separate approved monthly request count and candidate-data
grant; it accepts one complete text-only structured result and never follows generated tools.
Explicit `LLM_PROVIDER=ollama` with `OLLAMA_ENABLED=true` now uses the existing optional
provider ledger (`owner_preferences`, `ai:ollama:YYYY-MM`), including consumed requests,
cooldowns and unknown retained fields. It never silently selects a model, starts a daemon,
pulls weights or falls back to a remote service. The production endpoint is fixed to
`http://127.0.0.1:11434`; fixture overrides work only in explicit fictional mode.
Before candidate text, `/api/status` must report `cloud.disabled=true` and `/api/show`
must contain local model metadata without remote routing. Older daemons fail closed.
The request asks for two threads, a 2,048-token context, at most 256 output tokens and
`keep_alive=0`; these are daemon options, not measured resource guarantees. The serialized
request is capped at 5,000 bytes and responses at 128KiB. A shared transport deadline
bounds metadata and generation together. Incomplete results are rejected rather than
continued. The runtime shares one generation permit with graph inference; operators
must also enforce `OLLAMA_NUM_PARALLEL=1` for any other daemon clients.
No real Ollama generation has been accepted yet. The separate legacy
`OLLAMA_GENERATION_AUTHORIZED` rearranger, local fallback and CLI/application service
ports remain in progress; this port implements the explicitly enabled optional structured
draft path. Conservative grounding, context rechecks and owner review still apply.

The private dashboard notification inbox, mark-read receipts and saved delivery history
also run directly on the existing PostgreSQL connection. They retain fixed50/100-row
pages, private field projections and commit-before-ACK read receipts, with no delivery
dispatch or application authority. Notification preferences and synchronization remain
on the legacy path until their separate ports are complete.

The saved-jobs screen now has Rust listing, full17-field details, GET/POST matching and
shortlisting. Reads need no provider call; catalog reads do not require a candidate profile.
Matching remains read-only and preserves each method's legacy lookup order. Shortlisting
locks the row, refuses progressed jobs and commits a confirmed update before acknowledgement;
repeating an already-shortlisted selection preserves its timestamp. It grants no application
admission or submission authority.

The next packet service reuses a pure Rust readiness calculation with an explicit current
time cutoff and3,584 compact legacy comparisons. Its typed projections describe validated
saved data; packet context, persistence and API wiring remain pending. See
[the next packet slice](../docs/plans/application-packet-rust-slice.md).

Production local clients can use a private Unix socket alongside the loopback listener.
Set `RUST_AGENT_UNIX_SOCKET` in the explicit runtime/MCP config, the same variable in
Next.js for workflow controls, `BACKEND_UNIX_SOCKET` for its ordinary API gateway, and
`LOCAL_AGENT_UNIX_SOCKET` in the native bridge's adjacent private config. Keep the numeric
HTTP endpoint and port aligned with the runtime; private IPC does not assert forwarded TLS.
There is no fallback to TCP after a configured socket fails. MCP refuses production TLS
configuration without this private transport. Ordinary TCP still requires configured TLS
proxy trust; merely claiming HTTPS in a header or request URL grants no trust.

Use an absolute canonical socket path at most100 UTF-8 bytes long, with an existing
owner-owned0700 parent directory. Socket files are0600. The verified private parent protects
creation without changing the process-wide umask; kernel peer UID is checked on every Unix
connection. Bearer, origin, Host and owner-only lifecycle controls remain enforced. The host
recovers only an exact owned stale socket after connection refusal while holding its runtime
locks; active/uncertain sockets, files and symlinks are refused. Shutdown removes only its
unchanged socket inode. These ephemeral socket operations never clean runtime data/history.

The IPC listener shares the existing API state, request limits and database connection;
it creates no pool or writer family. Native IPC transport parity does not implement the
still-unported Chrome command dispatcher. Do not point the installed extension at the Rust
host until all command/service ports and the complete STOP-mode cutover checks pass.

The Rust local Gmail lifecycle now supports the two existing account slots: strict
read/draft consent, browser cookie + one-use PKCE state, exact callback URI, allowlisted
cross-checked identity, encrypted credentials, generation fences, refresh leases, verification
and local disconnect before provider revocation. Only the callback's GET path is exempt
from bearer authentication, as declared in the shared HTTP policy; transport checks remain.
Account IO shares the transient generation/document permit and stays outside the control
connection so Stop remains available. Owner preference writes supply production timestamps
explicitly and acknowledge commit before reporting success. Expired leases are removed
before completion so an older refresh cannot overwrite a newer result.

This lifecycle port has only fictional HTTP/PostgreSQL acceptance. Account status does
not perform an implicit provider check. Existing alert policy is retained, while the Rust
status reports monitoring unavailable until that poller is ported. Search/body review,
drafts, alert polling, legacy account variants and Drive services are still separate
remaining ports. No owner OAuth consent or installed configuration was changed.

Local Gmail search now uses only bounded INBOX metadata (at most5 results). Reading a
body additionally requires the existing reviewed-body setting and a recent, exact
slot/generation/message selection. MIME evidence skips attachments and hidden HTML,
bounds parts/depth/decoded bytes and returns unverified signals plus cleaned public links;
raw bodies are not saved or returned. Links are validated locally and never opened.

Draft creation requires the exact owner-reviewed recipient/subject/body hash and current
account generation. A durable dispatch record precedes its one fixed `/drafts` POST.
Repeated/uncertain requests reconcile by RFC message ID and exact provider content; they
never POST again. Readback rejects changed content, extra recipients and SENT labels.
Explicit self-test drafts also search SENT for original and provider message IDs.
Disconnects during network IO fence result publication without erasing dispatch history.
Neither SDK has a send/modify/delete endpoint. No live mailbox or test draft was created.

Pinned `mail-builder`1.0.0 (hostname discovery disabled), `mail-parser`0.11.9 and
`html5gum`0.9.1 provide MIME construction, RFC headers/addresses and bounded HTML tokenization.
Parser1.0.1 requires Rust1.98, above this workspace's declared minimum; it was not selected.
The older pinned parser is compiled/tested on the current host toolchain, not a separate
fresh Rust1.94 installation. Exactly four packages were added (including build-time
`hashify`0.2.9); existing external lockfile versions/checksums/edges were preserved.

Saved Drive resume reviews now have native source/status/review/approval routes. The
current design deliberately defers Drive downloading and directs the owner to manual
PDF upload; the Rust `/sync` route and attempts to enable downloading retain that409.
This does not add Drive OAuth grants, change sharing, or reuse Gmail credentials.
Status reports `download_available=false` and no Rust scheduler heartbeat. Source CAS
retains archived versions and active pointers when the latest source changes.

Review inspection proposes a skill union without modifying facts. Explicit owner approval
checks source generation, latest version, profile version, skill-removal consent, PDF
checksum and resource binding. Facts, active resume association, private resource, evidence
and encrypted review commit atomically. Rejected writes finish rollback before responding;
uncertain commit reconnects the control connection without replaying approval. Repeating
an already approved version preserves timestamps, evidence and bytes. Source/status reads
batch the50-version history and older active/latest pointers in two metadata-only queries;
ciphertext is never converted to JSON just to display status. No raw PDF, extracted text or
review data is sent to a model. This source is uninstalled and has fictional acceptance only.
