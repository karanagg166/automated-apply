# QTrino: real application reached, resume attachment failed

> Historical failure, subsequently resolved through owner-authorized native file
> selection. See [the first genuine receipt](qtrino-first-genuine-receipt-20261031.md):
> Naukri records Applied / Application Sent, and local duplicate exclusion is active.

**Next action: the owner selects the confirmed PDF through Upload Resume in the
existing Naukri questionnaire, then asks Codex to continue.** The selected PDF is
available privately. The site reported `File upload was unsuccessful. Please try
again.` No successful submission or application receipt is established. Do not
click Apply again to investigate this state.

Branch `fix/live-prepare-discovery-20261030`, base `main`,
[PR #48](https://github.com/karanagg166/automated-apply/pull/48).
Implementation remains
[`0efc7cdecdf71a902ab257a4d2fea7f58e170c63`](https://github.com/karanagg166/automated-apply/commit/0efc7cdecdf71a902ab257a4d2fea7f58e170c63),
with earlier report at
[`0fc95da746b1a533e145d5831b2fb3b98570cc95`](https://github.com/karanagg166/automated-apply/commit/0fc95da746b1a533e145d5831b2fb3b98570cc95).
This report adds genuine browser evidence; it installs no implementation.
Local date2026-10-31; actions occurred2026-10-30 UTC.

## Owner authority and actual actions

After the disclosed single-job immediate-submission/follow boundary, the owner
said to proceed and subsequently continued the task. Codex operated the ordinary
Naukri interface through the already-open Profile8 tab using macOS browser
scripting, without changing window focus, creating another profile, exporting
cookies, invoking an authenticated Apply endpoint directly or bypassing a
challenge. This is **software-operated owner-authorized UI assistance**, not an
owner-manual submission and not an officially integrated submission API.

The current heading still identified **Backend Developer, QTrino Labs Limited**,
posted by Naukri E-hire, requisition`261026028027`. Ordinary navigation through
the observed Application status link showed **zero applications in the last90
days** before the action. The observed profile link showed no uploaded resume.
The saved Automated Apply packet remained fresh and contained a confirmed
primary resume; no resume was fabricated or replaced with another resource.

At19:23:45 UTC Codex activated the selected job's enabled Apply button **once**.
The site opened a real chatbot questionnaire, warning that the supplied profile
information would also update the Naukri profile. The first question concerned a
personal profile attribute. Codex asked the owner for the exact selection and
applied only the owner's response. The value and candidate details are private
and are not published here. The next actual prompt was **Please upload your
resume**, offering Upload Resume and I'll do it later.

The confirmed primary PDF was retrieved through the existing authenticated local
resume-download route, validated as a PDF under the site's displayed2MB limit,
and supplied once to the actual application file input using browser File and
DataTransfer APIs and its change event. The site displayed the selected generic
file name and then **File upload was unsuccessful. Please try again.** The
questionnaire returned to the same upload prompt. File-input assignment is not
an upload receipt. The underlying cause of this rejection is **unproven**.
No private upload endpoint was called directly, no browser security flag changed,
no chooser automation attempted and no successful file receipt inferred.

The resume was not skipped to force submission. No second Apply click, automatic
file retry, Save/Submit action or claimed Applied transition followed the error.
The questionnaire is left open for owner file selection. The user's existing
background-only desktop constraint prevents Codex from operating a native file
chooser without further authority; this is the concrete remaining interaction.
The owner can choose the privately retained confirmed PDF and continue the same
questionnaire without restarting Apply.

## Evidence and validation

Private captures retain the before-history page, current profile state,
questionnaire structure, owner-selected response, exact canonical resource
version/PDF digest, single-click attempt fence and attachment failure. Candidate
attributes, account details, PDF contents, authenticated responses and raw page
captures remain outside Git. No screenshot or mailbox contents are published.

Exact live counts for this continuation: **1 Apply activation,1 owner-confirmed
question answered,1 PDF transfer attempt,1 visible upload failure,0 final
Save/Submit activations,0 verified submission receipts,0 automatic retries**.
One authenticated localhost packet GET and one canonical-PDF GET returned200.
These are actual Mac/browser observations, not fixtures. The prior217 focused
fixture passes are historical implementation validation and were not rerun for
this documentation-only milestone. No new code tests or performance comparison
was performed; no measured critical performance failure motivated optimization.

Reproduce the remaining step through the existing application tab: verify the
same requisition and visible upload prompt, use Upload Resume, select the current
confirmed canonical PDF, observe whether Naukri accepts it, then inspect any
new question before answering. Do not guess missing facts. After any actual
submission result, navigate normally to Application status and verify the exact
requisition's persistent record. An ambiguous outcome must not trigger resubmission.

| Check | Verdict | Actual evidence / remaining action |
| --- | --- | --- |
| Selected job identity | PASS | Live heading and exact requisition |
| Prior application check | PASS before action | Ordinary Application status displayed0 in last90 days |
| Reach genuine questionnaire | PASS | One Apply activation produced actual prompts |
| Unknown personal answer | PASS owner-confirmed | Asked and used exact response; value remains private |
| Confirmed canonical PDF availability | PASS | Current local packet and PDF download |
| Portal resume attachment | FAIL | Explicit upload-unsuccessful message after one attempt |
| Native file chooser under background-only scope | BLOCKED | Owner selection needed; no desktop interaction attempted |
| Final submission / persistent Applied Jobs receipt | NOT TESTED | No final submission result or receipt; no replay |
| Official third-party submission integration | NOT ESTABLISHED | UI assistance supplies no general API/partner permission |
| Installation, mailbox expansion, CI, merge, cleanup | NOT PERFORMED | Approved90 services and separate989 approval gate unchanged |

This replaces the earlier assumption that a potentially submitting Apply action
could not be authorized in this session: the owner has now authorized and Codex
has performed one ordinary UI attempt. It does not change the absence of an
official integration or justify unattended recurring submissions.
