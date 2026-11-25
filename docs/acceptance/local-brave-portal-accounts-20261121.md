# Local Brave portal account acceptance

## Latest verified sign-ins, November 25

Verified sign-ins stand at three of eight. Naukri verified the signed-in
account and canonical résumé in the existing dedicated Brave tab on
November 25. Instahyre completed onboarding and opened Opportunities on
November 23. Wellfound's signed-in session and canonical résumé were
verified. Its profile completion prompt still appears. HiringCafe confirmed
the selected email, with its tracker returning HTTP 403. YC Work at a
Startup, Internshala, Himalayas, and We Work Remotely still lack verified
account sessions in the dedicated profiles. The Naukri worker receipt is
tracked separately. [Naukri live status](naukri-bridge-release-20261125.md)

## November 22 profile follow-up

The saved Wellfound account still matches the owner's sign-in address. An
independent browser visit showed the owner-confirmed current city and
Software Engineer as the primary role. The education editor retained the
confirmed graduation month and bachelor-level degree. The canonical resume
was already verified. After an independent read, the profile showed Frontend
Engineer, Backend Engineer, Full-Stack Engineer and DevOps as additional
roles. The new biography and job-search statement both survived reload.
The experience picker retained the confirmed range of less than one year.
Five profile skills were verified after reload. The other three selected
skills were unconfirmed on readback.
Wellfound still showed its profile completion prompt.
Both the profile editor and the overview showed the same prompt. The editor
did not mark a field as required or invalid. The portfolio summary save
remains unconfirmed on the independent read.

