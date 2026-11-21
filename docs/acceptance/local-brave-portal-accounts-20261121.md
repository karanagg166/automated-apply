# Local Brave portal account acceptance

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
| Instahyre | Session verified | Apple Mail delivered the authenticated recovery email. The first password was rejected by the portal's length check. The corrected reset and sign-in succeeded. The session survived a reload and the candidate account settings showed the owner-selected email. The working password was stored in macOS Keychain. |
| YC Work at a Startup | Account unverified | The provider accepted the original sign-in link request. The separate candidate signup recorded one action with an unknown outcome. The existing-account check returned to the new-account flow. |
| Internshala | Email recovery unverified | The candidate recovery endpoint responded HTTP 200. No matching recovery message reached Apple Mail during the observed checks. |
| HiringCafe | Dashboard access blocked | The official combined form triggered an authenticated verification email. The retained browser session reported the chosen verified email, and the tracker returned HTTP 403. |
| Himalayas | Signup blocked | The official email recovery form reported no account for the selected address. The signup button stayed disabled after all four fields passed browser validation. The earlier signup intent remains in history. The latest check stopped before submission. |
| We Work Remotely | Owner session pending | The official registration route returned HTTP 403. |

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
