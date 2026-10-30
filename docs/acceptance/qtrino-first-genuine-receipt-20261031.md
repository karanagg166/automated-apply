# First genuine Naukri application recorded

**PASS: Backend Developer at QTrino Labs Limited, Naukri requisition
`261026028027`, was applied to through the ordinary Naukri interface.**
Naukri displayed successful application, then its Application Status page showed
**Applied / Application Sent,31 Oct2026, Awaiting Recruiter Action**. The exact
requisition remained associated with that record after an ordinary page reload.
The local application eligibility check now excludes this job as `already_applied`.

Branch `fix/live-prepare-discovery-20261030`, base `main`,
[PR #48](https://github.com/karanagg166/automated-apply/pull/48).
Implementation remains
[`0efc7cdecdf71a902ab257a4d2fea7f58e170c63`](https://github.com/karanagg166/automated-apply/commit/0efc7cdecdf71a902ab257a4d2fea7f58e170c63).
The earlier blocked attempt at
[`a6effa587c468f28675e5657ffa949f3c8b7fd1e`](https://github.com/karanagg166/automated-apply/commit/a6effa587c468f28675e5657ffa949f3c8b7fd1e)
is preserved. This report supersedes its pending-file-selection disposition.
[Sanitized genuine receipt and counts](qtrino-first-genuine-receipt-metrics-20261031.json).

## Actual repair and submission

The earlier file transfer skipped the site's Upload Resume button and failed.
Read-only inspection of the **public** chatbot JavaScript established that the
button initializes a `formKey` before opening its file input; the change handler
uses that key. Directly supplying file bytes did not initialize it. This is a
concrete defect in the prior interaction sequence, not proof that Naukri prohibits
all automatic file attachment. No authenticated endpoint was reverse engineered
into a submission client or called directly.

The owner was explicitly told native chooser interaction could affect the desktop
and authorized access in reply. Codex selected the existing Profile8 application
tab, activated the ordinary Upload Resume control and used the native file chooser
to select the **same confirmed canonical PDF**. The file was100,198 bytes, within
the displayed2MB limit. The initial DOM upload failure remains genuine evidence;
the later native selection succeeded. Browser focus changes during chooser
handling were handled by rechecking the target and chooser before continuing;
no file selection was sent into an unrelated app. No Chrome protection, profile,
extension permission, private session or installed release was changed.

Confirming the selected file in the native chooser caused Naukri to finish the
flow and navigate to its successful application page. There was no separate final
Save/Submit click. This is **owner-authorized, software-operated UI submission**,
with owner input for one unknown personal question. It is neither an owner-manual
submission nor an unattended recurring/official API integration.

The success page said `You have successfully applied to 'Backend Developer'`.
Normal navigation to Application status showed **one** Naukri application, the
matching title and posting recruiter, exact-requisition links, Applied and
Application Sent dates, and Awaiting Recruiter Action. A normal reload retained
all these conditions at19:34:56 UTC on2026-10-30, local2026-10-31. Application
Status labels the posting recruiter **Naukri E-hire**; the previously verified
listing header names **QTrino Labs Limited** as hiring company. These identities
are preserved separately. No independent employer response, recruiter viewing,
shortlisting or company-follow change was verified.

## Durable duplicate prevention and truthful tracking

A single transaction on the existing approved online PostgreSQL target took the
existing owner fence, checked the saved job identity, set its status to `applied`,
and retained existing discovery metadata while recording `already_applied` and
the observed receipt reference. A deduplicated private owner-preference receipt
and in-app notification were saved. No schema/migration or installed code change
was required. The transaction's operator connection closed after verification.

The receipt source is `naukri_application_status_ui`, operation mode
`owner_authorized_software_operated_ui`. The existing packet API only supports
human reports or fixture provider evidence, so it was **not falsely called with
human_confirmed=true**, and the packet was not mislabeled as a manual application
or promoted to an unsupported provider-confirmed lifecycle. The real job is marked
applied and protected by the existing prior-application fence. The authenticated
saved-jobs review API subsequently returned **REJECTED / already_applied** for
this exact job, not an employer rejection. No second Apply attempt was issued.

The generic packet submission counters can therefore still differ from the true
Naukri-recorded result. That representation gap remains for a future reviewed
implementation; it must not erase the genuine receipt or trigger resubmission.

## Counts, evidence and reproduction

Across the original attempt and this continuation: **1 selected-job Apply click,
1 failed direct file transfer,1 successful native file selection,1 genuine
Naukri-recorded application,0 additional jobs submitted,0 private Apply endpoint
replays,0 independent employer acknowledgments**. The first personal answer was
owner-provided and remains private. Both initial and reloaded status observations
were real Mac/browser observations. No fixture receipt substitutes for them.

Raw page captures, personal answers, canonical PDF/resource binding, screenshots,
query identifiers and detailed operation evidence remain private. Public evidence
contains only the job's public identity, aggregate actions and provider status.
No new automated tests were run: this milestone changes evidence and existing
application data, not implementation. The previous217 fixture passes remain
historical regression validation and are not counted as genuine submissions.
No performance optimization or before/after resource benchmark was performed.

Read-only reproduction: in the same normal Naukri account, open Application status
through its navigation, select Backend Developer / Naukri E-hire, verify the
associated requisition`261026028027` and Applied/Application Sent date, then reload.
In Automated Apply, review the saved job and observe `already_applied` exclusion.
**Do not reproduce by clicking Apply or uploading the resume again.**

## Continuous automation boundary

The native file-selection sequence worked; the deployed unattended worker has
not acquired this capability. Its normal extension cannot yet automate this
chooser, and a foreground interaction performed by Codex is not a background
24/7 acceptance result. Login/session expiry, new factual questions, challenges,
ambiguous outcomes and Mac sleep/offline state still require explicit handling.
No always-on host was provisioned, Mac power settings changed or new recurring
submission authority installed. The service release remains approved90;989 and
newer development changes remain uninstalled under the exact-SHA approval gate.

Current [Lever submission documentation](https://github.com/lever/postings-api#apply-to-a-job-posting)
requires an employer administrator's API key, as does
[Greenhouse's submission endpoint](https://docs.greenhouse.io/job-board.html#authentication).
Their public job listings are not a free applicant-side submission credential.
No applicable official Naukri submission integration for this project has been
established. Public terms retrieval remains restricted; prior primary-source
research is retained in the [route report](naukri-application-route-20261030.md).

The remaining product implementation is a durable, authorized UI upload and
receipt workflow inside the worker, validated for supported destinations and an
awake/always-on deployment. It must preserve duplicate fences, current facts,
bounded policy, Stop and no replay after an uncertain result. This live success
must not be used to enable the existing unrestricted-auto-apply flags or claim
compatibility with arbitrary jobs/platforms.

| Capability | Verdict | Evidence / limit |
| --- | --- | --- |
| Upload failure diagnosis | PASS for interaction-sequence defect | Public UI initialization step was skipped previously; same PDF succeeded through native chooser |
| Genuine resume attachment/application flow | PASS live | Native chooser confirmation led to Naukri success page |
| Persistent exact-job provider record | PASS live | Applied / Application Sent retained after reload |
| Local duplicate exclusion | PASS live | Saved-job review API returns already_applied |
| Independent employer acknowledgment | NOT TESTED | Awaiting recruiter action |
| Fully unattended24/7 submission | NOT TESTED / NOT ENABLED | Worker upload/receipt integration and always-on operation unaccepted |
| Official applicant-side submission API | NOT ESTABLISHED | No applicable project credential/contract |
| Release replacement, new Gmail access, CI, merge, cleanup | NOT PERFORMED | Existing gates/configuration preserved |
