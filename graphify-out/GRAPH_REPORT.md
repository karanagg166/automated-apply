# Graph Report - automated-apply  (2026-11-26)

## Corpus Check
- 1552 files · ~1,259,429 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 20 file(s) not represented in the graph (top: (none) 8, .example 5, .plist 3)

## Summary
- 688 nodes · 1465 edges · 35 communities (23 shown, 12 thin omitted)
- Extraction: 94% EXTRACTED · 6% INFERRED · 0% AMBIGUOUS · INFERRED: 92 edges (avg confidence: 0.88)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `1cd00e3b`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- MemoryStore
- rules.py
- test_mail_enrichment_api.py
- Any
- FeedAdapter
- autopilot-rules.tsx
- candidate_profile.py
- Store
- .process_job
- BrowserService
- HitlRecord
- test_public_sources_v2.py
- feeds.py
- .get_rules
- test_browser_v2_postgres_store.py
- store.py
- FeedJob
- PostgresStore
- service.py
- test_phase5_postgres.py
- intent.py
- test_v2_migration_sql.py
- build_service
- test_email_drafts_unique_application_and_reservation_semantics
- _record
- database
- _BoardSource
- public_sources.py
- FetchBudget
- _uuid
- FakeConnection
- api.d.ts
- test_agent_and_bus_share_the_single_serialized_connection
- FakeSource

## God Nodes (most connected - your core abstractions)
1. `PostgresStore` - 72 edges
2. `MemoryStore` - 61 edges
3. `Store` - 57 edges
4. `PortalRules` - 30 edges
5. `BrowserService` - 28 edges
6. `ApplicationRecord` - 24 edges
7. `FeedJob` - 22 edges
8. `FeedAdapter` - 21 edges
9. `HitlRecord` - 19 edges
10. `_now()` - 19 edges

## Surprising Connections (you probably didn't know these)
- `test_preferences_accept_the_new_board_lists()` --uses--> `JobSearchPreferences`  [INFERRED]
  backend/tests/test_public_sources_v2.py → backend/app/schemas/candidate_profile.py
- `_BoardSource` --uses--> `FeedJob`  [INFERRED]
  backend/app/browser_v2/adapters/public_sources.py → backend/app/browser_v2/adapters/feeds.py
- `HackerNewsAdapter` --uses--> `FeedJob`  [INFERRED]
  backend/app/browser_v2/adapters/public_sources.py → backend/app/browser_v2/adapters/feeds.py
- `BrowserService` --uses--> `PortalRules`  [INFERRED]
  backend/app/browser_v2/service.py → backend/app/browser_v2/rules.py
- `MemoryStore` --uses--> `PortalRules`  [INFERRED]
  backend/app/browser_v2/store.py → backend/app/browser_v2/rules.py

## Import Cycles
- None detected.

## Communities (35 total, 12 thin omitted)

### Community 0 - "MemoryStore"
Cohesion: 0.06
Nodes (7): _clip(), MemoryStore, _now(), _telegram_changes(), test_applications_filter_and_events(), test_status_reports_quota_auth_and_waiting_queue(), test_memory_store_lists_the_new_portals_disabled()

### Community 1 - "rules.py"
Cohesion: 0.07
Nodes (23): PortalInfo, unknown_age_default(), ApplicantCount, ApplicantPolicy, CandidatePreferences, contains_term(), Decision, dedup_key() (+15 more)

### Community 2 - "test_mail_enrichment_api.py"
Cohesion: 0.05
Nodes (12): store(), test_portal_rule_validation(), test_portal_rules_list_and_patch_increments_revision(), test_screening_profile_validation(), ctx(), parked(), test_applications_expose_draft_created_at(), test_draft_now_creates_exactly_one_draft_and_is_idempotent() (+4 more)

### Community 3 - "Any"
Cohesion: 0.07
Nodes (9): EmailDraftRecord, SerializedConnection, TelegramState, WorkerControl, WorkerState, store(), test_api_borrows_pooled_connection_and_commits(), test_worker_control_survives_restart() (+1 more)

### Community 5 - "autopilot-rules.tsx"
Cohesion: 0.06
Nodes (5): Feedback, NUMBER_INPUTS, PortalRulesCard(), PortalRulesEditor(), RULES_KEY

### Community 6 - "candidate_profile.py"
Cohesion: 0.10
Nodes (13): CandidateProfileCreate, CandidateProfileRead, CandidateProfileUpdate, Certification, CompensationFact, CountryAuthorization, EducationRecord, JobSearchPreferences (+5 more)

### Community 8 - ".process_job"
Cohesion: 0.15
Nodes (4): format_reason(), is_title_mismatch_only(), can_move(), ApplicationRecord

### Community 11 - "test_public_sources_v2.py"
Cohesion: 0.15
Nodes (11): HackerNewsAdapter, SmartRecruitersAdapter, default_adapters(), job_id_from_url(), client(), test_board_sources_read_only_allowlisted_boards_and_isolate_failures(), test_hn_feed_carries_the_employer_link(), test_preferences_accept_the_new_board_lists() (+3 more)

### Community 12 - "feeds.py"
Cohesion: 0.13
Nodes (5): ApplyLinkChallenge, ApplyLinkLoginWall, external_apply_link(), page_challenged(), PortalWallActive

