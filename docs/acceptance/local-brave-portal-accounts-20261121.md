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
