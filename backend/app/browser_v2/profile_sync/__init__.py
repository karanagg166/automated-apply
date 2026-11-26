"""Phase 9D: portal profile & resume sync (Naukri, Instahyre, Internshala, Wellfound, YC WaaS).

Modules (import them directly; this package ``__init__`` is import-free on purpose so the
portal adapters can import ``models`` without pulling the service in):

- ``models``     value objects (FieldStatus, FieldValue, FieldDiff, ProfileSnapshot, SyncReport)
- ``diff``       pure per-field normalisation and diffing (never-empty, add-only skills)
- ``canonical``  ProfileSnapshot from ``candidate_profiles`` + the active resume PDF
- ``runs``       ``public.profile_sync_runs`` persistence (Postgres on the store connection / memory)
- ``adapters``   per-portal profile adapters (uncalibrated adapters never touch the page)
- ``service``    ProfileSyncService.sync(): read -> diff -> (live) write + verify -> persist
- ``scheduler``  ProfileSyncScheduler (interval, on-demand queue, profile.updated debounce)
- ``status``     read-only status for the API / Telegram
- ``probe``      PII-scrubbed outline of a logged-in profile page (selector calibration)

Only SHA-256 references and lengths of profile values are ever persisted or logged.
"""
