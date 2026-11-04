# Genuine optional company-follow control supported; first receipt still pending

[PR #48](https://github.com/karanagg166/automated-apply/pull/48), branch
`fix/live-prepare-discovery-20261030`. **Naukri remains OPEN.**

An ordinary read of a genuinely leased inactive listing tab on November4 showed
the current header's optional company-follow control is an `i[role=checkbox]`
with an exact company-specific accessible label and `aria-checked=true`. The old
adapter only inspected native checkbox inputs, so it did not cover this control.
The same internship page displayed `3 months duration` in the normal experience
slot and `100+` applicants. Neither duration nor the URL establishes an experience
range; the applicant label supplies no upper bound. No Apply was attempted there.

[Exact implementation2959cd7](https://github.com/karanagg166/automated-apply/commit/2959cd713a550b1cdf527f2d20decd73edbd0b9d)
adds extension1.3.25. It recognizes only the observed company-labelled optional
follow control and includes its markup/state in the document seal. Inside a
single durably admitted Apply action, it opts out, verifies persistence and the
unchanged listing/button, then clicks Apply once within the existing permit.
Unrecognized checked choices, a changed control, failed opt-out, injected forms,
expired permits, owner activity and second attempts remain blocked. No claim is
made that a live provider opt-out or application has yet succeeded.

The exact immutable candidate built with the unchanged stable ID and permissions.
Its isolated Chromium156 acceptance passed44 cases in112.625 seconds, including
six new follow-control cases: checked/unchecked, unknown label, failed opt-out,
changed pre-admission state and a new checked choice injected during opt-out.
Successful fixture Apply saw follow=false; failures caused zero fixture Apply.
Zero live Naukri/unexpected requests or file chooser events occurred. An initial
fixture counter failed because the observation read the isolated world rather
than the main world; the corrected check reads the actual handler counters in
MAIN. Formatting, syntax, build and diff checks passed. These are fictional-page
regressions informed by genuine DOM, not live submission acceptance.

Actual extension-only installation passed at14:19:39UTC:

- Queue STOP119,1,922 durable records; Stop took13.032 seconds including subsequent
  verification requests. This is not a resolved Stop-latency claim.
- All24 installed extension files match2959cd7/1.3.25 and the stable path/ID
  `gdjbmkffcpicbpiikcohlmokkmcpipgp`; a fresh native heartbeat followed Reload.
- Ready200, frontend200, profile5, approved account binding1 and unchanged policy.
- API/execution/Telegram/frontend stayae66975; native stays414a260. Protected
  runtime files and all four service plists match their pre-install hashes.
- Exact previous1.3.24 bytes/hashes and rollback instructions remain retained.
  Failed cutover restores only those exact extension bytes under STOP and checks
  reconnection/readiness/data; it never restores old database data or replays Apply.
- Only the owned inactive extension manager was used. Front window and active-tab
  IDs matched before/after; no keyboard, clipboard or owner-tab activation.

The actual installed frontend then started RUN120. Any-skill/score50/14 days/
1,000 applicants/unknown-count review, lifetime-one/hour-one SUPERVISED remained
exact; zero unexpected frontend requests. The historical QTrino and uncertain
internship remain protected from replay. The lifetime allowance was not reset.

| Acceptance | Result | Evidence / limit |
| --- | --- | --- |
| Genuine current follow-control identification | PASS | Actual leased inactive listing DOM |
| Exact candidate optional-choice guards | PASS |44 isolated browser cases; zero provider requests |
| Exact extension installation and rollback inventory | PASS |24 files, fresh native reconnect, ready200, protected hashes/focus equal |
| Actual frontend Start with preserved policy | PASS | RUN120, lifetime-one/hour-one |
| Live provider opt-out / new application / receipt | NOT TESTED | No currently qualifying supported direct candidate |
| Recurring AUTOMATIC / locked application behavior | NOT TESTED | First independent worker receipt still required |

Reproduce relevant checks with:

```sh
pnpm -C extension build
node --check extension/naukri-execution.js
node extension/tests/naukri-execution.browser.mjs
pnpm -C frontend exec prettier --check ../extension/naukri-execution.js \
  ../extension/tests/naukri-execution.browser.mjs ../extension/manifest.json
git diff --check
```

The [online repair/recovery report](naukri-online-worker-repair-20261104.md) remains
valid. Next: accurate internship metadata, fresh eligible direct jobs, one real
submission and independent persistent history before bounded AUTO. No Gmail send,
other-platform activation, CAPTCHA/rate bypass, hosted Actions, merge, cleanup or
release deletion. Raw DOM, identity, resume and installation journals stay private.
