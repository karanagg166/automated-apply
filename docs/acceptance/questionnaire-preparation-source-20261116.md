# Grounded questionnaire preparation and evidence fences — source checkpoint 2026-11-16

Implementation [`37dac29550e14c70a133ef61dba177c2eac8f4de`](https://github.com/karanagg166/automated-apply/commit/37dac29550e14c70a133ef61dba177c2eac8f4de), branch `feat/rust-agent-runtime`, [PR50](https://github.com/karanagg166/automated-apply/pull/50), base `chore/uv-python-tooling`. Uninstalled source only; no model/browser/owner-data operation.

The original-step preparation runner now uses the separately bounded generation connection. It checks an idle hint before owner contention, claims and validates the current submitting context, then commits its owner transaction before any model wait. Confirmed factual answers use the existing deterministic/approved answer engine. Narrative rewriting is restricted to a separately configured, already authorized Cohere writer; other provider settings do not silently enable this path. No model is started, downloaded or called by this source checkpoint.

A current explicitly approved owner bank answer may be reused only with matching profile/question/hash/expiry and current approval. Saved facts that cannot fit the displayed controls hold for profile/control correction; unknown facts create a scoped owner question. File questions remain held for supported attachment handling. Neither a draft nor successful generation grants a browser action. Work resumption always begins with account/PDF, listing and original-form refresh.

New grounded answers retain request, source, evidence/context generation, project digest and approval identity. Handoff checks those sources, and answer admission checks them again: direct facts/links resolve against current saved data, exact-context approvals and reviewed draft reuse must still match, and Cohere answers require unchanged candidate/evidence/job/project context. Owner-correlated legacy answers retain their original existing checks. Revocation or changed evidence cannot silently promote an older newly generated answer.

Source audit also found two existing internal entry points still using READ COMMITTED while calling consistent-snapshot packet/answer readers. Application admission and submission observations now use SERIALIZABLE plus the owner-version fence. Factual preflight holds a share lock on the canonical profile through its transaction, preventing a correction from committing inside the admitted current-fact decision. This is a source correction, not evidence of an installed race test.

| Gate | Result | Evidence / limitation |
| --- | --- | --- |
| Source implementation | PASS (source only) | Grounded preparation, Cohere scope gate, source revalidation and snapshot/profile fence changes; formatter applied |
| New native PostgreSQL regressions | NOT TESTED | 6 declarations: idle owner-lock independence; confirmed fact/evidence/refresh/no extra Apply; unknown fact question; known fact/choice conflict; explicit owner bank reuse; modified retained fact rejected before another admission/budget |
| New standard tests | NOT TESTED | 0 additional declarations in this slice; earlier actual-function rules/oracles remain unrun |
| Compilation/Clippy/lint/all suites | NOT TESTED | New tests executed0; final combined gate remains deferred |
| Cohere loopback/Stop during inference/restart | NOT TESTED | Newly wired preparation path has no executed model/concurrency acceptance; existing provider/packet evidence is prior only |
| Native broker/host connection scheduling/HTTP/Telegram | NOT TESTED | Still incomplete; caller must use the generation connection without holding control mutex |
| Actual Mac/model/browser/PDF/application | NOT TESTED | No external request, owner data query or action |
| Install/strict receipt/focus/locked/24h resources | BLOCKED / NOT TESTED | Existing prerequisites remain; actual strict receipt count0 |

Prior fully validated checkpoint9c4ace570535a5856184775f8045ee89eafdd05f remains193 standard +262 native PostgreSQL passes,455 distinct. It does not validate this source. Approximate engineering estimate remains58% complete /42% remaining.

Final reproduction is `scripts/run_acceptance.py` after all planned source units are integrated. New fictional declarations are tests/support/questionnaire_preparation_pg.rs. No executed failure logs exist. Relevant conservative codes include questionnaire_grounded_context_changed, questionnaire_owner_answer_changed, questionnaire_saved_fact_does_not_fit_controls, candidate_cloud_authorization_required and execution_commit_outcome_unknown. Lost model/commit outcomes never authorize a provider-write replay.

There is no timing/RSS/latency gain claim. New current-fact preflight adds one profile share-lock read. Explicit reviewed-answer revalidation may inspect the existing bounded100-draft inventory; measure owner-fence/Stop latency during final load acceptance. Provider quotas, cooldowns and the shared generation permit remain in the existing answer service. Final connection scheduling, lost-response reconciliation bounds, complete native controls/dispatcher, remaining legacy services/providers/platforms and actual install/live acceptance remain required under the [plan](../plans/completion-execution-20261116.md). Installed STOP162, lifetime4/hour1, three quarantines, saved filters, first receipt prerequisites, Gmail read/draft-only and focus rules remain unchanged.
