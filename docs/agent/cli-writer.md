# Native CLI answer writer — source only

The Rust `agy` answer provider now has source for the existing explicit CLI writer.
It is untested and uninstalled. It does not establish authenticated CLI access, available
model quota, effective sandbox containment or current tool-free execution on this Mac.
Combined acceptance must include the fictional executable, disposable PostgreSQL and
actual independently reviewed runtime checks before enabling it.

Select `LLM_PROVIDER=agy` only with an explicit `AGY_MODEL`, `AGY_ENABLED=true` and
`AGY_QUOTA_AUTHORIZED=true` in the existing private host configuration. The executable
must be an absolute executable file owned by the current user or root and not group/world
writable. The default is `/opt/homebrew/bin/agy`; model input cannot replace argv or paths.
The CLI is never selected implicitly. Questionnaire automation remains Cohere-only.

The adapter reads, but never edits, owner CLI settings. It requires an existing private
owner-trusted `agy-answer-workspace` under the runtime Application Support folder and
exact copies of [the frozen legacy agent profile](../../rust/agent-runtime/schemas/agy-agent.md)
in both the owner's configured agent directory and that workspace. Settings/profiles
must be regular owner-only files, with no final symlink. Billing settings must establish
no G1-credit overage, provider API/Cloud billing or custom provider configuration.
The executable's local `agents` output must identify the named primary agent. The
adapter does not establish trust, log in, change credentials/settings, start downloads
or create a source/release checkout. Global CLI hooks still need independent review;
an empty advertised tool list does not prove the absence of a preconfigured hook.

Each attempt takes the existing shared provider semaphore and consumes one reservation
in `llm_monthly_usage` under `provider=agy`; failed, cancelled or uncertain work is not
refunded. Preflight private-policy failure precedes reservation. Rate failure keeps a
monotonic cooldown. Input is byte bounded; selected usage is recorded without printing
stderr/account data. Only a grounded result with unchanged candidate/job context can
be saved as a draft requiring review. No application, owner approval or sending action.

The process uses fixed arguments, cleared environment, separate process group, piped
stdin/stdout/stderr and no shell/PTY invocation. Candidate input waits for exactly one
no-tools initialization and a fresh private-policy/profile check. Every JSON frame,
including the final line without a newline, is inspected. Advertised/called tools,
subagents, malformed frames, duplicate results and multi-turn/error results are rejected.
Both output pipes cap64KiB. Discovery is capped at15seconds within the original deadline;
generation uses its remainder, with a CLI timeout margin. The sandbox flag is retained
but [may have no effect when unavailable](https://antigravity.google/docs/cli/reference/).

Normal failures/timeouts kill the owned process group and await the direct child.
Cancellation drops a group guard and Tokio's kill-on-drop child handle; actual descendant
termination/reaping is a deferred fixture/live acceptance gate, not inferred from source.
Unique schema/log artifact directories are private0700 with a child-only077 umask. They
remain private runtime evidence pending the existing separately reviewed retention policy;
this adapter does not delete historical artifacts. The prompt is not a command argument.

`RUST_AGY_FIXTURE_HOME` is a testing-only home substitution rejected by production writer
configuration. It exists solely for isolated fake-executable policy/IPC fixtures and
must not appear in an installed configuration. No production Python runtime was added.
