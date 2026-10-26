# Private resume and project review

This workflow prepares an owner review from the saved profile, encrypted resume,
committed authorized checkouts, and a private evidence plan. It does not confirm
personal facts, run a model, start services, or send application actions.

Preparation uses a repeatable-read, read-only transaction against the configured
owner-approved online PostgreSQL database. Existing versioned context records are
copied into a private `MemoryRecordStore`; `CandidateContextService` builds all
proposals there. Neither the candidate profile nor the running release changes.
The owner API authenticates the configured token before database access.

```sh
backend/venv/bin/python backend/scripts/prepare_onboarding_review.py \
  --env-file /private/path/operator.env \
  --plan /private/path/preparation-plan.json \
  --output /private/path/new-owner-review
```

The private plan contains the current `profile_version`, resume ID and SHA-256,
`CandidateConfiguration`, authorized checkout paths, selected committed source
paths, and proposed `ProjectFact` values. It also contains review differences,
limitations, missing information, and the questions to check. It contains no API
tokens. Generate it from existing evidence; never commit candidate data or plans.
Repository-backed references must match the selected commit, file digest, and line
bounds. Resume references identify the encrypted resource and its plaintext digest;
line numbers refer to safely extracted text. Repository ownership proves no personal
contribution. Document-only employment projects have no fabricated commit or URL.

The HTML report embeds the verified PDF, extracted text, saved profile, differences,
source references, fact IDs, project revisions, limitations, and actual approved-only
answer checks. All selections start unchecked. Project observations and personal
contributions have separate group selectors; individual facts can also be selected.
Choosing a new primary PDF clears the existing profile confirmation binding. A
separate unchecked profile checkbox prepares the existing version-1 reconfirmation
request, which is saved only if explicitly selected, after the resume confirmation.
This does not edit profile fields or infer new facts.

The report exports only selected confirmation requests. It cannot send them and
contains no token, external assets, or network-enabled controls. Artifacts must be
outside Git, with directory mode 0700 and file mode 0600; existing files are never
overwritten.

## Owner confirmation gate

Review the PDF and select it only if its actual contents are correct. Review each
project's statements, then separately select personal contributions. Unsupported
claims remain excluded. Unknown contributions, bugs, decisions, dates and metrics
remain unknown. Export the selected confirmations. Preparation never runs the apply
command.

Only after explicit owner approval, the exported selection can be persisted without
retyping through the existing resume confirmation handler and context services:

```sh
backend/venv/bin/python backend/scripts/apply_onboarding_review.py \
  --env-file /private/path/operator.env \
  --plan /private/path/preparation-plan.json \
  --manifest /private/path/new-owner-review/review-manifest.private.json \
  --selection /private/path/selected-owner-confirmations.json
```

The apply command authenticates with the running owner API. It verifies the complete
review and plan hashes, exact selected requests, current profile ID/version/content,
resume integrity, canonical primary selection, current source revisions, and allowed
fact IDs. It rebuilds selected proposals and requires their hashes to match the
review before approving anything. SQL compare-and-swap and row locks protect writes;
a failure rolls back the complete transaction. The profile version is preserved.
No unselected fact becomes approved. Re-running a stale selection requires a new
review rather than silently approving changed evidence.

If the owner explicitly delegates evidence review, pass `--reviewer-ref` with the
actual delegate identifier. Project approval and configuration audits retain that
identifier; the option grants no authorization and preserves all selection gates.
Do not use it to assert new personal facts or a review the owner did not perform.

Document-only context uses the existing JSON record store under `document_project-*`.
Older installed readers ignore that namespace; repository records retain their
existing contracts. No migration or service restart is required to stage the report.
The approved-context answer adapter is code in this branch; the installed release
continues using its installed implementation until a separately authorized upgrade.

The answer engine reads current approvals only, retains revision and fact provenance,
and uses personally attributable statements for personal experience questions.
Project observations alone cannot become first-person work. Questions without a
supported bug, API integration, decision, or requested project contribution abstain.
Extraction never enables a cloud provider or consumes a provider budget.

## Validation

Automated tests use fictional fixtures and a disposable local PostgreSQL 17 database.
The PostgreSQL verifier rejects remote hosts and database names other than the local
`candidate_profile_test` admin database, then creates and drops a unique child database.
It checks competing resume confirmations, duplicate-primary constraints, profile
version preservation, concurrent record/project CAS, and stale project approvals.
The regular backend suite also exercises migrations and existing resume workflows.

```sh
PROFILE_TEST_DATABASE_URL="${ONBOARDING_TEST_DATABASE_URL}" \
  backend/venv/bin/python -m pytest backend/tests/test_onboarding_review.py \
  backend/tests/test_onboarding_review_postgres.py -v
```

Changed implementation: candidate-context persistence, project contracts, repository
reading, versioned context service and private review rendering; dashboard resume
confirmation schemas/handler and project consent validation; grounded answer evidence,
question routing and approved-project retrieval. Supporting changes are the prepare,
apply and disposable-database scripts, onboarding regression tests, and regenerated
frontend API types. No extension, browser integration, installed configuration or
service files are changed.

## Changed files

```text
backend/app/ai/evidence.py
backend/app/ai/schemas.py
backend/app/candidate_context/persistence.py
backend/app/candidate_context/projects.py
backend/app/candidate_context/repository.py
backend/app/candidate_context/review.py
backend/app/candidate_context/runtime.py
backend/app/candidate_context/service.py
backend/app/dashboard/candidate_context.py
backend/app/dashboard/router.py
backend/app/dashboard/schemas.py
backend/app/services/application_answer_service.py
backend/app/services/application_question_classifier.py
backend/app/services/candidate_evidence_retrieval.py
backend/scripts/apply_onboarding_review.py
backend/scripts/prepare_onboarding_review.py
backend/scripts/verify_onboarding_review.py
backend/tests/test_candidate_context_runtime.py
backend/tests/test_onboarding_review.py
backend/tests/test_onboarding_review_postgres.py
docs/phase1/resume-project-readiness.md
frontend/src/types/api.d.ts
```
