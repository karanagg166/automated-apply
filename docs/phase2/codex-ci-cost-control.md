# Intentional hosted CI — 2026-10-27

The workflow-only change landed in [PR #32](https://github.com/karanagg166/automated-apply/pull/32), merge `3a2d6b3`, from verified baseline `975b8fc`. The backend, frontend and Phase 1 connection workflows now accept only `workflow_dispatch`. Every job, permission, security step, runner and timeout is unchanged.

Before the first push, authenticated `gh` inspection found exactly three active workflows, no queued/running jobs, no main branch protection, no repository rulesets and no effective branch rules. The newest run was the baseline main push. Their original states were recorded privately. Each workflow was temporarily disabled using `gh workflow disable`; the workflow branch was pushed only after all three reported `disabled_manually`. PR #32 contained only these three files, had no required checks, and was merged without an administrative protection bypass. The remote main definitions were fetched and checked before restoring all three to `active`. No new hosted runs appeared.

Local validation used PyYAML to parse each definition and assert the sole trigger and byte-identical permissions/jobs sections. Actionlint 1.7.12 subsequently passed all workflows (`actionlint -shellcheck=`); its official release archive matched the published SHA-256 checksum. Shellcheck was unavailable. The initial release download failed with an HTTP/2 stream error; a resumed checksum-verified download succeeded. No hosted test was dispatched or rerun.

Ordinary development uses local tests. Hosted execution requires deliberate owner authorization at a release or high-risk checkpoint. No paid runner change is authorized. A future required-check policy must be reviewed explicitly; this change does not remove or bypass one.

GitHub evaluates branch-specific definitions. Older branches must incorporate `3a2d6b3` before their next push, including the separate frontend branch. Re-enabling these workflows does not rewrite historical branch definitions. The Codex Phase 2 branch includes the manual-only definitions.

Private evidence is retained outside Git in the existing application-support directory under `phase2-codex-evidence`: original workflow states, local validation, actionlint output and the final remote audit. No runtime installation or deployment was changed.
