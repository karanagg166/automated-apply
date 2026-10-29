# Razorpay form preparation

The extension can prepare ordinary answers from the existing application packet
when a security widget is present. This produces a **read-only** plan: neither the
popup nor native authorization can turn it into a fill. A visible access-blocking
challenge is reported separately from an unverified widget. No CAPTCHA frame,
response token, completion signal or challenge control is read or manipulated.

The owner completes security checks on the official page, then prepares and reviews
a new snapshot. Removing or hiding a widget does not unlock an existing plan. If a
widget remains present, its completion remains unverified and filling stays disabled;
the owner can use the preview to complete ordinary fields manually.

| Razorpay control | Behavior in this change |
| --- | --- |
| Ordinary name/contact/text fields | Grounded proposals remain readable. Existing page values are omitted and preserved. React-controlled fields provide manual-entry proposals. |
| Country, career stage, industry, designation dropdowns | Native single-selects support up to 300 inspected options; native datalists support exact option values. Accessible custom lists provide read-only proposals when their unique `aria-controls` list and choices are already mounted and visible. Menus are never opened during preparation. Event-driven, lazy, ambiguous or virtualized widgets remain manual. |
| Start/end dates and months | Native `date` and `month` inputs accept exact verified ISO values, checked against the current minimum, maximum and step. Native month/year dropdowns use exact choices. Custom calendars, ambiguous formats and unknown dates remain manual. |
| Repeated employment questions | Diagnostics use actual control identity and section context. Distinct employment rows stay distinct. Repeated questions without a distinct context abstain from answer reuse. |
| Gender and other self-identification | Explicit manual owner choices; no inference or automatic answer retention. |
| CAPTCHA, OTP, consent, legal declarations, frames, uploads, submission | Manual. Security or sensitive access restrictions disable all automated filling while ordinary permitted proposals remain readable. |

Pending dashboard answers are shown as read-only proposals without overwriting them
or creating another missing-input question. Reviewed answers retain revision and
expiry checks. Per-control preview restrictions, single-use authorization, option
node/code bindings, DOM invalidation and page-value preservation remain enforced.
Inspection itself fires no input, change or dropdown events.

Validation is limited to inspector/diagnostic/dropdown/CAPTCHA unit tests, the form
bridge and popup unit modules, selected native preview/authorization/date tests,
and one fictional Greenhouse Chromium journey using a fake native transport. That
journey exercises the actual inspector, bridge and popup and captures
[the read-only popup](screenshots/razorpay-fictional-preview.png). It does not establish
live Razorpay compatibility for every custom widget. No real data, real filling,
installed-release changes, hosted Actions or full regression suites were used.
