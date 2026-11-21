# Local Brave portal account acceptance

One of eight portal sessions has been verified in the dedicated Brave profile.
Wellfound restored the owner-selected account from disk after Brave closed and
reopened. The Keychain holds the new password. The resume page showed the
canonical PDF after a fresh navigation. The upload used the confirmed version
5 profile and the verified PDF checksum, and preserved the existing account.
The candidate editor still reports required profile fields.

| Portal | State | Evidence |
| --- | --- | --- |
| Wellfound | Session verified | Recovery email arrived in Apple Mail. The exact account matched its settings after Brave reopened. The canonical resume appeared after a fresh navigation. |
| Naukri | Owner sign-in pending | The dedicated Brave window opened with the owner's approval. The loaded extension matched all 26 files in the accepted bundle and retained permission for the official Naukri origin. Email recovery returned HTTP 403, and the ordinary Google sign-in path reported a block. The Naukri password form is open with the chosen email entered. |
| Instahyre | Owner session pending | The mailbox contains a prior welcome message. Live access showed a browser challenge. |
| YC Work at a Startup | Verification pending | The provider accepted the original sign-in link request. The separate official candidate signup recorded one action, with its outcome still unknown. |
| Internshala | Owner session pending | The portal exposed its sign-in form and a browser challenge. |
| HiringCafe | Outcome unknown | The official combined form triggered an authenticated verification email. The verification link was opened once. The signed-in account still awaits confirmation. |
| Himalayas | Outcome unknown | A single signup intent is retained. A separate sign-in check returned credentials unaccepted. |
| We Work Remotely | Owner session pending | The official registration route returned HTTP 403. |

The readiness record in `.local/browser-profiles/portal-status.private.json`
is available to AGY as local evidence. It records the last check for each
portal. The runtime's selected browser connection still uses its separately
verified Naukri automation profile. macOS snapshots matched foreground app and
window order across the Wellfound recovery checks.