Instahyre retained the student-or-fresher choice and all 20 skills after a
reload. Its preferences form returned HTTP 200 after saving the confirmed
city, salary floor and the available domestic, international and remote
choices. The owner's linked portfolio identifies a completed internship.
Instahyre accepted that company with HTTP 202 and retained the education
step. The final form accepted the owner's confirmed contact and gender,
preserved the uploaded resume and selected visibility, and sent a mobile
verification code. The authenticated verification page shows the matching
owner mobile. The initial final-form request returned HTTP 400 and explicitly
identified both missing fields. macOS foreground and window order matched
through the accepted follow-up. [Portfolio work experience](https://portfolio-kappa-bay-76.vercel.app/#experience)

LinkedIn returned HTTP 999 through its public page and the dedicated Brave
profile. The portfolio supplied the internship company and dates. The
verified candidate profile records the other work role without classifying
it as an internship.

The owner's confirmed portal facts are stored in the restricted
`owner_preferences` record `portal_candidate_facts_v1`. AGY can retrieve
the latest owner-confirmed contact, onboarding and work preferences from
that record. The saved resume keeps its original confirmation binding.
The mobile verification code is transient and is kept out of the facts
record.

The private portal record contains the exact owner-confirmed preferences
for AGY. The account count remains two of eight. The Naukri tab still shows
sign-in in the dedicated Brave profile. Email recovery returned HTTP 403,
and the matched inbox check found no recovery email. The application queue
is stopped.

## Earlier account setup

Two of eight portal sessions have been verified in the dedicated Brave profiles.
Wellfound restored the owner-selected account from disk after Brave closed and
reopened. The Keychain holds the new password. The resume page showed the
canonical PDF after a fresh navigation. The upload used the confirmed version
5 profile and the verified PDF checksum, and preserved the existing account.
The candidate editor still reports required profile fields.

| Portal | State | Evidence |
| --- | --- | --- |
| Wellfound | Session verified | The exact account matched its settings after Brave reopened. The canonical resume appeared after a fresh navigation. An authenticated Wellfound email confirmed the owner-requested password change. The retained session passed another restart readback. A new independent login with the changed password remains unconfirmed. |
| Naukri | Email-only sign-in blocked | The dedicated Brave window opened with the owner's approval. The loaded extension matched all 26 files in the accepted bundle and retained permission for the official Naukri origin. Email recovery returned HTTP 403, and the ordinary Google sign-in path reported a block. The owner selected email-only recovery. |
| Instahyre | Session + partial onboarding verified | Apple Mail delivered the authenticated recovery email. The corrected reset and sign-in succeeded in `brave-automation`, surviving reload with candidate settings matching the owner-selected email (working password in Keychain). Onboarding Step 1 expanded verified skills from `4` to `20`, Step 2 preserved pre-saved preferences, and Step 3 saved education (`5693636`) and uploaded the confirmed canonical v5 PDF (`100,198` bytes, SHA-256 `cfc0d859eafdf99094ed643791b9532006fdf70199191d88f624f5cb3e824d6c`, `resume_id: 4826702`) with macOS focus preserved (`PASS`). Paused before Step 4 on required current job title/company because profile v5 records no post-September-2026 employer and switching career stage in the UI resets the pre-saved compensation value; zero applications submitted. |
| YC Work at a Startup | Account unverified | The provider accepted the original sign-in link request. The separate candidate signup recorded one action with an unknown outcome. The existing-account check returned to the new-account flow. |
| Internshala | Email recovery unverified | The candidate recovery endpoint responded HTTP 200. No matching recovery message reached Apple Mail during the observed checks. |
| HiringCafe | Dashboard access blocked | The official combined form triggered an authenticated verification email. The retained browser session reported the chosen verified email, and the tracker returned HTTP 403. |
| Himalayas | Signup blocked | The official email recovery form reported no account for the selected address. The signup button stayed disabled after all four fields passed browser validation. The earlier signup intent remains in history. The latest check stopped before submission. |
| We Work Remotely | Owner session pending | The official registration route returned HTTP 403. |

The installed We Work Remotely MCP successfully collected and saved 20 jobs
from the attributed public RSS feed. The portal account remains pending.
[Official RSS feed](https://weworkremotely.com/remote-job-rss-feed)

The readiness record in `.local/browser-profiles/portal-status.private.json`
is available to AGY as local evidence. It records the last check for each
portal. Instahyre is in `.local/browser-profiles/brave-automation`. Wellfound
is in `.local/browser-profiles/brave-portal-accounts`. Both sessions belong to
the owner-selected email. Keychain items remain local and the handoff contains
item names and session evidence. Portal authentication remains independent of
the selected Naukri worker binding and application queue permissions. macOS
snapshots matched foreground app and window order across the Wellfound recovery checks.

The Instahyre working sign-in is usable in Brave. A separate password
change through its verified account settings stopped when macOS Keychain
declined unattended readback of the existing credential. The official
recovery route did not expose its form in the inactive dedicated tab.
The exact signed-in account still matched after this check, and macOS
foreground and window order matched before and after. The session remains
the verified handoff. For Wellfound, local Keychain comparison matched the
latest owner choice against the credential saved for the password change
confirmed by the provider's email.

The dedicated Brave automation profile and its saved runtime binding agree on
their browser session. The runtime reports that binding as `CONNECTED`.
The dashboard selection points to a different binding that reports
`PROFILE_OFFLINE`. The dedicated profile has commands disabled. Its one
inactive Naukri tab still shows the official sign-in form with the selected
email filled. The next acceptance check needs the signed-in account and
resume identity before using the live binding for supervised execution.

The saved Naukri Jobs search returned zero matches in 2.738 seconds for
published dates within 14 days and a minimum match score of 50. That read
covered the saved inventory. Once the owner signs in, fresh discovery and
listing inspection are still needed to find an eligible vacancy.

Wellfound's account settings confirmed the selected sign-in email. Its
display name differs from the confirmed local profile name and was preserved.
One admission to add the missing LinkedIn URL recorded an unknown outcome.
A new browser read found the field empty, and the save intent remains open
for reconciliation. The current location is empty on the portal and absent
from the confirmed local profile. The education editor uses a month-and-year
picker. The saved education gives a year, and the canonical PDF did not
provide an unambiguous month for that institution. These checks preserved
macOS foreground and window order.

The saved selection is version 3 and is enforced by the fixed legacy Chrome
pin. The approved Naukri account is revision 1 and matches the owner-selected
address. It still points to the pinned Chrome binding. The fixed pin blocks
selection of the connected dedicated Brave profile. The only retained
nonterminal extension task is paused by global STOP and has no plan. There
are zero active commands and form plans.

The official inactive login page still offers password recovery, mobile OTP,
and Google sign-in. Its email recovery link is the same route already tried.
A recipient- and sender-domain-matched Apple Mail check found zero recovery
messages from Naukri in the preceding 48 hours. The existing request remains
recorded. [Naukri’s account support form](https://w5.naukri.com/fdbck/main/feedback.php)

After sign-in, verify the account and canonical resume in the dedicated Brave
profile. The fixed-profile replacement must preserve the previous mapping and
paused task, revoke old authority under the owner lock, and keep both queues
stopped. After changing the fixed pin and selection, use the normal account
approval flow to bind the independently verified account to the new profile.
See the [fixed profile procedure](../phase54/local-mail-and-fixed-profile.md#fixed-chrome-identity).

The new local Brave pin maintenance command now has a read-only preview
and an explicit apply mode. Six focused disposable PostgreSQL checks passed.
They covered the replacement and existing select and disconnect behavior,
preservation of STOP, the paused task and unknown application evidence,
refusal of stale account or resume evidence and active work, rollback after
a failed selection write, and one winner for concurrent attempts. The
local binary also rejected an invalid review file before connecting to
PostgreSQL. Live pin replacement still needs the signed-in Brave review
and separate approval of the account on the new binding.
