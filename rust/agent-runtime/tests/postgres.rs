//! Only the disposable harness URL is accepted. These tests never load application settings.
use automated_apply_agents::{
    Failure, Result,
    contracts::*,
    engine,
    postgres::Store,
    runner::{Model, Tools, tick},
};
use serde_json::json;
use sqlx::{Connection, PgConnection, Row};
use uuid::Uuid;

async fn connection() -> PgConnection {
    let url =
        std::env::var("RUST_AGENT_TEST_DATABASE_URL").expect("run the dedicated fixture harness");
    let port = url
        .strip_prefix("postgresql://rust_agent_fixture@127.0.0.1:")
        .and_then(|s| s.strip_suffix("/rust_agent_fixture"))
        .and_then(|s| s.parse::<u16>().ok())
        .filter(|p| *p > 1024)
        .expect("exact disposable loopback fixture URL required");
    assert!(port > 1024);
    PgConnection::connect(&url)
        .await
        .expect("fixture connection")
}
async fn setup() -> PgConnection {
    let mut c = connection().await;
    sqlx::raw_sql("DROP TABLE IF EXISTS rust_agent_events; DROP TABLE IF EXISTS rust_agent_runs; DROP TABLE IF EXISTS llm_monthly_usage;")
        .execute(&mut c)
        .await
        .unwrap();
    sqlx::raw_sql(include_str!("../sql/001_runtime.sql"))
        .execute(&mut c)
        .await
        .unwrap();
    sqlx::raw_sql("CREATE TABLE llm_monthly_usage (provider varchar(30) NOT NULL,month varchar(7) NOT NULL,requests integer NOT NULL DEFAULT 0,input_tokens integer NOT NULL DEFAULT 0,output_tokens integer NOT NULL DEFAULT 0,cooldown_until timestamptz,created_at timestamptz NOT NULL DEFAULT clock_timestamp(),updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),PRIMARY KEY(provider,month))").execute(&mut c).await.unwrap();
    c
}
fn run() -> Run {
    Run::new(Uuid::new_v4(), Limits::default()).unwrap()
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn request_idempotency_preserves_original_run_and_rejects_conflict() {
    let mut c = setup().await;
    let mut store = Store { connection: &mut c };
    let first = run();
    let id = store.create(&first).await.unwrap();
    let same = Run::new(first.request_key, Limits::default()).unwrap();
    assert_eq!(store.create(&same).await.unwrap(), id);
    let mut different = same;
    different.limits.tokens += 1;
    assert_eq!(
        store.create(&different).await,
        Err(Failure("agent_request_key_conflict"))
    );
    let count: i64 = sqlx::query_scalar("SELECT count(*) FROM rust_agent_runs")
        .fetch_one(&mut c)
        .await
        .unwrap();
    assert_eq!(count, 1);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn two_workers_cannot_claim_the_same_active_lease() {
    let mut c1 = setup().await;
    let mut c2 = connection().await;
    Store {
        connection: &mut c1,
    }
    .create(&run())
    .await
    .unwrap();
    let mut s1 = Store {
        connection: &mut c1,
    };
    let mut s2 = Store {
        connection: &mut c2,
    };
    let (a, b) = tokio::join!(s1.claim(), s2.claim());
    assert_ne!(a.unwrap().is_some(), b.unwrap().is_some());
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn expired_worker_is_fenced_and_cannot_save_or_release() {
    let mut c = setup().await;
    let mut store = Store { connection: &mut c };
    store.create(&run()).await.unwrap();
    let mut old = store.claim().await.unwrap().unwrap();
    sqlx::query("UPDATE rust_agent_runs SET lease_until=clock_timestamp()-interval '1 second'")
        .execute(&mut *store.connection)
        .await
        .unwrap();
    let mut fresh = store.claim().await.unwrap().unwrap();
    assert_eq!(
        store.save(&mut old).await,
        Err(Failure("agent_lease_or_revision_lost"))
    );
    assert_eq!(
        store.release(&old).await,
        Err(Failure("agent_lease_or_revision_lost"))
    );
    store.save(&mut fresh).await.unwrap();
    store.release(&fresh).await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn committed_external_intent_survives_connection_loss_and_is_not_replayed() {
    let mut c = setup().await;
    let mut r = run();
    r.role = Role::Execution;
    r.known_jobs = vec![Uuid::from_u128(1)];
    engine::begin_model(&mut r).unwrap();
    engine::accept(
        &mut r,
        Proposal::Tool {
            call: ToolCall {
                name: ToolName::OpenBrowser,
                job_id: Some(Uuid::from_u128(1)),
                evidence: vec![],
            },
        },
    )
    .unwrap();
    let mut store = Store { connection: &mut c };
    store.create(&r).await.unwrap();
    let mut lease = store.claim().await.unwrap().unwrap();
    engine::begin_tool(
        &mut lease.run,
        &Authority {
            inactive_owned_browser: true,
            ..Authority::default()
        },
    )
    .unwrap();
    store.save(&mut lease).await.unwrap();
    let effect = lease.run.pending.as_ref().unwrap().id;
    sqlx::query("UPDATE rust_agent_runs SET lease_until=clock_timestamp()-interval '1 second'")
        .execute(&mut *store.connection)
        .await
        .unwrap();
    drop(c);
    let mut c = connection().await;
    let mut store = Store { connection: &mut c };
    let mut recovered = store.claim().await.unwrap().unwrap();
    engine::recover(&mut recovered.run);
    store.save(&mut recovered).await.unwrap();
    assert_eq!(recovered.run.state, State::OutcomeUnknown);
    assert_eq!(recovered.run.pending.as_ref().unwrap().id, effect);
    assert_eq!(recovered.run.usage.tool_calls, 1);
    store.release(&recovered).await.unwrap();
    assert!(store.claim().await.unwrap().is_none());
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn model_reservation_is_durable_before_provider_dispatch() {
    let mut c = setup().await;
    let mut store = Store { connection: &mut c };
    store.create(&run()).await.unwrap();
    let mut lease = store.claim().await.unwrap().unwrap();
    engine::begin_model(&mut lease.run).unwrap();
    store.save(&mut lease).await.unwrap();
    sqlx::query("UPDATE rust_agent_runs SET lease_until=clock_timestamp()-interval '1 second'")
        .execute(&mut *store.connection)
        .await
        .unwrap();
    drop(c);
    let mut c = connection().await;
    let mut store = Store { connection: &mut c };
    let mut recovered = store.claim().await.unwrap().unwrap();
    let charged = recovered.run.usage.reserved_tokens;
    engine::recover(&mut recovered.run);
    assert_eq!(recovered.run.usage.reserved_tokens, charged);
    assert_eq!(recovered.run.usage.model_calls, 1);
    assert_eq!(recovered.run.state, State::Ready);
}

struct FictionalModel {
    roles: Vec<Role>,
}
impl Model for FictionalModel {
    async fn propose(
        &mut self,
        role: Role,
        context: &[Context],
        _: ModelBudget,
        _: &mut Store<'_>,
    ) -> Result<Proposal> {
        self.roles.push(role);
        let name = match role {
            Role::Discovery => ToolName::SearchJobs,
            Role::Matching => ToolName::RankJobs,
            Role::Answers => ToolName::PrepareApplication,
            Role::Review => ToolName::InspectApplication,
            Role::Execution => ToolName::OpenBrowser,
        };
        if !context.iter().any(|c| c.tool == name) {
            return Ok(Proposal::Tool {
                call: ToolCall {
                    name,
                    job_id: Some(Uuid::from_u128(1)),
                    evidence: vec![],
                },
            });
        }
        Ok(match role.next() {
            Some(next) => Proposal::Handoff {
                next,
                evidence: context
                    .iter()
                    .flat_map(|c| c.evidence.clone())
                    .take(12)
                    .collect(),
            },
            None => Proposal::Complete { evidence: vec![] },
        })
    }
}
struct FictionalTools {
    calls: Vec<ToolName>,
}
impl Tools for FictionalTools {
    async fn authority(&mut self, _: &ToolCall, _: &mut Store<'_>) -> Result<Authority> {
        Ok(Authority {
            prepare: true,
            inactive_owned_browser: true,
            fill: false,
            telegram_paired: false,
        })
    }
    async fn execute(&mut self, effect: &Effect, _: &mut Store<'_>) -> Result<Observation> {
        self.calls.push(effect.call.name);
        let jobs = if matches!(effect.call.name, ToolName::SearchJobs | ToolName::RankJobs) {
            vec![Uuid::from_u128(1)]
        } else {
            vec![]
        };
        let mut evidence = vec![Uuid::new_v4()];
        evidence.extend(jobs.iter().copied());
        Ok(Observation {
            jobs,
            evidence,
            data: json!({"fixture":true}),
        })
    }
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn five_specialists_execute_a_durable_fictional_workflow() {
    let mut c = setup().await;
    let mut store = Store { connection: &mut c };
    let r = Run::new(
        Uuid::new_v4(),
        Limits {
            tokens: 8000,
            ..Limits::default()
        },
    )
    .unwrap();
    let id = store.create(&r).await.unwrap();
    let mut model = FictionalModel { roles: vec![] };
    let mut tools = FictionalTools { calls: vec![] };
    for _ in 0..24 {
        let Some(mut lease) = store.claim().await.unwrap() else {
            break;
        };
        tick(&mut store, &mut lease, &mut model, &mut tools)
            .await
            .unwrap();
    }
    let row = sqlx::query("SELECT run FROM rust_agent_runs WHERE id=$1")
        .bind(id)
        .fetch_one(&mut *store.connection)
        .await
        .unwrap();
    let final_run: Run = serde_json::from_value(row.get("run")).unwrap();
    assert_eq!(final_run.state, State::Completed);
    assert_eq!(final_run.usage.model_calls, 10);
    assert_eq!(final_run.usage.tool_calls, 5);
    assert_eq!(final_run.context.len(), 5);
    assert_eq!(
        tools.calls,
        vec![
            ToolName::SearchJobs,
            ToolName::RankJobs,
            ToolName::PrepareApplication,
            ToolName::InspectApplication,
            ToolName::OpenBrowser
        ]
    );
    for role in [
        Role::Discovery,
        Role::Matching,
        Role::Answers,
        Role::Review,
        Role::Execution,
    ] {
        assert!(model.roles.contains(&role));
    }
    let events: Value =
        sqlx::query_scalar("SELECT jsonb_agg(to_jsonb(e)) FROM rust_agent_events e")
            .fetch_one(&mut *store.connection)
            .await
            .unwrap();
    assert!(!events.to_string().contains("untrusted_data"));
    assert!(!events.to_string().contains("fictional-native-token"));
}
use serde_json::Value;

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn active_lease_caps_total_parallel_work_even_for_different_runs() {
    let mut c1 = setup().await;
    let mut c2 = connection().await;
    Store {
        connection: &mut c1,
    }
    .create(&run())
    .await
    .unwrap();
    Store {
        connection: &mut c1,
    }
    .create(&run())
    .await
    .unwrap();
    let mut s1 = Store {
        connection: &mut c1,
    };
    let mut s2 = Store {
        connection: &mut c2,
    };
    let (a, b) = tokio::join!(s1.claim(), s2.claim());
    assert_ne!(a.unwrap().is_some(), b.unwrap().is_some());
    let count: i64 =
        sqlx::query_scalar("SELECT count(*) FROM rust_agent_runs WHERE lease_token IS NOT NULL")
            .fetch_one(&mut c1)
            .await
            .unwrap();
    assert_eq!(count, 1);
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn client_role_cannot_read_private_context_even_if_select_is_granted() {
    let mut c = setup().await;
    Store { connection: &mut c }.create(&run()).await.unwrap();
    sqlx::raw_sql("CREATE ROLE rust_agent_untrusted NOLOGIN; GRANT USAGE ON SCHEMA public TO rust_agent_untrusted; GRANT SELECT ON rust_agent_runs,rust_agent_events TO rust_agent_untrusted; SET ROLE rust_agent_untrusted;").execute(&mut c).await.unwrap();
    let count: i64 = sqlx::query_scalar("SELECT count(*) FROM rust_agent_runs")
        .fetch_one(&mut c)
        .await
        .unwrap();
    assert_eq!(count, 0);
    let count: i64 = sqlx::query_scalar("SELECT count(*) FROM rust_agent_events")
        .fetch_one(&mut c)
        .await
        .unwrap();
    assert_eq!(count, 0);
    sqlx::raw_sql("RESET ROLE").execute(&mut c).await.unwrap();
    let count: i64 = sqlx::query_scalar("SELECT count(*) FROM rust_agent_runs")
        .fetch_one(&mut c)
        .await
        .unwrap();
    assert_eq!(count, 1);
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn audit_failure_blocks_provider_dispatch_without_partial_budget_write() {
    let mut c = setup().await;
    let mut store = Store { connection: &mut c };
    store.create(&run()).await.unwrap();
    let mut lease = store.claim().await.unwrap().unwrap();
    sqlx::raw_sql(
        "ALTER TABLE rust_agent_events ADD CONSTRAINT fixture_audit_failure CHECK (model_calls=0)",
    )
    .execute(&mut *store.connection)
    .await
    .unwrap();
    let mut model = FictionalModel { roles: vec![] };
    let mut tools = FictionalTools { calls: vec![] };
    assert_eq!(
        tick(&mut store, &mut lease, &mut model, &mut tools).await,
        Err(Failure("agent_database_error"))
    );
    assert!(model.roles.is_empty());
    assert!(tools.calls.is_empty());
    let value: Value = sqlx::query_scalar("SELECT run FROM rust_agent_runs")
        .fetch_one(&mut *store.connection)
        .await
        .unwrap();
    let saved: Run = serde_json::from_value(value).unwrap();
    assert_eq!(saved.usage.model_calls, 0);
    assert_eq!(saved.usage.reserved_tokens, 0);
    assert_eq!(saved.state, State::Ready);
}

use automated_apply_agents::monthly::{self, MonthlyPolicy};
fn monthly_policy() -> MonthlyPolicy {
    MonthlyPolicy {
        requests: 3,
        cohere_requests: 3,
        cohere_tokens: 1000000,
        reserved_input_bytes: 1000,
        reserved_output_tokens: 64,
    }
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn shared_provider_ledger_preserves_existing_count_and_never_refunds() {
    let mut c = setup().await;
    sqlx::raw_sql("INSERT INTO llm_monthly_usage(provider,month,requests)VALUES('cohere',to_char(clock_timestamp() AT TIME ZONE 'UTC','YYYY-MM'),2)").execute(&mut c).await.unwrap();
    let month = monthly::reserve(&mut c, monthly_policy()).await.unwrap();
    monthly::tokens(&mut c, &month, Some(5), Some(7))
        .await
        .unwrap();
    assert_eq!(
        monthly::reserve(&mut c, monthly_policy()).await.err(),
        Some(Failure("rate_limited"))
    );
    sqlx::raw_sql(
        "UPDATE llm_monthly_usage SET cooldown_until=clock_timestamp()-interval '1 second'",
    )
    .execute(&mut c)
    .await
    .unwrap();
    assert_eq!(
        monthly::reserve(&mut c, monthly_policy()).await.err(),
        Some(Failure("monthly_request_limit"))
    );
    let row = sqlx::query("SELECT requests,input_tokens,output_tokens FROM llm_monthly_usage")
        .fetch_one(&mut c)
        .await
        .unwrap();
    assert_eq!(row.get::<i32, _>("requests"), 3);
    assert_eq!(row.get::<i32, _>("input_tokens"), 5);
    assert_eq!(row.get::<i32, _>("output_tokens"), 7);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn provider_cooldown_survives_month_boundary() {
    let mut c = setup().await;
    sqlx::raw_sql("INSERT INTO llm_monthly_usage(provider,month,requests,cooldown_until)VALUES('cohere','1999-12',1,clock_timestamp()+interval '60 seconds')").execute(&mut c).await.unwrap();
    assert_eq!(
        monthly::reserve(&mut c, monthly_policy()).await.err(),
        Some(Failure("rate_limited"))
    );
    let count: i64 = sqlx::query_scalar("SELECT count(*) FROM llm_monthly_usage")
        .fetch_one(&mut c)
        .await
        .unwrap();
    assert_eq!(count, 1);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn concurrent_provider_reservations_share_one_cooldown_and_cap() {
    let mut c1 = setup().await;
    let mut c2 = connection().await;
    let (a, b) = tokio::join!(
        monthly::reserve(&mut c1, monthly_policy()),
        monthly::reserve(&mut c2, monthly_policy())
    );
    assert_ne!(a.is_ok(), b.is_ok());
    let count: i32 = sqlx::query_scalar("SELECT requests FROM llm_monthly_usage")
        .fetch_one(&mut c1)
        .await
        .unwrap();
    assert_eq!(count, 1);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn unknown_provider_result_retains_request_after_connection_restart() {
    let mut c = setup().await;
    monthly::reserve(&mut c, monthly_policy()).await.unwrap();
    drop(c);
    let mut c = connection().await;
    let count: i32 = sqlx::query_scalar("SELECT requests FROM llm_monthly_usage")
        .fetch_one(&mut c)
        .await
        .unwrap();
    assert_eq!(count, 1);
    assert_eq!(
        monthly::reserve(&mut c, monthly_policy()).await.err(),
        Some(Failure("rate_limited"))
    );
    sqlx::raw_sql(
        "UPDATE llm_monthly_usage SET cooldown_until=clock_timestamp()-interval '1 second'",
    )
    .execute(&mut c)
    .await
    .unwrap();
    let month = monthly::reserve(&mut c, monthly_policy()).await.unwrap();
    monthly::cooldown(&mut c, &month, 120).await.unwrap();
    let seconds:f64=sqlx::query_scalar("SELECT EXTRACT(EPOCH FROM cooldown_until-clock_timestamp())::double precision FROM llm_monthly_usage").fetch_one(&mut c).await.unwrap();
    assert!(seconds > 115.0);
}

use automated_apply_agents::knowledge::{self, ProfilePin};
async fn knowledge_fixture() -> PgConnection {
    let mut c = setup().await;
    sqlx::raw_sql(include_str!("fixtures/knowledge.sql"))
        .execute(&mut c)
        .await
        .unwrap();
    let _: Value = sqlx::query_scalar(include_str!("../sql/saved_naukri.sql"))
        .fetch_one(&mut c)
        .await
        .expect("fictional source SQL contract");
    c
}
fn profile_pin() -> ProfilePin {
    ProfilePin {
        id: Uuid::from_u128(2),
        version: 4,
    }
}
async fn saved_job(c: &mut PgConnection, index: u128) -> Uuid {
    let id = Uuid::from_u128(1000 + index);
    sqlx::query("INSERT INTO jobs(id,title,job_url)VALUES($1,'Rust Developer',$2)")
        .bind(id)
        .bind(format!(
            "https://www.naukri.com/job-listings-fictional-role-{:012}",
            index
        ))
        .execute(c)
        .await
        .unwrap();
    id
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn knowledge_profile_confirmation_is_version_bound_and_omits_identity() {
    let mut c = knowledge_fixture().await;
    let profile = knowledge::reviewed_profile(&mut c).await.unwrap().unwrap();
    assert_eq!(profile.pin.version, 4);
    assert_eq!(profile.facts.verified_skills, vec!["Rust"]);
    let encoded = serde_json::to_string(&profile.facts).unwrap();
    for private in [
        "Private Fictional Name",
        "private-fictional@example.com",
        "fictional-phone-value",
        "current_compensation",
    ] {
        assert!(!encoded.contains(private));
    }
    sqlx::raw_sql("UPDATE candidate_profiles SET version=5")
        .execute(&mut c)
        .await
        .unwrap();
    assert!(knowledge::reviewed_profile(&mut c).await.unwrap().is_none());
    assert_eq!(
        knowledge::rank_saved_naukri(&mut c, &profile_pin(), 10)
            .await
            .err(),
        Some(Failure("profile_review_required"))
    );
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn knowledge_ranking_uses_actual_saved_facts_and_rejects_a_stale_pin() {
    let mut c = knowledge_fixture().await;
    let id = saved_job(&mut c, 1).await;
    let result = knowledge::rank_saved_naukri(&mut c, &profile_pin(), 10)
        .await
        .unwrap();
    assert_eq!(result.scanned, 1);
    assert_eq!(result.jobs.len(), 1);
    assert_eq!(result.jobs[0].job_id, id);
    assert_eq!(result.jobs[0].ranking.match_score, 100.0);
    assert!(
        result.jobs[0]
            .ranking
            .unknown_fields
            .contains(&"company_size".into())
    );
    assert!(result.scope.contains("not_application_admission"));
    assert_eq!(
        knowledge::rank_saved_naukri(
            &mut c,
            &ProfilePin {
                id: Uuid::from_u128(2),
                version: 3
            },
            10
        )
        .await
        .err(),
        Some(Failure("verified_profile_context_changed"))
    );
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn knowledge_replay_fences_cover_unknown_packets_damaged_receipts_and_admissions() {
    let mut c = knowledge_fixture().await;
    for i in 1..=8 {
        saved_job(&mut c, i).await;
    }
    sqlx::query("UPDATE jobs SET status='applied' WHERE id=$1")
        .bind(Uuid::from_u128(1001))
        .execute(&mut c)
        .await
        .unwrap();
    sqlx::query("INSERT INTO application_packets(id,job_id,candidate_profile_id,lifecycle_state)VALUES($1,$2,$3,'submission_unknown')").bind(Uuid::from_u128(2002)).bind(Uuid::from_u128(1002)).bind(Uuid::from_u128(2)).execute(&mut c).await.unwrap();
    sqlx::raw_sql("INSERT INTO owner_preferences VALUES('naukri_receipt:000000000003','{}'),('naukri_worker_receipt:000000000004','{}'),('apply_work:fictional','{\"job_id\":\"00000000-0000-0000-0000-0000000003ed\",\"stage\":\"SUBMISSION_UNKNOWN\",\"admitted_actions\":[\"apply\"]}')").execute(&mut c).await.unwrap();
    sqlx::query("UPDATE jobs SET discovery_metadata='{\"data_provenance\":{\"posting_status\":\"already_applied\"}}' WHERE id=$1").bind(Uuid::from_u128(1006)).execute(&mut c).await.unwrap();
    sqlx::raw_sql("INSERT INTO owner_preferences VALUES('gmail_application:fictional','{\"confirmed_application\":true,\"job_url\":\"https://www.naukri.com/job-listings-fictional-role-000000000007?tracking=fixture\",\"expires_at\":\"2030-01-01T00:00:00+00:00\"}')").execute(&mut c).await.unwrap();
    let result = knowledge::rank_saved_naukri(&mut c, &profile_pin(), 10)
        .await
        .unwrap();
    assert_eq!(result.scanned, 8);
    assert_eq!(result.excluded_prior_or_unknown, 7);
    assert_eq!(result.jobs.len(), 1);
    assert_eq!(result.jobs[0].job_id, Uuid::from_u128(1008));
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn knowledge_same_requisition_and_company_history_fence_distinct_saved_ids() {
    let mut c = knowledge_fixture().await;
    let first = saved_job(&mut c, 1).await;
    let second = saved_job(&mut c, 2).await;
    let third = saved_job(&mut c, 3).await;
    sqlx::query("UPDATE jobs SET job_url='https://www.naukri.com/job-listings-alias-role-000000000001?tracking=fixture' WHERE id=$1").bind(second).execute(&mut c).await.unwrap();
    sqlx::query("INSERT INTO application_packets(id,job_id,candidate_profile_id,lifecycle_state)VALUES($1,$2,$3,'submitting')").bind(Uuid::from_u128(2001)).bind(first).bind(Uuid::from_u128(2)).execute(&mut c).await.unwrap();
    sqlx::raw_sql("INSERT INTO companies(id,name)VALUES('00000000-0000-0000-0000-000000000005','Fictional Company')").execute(&mut c).await.unwrap();
    sqlx::query("UPDATE jobs SET company_id=$1 WHERE id=$2")
        .bind(Uuid::from_u128(5))
        .bind(third)
        .execute(&mut c)
        .await
        .unwrap();
    let prior = saved_job(&mut c, 4).await;
    sqlx::query("UPDATE jobs SET company_id=$1,status='applied' WHERE id=$2")
        .bind(Uuid::from_u128(5))
        .bind(prior)
        .execute(&mut c)
        .await
        .unwrap();
    let result = knowledge::rank_saved_naukri(&mut c, &profile_pin(), 10)
        .await
        .unwrap();
    assert_eq!(result.jobs.len(), 0);
    assert_eq!(result.excluded_prior_or_unknown, 4);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn knowledge_scan_and_history_are_bounded_without_other_profile_data() {
    let mut c = knowledge_fixture().await;
    for i in 1..=105 {
        saved_job(&mut c, i).await;
    }
    let result = knowledge::rank_saved_naukri(&mut c, &profile_pin(), 10)
        .await
        .unwrap();
    assert_eq!(result.scanned, 100);
    assert_eq!(result.jobs.len(), 10);
    assert_eq!(result.jobs[0].job_id, Uuid::from_u128(1001));
    sqlx::raw_sql("INSERT INTO application_packets SELECT (lpad(to_hex(i),32,'0'))::uuid,'00000000-0000-0000-0000-0000000003e9','00000000-0000-0000-0000-000000000002','created','needs_input',clock_timestamp() FROM generate_series(3001,3015) i").execute(&mut c).await.unwrap();
    sqlx::raw_sql("INSERT INTO application_packets VALUES('00000000-0000-0000-0000-000000009999','00000000-0000-0000-0000-0000000003e9','00000000-0000-0000-0000-000000000099','created','private_other_profile',clock_timestamp())").execute(&mut c).await.unwrap();
    let history = knowledge::application_history(&mut c, &profile_pin())
        .await
        .unwrap();
    assert_eq!(history["applications"].as_array().unwrap().len(), 10);
    assert!(!history.to_string().contains("private_other_profile"));
    assert_eq!(
        knowledge::rank_saved_naukri(&mut c, &profile_pin(), 11)
            .await
            .err(),
        Some(Failure("invalid_saved_result_limit"))
    );
}

use automated_apply_agents::knowledge_tools::KnowledgeTools;
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn actual_knowledge_tools_bind_database_jobs_and_refuse_unmigrated_actions() {
    let mut c = knowledge_fixture().await;
    let job = saved_job(&mut c, 1).await;
    let mut store = Store { connection: &mut c };
    let mut tools = KnowledgeTools {
        profile: profile_pin(),
    };
    let effect = Effect {
        id: Uuid::new_v4(),
        call: ToolCall {
            name: ToolName::SearchJobs,
            job_id: None,
            evidence: vec![],
        },
    };
    assert!(tools.authority(&effect.call, &mut store).await.is_ok());
    let result = tools.execute(&effect, &mut store).await.unwrap();
    assert_eq!(result.jobs, vec![job]);
    assert!(result.evidence.contains(&job));
    assert_eq!(result.data["jobs"][0]["job_id"], job.to_string());
    let call = ToolCall {
        name: ToolName::PrepareApplication,
        job_id: Some(job),
        evidence: vec![job],
    };
    assert_eq!(
        tools.authority(&call, &mut store).await.err(),
        Some(Failure("tool_adapter_not_migrated"))
    );
    sqlx::raw_sql("UPDATE candidate_profiles SET version=5")
        .execute(&mut *store.connection)
        .await
        .unwrap();
    assert_eq!(
        tools.authority(&effect.call, &mut store).await.err(),
        Some(Failure("profile_review_required"))
    );
}

struct KnowledgePlan;
impl Model for KnowledgePlan {
    async fn propose(
        &mut self,
        role: Role,
        context: &[Context],
        _: ModelBudget,
        _: &mut Store<'_>,
    ) -> Result<Proposal> {
        let tool = match role {
            Role::Discovery => ToolName::SearchJobs,
            Role::Matching => ToolName::RankJobs,
            Role::Answers => ToolName::VerifiedContext,
            _ => return Err(Failure("fixture_unexpected_role")),
        };
        if !context.iter().any(|c| c.tool == tool) {
            return Ok(Proposal::Tool {
                call: ToolCall {
                    name: tool,
                    job_id: None,
                    evidence: vec![],
                },
            });
        }
        if role == Role::Answers {
            let saved = context
                .iter()
                .find(|c| c.tool == ToolName::RankJobs)
                .unwrap();
            let id: Uuid =
                serde_json::from_value(saved.untrusted_data["jobs"][0]["job_id"].clone()).unwrap();
            return Ok(Proposal::Tool {
                call: ToolCall {
                    name: ToolName::PrepareApplication,
                    job_id: Some(id),
                    evidence: vec![id],
                },
            });
        }
        Ok(Proposal::Handoff {
            next: role.next().unwrap(),
            evidence: vec![],
        })
    }
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn durable_coordinator_consumes_real_postgres_tool_outputs_before_any_application_work() {
    let mut c = knowledge_fixture().await;
    let job = saved_job(&mut c, 1).await;
    let mut store = Store { connection: &mut c };
    let mut run = run();
    run.profile = Some(profile_pin());
    let id = store.create(&run).await.unwrap();
    let mut model = KnowledgePlan;
    let mut tools = KnowledgeTools {
        profile: profile_pin(),
    };
    for _ in 0..20 {
        let Some(mut lease) = store.claim().await.unwrap() else {
            break;
        };
        tick(&mut store, &mut lease, &mut model, &mut tools)
            .await
            .unwrap();
    }
    let saved: Value = sqlx::query_scalar("SELECT run FROM rust_agent_runs WHERE id=$1")
        .bind(id)
        .fetch_one(&mut *store.connection)
        .await
        .unwrap();
    let run: Run = serde_json::from_value(saved).unwrap();
    assert_eq!(run.known_jobs, vec![job]);
    assert_eq!(run.usage.tool_calls, 3);
    assert_eq!(run.context.len(), 3);
    assert_eq!(run.state, State::Failed);
    assert_eq!(run.diagnostic.as_deref(), Some("tool_adapter_not_migrated"));
    let packets: i64 = sqlx::query_scalar("SELECT count(*) FROM application_packets")
        .fetch_one(&mut *store.connection)
        .await
        .unwrap();
    assert_eq!(packets, 0);
}
