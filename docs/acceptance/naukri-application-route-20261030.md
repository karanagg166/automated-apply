# Genuine Naukri application route and platform support

**No real application has been prepared, filled or submitted.** The selected page is job details, with no accessible application form or verified navigation-only form link. Its Apply control may immediately submit or change follow state. The owner now requires background-only execution without desktop interference; no further browser UI action is being attempted.

Implementation branch: `fix/live-prepare-discovery-20261030`, base `main`, [PR #48](https://github.com/karanagg166/automated-apply/pull/48). Service runtime is approved [`90f2f2ade50a1c31b26ca85cc7fdf5e93bb67c20`](https://github.com/karanagg166/automated-apply/commit/90f2f2ade50a1c31b26ca85cc7fdf5e93bb67c20); the extension cutover is incomplete. Development correction [`98965f7607a4714371599fef0143d5e1f8eed25b`](https://github.com/karanagg166/automated-apply/commit/98965f7607a4714371599fef0143d5e1f8eed25b) is uninstalled. [Installation, counts and failures](approved90-installation-20261030.md); [sanitized measurements](approved90-installation-metrics-20261030.json).

## Genuine target and persisted field structure

Read-only observation at16:32 UTC established the public heading:

- Role: **Backend Developer**, Gurugram, public Naukri listing ID `261026028027`.
- Hiring company displayed in the header: **QTrino Labs Limited**.
- Posting recruiter: **Naukri E-hire**.
- [Exact public job-details URL](https://www.naukri.com/job-listings-backend-developer-naukri-e-hire-gurugram-0-to-2-years-261026028027).

The header explicitly separates hiring company from posting recruiter. Structured JobPosting metadata and the URL slug name Naukri E-hire; that metadata must not silently replace QTrino as the displayed hiring company. This observation resolves the apparent disagreement; independent employer/requisition corroboration is still required before claiming an employer receipt. No candidate identity, saved answers, resume contents or application history is published here.

Actual read-only DOM structure was persisted privately. Sanitized observed structure:

| Visible control | Actual type | Required | Existing value | Application field? |
| --- | --- | --- | --- | --- |
| Select job type (`jobType`) | text input | false | empty | No: site search |
| Enter keyword / designation / companies | text input | false | empty | No: site search |
| Enter location | text input | false | empty | No: site search |
| Apply (`apply-button`) | enabled button, default type submit | no form association | not activated | Potential application action |

The document has **zero forms, zero iframes, zero visible application fields**. No questionnaire, required question, resume selector/upload or approved answer value was observed. No recognition/preparation PASS follows from these three search controls. The ordinary Careers link goes to Info Edge's own careers site; it is not an application destination for the selected QTrino job.

The previous read-only public-asset inspection established that Apply initiates an authenticated POST workflow, with conditional company-follow writes and response-dependent questionnaire/redirect handling. This milestone did not call that endpoint, capture/replay an authenticated request, add auto-apply URL parameters, bypass a challenge or activate Apply. A button's default submit type without a form does not prove its script behavior. The exact account/job branch remains unobserved.

## Primary-source findings and their limits

[Naukri's own workflow guide](https://www.naukri.com/blog/how-naukri-works/) describes profiles, recommendations and sending applications to recruiters. Its [recruiter questionnaire documentation](https://recruiterzone.naukri.com/introducing-new-job-posting-experience-for-recruiters/) confirms that employers can require questions before applying. Its [fresher profile guidance](https://www.naukri.com/blog/how-to-find-jobs-for-fresher-on-naukri/) explains that missing crucial profile fields can prevent applications. These establish possible flows, not this job's unobserved branch.

[Naukri's communication guidance](https://www.naukri.com/blog/greater-control-over-communication-from-naukri-com/) describes application/status alerts and the Applied Jobs section. A generic success response or Apply-click receipt is insufficient to establish independent employer receipt. An already-applied display should fence another action; it does not justify retrying through another route.

The current [official terms](https://www.naukri.com/termsconditions) were read through the normal selected Chrome profile; the public page's text hash is in the sanitized metrics. Web retrieval of the main FAQ/terms was unavailable/robots-restricted; no challenge bypass was used. Section13 describes **Naukri Apply Integration for recruiters/employers connecting supported ATS systems**: job posting, receiving candidate application data and returning status signals. It does not establish a public jobseeker submission API or authorize this project's third-party submitting agent. The terms restrict scraping/extraction without written authorization and require provided interfaces. No platform authorization for unattended third-party Direct Apply has been established. Technical feasibility and owner willingness do not supply that evidence.

| Flow | Supported finding | Current disposition |
| --- | --- | --- |
| Naukri Direct Apply | Native applicant interface exists; selected button can initiate a write | Possible immediate application/follow; no automated submission permission established |
| Additional questions | Official recruiter documentation establishes pre-application questionnaires | No actual questionnaire reached for this job; fields/answers NOT TESTED |
| Incomplete profile | Official guidance establishes required-profile blockers | No profile completion or factual answers fabricated; candidate profile not modified |
| External company/ATS application | Must establish the exact employer's ordinary application URL, requisition, terms, controls and receipt independently | Selected page exposes no verified navigation-only link to its application form; no speculative redirect opened |
| Official Naukri integration | Employer/recruiter supported-ATS integration, not a jobseeker API for this project | Requires actual approved partner/employer arrangement; none established |
| Unsupported third-party POST/replay | No authorized mechanism established | Not implemented or invoked |
| Confirmation / already-applied | Official status channels exist; employer receipt is a distinct claim | No new application or receipt; do not mark Applied |

An external employer form can offer a different permitted route, but its platform-specific permission and authorization must be verified first. No third-party auto-apply vendor's marketing, unofficial API client or another site's FAQ was treated as permission or evidence of Naukri behavior. Current Naukri daily limits were not independently verified; the owner's saved threshold/limits were not lowered or replaced with an unverified public number.

## Exact separate action request, not permission to execute

The precise submission-risk boundary for this selected listing is **one activation of Apply for Backend Developer at QTrino Labs Limited, posted by Naukri E-hire, Naukri listing261026028027, in Profile8**. It may immediately submit an application and may enable a company-follow change. Likely transmitted categories are the Naukri account's currently saved CV/resume, contact information, education, employment/experience, skills, profile attributes and application metadata. The currently saved Naukri resume/version has not been verified against the software's approved canonical resume; do not claim they are the same.

No approval for that exact action has been recorded in this milestone. Generic machine access is not a verified platform integration. The supported alternative presently established is an **owner-operated action through the ordinary Naukri interface**, followed by read-only inspection; a software-operated click remains blocked on established platform support as well as the exact action authority. No automatically repeated click is acceptable.

If that separate action is later specifically authorized through a supported route, verify the exact displayed employer/listing and saved profile/resume first. Observe whether the result is a real questionnaire, profile blocker, employer redirect, explicit confirmation or already-applied state. Persist that actual structure/state before further action. For a questionnaire, request only necessary factual input or field-specific filling authority; do not submit in a fill-only test. If submission occurs immediately, reconcile the exact job in the provider's persisted Applied Jobs state and seek an independently attributable employer/ATS acknowledgment. Email evidence may be checked only under already-enabled explicit read-only mailbox policy; no deferred Gmail source or broader mailbox access may be activated. A Naukri-recorded application without employer corroboration must be labeled accordingly. Unknown outcomes remain stopped without resubmission.

No one-time click authority authorizes unattended recurring applications, resume replacement, follow changes beyond those explicitly covered, later questionnaire submission, new providers or other platforms.

Reproduction, only during a later permitted owner inspection: open the exact ordinary public job-details URL above, without auto-apply query parameters, and evaluate the following read-only expression in that document. Do not activate Apply to reproduce the zero-form finding.

```js
({
  forms: document.forms.length,
  iframes: document.querySelectorAll('iframe').length,
  visibleControls: [...document.querySelectorAll('input:not([type=hidden]),select,textarea')]
    .filter(e => e.getClientRects().length)
    .map(e => ({type: e.type, name: e.name, placeholder: e.placeholder,
      required: e.required, maxLength: e.maxLength}))
})
```

Exact route-validation counts: one genuine page observed, zero application questionnaires reached, zero field fills, zero submissions and zero independently verified application receipts. No new route unit test or performance comparison substitutes for those observations. The47 isolated history/safety test passes and measured timing/resource comparisons belong to the linked installation/correction report.

## Acceptance and next actions

| Milestone | Verdict | Exact evidence / next action |
| --- | --- | --- |
| Selected genuine job identity and real document | PASS read-only | Hiring company/recruiter distinguished; structure observed and privately persisted |
| Reach genuine form without a potentially submitting action | **BLOCKED** | Zero forms/application fields; no verified navigation-only form link |
| Real questions accurately prepared / fields filled | **NOT TESTED,0** | No form, no saved new plan, no approved field fill |
| Correctly characterize Direct Apply risk | PASS for risk classification | Submission/follow possible; exact job/account outcome remains unobserved |
| Permitted third-party Naukri submission mechanism | **NOT ESTABLISHED** | Official integration concerns employer ATS; no jobseeker agent authorization |
| Genuine authorized submission / independent receipt | **NOT TESTED,0** | No Apply activation, submission, fabricated receipt or Applied transition |
| Automatic discovery demonstration | NOT TESTED in this milestone | No Gmail policy expansion or source activation; approved matching threshold unchanged |
| Awake/locked unattended workflow | NOT TESTED / NOT ACCEPTED | Functional and desktop gates unmet; no sleep/logout/off claim |

Do not turn the platform blocker into another backend rewrite. Finish review of the narrow history correction, preserve the background-only constraint, then choose a specifically authorized, platform-supported route or owner-operated Direct Apply. Until one genuine application is independently confirmed, fully automatic Naukri applying remains unproven.

## Owner-operated first application: exact next action

The extension and history-fix installation are **not prerequisites** for this
manual application. In the existing Profile 8, the owner should open the
[selected QTrino Backend Developer listing261026028027](https://www.naukri.com/job-listings-backend-developer-naukri-e-hire-gurugram-0-to-2-years-261026028027),
check that the live heading still identifies QTrino Labs Limited, and verify the
account's currently saved resume/profile. The saved application packet's local
checklist is not evidence of a portal form or of the resume currently on Naukri.

Check Applied Jobs first for this exact requisition; if already recorded, do
not click again. Otherwise, when satisfied with the vacancy and saved resume,
the **owner** activates Apply once. That activation may itself submit the saved
profile/resume. It may also change company-follow state; inspect any visible
follow option beforehand, deselect it if unwanted, or stop if its effect is
unacceptable/unclear. A second confirmation screen cannot be assumed.

If a questionnaire appears, use its actual wording/options, answer truthfully
from confirmed facts, and leave unknown salary, authorization, availability or
other facts for owner input. Additional submission buttons are separate manual
actions. If profile completion, login, expiry, challenge or an external redirect
appears, record that result and stop; do not call an internal endpoint or retry
Apply to investigate. An external route needs the actual employer/requisition
and its own permitted interface verified before submission.

After a success or ambiguous result, use Naukri's own **Applied Jobs** navigation
to find the exact listing/requisition, role and displayed hiring company/posting
recruiter. Reopen the status through normal navigation to check persistence;
retain the displayed status, application time and any receipt/reference privately.
Do not treat a click, follow notification, saved job, toast alone or opened page
as proof. If absent/ambiguous, mark outcome unconfirmed and do not resubmit.
The owner can retain a private screenshot of the exact status with candidate
details redacted before sharing any evidence. Gmail confirmation is optional;
only the already approved account/purpose/selection may be used for a later read.

An exact persistent **Applied Jobs** record is a genuine **Naukri-recorded manual
application receipt**. Employer acknowledgment, recruiter viewing and shortlisting
are separate later evidence; they are not prerequisites for recognizing that
Naukri recorded the application. The app's owner-report endpoint still labels a
manually entered report `user_reported` / `self_reported_unverified`; it cannot
independently attest to a screenshot or upgrade it to an automatic provider receipt.
Record it through Applications → the selected packet → Report manual submission
only after the real action, with the private receipt reference. No automatic
submission is implemented or claimed.

Fresh primary-source review on2026-10-30:

- [Naukri communication guidance](https://www.naukri.com/blog/greater-control-over-communication-from-naukri-com/amp/)
  confirms custom job alerts and Applied Jobs/status communications.
- [Naukri's Apply Integration description](https://recruiterzone.naukri.com/tag/apply-integration/)
  addresses recruiters and collecting applications into their ATS.
- [Greenhouse's Naukri setup](https://support.greenhouse.io/hc/en-us/articles/16297968058651-Naukri-integration)
  requires employer integration credentials, a Naukri subscription and integration
  module. It does not offer this applicant agent a general submission grant.
- [Ashby's Naukri integration](https://docs.ashbyhq.com/naukri) likewise concerns
  employer job posting with a Naukri-issued team API key.

**No officially supported or explicitly permitted third-party Naukri submission
path available to this project was found.** This is a scoped research conclusion,
not a claim that no private commercial partnership could ever exist. Current
public terms retrieval remained robots-restricted; the earlier normal-profile
terms observation is retained above. No unofficial MCP, authenticated Apply POST,
cookie replay or speculative partner credential was implemented or tested.
