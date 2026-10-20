# Notification foundation

Phase 10 extends this foundation with an opt-in standalone scheduler. It reuses these
same rows/delivery keys/digest keys and adds score thresholds and redacted discovery
failure/stale-profile/review alerts. Scheduled generation requires saved in-app opt-in,
honors pause/quiet hours, and uses approved cached match results. Existing on-demand
checks remain available. See [Phase 10](phase10-automation.md); no live worker is activated.

In-app notifications are private PostgreSQL rows with a unique deduplication key, event type, redacted title/body, workspace destination, read state and timestamps. Owner preferences are durable and independently validated. This phase starts no worker or scheduled delivery in a real environment.

The explicit “Check saved activity” action evaluates saved high-match jobs/startups, current contact evidence, provider failures, reviewable application packets and local drafts, then adds at most one daily summary per owner-local calendar date. Generation respects in-app opt-in, global pause and IANA-timezone quiet hours; equal start/end hours disable quiet hours. Deferred events can be generated on a later check. Titles and summaries avoid candidate contact details, resume text, email contents or sensitive opportunity descriptions.

Unique database keys deduplicate concurrent activity checks. Each packet/draft revision has a distinct event key. In-app read state is durable. UI errors are surfaced; mutation retries are disabled. All external delivery channels are schema-gated to `false`, so a browser cannot accidentally turn them on. A channel-neutral outbox records in-app availability with unique notification/channel keys, attempt counts, fixed failure categories and next-attempt fields. The dashboard exposes this history. No external attempt exists and no external success or delivery receipt is fabricated.

Future adapters must extend this delivery outbox with per-channel opt-in, a unique event/channel key, safe outcome classification, bounded retry/backoff, quiet-hour scheduling, redaction, failure history and pause controls before any scheduler is authorized. Do not retry unknown transmission outcomes. Existing Gmail outreach is a separate approval-controlled workflow, not a notification channel.

- **In-app:** implemented, owner-triggered, deduplicated, private, pauseable.
- **Browser push:** not implemented; requires secure subscriptions and owner permission. No permission prompt is shown prematurely.
- **Telegram:** disabled; requires a privately stored bot token, owner-approved recipient and explicit opt-in before a delivery adapter is enabled.
- **WhatsApp Cloud API:** disabled. Official API only. Business setup, sender/recipient authorization, approved templates, current provider pricing review, budget and explicit notification opt-in are prerequisites. Pricing was not assumed or live-verified. Proactive WhatsApp alerts are **not labeled free**. No unofficial WhatsApp Web automation is included.

Preferences are available at `/settings`; notification activity is at `/notifications`. Tests cover quiet-hour preferences, daily deduplication, read state, pause and refusal to enable unimplemented channels.