### Community 13 - ".get_rules"
Cohesion: 0.14
Nodes (5): apply_overrides(), parked(), test_phase6a_dashboard_quota_columns_drive_the_processor(), test_ten_portals_are_seeded_with_only_naukri_enabled(), test_postgres_store_self_seeds_missing_portal_rows_once()

### Community 14 - "test_browser_v2_postgres_store.py"
Cohesion: 0.14
Nodes (6): ApplicationQuery, listing(), test_backlog_hitl_auth_and_portal_limit(), test_transitions_events_dedup_and_listing(), pg(), test_mail_events_dedup_and_digest_date_survive_restarts()

### Community 15 - "store.py"
Cohesion: 0.13
Nodes (5): ProfileMissing, RevisionConflict, RulesNotFound, validate_preferences(), test_rules_quota_pause_and_preferences_round_trip()

### Community 16 - "FeedJob"
Cohesion: 0.22
Nodes (8): FeedJob, ArbeitnowAdapter, request(), RemotiveAdapter, SourceFeedAdapter, load(), to_feed_job(), test_listing_page_sources_resolve_apply_links_or_keep_direct_ones()

### Community 18 - "service.py"
Cohesion: 0.18
Nodes (4): PortalRules, apply_env_profile(), day_start(), quota_counts()

### Community 19 - "test_phase5_postgres.py"
Cohesion: 0.15
Nodes (5): test_rules_crud_with_revision_and_db_constraints(), test_credit_reservation_is_atomic_under_concurrency(), test_enrichment_cache_upsert_ttl_and_status_constraint(), test_migration_reapplies_twice_over_live_data_with_phase6a_objects(), test_overlay_requires_all_or_none()

### Community 20 - "intent.py"
Cohesion: 0.20
Nodes (7): Intent, llm_parse(), LLMIntent, _num(), parse(), portals_in(), _split_items()

### Community 21 - "test_v2_migration_sql.py"
Cohesion: 0.19
Nodes (5): parse_posted_age_days(), statements(), test_every_create_is_idempotent(), test_migration_is_additive(), test_migration_tables_match_overlay_inventory()

### Community 22 - "build_service"
Cohesion: 0.17
Nodes (4): build_ai(), build_service(), env_profile_overrides(), open_store()

### Community 23 - "test_email_drafts_unique_application_and_reservation_semantics"
Cohesion: 0.20
Nodes (3): _draft(), DraftReservation, test_email_drafts_unique_application_and_reservation_semantics()

### Community 24 - "_record"
Cohesion: 0.22
Nodes (3): _json(), _record(), test_quota_lifecycle_survives_restarts_with_exactly_one_draft()

### Community 25 - "database"
Cohesion: 0.29
Nodes (4): database(), free_port(), test_migration_applies_twice_on_disposable_postgres(), test_migration_runs_as_supabase_style_non_superuser_owner()

### Community 26 - "_BoardSource"
Cohesion: 0.24
Nodes (4): fetch_all_pages(), AshbyAdapter, _BoardSource, load()

### Community 31 - "api.d.ts"
Cohesion: 0.33
Nodes (5): components, $defs, operations, paths, webhooks

## Knowledge Gaps
- **12 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `PostgresStore` connect `PostgresStore` to `.get_telegram_state`, `MemoryStore`, `test_agent_and_bus_share_the_single_serialized_connection`, `Any`, `Store`, `test_public_sources_v2.py`, `.get_rules`, `test_browser_v2_postgres_store.py`, `store.py`, `service.py`, `test_phase5_postgres.py`, `build_service`, `test_email_drafts_unique_application_and_reservation_semantics`, `_record`, `_uuid`?**
  _High betweenness centrality (0.150) - this node is a cross-community bridge._
- **Are the 4 inferred relationships involving `PostgresStore` (e.g. with `open_store()` and `PortalRules`) actually correct?**
  _`PostgresStore` has 4 INFERRED edges - model-reasoned connections that need verification._
- **Should `MemoryStore` be split into smaller, more focused modules?**
  _Cohesion score 0.06033182503770739 - nodes in this community are weakly interconnected._
- **Why does `MemoryStore` connect `MemoryStore` to `test_mail_enrichment_api.py`, `Any`, `Store`, `.process_job`, `test_public_sources_v2.py`, `store.py`, `service.py`, `build_service`?**
  _High betweenness centrality (0.135) - this node is a cross-community bridge._
- **Are the 5 inferred relationships involving `Store` (e.g. with `BrowserService` and `build_ai()`) actually correct?**
  _`Store` has 5 INFERRED edges - model-reasoned connections that need verification._
- **Should `rules.py` be split into smaller, more focused modules?**
  _Cohesion score 0.07446808510638298 - nodes in this community are weakly interconnected._
- **Why does `Store` connect `Store` to `Any`, `.process_job`, `BrowserService`, `HitlRecord`, `test_browser_v2_postgres_store.py`, `store.py`, `service.py`, `build_service`, `test_email_drafts_unique_application_and_reservation_semantics`?**
  _High betweenness centrality (0.100) - this node is a cross-community bridge._