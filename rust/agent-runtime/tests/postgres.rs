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
    sqlx::raw_sql("DROP TABLE IF EXISTS rust_agent_control_events; DROP TABLE IF EXISTS rust_agent_control; DROP TABLE IF EXISTS rust_agent_events; DROP TABLE IF EXISTS rust_agent_runs; DROP TABLE IF EXISTS llm_monthly_usage;")
        .execute(&mut c)
        .await
        .unwrap();
    sqlx::raw_sql(include_str!("../sql/001_runtime.sql"))
        .execute(&mut c)
        .await
        .unwrap();
    sqlx::raw_sql(include_str!("../sql/002_control.sql"))
        .execute(&mut c)
        .await
        .unwrap();
    sqlx::raw_sql(include_str!("../sql/004_graph.sql"))
        .execute(&mut c)
        .await
        .unwrap();
    sqlx::raw_sql("UPDATE rust_agent_control SET mode='RUNNING'")
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
    // Pre-graph records omitted new default fields. Idempotency must not create a
    // second run or refund the old record's spent allowance during an upgrade.
    sqlx::query("UPDATE rust_agent_runs SET run=(run-'graph') #- '{limits,human_review}' #- '{limits,replans}' WHERE id=$1").bind(id).execute(&mut *store.connection).await.unwrap();
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
            requires_human_approval: false,
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
    for malformed in [json!(false), json!(0), json!([]), json!({}), json!("")] {
        sqlx::query("UPDATE owner_preferences SET value=jsonb_set(value,'{confirmed_at}',$1) WHERE key='phase1_profile_confirmation'").bind(malformed).execute(&mut c).await.unwrap();
        assert!(knowledge::reviewed_profile(&mut c).await.unwrap().is_none());
    }
    sqlx::raw_sql("UPDATE owner_preferences SET value=jsonb_set(value,'{confirmed_at}','\"2026-11-14T00:00:00Z\"') WHERE key='phase1_profile_confirmation'").execute(&mut c).await.unwrap();
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

use automated_apply_agents::{
    lifecycle::{self, Action, Mode},
    worker::{self, Wake},
};
use std::time::Duration;
use tokio_util::sync::CancellationToken;

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn additive_control_migration_defaults_to_stopped_and_requires_revision() {
    let mut c = setup().await;
    sqlx::raw_sql("UPDATE rust_agent_control SET mode='STOPPED'")
        .execute(&mut c)
        .await
        .unwrap();
    Store { connection: &mut c }.create(&run()).await.unwrap();
    assert!(
        Store { connection: &mut c }
            .claim()
            .await
            .unwrap()
            .is_none()
    );
    let state = lifecycle::control(&mut c).await.unwrap();
    assert_eq!(state.mode, Mode::Stopped);
    assert!(!state.worker_online);
    assert_eq!(
        lifecycle::set_control(&mut c, 2, Mode::Running).await.err(),
        Some(Failure("agent_control_revision_conflict"))
    );
    let audit: i64 = sqlx::query_scalar("SELECT count(*) FROM rust_agent_control_events")
        .fetch_one(&mut c)
        .await
        .unwrap();
    assert_eq!(audit, 1);
    let state = lifecycle::set_control(&mut c, 1, Mode::Running)
        .await
        .unwrap();
    assert_eq!(state.revision, 2);
    assert!(
        Store { connection: &mut c }
            .claim()
            .await
            .unwrap()
            .is_some()
    );
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn global_pause_fences_inference_and_retains_budget_across_resume() {
    let mut c = setup().await;
    let initial = run();
    Store { connection: &mut c }.create(&initial).await.unwrap();
    let mut lease = Store { connection: &mut c }.claim().await.unwrap().unwrap();
    engine::begin_model(&mut lease.run).unwrap();
    Store { connection: &mut c }.save(&mut lease).await.unwrap();
    let reserved = lease.run.usage.reserved_tokens;
    let paused = lifecycle::set_control(&mut c, 1, Mode::Paused)
        .await
        .unwrap();
    let saved = lifecycle::load(&mut c, initial.id).await.unwrap();
    assert_eq!(saved.run.state, State::Paused);
    assert_eq!(saved.run.resume_state, Some(State::Ready));
    assert_eq!(saved.run.usage.reserved_tokens, reserved);
    assert_eq!(
        Store { connection: &mut c }.save(&mut lease).await,
        Err(Failure("agent_lease_or_revision_lost"))
    );
    assert!(
        Store { connection: &mut c }
            .claim()
            .await
            .unwrap()
            .is_none()
    );
    lifecycle::set_control(&mut c, paused.revision, Mode::Running)
        .await
        .unwrap();
    assert_eq!(
        Store { connection: &mut c }.save(&mut lease).await,
        Err(Failure("agent_lease_or_revision_lost"))
    );
    let next = Store { connection: &mut c }.claim().await.unwrap().unwrap();
    assert_eq!(next.run.usage.model_calls, 1);
    assert_eq!(next.run.usage.decision_calls, 1);
    assert_eq!(next.run.usage.reserved_tokens, reserved);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn manual_pause_is_not_resumed_by_global_start_and_stale_control_is_rejected() {
    let mut c = setup().await;
    let r = run();
    Store { connection: &mut c }.create(&r).await.unwrap();
    let paused = lifecycle::control_run(&mut c, r.id, 1, Action::Pause)
        .await
        .unwrap();
    assert_eq!(
        lifecycle::control_run(&mut c, r.id, 1, Action::Resume)
            .await
            .err(),
        Some(Failure("agent_revision_conflict"))
    );
    lifecycle::set_control(&mut c, 1, Mode::Stopped)
        .await
        .unwrap();
    lifecycle::set_control(&mut c, 2, Mode::Running)
        .await
        .unwrap();
    assert!(
        Store { connection: &mut c }
            .claim()
            .await
            .unwrap()
            .is_none()
    );
    let same = lifecycle::load(&mut c, r.id).await.unwrap();
    assert_eq!(same.revision, paused.revision);
    assert!(!same.run.paused_by_global);
    lifecycle::control_run(&mut c, r.id, same.revision, Action::Resume)
        .await
        .unwrap();
    assert!(
        Store { connection: &mut c }
            .claim()
            .await
            .unwrap()
            .is_some()
    );
}
fn running_browser() -> Run {
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
    engine::begin_tool(
        &mut r,
        &Authority {
            inactive_owned_browser: true,
            ..Authority::default()
        },
    )
    .unwrap();
    r
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn stop_quarantines_dispatched_actions_and_never_refunds_or_replays_them() {
    let mut c = setup().await;
    let original = running_browser();
    let effect = original.pending.as_ref().unwrap().id;
    Store { connection: &mut c }
        .create(&original)
        .await
        .unwrap();
    let lease = Store { connection: &mut c }.claim().await.unwrap().unwrap();
    lifecycle::set_control(&mut c, 1, Mode::Stopped)
        .await
        .unwrap();
    let saved = lifecycle::load(&mut c, original.id).await.unwrap();
    assert_eq!(saved.run.state, State::OutcomeUnknown);
    assert_eq!(saved.run.pending.as_ref().unwrap().id, effect);
    assert_eq!(saved.run.usage.tool_calls, 1);
    assert_eq!(
        saved.run.usage.reserved_tokens,
        original.usage.reserved_tokens
    );
    let stopped = lifecycle::control_run(&mut c, original.id, saved.revision, Action::Stop)
        .await
        .unwrap();
    assert_eq!(stopped.run.state, State::OutcomeUnknown);
    assert_eq!(
        Store { connection: &mut c }.release(&lease).await,
        Err(Failure("agent_lease_or_revision_lost"))
    );
    lifecycle::set_control(&mut c, 2, Mode::Running)
        .await
        .unwrap();
    assert!(
        Store { connection: &mut c }
            .claim()
            .await
            .unwrap()
            .is_none()
    );
    assert_eq!(
        lifecycle::control_run(&mut c, original.id, stopped.revision, Action::Resume)
            .await
            .err(),
        Some(Failure("invalid_agent_control"))
    );
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn interrupted_read_retains_effect_and_counts_each_real_dispatch() {
    let mut c = setup().await;
    let mut r = run();
    engine::begin_model(&mut r).unwrap();
    engine::accept(
        &mut r,
        Proposal::Tool {
            call: ToolCall {
                name: ToolName::SearchJobs,
                job_id: None,
                evidence: vec![],
            },
        },
    )
    .unwrap();
    let effect = engine::begin_tool(&mut r, &Authority::default())
        .unwrap()
        .id;
    Store { connection: &mut c }.create(&r).await.unwrap();
    Store { connection: &mut c }.claim().await.unwrap().unwrap();
    lifecycle::set_control(&mut c, 1, Mode::Paused)
        .await
        .unwrap();
    lifecycle::set_control(&mut c, 2, Mode::Running)
        .await
        .unwrap();
    let mut next = Store { connection: &mut c }.claim().await.unwrap().unwrap();
    assert_eq!(next.run.state, State::ToolPending);
    assert_eq!(
        engine::begin_tool(&mut next.run, &Authority::default())
            .unwrap()
            .id,
        effect
    );
    assert_eq!(next.run.usage.tool_calls, 2);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn control_audit_failure_rolls_back_mode_and_run_fence_together() {
    let mut c = setup().await;
    let r = run();
    Store { connection: &mut c }.create(&r).await.unwrap();
    let mut lease = Store { connection: &mut c }.claim().await.unwrap().unwrap();
    sqlx::raw_sql(
        "ALTER TABLE rust_agent_control_events ADD CONSTRAINT fixture_failure CHECK(revision<2)",
    )
    .execute(&mut c)
    .await
    .unwrap();
    assert_eq!(
        lifecycle::set_control(&mut c, 1, Mode::Stopped).await.err(),
        Some(Failure("agent_database_error"))
    );
    assert_eq!(
        lifecycle::control(&mut c).await.unwrap().mode,
        Mode::Running
    );
    Store { connection: &mut c }.save(&mut lease).await.unwrap();
}
async fn waiting_fact(c: &mut PgConnection, key: &str) -> Run {
    let mut r = run();
    r.profile = Some(profile_pin());
    engine::begin_model(&mut r).unwrap();
    engine::accept(
        &mut r,
        Proposal::NeedsInput {
            question_key: key.into(),
        },
    )
    .unwrap();
    Store { connection: c }.create(&r).await.unwrap();
    r
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn owner_question_uses_confirmed_saved_fact_and_retains_prior_spend() {
    let mut c = knowledge_fixture().await;
    let r = waiting_fact(&mut c, "notice_period_days").await;
    let question = r.question.as_ref().unwrap().id;
    assert_eq!(lifecycle::pending_questions(&mut c).await.unwrap().len(), 1);
    assert_eq!(
        lifecycle::resolve_question(&mut c, r.id, 1, question, &profile_pin())
            .await
            .err(),
        Some(Failure("owner_fact_not_confirmed"))
    );
    sqlx::raw_sql("UPDATE candidate_profiles SET version=5,preferences=preferences||'{\"notice_period_days\":0}'").execute(&mut c).await.unwrap();
    assert_eq!(
        lifecycle::resolve_question(&mut c, r.id, 1, question, &profile_pin())
            .await
            .err(),
        Some(Failure("owner_fact_not_confirmed"))
    );
    sqlx::raw_sql("UPDATE owner_preferences SET value=jsonb_set(value,'{profile_version}','5')")
        .execute(&mut c)
        .await
        .unwrap();
    assert_eq!(
        lifecycle::resolve_question(&mut c, r.id, 1, question, &profile_pin())
            .await
            .err(),
        Some(Failure("verified_profile_context_changed"))
    );
    let pin = ProfilePin {
        version: 5,
        ..profile_pin()
    };
    let saved = lifecycle::resolve_question(&mut c, r.id, 1, question, &pin)
        .await
        .unwrap();
    assert_eq!(saved.run.state, State::Ready);
    assert!(saved.run.question.is_none());
    assert_eq!(saved.run.usage.model_calls, 1);
    assert_eq!(saved.run.usage.reserved_tokens, r.usage.reserved_tokens);
    assert_eq!(saved.run.profile.as_ref().unwrap().version, 5);
    assert_eq!(
        lifecycle::resolve_question(&mut c, r.id, saved.revision, question, &pin)
            .await
            .err(),
        Some(Failure("agent_question_not_pending"))
    );
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn known_facts_are_not_asked_again_and_reconcile_without_an_owner_action() {
    let mut c = knowledge_fixture().await;
    let r = waiting_fact(&mut c, "notice_period_days").await;
    sqlx::raw_sql(
        "UPDATE candidate_profiles SET preferences=preferences||'{\"notice_period_days\":false}'",
    )
    .execute(&mut c)
    .await
    .unwrap();
    assert_eq!(
        lifecycle::reconcile_known_questions(&mut c).await.unwrap(),
        0
    );
    sqlx::raw_sql(
        "UPDATE candidate_profiles SET preferences=preferences||'{\"notice_period_days\":30}'",
    )
    .execute(&mut c)
    .await
    .unwrap();
    assert!(
        lifecycle::pending_questions(&mut c)
            .await
            .unwrap()
            .is_empty()
    );
    lifecycle::set_control(&mut c, 1, Mode::Stopped)
        .await
        .unwrap();
    assert_eq!(
        lifecycle::reconcile_known_questions(&mut c).await.unwrap(),
        0
    );
    lifecycle::set_control(&mut c, 2, Mode::Running)
        .await
        .unwrap();
    assert_eq!(
        lifecycle::reconcile_known_questions(&mut c).await.unwrap(),
        1
    );
    assert_eq!(
        lifecycle::load(&mut c, r.id).await.unwrap().run.state,
        State::Ready
    );
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn fact_resolution_rejects_unknown_question_identity_switch_and_uncertain_actions() {
    let mut c = knowledge_fixture().await;
    let mut r = waiting_fact(&mut c, "profile_review_required").await;
    let q = r.question.as_ref().unwrap().id;
    assert_eq!(
        lifecycle::resolve_question(&mut c, r.id, 1, Uuid::new_v4(), &profile_pin())
            .await
            .err(),
        Some(Failure("agent_question_not_pending"))
    );
    r.profile = Some(ProfilePin {
        id: Uuid::from_u128(3),
        version: 4,
    });
    sqlx::query("UPDATE rust_agent_runs SET run=$1 WHERE id=$2")
        .bind(serde_json::to_value(&r).unwrap())
        .bind(r.id)
        .execute(&mut c)
        .await
        .unwrap();
    assert_eq!(
        lifecycle::resolve_question(&mut c, r.id, 1, q, &profile_pin())
            .await
            .err(),
        Some(Failure("verified_profile_identity_changed"))
    );
    r.profile = Some(profile_pin());
    r.pending = running_browser().pending;
    sqlx::query("UPDATE rust_agent_runs SET run=$1 WHERE id=$2")
        .bind(serde_json::to_value(&r).unwrap())
        .bind(r.id)
        .execute(&mut c)
        .await
        .unwrap();
    assert_eq!(
        lifecycle::resolve_question(&mut c, r.id, 1, q, &profile_pin())
            .await
            .err(),
        Some(Failure("agent_reconciliation_required"))
    );
    assert_eq!(
        lifecycle::reconcile_known_questions(&mut c).await.unwrap(),
        0
    );
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn intake_waits_for_profile_and_request_replay_cannot_change_profile_identity() {
    let mut c = knowledge_fixture().await;
    sqlx::raw_sql("UPDATE owner_preferences SET value=value-'confirmed_at'")
        .execute(&mut c)
        .await
        .unwrap();
    let key = Uuid::new_v4();
    let first = lifecycle::intake(&mut c, key, Limits::default())
        .await
        .unwrap();
    assert_eq!(first.run.state, State::WaitingOwner);
    let same = lifecycle::intake(&mut c, key, Limits::default())
        .await
        .unwrap();
    assert_eq!(same.run.id, first.run.id);
    sqlx::raw_sql(
        "UPDATE owner_preferences SET value=value||'{\"confirmed_at\":\"2026-11-14T00:00:00Z\"}'",
    )
    .execute(&mut c)
    .await
    .unwrap();
    assert_eq!(
        lifecycle::intake(&mut c, key, Limits::default())
            .await
            .err(),
        Some(Failure("agent_request_key_conflict"))
    );
    assert_eq!(
        lifecycle::reconcile_known_questions(&mut c).await.unwrap(),
        1
    );
    assert!(
        lifecycle::load(&mut c, first.run.id)
            .await
            .unwrap()
            .run
            .profile
            == Some(profile_pin())
    );
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn actual_worker_completes_saved_review_with_four_reads_and_no_inference() {
    let mut c = knowledge_fixture().await;
    saved_job(&mut c, 1).await;
    let first = lifecycle::intake(&mut c, Uuid::new_v4(), Limits::default())
        .await
        .unwrap();
    let mut worker_connection = connection().await;
    let wake = Wake::default();
    let stop = CancellationToken::new();
    let monitor = async {
        tokio::time::timeout(Duration::from_secs(5), async {
            loop {
                let saved = lifecycle::load(&mut c, first.run.id).await.unwrap();
                if saved.run.state == State::Completed {
                    assert_eq!(saved.run.usage.decision_calls, 9);
                    assert_eq!(saved.run.usage.tool_calls, 4);
                    assert_eq!(saved.run.usage.model_calls, 0);
                    assert_eq!(saved.run.usage.reserved_tokens, 0);
                    assert_eq!(saved.run.context.len(), 4);
                    assert!(lifecycle::control(&mut c).await.unwrap().worker_online);
                    let public = lifecycle::summary(&saved).to_string();
                    assert!(public.contains("saved_job_review_no_application_dispatch"));
                    assert!(!public.contains("Private Fictional"));
                    break;
                }
                assert_ne!(saved.run.state, State::Failed, "{:?}", saved.run.diagnostic);
                tokio::time::sleep(Duration::from_millis(5)).await;
            }
        })
        .await
        .unwrap();
        stop.cancel();
    };
    let (result, _) = tokio::join!(
        worker::serve(&mut worker_connection, wake, stop.clone()),
        monitor
    );
    result.unwrap();
    assert_eq!(lifecycle::control(&mut c).await.unwrap().mode, Mode::Paused);
    let provider_requests: i64 = sqlx::query_scalar("SELECT count(*) FROM llm_monthly_usage")
        .fetch_one(&mut c)
        .await
        .unwrap();
    assert_eq!(provider_requests, 0);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn stopped_worker_sleeps_and_wakes_on_committed_owner_start() {
    let mut c = knowledge_fixture().await;
    lifecycle::set_control(&mut c, 1, Mode::Stopped)
        .await
        .unwrap();
    let first = lifecycle::intake(&mut c, Uuid::new_v4(), Limits::default())
        .await
        .unwrap();
    let mut wc = connection().await;
    let wake = Wake::default();
    let stop = CancellationToken::new();
    let owner = async {
        tokio::time::sleep(Duration::from_millis(25)).await;
        let saved = lifecycle::load(&mut c, first.run.id).await.unwrap();
        assert_eq!(saved.run.state, State::Ready);
        assert_eq!(saved.run.usage.decision_calls, 0);
        lifecycle::set_control(&mut c, 2, Mode::Running)
            .await
            .unwrap();
        wake.controls_changed();
        tokio::time::timeout(Duration::from_secs(2), async {
            loop {
                if lifecycle::load(&mut c, first.run.id)
                    .await
                    .unwrap()
                    .run
                    .state
                    == State::Completed
                {
                    break;
                }
                tokio::time::sleep(Duration::from_millis(5)).await;
            }
        })
        .await
        .unwrap();
        stop.cancel();
    };
    let (result, _) = tokio::join!(worker::serve(&mut wc, wake.clone(), stop.clone()), owner);
    result.unwrap();
}

struct BlockedModel {
    started: std::sync::Arc<tokio::sync::Notify>,
}
impl Model for BlockedModel {
    async fn propose(
        &mut self,
        _: Role,
        _: &[Context],
        _: ModelBudget,
        _: &mut Store<'_>,
    ) -> Result<Proposal> {
        self.started.notify_one();
        std::future::pending().await
    }
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn committed_stop_remains_responsive_during_a_blocked_model_call() {
    let mut owner = setup().await;
    let r = run();
    Store {
        connection: &mut owner,
    }
    .create(&r)
    .await
    .unwrap();
    let mut wc = connection().await;
    let started = std::sync::Arc::new(tokio::sync::Notify::new());
    let cancelled = CancellationToken::new();
    let mut model = BlockedModel {
        started: started.clone(),
    };
    let worker = async {
        let mut store = Store {
            connection: &mut wc,
        };
        let mut lease = store.claim().await.unwrap().unwrap();
        let mut tools = FictionalTools { calls: vec![] };
        tokio::select! {
            biased;
            _=cancelled.cancelled()=>{},
            result=tick(&mut store,&mut lease,&mut model,&mut tools)=>panic!("blocked call unexpectedly finished: {result:?}"),
        }
        assert_eq!(
            store.save(&mut lease).await,
            Err(Failure("agent_lease_or_revision_lost"))
        );
    };
    let control = async {
        tokio::time::timeout(Duration::from_secs(2), started.notified())
            .await
            .unwrap();
        // Stop has a separate borrowed owner connection and never waits for the model.
        tokio::time::timeout(
            Duration::from_secs(1),
            lifecycle::set_control(&mut owner, 1, Mode::Stopped),
        )
        .await
        .unwrap()
        .unwrap();
        let saved = lifecycle::load(&mut owner, r.id).await.unwrap();
        assert_eq!(saved.run.state, State::Paused);
        assert_eq!(saved.run.usage.model_calls, 1);
        assert!(saved.run.usage.reserved_tokens > 0);
        cancelled.cancel();
    };
    tokio::join!(worker, control);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn control_and_audit_tables_reject_a_public_client_even_with_select_granted() {
    let mut c = setup().await;
    sqlx::raw_sql("DO $body$ BEGIN IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='rust_fixture_client')THEN CREATE ROLE rust_fixture_client; END IF; END $body$; GRANT SELECT ON rust_agent_control,rust_agent_control_events TO rust_fixture_client; SET ROLE rust_fixture_client;").execute(&mut c).await.unwrap();
    for query in [
        "SELECT count(*) FROM rust_agent_control",
        "SELECT count(*) FROM rust_agent_control_events",
    ] {
        let count: i64 = sqlx::query_scalar(query).fetch_one(&mut c).await.unwrap();
        assert_eq!(count, 0);
    }
    sqlx::raw_sql("RESET ROLE").execute(&mut c).await.unwrap();
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn missing_older_facts_do_not_starve_a_later_known_question() {
    let mut c = knowledge_fixture().await;
    for _ in 0..10 {
        waiting_fact(&mut c, "notice_period_days").await;
    }
    let known = waiting_fact(&mut c, "profile_review_required").await;
    assert_eq!(
        lifecycle::reconcile_known_questions(&mut c).await.unwrap(),
        0
    );
    assert_eq!(
        lifecycle::reconcile_known_questions(&mut c).await.unwrap(),
        1
    );
    let saved = lifecycle::load(&mut c, known.id).await.unwrap();
    assert_eq!(saved.run.state, State::Ready);
    assert_eq!(saved.run.usage.model_calls, 1);
}

use automated_apply_agents::{
    configuration::Configuration,
    server::{self, Api},
};
use std::{collections::BTreeMap, os::unix::fs::PermissionsExt, sync::Arc};
const HOST_TOKEN: &str = "0123456789abcdefghijklmnopqrstuvwxyzABCDEF";
fn host_values() -> BTreeMap<String, String> {
    BTreeMap::from([
        ("ENVIRONMENT".into(), "testing".into()),
        ("RUST_RUNTIME_FIXTURE".into(), "true".into()),
        (
            "DATABASE_URL".into(),
            std::env::var("RUST_AGENT_TEST_DATABASE_URL").unwrap(),
        ),
        ("JOB_AGENT_API_TOKEN".into(), HOST_TOKEN.into()),
        ("API_REQUIRE_TLS".into(), "false".into()),
        ("RUST_AGENT_LISTEN".into(), "127.0.0.1:0".into()),
    ])
}
async fn http_fixture() -> (String, CancellationToken, tokio::task::JoinHandle<()>) {
    http_fixture_values(host_values()).await
}
async fn http_fixture_values(
    values: BTreeMap<String, String>,
) -> (String, CancellationToken, tokio::task::JoinHandle<()>) {
    let config = Arc::new(Configuration::from_values(&values).unwrap());
    let mut c = config.connect(false).await.unwrap();
    server::readiness(&mut c, &config).await.unwrap();
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let stop = CancellationToken::new();
    let api = Api::new(config, c, Wake::default());
    let shutdown = stop.clone();
    let service = tokio::spawn(async move {
        axum::serve(
            listener,
            server::router(api).into_make_service_with_connect_info::<std::net::SocketAddr>(),
        )
        .with_graceful_shutdown(shutdown.cancelled_owned())
        .await
        .unwrap();
    });
    (format!("http://{address}"), stop, service)
}
fn client() -> reqwest::Client {
    reqwest::Client::builder()
        .no_proxy()
        .redirect(reqwest::redirect::Policy::none())
        .timeout(Duration::from_secs(2))
        .build()
        .unwrap()
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn actual_owner_http_api_checks_auth_origin_body_and_private_response_boundary() {
    let _source = knowledge_fixture().await;
    let (url, stop, service) = http_fixture().await;
    let http = client();
    let public = http.get(format!("{url}/health")).send().await.unwrap();
    assert_eq!(public.status(), 200);
    let denied = http.get(format!("{url}/ready")).send().await.unwrap();
    assert_eq!(denied.status(), 401);
    assert_eq!(denied.headers()["cache-control"], "private, no-store");
    let ready = http
        .get(format!("{url}/ready"))
        .bearer_auth(HOST_TOKEN)
        .send()
        .await
        .unwrap();
    assert_eq!(ready.status(), 200);
    let duplicate = http
        .get(format!("{url}/ready"))
        .bearer_auth(HOST_TOKEN)
        .header("authorization", "Bearer other")
        .send()
        .await
        .unwrap();
    assert_eq!(duplicate.status(), 401);
    let origin = http
        .get(format!("{url}/ready"))
        .bearer_auth(HOST_TOKEN)
        .header("origin", "https://untrusted.example.net")
        .send()
        .await
        .unwrap();
    assert_eq!(origin.status(), 403);
    let extension = http
        .get(format!("{url}/ready"))
        .bearer_auth(HOST_TOKEN)
        .header("x-agent-client", "extension")
        .send()
        .await
        .unwrap();
    assert_eq!(extension.status(), 403);
    let injected = http
        .post(format!("{url}/api/v1/rust-agent/runs"))
        .bearer_auth(HOST_TOKEN)
        .json(&json!({"request_id":Uuid::new_v4(),"submit":true,"private_marker":"do-not-echo"}))
        .send()
        .await
        .unwrap();
    assert_eq!(injected.status(), 400);
    assert!(!injected.text().await.unwrap().contains("do-not-echo"));
    let large = http
        .post(format!("{url}/api/v1/rust-agent/runs"))
        .bearer_auth(HOST_TOKEN)
        .body(vec![b'x'; 65537])
        .send()
        .await
        .unwrap();
    assert_eq!(large.status(), 413);
    let listing = http
        .get(format!("{url}/api/v1/rust-agent/runs"))
        .bearer_auth(HOST_TOKEN)
        .send()
        .await
        .unwrap()
        .text()
        .await
        .unwrap();
    assert!(!listing.contains("Private Fictional"));
    assert!(!listing.contains(HOST_TOKEN));
    stop.cancel();
    service.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn actual_http_controls_enforce_cas_and_accept_only_confirmed_fact_references() {
    let mut source = knowledge_fixture().await;
    let (url, stop, service) = http_fixture().await;
    let http = client();
    let created: Value = http
        .post(format!("{url}/api/v1/rust-agent/runs"))
        .bearer_auth(HOST_TOKEN)
        .json(&json!({"request_id":Uuid::new_v4()}))
        .send()
        .await
        .unwrap()
        .json()
        .await
        .unwrap();
    let id = created["id"].as_str().unwrap();
    let paused = http
        .post(format!("{url}/api/v1/rust-agent/runs/{id}/control"))
        .bearer_auth(HOST_TOKEN)
        .json(&json!({"expected_revision":1,"action":"pause"}))
        .send()
        .await
        .unwrap();
    assert_eq!(paused.status(), 200);
    assert_eq!(paused.json::<Value>().await.unwrap()["state"], "paused");
    let stale = http
        .post(format!("{url}/api/v1/rust-agent/runs/{id}/control"))
        .bearer_auth(HOST_TOKEN)
        .json(&json!({"expected_revision":1,"action":"resume"}))
        .send()
        .await
        .unwrap();
    assert_eq!(stale.status(), 409);
    let mode = http
        .put(format!("{url}/api/v1/rust-agent/control"))
        .bearer_auth(HOST_TOKEN)
        .json(&json!({"expected_revision":1,"mode":"STOPPED"}))
        .send()
        .await
        .unwrap();
    assert_eq!(mode.status(), 200);
    let events: Value = http
        .get(format!("{url}/api/v1/rust-agent/runs/{id}/events"))
        .bearer_auth(HOST_TOKEN)
        .send()
        .await
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(events["events"].as_array().unwrap().len(), 1);
    assert!(!events.to_string().contains("untrusted_data"));
    let waiting = waiting_fact(&mut source, "notice_period_days").await;
    let q = waiting.question.as_ref().unwrap().id;
    let address = format!(
        "{url}/api/v1/rust-agent/runs/{}/questions/{q}/resolve",
        waiting.id
    );
    let invented=http.post(&address).bearer_auth(HOST_TOKEN).json(&json!({"expected_revision":1,"profile":{"id":profile_pin().id,"version":4},"answer":30})).send().await.unwrap();
    assert_eq!(invented.status(), 400);
    let unresolved = http
        .post(&address)
        .bearer_auth(HOST_TOKEN)
        .json(&json!({"expected_revision":1,"profile":{"id":profile_pin().id,"version":4}}))
        .send()
        .await
        .unwrap();
    assert_eq!(unresolved.status(), 409);
    sqlx::raw_sql(
        "UPDATE candidate_profiles SET preferences=preferences||'{\"notice_period_days\":0}'",
    )
    .execute(&mut source)
    .await
    .unwrap();
    let resolved = http
        .post(&address)
        .bearer_auth(HOST_TOKEN)
        .json(&json!({"expected_revision":1,"profile":{"id":profile_pin().id,"version":4}}))
        .send()
        .await
        .unwrap();
    assert_eq!(resolved.status(), 200);
    assert_eq!(resolved.json::<Value>().await.unwrap()["state"], "ready");
    stop.cancel();
    service.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn actual_cli_runs_the_durable_worker_refuses_duplicate_executor_and_quiesces_on_sigterm() {
    use tokio::io::AsyncBufReadExt;
    let mut source = knowledge_fixture().await;
    saved_job(&mut source, 1).await;
    lifecycle::set_control(&mut source, 1, Mode::Stopped)
        .await
        .unwrap();
    let directory = tempfile::tempdir().unwrap();
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
    let path = directory.path().join("runtime.env");
    std::fs::write(
        &path,
        host_values()
            .iter()
            .map(|(k, v)| format!("{k}='{v}'\n"))
            .collect::<String>(),
    )
    .unwrap();
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o600)).unwrap();
    let binary = env!("CARGO_BIN_EXE_automated-apply-agents");
    let mut child = tokio::process::Command::new(binary)
        .args(["serve", "--config"])
        .arg(&path)
        .arg("--fixture-lock-directory")
        .arg(directory.path())
        .env_clear()
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::piped())
        .kill_on_drop(true)
        .spawn()
        .unwrap();
    let mut stdout = tokio::io::BufReader::new(child.stdout.take().unwrap());
    let mut line = String::new();
    tokio::time::timeout(Duration::from_secs(10), stdout.read_line(&mut line))
        .await
        .unwrap()
        .unwrap();
    let ready: Value = serde_json::from_str(&line).expect("sanitized CLI readiness event");
    assert_eq!(ready["event"], "rust_agent_ready");
    assert!(!line.contains(HOST_TOKEN));
    let url = format!("http://{}", ready["address"].as_str().unwrap());
    let http = client();
    let mode: Value = http
        .get(format!("{url}/api/v1/rust-agent/control"))
        .bearer_auth(HOST_TOKEN)
        .send()
        .await
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(mode["mode"], "STOPPED");
    let created: Value = http
        .post(format!("{url}/api/v1/rust-agent/runs"))
        .bearer_auth(HOST_TOKEN)
        .json(&json!({"request_id":Uuid::new_v4()}))
        .send()
        .await
        .unwrap()
        .json()
        .await
        .unwrap();
    let id = created["id"].as_str().unwrap();
    let start = http
        .put(format!("{url}/api/v1/rust-agent/control"))
        .bearer_auth(HOST_TOKEN)
        .json(&json!({"expected_revision":2,"mode":"RUNNING"}))
        .send()
        .await
        .unwrap();
    assert_eq!(start.status(), 200);
    tokio::time::timeout(Duration::from_secs(5), async {
        loop {
            let saved: Value = http
                .get(format!("{url}/api/v1/rust-agent/runs/{id}"))
                .bearer_auth(HOST_TOKEN)
                .send()
                .await
                .unwrap()
                .json()
                .await
                .unwrap();
            if saved["state"] == "completed" {
                assert_eq!(saved["usage"]["model_calls"], 0);
                assert_eq!(saved["usage"]["tool_calls"], 4);
                break;
            }
            assert_ne!(saved["state"], "failed");
            tokio::time::sleep(Duration::from_millis(5)).await;
        }
    })
    .await
    .unwrap();
    let duplicate = tokio::process::Command::new(binary)
        .args(["serve", "--config"])
        .arg(&path)
        .arg("--fixture-lock-directory")
        .arg(directory.path())
        .env_clear()
        .output()
        .await
        .unwrap();
    assert!(!duplicate.status.success());
    assert_eq!(
        String::from_utf8(duplicate.stderr).unwrap().trim(),
        "execution_worker_already_running"
    );
    assert!(duplicate.stdout.is_empty());
    let root = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../..");
    let legacy_script = r#"
import asyncio, sys
from pathlib import Path
from types import SimpleNamespace
from backend.app.local_agent.process_lock import process_lock, WorkerAlreadyRunning
async def check():
    settings=SimpleNamespace(DATABASE_URL=sys.argv[1].replace('postgresql://','postgresql+asyncpg://',1),DATABASE_SCHEMA='public')
    try:
        async with process_lock(settings,'execution',directory=Path(sys.argv[2])):
            raise SystemExit(0)
    except WorkerAlreadyRunning:
        raise SystemExit(75)
asyncio.run(check())
"#;
    let legacy = tokio::process::Command::new("uv")
        .args(["run", "--no-project", "--python"])
        .arg(root.join(".venv/bin/python"))
        .args(["python", "-c", legacy_script])
        .arg(std::env::var("RUST_AGENT_TEST_DATABASE_URL").unwrap())
        .arg(directory.path())
        .current_dir(&root)
        .output()
        .await
        .unwrap();
    assert_eq!(
        legacy.status.code(),
        Some(75),
        "legacy fixture lease must detect the Rust-held inode"
    );
    assert!(legacy.stdout.is_empty());
    let active:i64=sqlx::query_scalar("SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND application_name IN ('automated-apply:api','automated-apply:execution')").fetch_one(&mut source).await.unwrap();
    assert_eq!(active, 2);
    let old_execution:i32=sqlx::query_scalar("SELECT pid FROM pg_stat_activity WHERE datname=current_database() AND application_name='automated-apply:execution'").fetch_one(&mut source).await.unwrap();
    let killed: bool = sqlx::query_scalar("SELECT pg_terminate_backend($1)")
        .bind(old_execution)
        .fetch_one(&mut source)
        .await
        .unwrap();
    assert!(killed);
    let next: Value = http
        .post(format!("{url}/api/v1/rust-agent/runs"))
        .bearer_auth(HOST_TOKEN)
        .json(&json!({"request_id":Uuid::new_v4()}))
        .send()
        .await
        .unwrap()
        .json()
        .await
        .unwrap();
    let next_id = next["id"].as_str().unwrap();
    tokio::time::timeout(Duration::from_secs(10), async {
        loop {
            let saved: Value = http
                .get(format!("{url}/api/v1/rust-agent/runs/{next_id}"))
                .bearer_auth(HOST_TOKEN)
                .send()
                .await
                .unwrap()
                .json()
                .await
                .unwrap();
            if saved["state"] == "completed" {
                assert_eq!(saved["usage"]["model_calls"], 0);
                assert_eq!(saved["usage"]["tool_calls"], 4);
                break;
            }
            assert_ne!(saved["state"], "failed");
            tokio::time::sleep(Duration::from_millis(25)).await;
        }
    })
    .await
    .unwrap();
    let fresh_execution:i32=sqlx::query_scalar("SELECT pid FROM pg_stat_activity WHERE datname=current_database() AND application_name='automated-apply:execution'").fetch_one(&mut source).await.unwrap();
    assert_ne!(fresh_execution, old_execution);
    assert!(child.try_wait().unwrap().is_none());
    let active:i64=sqlx::query_scalar("SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND application_name IN ('automated-apply:api','automated-apply:execution')").fetch_one(&mut source).await.unwrap();
    assert_eq!(active, 2);
    let ambient = tokio::process::Command::new(binary)
        .args(["serve", "--config"])
        .arg(&path)
        .arg("--fixture-lock-directory")
        .arg(directory.path())
        .env_clear()
        .env("PGHOST", "ambient.invalid")
        .output()
        .await
        .unwrap();
    assert!(!ambient.status.success());
    assert_eq!(
        String::from_utf8(ambient.stderr).unwrap().trim(),
        "ambient_postgresql_options_forbidden"
    );
    // SAFETY: this PID belongs to the exact fixture child retained above, which has not exited.
    assert_eq!(
        unsafe { libc::kill(child.id().unwrap() as i32, libc::SIGTERM) },
        0
    );
    assert!(
        tokio::time::timeout(Duration::from_secs(5), child.wait())
            .await
            .unwrap()
            .unwrap()
            .success()
    );
    let control = lifecycle::control(&mut source).await.unwrap();
    assert_eq!(control.mode, Mode::Paused);
    assert!(!control.worker_online);
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn owner_api_reconnects_without_replaying_the_failed_control_request() {
    let mut source = knowledge_fixture().await;
    let (url, stop, service) = http_fixture().await;
    let http = client();
    let pid:i32=sqlx::query_scalar("SELECT pid FROM pg_stat_activity WHERE datname=current_database() AND application_name='automated-apply:api' ORDER BY backend_start DESC LIMIT 1").fetch_one(&mut source).await.unwrap();
    let killed: bool = sqlx::query_scalar("SELECT pg_terminate_backend($1)")
        .bind(pid)
        .fetch_one(&mut source)
        .await
        .unwrap();
    assert!(killed);
    let failed = http
        .put(format!("{url}/api/v1/rust-agent/control"))
        .bearer_auth(HOST_TOKEN)
        .json(&json!({"expected_revision":1,"mode":"STOPPED"}))
        .send()
        .await
        .unwrap();
    assert_eq!(failed.status(), 503);
    assert_eq!(
        lifecycle::control(&mut source).await.unwrap().mode,
        Mode::Running
    );
    let waiting = http
        .get(format!("{url}/api/v1/rust-agent/control"))
        .bearer_auth(HOST_TOKEN)
        .send()
        .await
        .unwrap();
    assert_eq!(waiting.status(), 503);
    assert_eq!(
        waiting.json::<Value>().await.unwrap()["error"],
        "agent_database_reconnecting"
    );
    tokio::time::sleep(Duration::from_millis(1100)).await;
    let recovered = http
        .get(format!("{url}/api/v1/rust-agent/control"))
        .bearer_auth(HOST_TOKEN)
        .send()
        .await
        .unwrap();
    assert_eq!(recovered.status(), 200);
    let control: Value = recovered.json().await.unwrap();
    assert_eq!(control["revision"], 1);
    assert_eq!(control["mode"], "RUNNING");
    let changed = http
        .put(format!("{url}/api/v1/rust-agent/control"))
        .bearer_auth(HOST_TOKEN)
        .json(&json!({"expected_revision":1,"mode":"STOPPED"}))
        .send()
        .await
        .unwrap();
    assert_eq!(changed.status(), 200);
    stop.cancel();
    service.await.unwrap();
}

use automated_apply_agents::telegram::{
    self, Identity as TelegramIdentity, Settings as TelegramSettings,
};
fn telegram_values(endpoint: &str) -> BTreeMap<String, String> {
    let mut values = host_values();
    values.extend([
        ("RUST_TELEGRAM_ENABLED".into(), "true".into()),
        (
            "TELEGRAM_BOT_TOKEN".into(),
            "123:abcdefghijklmnopqrstuvwx".into(),
        ),
        ("TELEGRAM_OWNER_USER_ID".into(), "11".into()),
        ("TELEGRAM_OWNER_CHAT_ID".into(), "22".into()),
        ("RUST_TELEGRAM_FIXTURE_ENDPOINT".into(), endpoint.into()),
    ]);
    values
}
async fn telegram_fixture() -> (PgConnection, TelegramSettings, TelegramIdentity) {
    let mut c = knowledge_fixture().await;
    sqlx::raw_sql("DROP TABLE IF EXISTS rust_telegram_outbox,rust_telegram_runtime,agent_telegram_deliveries,agent_telegram_state;CREATE TABLE agent_telegram_state(key text PRIMARY KEY,next_update_id bigint NOT NULL DEFAULT 0,bot_id text,last_poll_at timestamptz,last_error text,evidence_type text NOT NULL DEFAULT 'unverified');CREATE TABLE agent_telegram_deliveries(update_id bigint PRIMARY KEY,reply text NOT NULL,state text NOT NULL CHECK(state IN('pending','sending','sent')));").execute(&mut c).await.unwrap();
    sqlx::raw_sql(include_str!("../sql/003_telegram.sql"))
        .execute(&mut c)
        .await
        .unwrap();
    let settings = TelegramSettings::from_values(&telegram_values("http://127.0.0.1:54321"), true)
        .unwrap()
        .unwrap();
    let identity = TelegramIdentity {
        id: 123,
        username: "fictional_bot".into(),
    };
    telegram::initialize(&mut c, &settings, &identity)
        .await
        .unwrap();
    (c, settings, identity)
}
fn telegram_update(id: i64, text: &str) -> Value {
    json!({"update_id":id,"message":{"chat":{"id":22,"type":"private"},"from":{"id":11,"is_bot":false},"text":text}})
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn telegram_commands_cursor_and_bound_outbox_commit_once_and_unknown_send_is_quarantined() {
    let (mut c, settings, identity) = telegram_fixture().await;
    let wake = Wake::default();
    assert!(
        telegram::receive(
            &mut c,
            &settings,
            &identity,
            &telegram_update(42, "/agents review"),
            &wake
        )
        .await
        .unwrap()
    );
    assert!(
        !telegram::receive(
            &mut c,
            &settings,
            &identity,
            &telegram_update(42, "/agents review"),
            &wake
        )
        .await
        .unwrap()
    );
    let count: i64 = sqlx::query_scalar("SELECT count(*) FROM rust_agent_runs")
        .fetch_one(&mut c)
        .await
        .unwrap();
    assert_eq!(count, 1);
    let mut unauthorized = telegram_update(43, "/agents start");
    unauthorized["message"]["from"]["id"] = json!(12);
    assert!(
        !telegram::receive(&mut c, &settings, &identity, &unauthorized, &wake)
            .await
            .unwrap()
    );
    let offset: i64 = sqlx::query_scalar("SELECT next_update_id FROM agent_telegram_state")
        .fetch_one(&mut c)
        .await
        .unwrap();
    assert_eq!(offset, 44);
    let delivery = telegram::claim_delivery(&mut c, &settings)
        .await
        .unwrap()
        .unwrap();
    let id = delivery.id;
    assert!(!delivery.text.contains("Private Fictional"));
    telegram::finish_delivery(
        &mut c,
        &settings,
        &delivery,
        Err(telegram::Error {
            code: "telegram_network_or_response_error",
            retry_after: Duration::ZERO,
        }),
    )
    .await
    .unwrap();
    drop(c);
    let mut c = connection().await;
    telegram::initialize(&mut c, &settings, &identity)
        .await
        .unwrap();
    assert!(
        telegram::claim_delivery(&mut c, &settings)
            .await
            .unwrap()
            .is_none()
    );
    let state: String = sqlx::query_scalar("SELECT state FROM rust_telegram_outbox WHERE id=$1")
        .bind(id)
        .fetch_one(&mut c)
        .await
        .unwrap();
    assert_eq!(state, "sending");
    let legacy: String =
        sqlx::query_scalar("SELECT state FROM agent_telegram_deliveries WHERE update_id=42")
            .fetch_one(&mut c)
            .await
            .unwrap();
    assert_eq!(legacy, "sending");
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn telegram_verified_429_retains_real_cooldown_and_owner_bot_changes_are_rejected() {
    let (mut c, settings, identity) = telegram_fixture().await;
    telegram::receive(
        &mut c,
        &settings,
        &identity,
        &telegram_update(1, "/ping"),
        &Wake::default(),
    )
    .await
    .unwrap();
    let delivery = telegram::claim_delivery(&mut c, &settings)
        .await
        .unwrap()
        .unwrap();
    telegram::finish_delivery(
        &mut c,
        &settings,
        &delivery,
        Err(telegram::Error {
            code: "telegram_rate_limited",
            retry_after: Duration::from_secs(600),
        }),
    )
    .await
    .unwrap();
    let seconds:f64=sqlx::query_scalar("SELECT EXTRACT(EPOCH FROM next_request_at-clock_timestamp())::double precision FROM rust_telegram_runtime").fetch_one(&mut c).await.unwrap();
    assert!(seconds > 590.0);
    assert!(
        telegram::claim_delivery(&mut c, &settings)
            .await
            .unwrap()
            .is_none()
    );
    let mut changed = telegram_values("http://127.0.0.1:54321");
    changed.insert("TELEGRAM_OWNER_CHAT_ID".into(), "23".into());
    let changed = TelegramSettings::from_values(&changed, true)
        .unwrap()
        .unwrap();
    assert_eq!(
        telegram::initialize(&mut c, &changed, &identity).await,
        Err(Failure("telegram_owner_binding_changed"))
    );
    assert_eq!(
        telegram::initialize(
            &mut c,
            &settings,
            &TelegramIdentity {
                id: 124,
                username: "another_bot".into()
            }
        )
        .await,
        Err(Failure("telegram_bot_identity_changed"))
    );
    let state: String =
        sqlx::query_scalar("SELECT state FROM agent_telegram_deliveries WHERE update_id=1")
            .fetch_one(&mut c)
            .await
            .unwrap();
    assert_eq!(state, "pending");
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn telegram_history_is_not_imported_and_outbox_failure_rolls_back_command_and_offset() {
    let (mut c, settings, identity) = telegram_fixture().await;
    sqlx::raw_sql("UPDATE agent_telegram_state SET next_update_id=500;INSERT INTO agent_telegram_deliveries VALUES(499,'private historical reply','pending');").execute(&mut c).await.unwrap();
    telegram::initialize(&mut c, &settings, &identity)
        .await
        .unwrap();
    assert!(
        telegram::claim_delivery(&mut c, &settings)
            .await
            .unwrap()
            .is_none()
    );
    sqlx::raw_sql(
        "ALTER TABLE rust_telegram_outbox ADD CONSTRAINT fixture_outbox_refusal CHECK(false)",
    )
    .execute(&mut c)
    .await
    .unwrap();
    assert_eq!(
        telegram::receive(
            &mut c,
            &settings,
            &identity,
            &telegram_update(501, "/agents review"),
            &Wake::default()
        )
        .await,
        Err(Failure("telegram_database_error"))
    );
    let offset: i64 = sqlx::query_scalar("SELECT next_update_id FROM agent_telegram_state")
        .fetch_one(&mut c)
        .await
        .unwrap();
    assert_eq!(offset, 500);
    let runs: i64 = sqlx::query_scalar("SELECT count(*) FROM rust_agent_runs")
        .fetch_one(&mut c)
        .await
        .unwrap();
    assert_eq!(runs, 0);
    let replies: i64 = sqlx::query_scalar("SELECT count(*) FROM agent_telegram_deliveries")
        .fetch_one(&mut c)
        .await
        .unwrap();
    assert_eq!(replies, 1);
}

struct TelegramFixtureServer {
    sent: tokio::sync::Mutex<Vec<Value>>,
}
async fn telegram_fixture_http(
    axum::extract::State(state): axum::extract::State<Arc<TelegramFixtureServer>>,
    request: axum::extract::Request,
) -> axum::Json<Value> {
    let path = request.uri().path().to_owned();
    let bytes = axum::body::to_bytes(request.into_body(), 65536)
        .await
        .unwrap();
    let payload: Value = serde_json::from_slice(&bytes).unwrap();
    let result = match path.rsplit('/').next().unwrap() {
        "getMe" => json!({"id":123,"is_bot":true,"username":"fictional_bot"}),
        "getWebhookInfo" => json!({"url":""}),
        "getUpdates" => {
            assert!(payload["offset"].as_i64().unwrap() >= 0);
            if payload["offset"].as_i64().unwrap() <= 20 {
                json!([
                    telegram_update(20, "/agents start"),
                    telegram_update(21, "/agents review")
                ])
            } else {
                json!([])
            }
        }
        "sendMessage" => {
            assert_eq!(payload["chat_id"], 22);
            let mut sent = state.sent.lock().await;
            sent.push(payload);
            json!({"message_id":sent.len(),"chat":{"id":22,"type":"private"}})
        }
        _ => panic!("unapproved Telegram method"),
    };
    axum::Json(json!({"ok":true,"result":result}))
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn actual_cli_routes_telegram_owner_commands_through_five_agents_and_bound_notification_tool()
{
    use tokio::io::AsyncBufReadExt;
    let (mut c, _, _) = telegram_fixture().await;
    saved_job(&mut c, 1).await;
    lifecycle::set_control(&mut c, 1, Mode::Stopped)
        .await
        .unwrap();
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let endpoint = format!("http://{}", listener.local_addr().unwrap());
    let state = Arc::new(TelegramFixtureServer {
        sent: tokio::sync::Mutex::new(vec![]),
    });
    let stop = CancellationToken::new();
    let shutdown = stop.clone();
    let router = axum::Router::new()
        .fallback(telegram_fixture_http)
        .with_state(state.clone());
    let api = tokio::spawn(async move {
        axum::serve(listener, router)
            .with_graceful_shutdown(shutdown.cancelled_owned())
            .await
            .unwrap();
    });
    let directory = tempfile::tempdir().unwrap();
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
    let path = directory.path().join("runtime.env");
    std::fs::write(
        &path,
        telegram_values(&endpoint)
            .iter()
            .map(|(k, v)| format!("{k}='{v}'\n"))
            .collect::<String>(),
    )
    .unwrap();
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o600)).unwrap();
    let mut child = tokio::process::Command::new(env!("CARGO_BIN_EXE_automated-apply-agents"))
        .args(["serve", "--config"])
        .arg(&path)
        .arg("--fixture-lock-directory")
        .arg(directory.path())
        .env_clear()
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::piped())
        .kill_on_drop(true)
        .spawn()
        .unwrap();
    let mut stdout = tokio::io::BufReader::new(child.stdout.take().unwrap());
    let mut line = String::new();
    tokio::time::timeout(Duration::from_secs(10), stdout.read_line(&mut line))
        .await
        .unwrap()
        .unwrap();
    assert_eq!(
        serde_json::from_str::<Value>(&line).unwrap()["event"],
        "rust_agent_ready"
    );
    tokio::time::timeout(Duration::from_secs(10), async {
        loop {
            let completed: Option<Value> = sqlx::query_scalar(
                "SELECT run FROM rust_agent_runs WHERE run->>'state'='completed'",
            )
            .fetch_optional(&mut c)
            .await
            .unwrap();
            if let Some(run) = completed {
                assert_eq!(run["usage"]["decision_calls"], 10);
                assert_eq!(run["usage"]["model_calls"], 0);
                assert_eq!(run["usage"]["tool_calls"], 5);
                if state.sent.lock().await.len() == 3 {
                    break;
                }
            }
            tokio::time::sleep(Duration::from_millis(25)).await;
        }
    })
    .await
    .unwrap();
    assert!(
        state
            .sent
            .lock()
            .await
            .iter()
            .all(|message| !message.to_string().contains("Private Fictional"))
    );
    let cursor: i64 = sqlx::query_scalar("SELECT next_update_id FROM agent_telegram_state")
        .fetch_one(&mut c)
        .await
        .unwrap();
    assert_eq!(cursor, 22);
    let sent: i64 =
        sqlx::query_scalar("SELECT count(*) FROM rust_telegram_outbox WHERE state='sent'")
            .fetch_one(&mut c)
            .await
            .unwrap();
    assert_eq!(sent, 3);
    let legacy: i64 =
        sqlx::query_scalar("SELECT count(*) FROM agent_telegram_deliveries WHERE state='sent'")
            .fetch_one(&mut c)
            .await
            .unwrap();
    assert_eq!(legacy, 2);
    let active:i64=sqlx::query_scalar("SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND application_name IN ('automated-apply:api','automated-apply:execution','automated-apply:telegram')").fetch_one(&mut c).await.unwrap();
    assert_eq!(active, 3);
    // SAFETY: the retained PID belongs to this fictional fixture child only.
    assert_eq!(
        unsafe { libc::kill(child.id().unwrap() as i32, libc::SIGTERM) },
        0
    );
    assert!(
        tokio::time::timeout(Duration::from_secs(5), child.wait())
            .await
            .unwrap()
            .unwrap()
            .success()
    );
    assert_eq!(lifecycle::control(&mut c).await.unwrap().mode, Mode::Paused);
    stop.cancel();
    api.await.unwrap();
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn confirmed_compensation_decimal_forms_reconcile_without_reasking_for_known_facts() {
    let mut c = knowledge_fixture().await;
    for amount in ["100.000", "1E+2", "-0.000", "1000000000000.000", "100.0100"] {
        let value = json!({"expected_compensation":{"amount":amount,"currency":"INR","period":"year","kind":"ctc"}});
        sqlx::query("UPDATE candidate_profiles SET preferences=preferences||$1")
            .bind(value)
            .execute(&mut c)
            .await
            .unwrap();
        let waiting = waiting_fact(&mut c, "expected_compensation").await;
        assert!(
            lifecycle::pending_questions(&mut c)
                .await
                .unwrap()
                .is_empty()
        );
        assert_eq!(
            lifecycle::reconcile_known_questions(&mut c).await.unwrap(),
            1
        );
        let stored = lifecycle::load(&mut c, waiting.id).await.unwrap();
        assert_eq!(stored.run.state, State::Ready);
        assert_eq!(stored.run.usage.model_calls, 1);
    }
}

use automated_apply_agents::{graph, planner::SavedReviewPlanner};
async fn review_checkpoint(c: &mut PgConnection) -> lifecycle::Stored {
    let first = lifecycle::intake(
        c,
        Uuid::new_v4(),
        Limits {
            human_review: true,
            decision_calls: 32,
            ..Limits::default()
        },
    )
    .await
    .unwrap();
    let mut model = SavedReviewPlanner { notify: false };
    let mut tools = KnowledgeTools {
        profile: profile_pin(),
    };
    for _ in 0..30 {
        let mut store = Store { connection: c };
        let Some(mut lease) = store.claim().await.unwrap() else {
            break;
        };
        tick(&mut store, &mut lease, &mut model, &mut tools)
            .await
            .unwrap();
        if lease.run.state == State::WaitingApproval {
            break;
        }
    }
    let saved = lifecycle::load(c, first.run.id).await.unwrap();
    assert_eq!(
        saved.run.state,
        State::WaitingApproval,
        "{:?}",
        saved.run.diagnostic
    );
    saved
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn graph_http_approval_requires_exact_revision_and_review_then_resumes_without_new_authority()
{
    let mut c = knowledge_fixture().await;
    saved_job(&mut c, 1).await;
    let waiting = review_checkpoint(&mut c).await;
    let approval = waiting.run.graph.approvals.last().unwrap().id;
    assert_eq!(waiting.run.usage.decision_calls, 8);
    assert_eq!(waiting.run.usage.tool_calls, 4);
    let (url, stop, server) = http_fixture().await;
    let http = client();
    let preview: Value = http
        .get(format!(
            "{url}/api/v1/rust-agent/runs/{}/plan",
            waiting.run.id
        ))
        .bearer_auth(HOST_TOKEN)
        .send()
        .await
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(preview["prepared_results"].as_array().unwrap().len(), 4);
    assert_eq!(preview["approval_grants_submission"], false);
    assert!(
        preview["diagram"]
            .as_str()
            .unwrap()
            .contains("bounded replan")
    );
    let address = format!(
        "{url}/api/v1/rust-agent/runs/{}/approvals/{approval}",
        waiting.run.id
    );
    let forged=http.post(&address).bearer_auth(HOST_TOKEN).json(&json!({"expected_revision":waiting.revision,"decision":"approve","actor":"owner_api","submit":true})).send().await.unwrap();
    assert_eq!(forged.status(), 400);
    let stale = http
        .post(&address)
        .bearer_auth(HOST_TOKEN)
        .json(&json!({"expected_revision":waiting.revision-1,"decision":"approve"}))
        .send()
        .await
        .unwrap();
    assert_eq!(stale.status(), 409);
    let response = http
        .post(&address)
        .bearer_auth(HOST_TOKEN)
        .json(&json!({"expected_revision":waiting.revision,"decision":"approve"}))
        .send()
        .await
        .unwrap();
    assert_eq!(response.status(), 200);
    let mut store = Store { connection: &mut c };
    let mut lease = store.claim().await.unwrap().unwrap();
    let mut model = SavedReviewPlanner { notify: false };
    let mut tools = KnowledgeTools {
        profile: profile_pin(),
    };
    tick(&mut store, &mut lease, &mut model, &mut tools)
        .await
        .unwrap();
    assert_eq!(lease.run.state, State::Completed);
    assert_eq!(lease.run.usage.decision_calls, 9);
    assert_eq!(lease.run.usage.tool_calls, 4);
    let audit = lifecycle::events(&mut c, waiting.run.id).await.unwrap();
    assert!(
        audit
            .iter()
            .any(|event| event["graph_node"] == "human_approval"
                && event["approval_required"] == true)
    );
    let repeated = http
        .post(&address)
        .bearer_auth(HOST_TOKEN)
        .json(&json!({"expected_revision":waiting.revision,"decision":"approve"}))
        .send()
        .await
        .unwrap();
    assert_eq!(repeated.status(), 409);
    stop.cancel();
    server.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn human_changes_loop_recomputes_actual_saved_facts_and_keeps_spent_usage() {
    let mut c = knowledge_fixture().await;
    saved_job(&mut c, 1).await;
    let waiting = review_checkpoint(&mut c).await;
    let approval = waiting.run.graph.approvals.last().unwrap().id;
    let changed = lifecycle::approve(
        &mut c,
        waiting.run.id,
        waiting.revision,
        approval,
        graph::Decision::RequestChanges,
        graph::Actor::OwnerApi,
    )
    .await
    .unwrap();
    assert_eq!(changed.run.graph.iterations, 1);
    assert_eq!(changed.run.usage.tool_calls, 4);
    assert_eq!(changed.run.usage.decision_calls, 8);
    assert!(changed.run.context.is_empty());
    let mut model = SavedReviewPlanner { notify: false };
    let mut tools = KnowledgeTools {
        profile: profile_pin(),
    };
    for _ in 0..30 {
        let mut store = Store { connection: &mut c };
        let mut lease = store.claim().await.unwrap().unwrap();
        tick(&mut store, &mut lease, &mut model, &mut tools)
            .await
            .unwrap();
        if lease.run.state == State::WaitingApproval {
            break;
        }
    }
    let next = lifecycle::load(&mut c, waiting.run.id).await.unwrap();
    assert_eq!(next.run.state, State::WaitingApproval);
    assert_eq!(next.run.usage.decision_calls, 16);
    assert_eq!(next.run.usage.tool_calls, 8);
    assert_ne!(next.run.graph.approvals.last().unwrap().id, approval);
    let rejected = lifecycle::approve(
        &mut c,
        next.run.id,
        next.revision,
        next.run.graph.approvals.last().unwrap().id,
        graph::Decision::Reject,
        graph::Actor::OwnerApi,
    )
    .await
    .unwrap();
    assert_eq!(rejected.run.state, State::Stopped);
    assert_eq!(rejected.run.usage.tool_calls, 8);
    assert!(
        Store { connection: &mut c }
            .claim()
            .await
            .unwrap()
            .is_none()
    );
}
struct OneReplan {
    saved: SavedReviewPlanner,
    replanned: bool,
}
impl Model for OneReplan {
    fn inference_required(&self, _: Role, _: &[Context]) -> bool {
        false
    }
    async fn propose(
        &mut self,
        role: Role,
        context: &[Context],
        budget: ModelBudget,
        store: &mut Store<'_>,
    ) -> Result<Proposal> {
        if role == Role::Review
            && !self.replanned
            && context
                .iter()
                .any(|c| c.tool == ToolName::ApplicationHistory)
        {
            self.replanned = true;
            return Ok(Proposal::Replan {
                target: Role::Matching,
                reason: graph::ReplanReason::RecheckEligibility,
                evidence: vec![],
            });
        }
        self.saved.propose(role, context, budget, store).await
    }
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn reviewer_graph_replan_runs_actual_tools_again_and_preserves_source_binding() {
    let mut c = knowledge_fixture().await;
    let job = saved_job(&mut c, 1).await;
    let run = lifecycle::intake(&mut c, Uuid::new_v4(), Limits::default())
        .await
        .unwrap();
    let mut model = OneReplan {
        saved: SavedReviewPlanner { notify: false },
        replanned: false,
    };
    let mut tools = KnowledgeTools {
        profile: profile_pin(),
    };
    for _ in 0..30 {
        let mut store = Store { connection: &mut c };
        let Some(mut lease) = store.claim().await.unwrap() else {
            break;
        };
        tick(&mut store, &mut lease, &mut model, &mut tools)
            .await
            .unwrap();
        if lease.run.state == State::Completed {
            break;
        }
    }
    let saved = lifecycle::load(&mut c, run.run.id).await.unwrap();
    assert_eq!(saved.run.state, State::Completed);
    assert_eq!(saved.run.graph.iterations, 1);
    assert_eq!(saved.run.usage.decision_calls, 15);
    assert_eq!(saved.run.usage.tool_calls, 7);
    assert_eq!(saved.run.known_jobs, vec![job]);
}
struct GuardedTool {
    allowed: bool,
    executed: usize,
}
impl Tools for GuardedTool {
    async fn authority(&mut self, _: &ToolCall, _: &mut Store<'_>) -> Result<Authority> {
        Ok(Authority {
            requires_human_approval: true,
            inactive_owned_browser: self.allowed,
            ..Authority::default()
        })
    }
    async fn execute(&mut self, _: &Effect, _: &mut Store<'_>) -> Result<Observation> {
        self.executed += 1;
        Ok(Observation {
            jobs: vec![],
            evidence: vec![],
            data: json!({"fixture":true}),
        })
    }
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn human_tool_approval_never_overrides_changed_backend_authority_or_resets_usage() {
    let mut c = knowledge_fixture().await;
    let job = saved_job(&mut c, 1).await;
    let mut run = run();
    run.role = Role::Execution;
    run.profile = Some(profile_pin());
    run.known_jobs = vec![job];
    engine::begin_model(&mut run).unwrap();
    engine::accept(
        &mut run,
        Proposal::Tool {
            call: ToolCall {
                name: ToolName::OpenBrowser,
                job_id: Some(job),
                evidence: vec![],
            },
        },
    )
    .unwrap();
    let effect = run.pending.as_ref().unwrap().id;
    Store { connection: &mut c }.create(&run).await.unwrap();
    let mut lease = Store { connection: &mut c }.claim().await.unwrap().unwrap();
    let mut tool = GuardedTool {
        allowed: true,
        executed: 0,
    };
    let mut model = SavedReviewPlanner { notify: false };
    tick(
        &mut Store { connection: &mut c },
        &mut lease,
        &mut model,
        &mut tool,
    )
    .await
    .unwrap();
    assert_eq!(lease.run.state, State::WaitingApproval);
    assert_eq!(tool.executed, 0);
    assert_eq!(lease.run.usage.tool_calls, 0);
    let saved = lifecycle::load(&mut c, run.id).await.unwrap();
    let approved = lifecycle::approve(
        &mut c,
        run.id,
        saved.revision,
        saved.run.graph.approvals[0].id,
        graph::Decision::Approve,
        graph::Actor::OwnerApi,
    )
    .await
    .unwrap();
    assert_eq!(approved.run.pending.as_ref().unwrap().id, effect);
    tool.allowed = false;
    let mut lease = Store { connection: &mut c }.claim().await.unwrap().unwrap();
    tick(
        &mut Store { connection: &mut c },
        &mut lease,
        &mut model,
        &mut tool,
    )
    .await
    .unwrap();
    assert_eq!(tool.executed, 0);
    assert_eq!(lease.run.usage.tool_calls, 0);
    assert_eq!(lease.run.state, State::WaitingOwner);
}

async fn graph_model_fixture(
    axum::extract::State(calls): axum::extract::State<Arc<std::sync::Mutex<Vec<Value>>>>,
    axum::Json(body): axum::Json<Value>,
) -> axum::Json<Value> {
    let mut observed = calls.lock().unwrap();
    let planner = body["messages"][0]["content"]
        .as_str()
        .unwrap()
        .starts_with(Role::Discovery.instruction());
    observed.push(body);
    let reviews = observed
        .iter()
        .filter(|body| {
            body["messages"][0]["content"]
                .as_str()
                .unwrap()
                .starts_with(Role::Review.instruction())
        })
        .count();
    let decision = if planner {
        json!({"action":"handoff","next":"matching","evidence":[]})
    } else if reviews == 1 {
        json!({"action":"replan","target":"matching","reason":"recheck_eligibility","evidence":[]})
    } else {
        json!({"action":"handoff","next":"execution","evidence":[]})
    };
    axum::Json(
        json!({"finish_reason":"COMPLETE","message":{"role":"assistant","content":[{"type":"text","text":decision.to_string()}]},"usage":{"tokens":{"input_tokens":800,"output_tokens":30}}}),
    )
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn actual_cli_model_reviewer_replans_waits_without_recharging_and_requires_human_decision() {
    exercise_model_roles(false).await;
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn actual_cli_two_model_agents_plan_review_replan_and_wait_for_human_approval() {
    exercise_model_roles(true).await;
}
async fn exercise_model_roles(dual: bool) {
    use tokio::io::AsyncBufReadExt;
    let mut c = knowledge_fixture().await;
    saved_job(&mut c, 1).await;
    sqlx::query("UPDATE candidate_profiles SET preferences=preferences || '{\"email\":\"privacy-canary@example.invalid\",\"resume_text\":\"private-resume-canary\"}'::jsonb").execute(&mut c).await.unwrap();
    let calls = Arc::new(std::sync::Mutex::new(Vec::<Value>::new()));
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let endpoint = format!("http://{}/v2/chat", listener.local_addr().unwrap());
    let stop = CancellationToken::new();
    let shutdown = stop.clone();
    let app = axum::Router::new()
        .route("/v2/chat", axum::routing::post(graph_model_fixture))
        .with_state(calls.clone());
    let fake = tokio::spawn(async move {
        axum::serve(listener, app)
            .with_graceful_shutdown(shutdown.cancelled_owned())
            .await
            .unwrap();
    });
    let mut values = host_values();
    if dual {
        values.insert("RUST_AGENT_MODEL_ROLES".into(), "discovery,review".into());
    }
    for (key, value) in [
        ("RUST_AGENT_REVIEW_MODEL", "cohere"),
        ("COHERE_ENABLED", "true"),
        ("COHERE_EVALUATION_KEY_CONFIRMED", "true"),
        ("COHERE_OWNER_TEXT_AUTHORIZED", "true"),
        ("COHERE_CANDIDATE_DATA_AUTHORIZED", "true"),
        ("COHERE_API_KEY", "fictional-fixture-key"),
        ("LLM_MAX_INPUT_CHARS", "5000"),
        ("LLM_MAX_OUTPUT_TOKENS", "128"),
    ] {
        values.insert(key.into(), value.into());
    }
    values.insert("RUST_COHERE_FIXTURE_ENDPOINT".into(), endpoint);
    let directory = tempfile::tempdir().unwrap();
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
    let path = directory.path().join("runtime.env");
    std::fs::write(
        &path,
        values
            .iter()
            .map(|(k, v)| format!("{k}='{v}'\n"))
            .collect::<String>(),
    )
    .unwrap();
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o600)).unwrap();
    let mut child = tokio::process::Command::new(env!("CARGO_BIN_EXE_automated-apply-agents"))
        .args(["serve", "--config"])
        .arg(&path)
        .arg("--fixture-lock-directory")
        .arg(directory.path())
        .env_clear()
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::piped())
        .kill_on_drop(true)
        .spawn()
        .unwrap();
    let mut stdout = tokio::io::BufReader::new(child.stdout.take().unwrap());
    let mut line = String::new();
    tokio::time::timeout(Duration::from_secs(10), stdout.read_line(&mut line))
        .await
        .unwrap()
        .unwrap();
    let ready: Value = serde_json::from_str(&line).expect("sanitized fixture readiness");
    let url = format!(
        "http://{}/api/v1/rust-agent",
        ready["address"].as_str().unwrap()
    );
    let http = client();
    let capabilities: Value = http
        .get(format!("{url}/capabilities"))
        .bearer_auth(HOST_TOKEN)
        .send()
        .await
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(capabilities["review_model"], "cohere");
    assert_eq!(
        capabilities["model_roles"],
        if dual {
            json!(["discovery", "review"])
        } else {
            json!(["review"])
        }
    );
    let final_calls = if dual { 3 } else { 2 };
    let per_call = if dual { 3928 } else { 5128 };
    let mut waits = BTreeMap::new();
    let created: Value = http
        .post(format!("{url}/runs"))
        .bearer_auth(HOST_TOKEN)
        .json(&json!({"request_id":Uuid::new_v4(),"limits":capabilities["recommended_limits"]}))
        .send()
        .await
        .unwrap()
        .json()
        .await
        .unwrap();
    let id = created["id"].as_str().unwrap();
    let waiting: Value = tokio::time::timeout(Duration::from_secs(25), async {
        let mut saw_wait = false;
        loop {
            let saved: Value = http
                .get(format!("{url}/runs/{id}"))
                .bearer_auth(HOST_TOKEN)
                .send()
                .await
                .unwrap()
                .json()
                .await
                .unwrap();
            assert_ne!(saved["state"], "failed", "{saved}");
            if saved["graph"]["node"] == "provider_wait" {
                saw_wait = true;
                let calls = saved["usage"]["model_calls"].as_u64().unwrap();
                assert!((1..final_calls).contains(&calls));
                assert_eq!(saved["usage"]["reserved_tokens"], calls * per_call);
                let key = format!("{}:{}", saved["role"], saved["graph"]["iteration"]);
                if let Some(prior) = waits.insert(key, saved["usage"].clone()) {
                    assert_eq!(prior, saved["usage"]);
                }
            }
            if saved["state"] == "waiting_approval" {
                assert!(saw_wait);
                break saved;
            }
            tokio::time::sleep(Duration::from_millis(20)).await;
        }
    })
    .await
    .unwrap();
    assert_eq!(waiting["graph"]["iteration"], 1);
    assert_eq!(waiting["usage"]["model_calls"], final_calls);
    assert_eq!(waiting["usage"]["tool_calls"], 7);
    assert_eq!(waiting["usage"]["reserved_tokens"], final_calls * per_call);
    let approval = waiting["graph"]["approvals"][0]["id"].as_str().unwrap();
    let approved = http
        .post(format!("{url}/runs/{id}/approvals/{approval}"))
        .bearer_auth(HOST_TOKEN)
        .json(&json!({"expected_revision":waiting["revision"],"decision":"approve"}))
        .send()
        .await
        .unwrap();
    assert_eq!(approved.status(), 200);
    tokio::time::timeout(Duration::from_secs(5), async {
        loop {
            let saved: Value = http
                .get(format!("{url}/runs/{id}"))
                .bearer_auth(HOST_TOKEN)
                .send()
                .await
                .unwrap()
                .json()
                .await
                .unwrap();
            if saved["state"] == "completed" {
                assert_eq!(saved["usage"]["model_calls"], final_calls);
                break;
            }
            assert_ne!(saved["state"], "failed", "{saved}");
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
    })
    .await
    .unwrap();
    let ledger: i32 = sqlx::query_scalar(
        "SELECT sum(requests)::int FROM llm_monthly_usage WHERE provider='cohere'",
    )
    .fetch_one(&mut c)
    .await
    .unwrap();
    assert_eq!(ledger as u64, final_calls);
    {
        let sent = calls.lock().unwrap();
        assert_eq!(sent.len() as u64, final_calls);
        let roles = sent
            .iter()
            .map(|body| {
                if body["messages"][0]["content"]
                    .as_str()
                    .unwrap()
                    .starts_with(Role::Discovery.instruction())
                {
                    Role::Discovery
                } else {
                    Role::Review
                }
            })
            .collect::<Vec<_>>();
        assert_eq!(
            roles,
            if dual {
                vec![Role::Discovery, Role::Review, Role::Review]
            } else {
                vec![Role::Review, Role::Review]
            }
        );
        for body in sent.iter() {
            let encoded = serde_json::to_string(body).unwrap();
            assert!(encoded.len() <= if dual { 3800 } else { 5000 });
            assert!(!encoded.contains("privacy-canary"));
            assert!(!encoded.contains("private-resume-canary"));
            assert!(!encoded.contains("fictional-fixture-key"));
            assert_eq!(body["max_tokens"], 128);
        }
    }
    // SAFETY: retained PID is the exact isolated fixture child, still running.
    assert_eq!(
        unsafe { libc::kill(child.id().unwrap() as i32, libc::SIGTERM) },
        0
    );
    assert!(
        tokio::time::timeout(Duration::from_secs(5), child.wait())
            .await
            .unwrap()
            .unwrap()
            .success()
    );
    stop.cancel();
    fake.await.unwrap();
}

async fn profile_fixture() -> PgConnection {
    let mut c = knowledge_fixture().await;
    sqlx::raw_sql("ALTER TABLE candidate_profiles ADD COLUMN linkedin_url text,ADD COLUMN github_url text,ADD COLUMN portfolio_url text,ADD COLUMN personal_website text,ADD COLUMN verified_roles jsonb NOT NULL DEFAULT '[]',ADD COLUMN education jsonb NOT NULL DEFAULT '[]',ADD COLUMN projects jsonb NOT NULL DEFAULT '[]',ADD COLUMN certifications jsonb NOT NULL DEFAULT '[]',ADD COLUMN summary text,ADD COLUMN created_at timestamptz NOT NULL DEFAULT '2026-11-14T00:00:00Z',ADD COLUMN updated_at timestamptz NOT NULL DEFAULT '2026-11-14T00:00:00Z',ADD COLUMN active_resume_version_id uuid").execute(&mut c).await.unwrap();
    c
}
async fn resource_fixture() -> PgConnection {
    let mut c = profile_fixture().await;
    sqlx::raw_sql(include_str!("fixtures/resources.sql"))
        .execute(&mut c)
        .await
        .unwrap();
    c
}
include!("support/resources_pg.rs");
include!("support/drafts_pg.rs");
include!("support/owner_proof_pg.rs");
include!("support/project_context_pg.rs");
include!("support/job_context_pg.rs");
include!("support/answer_context_pg.rs");
include!("support/missing_store_pg.rs");
include!("support/answer_service_pg.rs");
include!("support/answer_reuse_pg.rs");
include!("support/gemini_pg.rs");
include!("support/ollama_pg.rs");
include!("support/notifications_pg.rs");
include!("support/notification_preferences_pg.rs");
include!("support/job_catalog_pg.rs");
include!("support/packet_fields_pg.rs");
include!("support/packet_context_pg.rs");
include!("support/packet_service_pg.rs");
include!("support/packet_edit_pg.rs");
include!("support/packet_generation_pg.rs");
include!("support/packet_review_pg.rs");
include!("support/private_resume_pg.rs");
include!("support/mcp_pg.rs");
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn owner_resume_inspection_scopes_saved_references_and_never_admits_or_fetches() {
    let mut c = resource_fixture().await;
    let before: Value = sqlx::query_scalar("SELECT jsonb_build_object('profile',(SELECT to_jsonb(p) FROM candidate_profiles p),'resources',(SELECT jsonb_agg(to_jsonb(r) ORDER BY id) FROM candidate_resources r),'confirmation',(SELECT value FROM owner_preferences WHERE key='phase1_profile_confirmation'))").fetch_one(&mut c).await.unwrap();
    let (url, stop, server) = http_fixture().await;
    let target = format!("{url}/api/v1/rust-agent/resume-selection");
    let http = client();
    assert_eq!(http.get(&target).send().await.unwrap().status(), 401);
    assert_eq!(
        http.get(&target)
            .bearer_auth(HOST_TOKEN)
            .header("x-agent-client", "extension")
            .send()
            .await
            .unwrap()
            .status(),
        403
    );
    let response = http
        .get(&target)
        .header("authorization", format!("bearer {HOST_TOKEN}"))
        .send()
        .await
        .unwrap();
    assert_eq!(response.status(), 200);
    let selection: Value = response.json().await.unwrap();
    assert_eq!(selection["alternatives"].as_array().unwrap().len(), 1);
    assert_eq!(selection["selected"]["label"], "Fictional résumé 🚀");
    assert_eq!(
        selection["selected"]["url"],
        "private-resume:20000000-0000-0000-0000-000000000001"
    );
    assert_eq!(
        selection["selected"]["download_path"],
        "/api/backend/dashboard/resumes/20000000-0000-0000-0000-000000000001"
    );
    assert_eq!(selection["upload_status"], "manual_resume_upload_required");
    let foreign: Value = http
        .get(format!(
            "{target}?selected_id=10000000-0000-0000-0000-000000000002"
        ))
        .bearer_auth(HOST_TOKEN)
        .send()
        .await
        .unwrap()
        .json()
        .await
        .unwrap();
    assert!(foreign["selected"].is_null());
    for query in [
        "selected_id=bad",
        "selected_id=10000000-0000-0000-0000-000000000001&selected_id=10000000-0000-0000-0000-000000000002",
        "submit=true",
    ] {
        assert_eq!(
            http.get(format!("{target}?{query}"))
                .bearer_auth(HOST_TOKEN)
                .send()
                .await
                .unwrap()
                .status(),
            422
        );
    }
    let method = http
        .post(&target)
        .bearer_auth(HOST_TOKEN)
        .send()
        .await
        .unwrap();
    assert_eq!(method.status(), 405);
    assert_eq!(method.headers()["allow"], "GET");
    assert_eq!(
        http.get(format!(
            "{url}/api/v1/profile?selected_id=00000000-0000-0000-0000-000000000002"
        ))
        .bearer_auth(HOST_TOKEN)
        .send()
        .await
        .unwrap()
        .status(),
        400
    );
    let after: Value = sqlx::query_scalar("SELECT jsonb_build_object('profile',(SELECT to_jsonb(p) FROM candidate_profiles p),'resources',(SELECT jsonb_agg(to_jsonb(r) ORDER BY id) FROM candidate_resources r),'confirmation',(SELECT value FROM owner_preferences WHERE key='phase1_profile_confirmation'))").fetch_one(&mut c).await.unwrap();
    assert_eq!(before, after);
    let count: i64 = sqlx::query_scalar("SELECT count(*) FROM application_packets")
        .fetch_one(&mut c)
        .await
        .unwrap();
    assert_eq!(count, 0);
    stop.cancel();
    server.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn profile_readiness_checks_unknown_facts_without_claiming_identity_or_pdf_acceptance() {
    let mut c = resource_fixture().await;
    let (url, stop, server) = http_fixture().await;
    let target = format!("{url}/api/v1/rust-agent/profile-readiness");
    let http = client();
    let blocked: Value = http
        .get(&target)
        .bearer_auth(HOST_TOKEN)
        .send()
        .await
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(
        blocked["missing"],
        json!([
            "projects",
            "github_url",
            "linkedin_url",
            "portfolio_or_personal_website"
        ])
    );
    assert_eq!(blocked["resume_selected"], true);
    let patch = json!({"projects":[{"name":"Fictional implementation","description":"Confirmed work","contribution":"Built coordinator","technologies":["Rust"]}],"github_url":"https://github.com/fictional","linkedin_url":"https://linkedin.com/in/fictional","portfolio_url":"https://example.com"});
    profile_store::save(&mut c, patch, Some(4), true, false)
        .await
        .unwrap();
    let ready: Value = http
        .get(&target)
        .bearer_auth(HOST_TOKEN)
        .send()
        .await
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(ready["status"], "owner_confirmation_required");
    assert_eq!(ready["profile_version"], 5);
    assert_eq!(ready["missing"], json!([]));
    assert_eq!(ready["identity_independently_verified"], false);
    assert_eq!(ready["warnings"].as_array().unwrap().len(), 2);
    assert_eq!(
        automated_apply_agents::resource_store::inspect(&mut c, None, true, true)
            .await
            .err(),
        Some(Failure("fictional_or_placeholder_profile_rejected"))
    );
    sqlx::query("DELETE FROM candidate_profiles")
        .execute(&mut c)
        .await
        .unwrap();
    let missing: Value = http
        .get(&target)
        .bearer_auth(HOST_TOKEN)
        .send()
        .await
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(missing["missing"], json!(["candidate_profile"]));
    assert_eq!(missing["resume_selected"], false);
    assert_eq!(
        http.get(format!("{url}/api/v1/rust-agent/resume-selection"))
            .bearer_auth(HOST_TOKEN)
            .send()
            .await
            .unwrap()
            .status(),
        404
    );
    stop.cancel();
    server.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn resume_inspection_fails_closed_on_truncation_and_bad_records_then_releases_snapshot() {
    let mut c = resource_fixture().await;
    sqlx::query(
        "UPDATE candidate_resources SET updated_at='infinity' WHERE candidate_profile_id=$1",
    )
    .bind(profile_pin().id)
    .execute(&mut c)
    .await
    .unwrap();
    assert_eq!(
        automated_apply_agents::resource_store::inspect(&mut c, None, false, false)
            .await
            .err(),
        Some(Failure("invalid_resource_record"))
    );
    sqlx::query("UPDATE candidate_resources SET updated_at='2026-11-14T00:00:00Z' WHERE candidate_profile_id=$1").bind(profile_pin().id).execute(&mut c).await.unwrap();
    sqlx::query("INSERT INTO candidate_resources(id,candidate_profile_id,resource_type,label,url,user_confirmed,is_primary,source_type) SELECT gen_random_uuid(),$1,'other','Fictional resource','https://example.com/'||n::text,false,false,'user' FROM generate_series(1,10000) n").bind(profile_pin().id).execute(&mut c).await.unwrap();
    assert_eq!(
        automated_apply_agents::resource_store::inspect(&mut c, None, false, false)
            .await
            .err(),
        Some(Failure("resource_inventory_limit"))
    );
    assert_eq!(profile_store::get(&mut c).await.unwrap().version, 4);
}
use automated_apply_agents::{profile_contract, profile_store};
fn profile_body() -> Value {
    json!({"full_name":"Fictional Person","email":"fictional@example.com","verified_skills":["Rust","RUST"],"preferences":{"notice_period_days":30,"target_titles":["Engineer"]}})
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn profile_http_commits_before_ack_preserves_resume_and_uses_strong_cas_etags() {
    let mut c = profile_fixture().await;
    sqlx::query("DELETE FROM candidate_profiles")
        .execute(&mut c)
        .await
        .unwrap();
    let (url, stop, server) = http_fixture().await;
    let target = format!("{url}/api/v1/profile");
    let http = client();
    assert_eq!(
        http.put(&target)
            .body("x".repeat(65537))
            .send()
            .await
            .unwrap()
            .status(),
        401
    );
    assert_eq!(
        http.put(&target)
            .bearer_auth(HOST_TOKEN)
            .body("x".repeat(65537))
            .send()
            .await
            .unwrap()
            .status(),
        413
    );
    assert_eq!(
        http.get(&target)
            .bearer_auth(HOST_TOKEN)
            .send()
            .await
            .unwrap()
            .status(),
        404
    );
    assert_eq!(
        http.put(&target)
            .bearer_auth(HOST_TOKEN)
            .header("if-match", "\"1\"")
            .json(&profile_body())
            .send()
            .await
            .unwrap()
            .status(),
        409
    );
    let created = http
        .put(&target)
        .bearer_auth(HOST_TOKEN)
        .json(&profile_body())
        .send()
        .await
        .unwrap();
    assert_eq!(created.status(), 201);
    assert_eq!(created.headers()["etag"], "\"1\"");
    assert!(
        created.headers()["cache-control"]
            .to_str()
            .unwrap()
            .contains("no-store")
    );
    let body: Value = created.json().await.unwrap();
    let id = body["id"].as_str().unwrap().parse::<Uuid>().unwrap();
    assert_eq!(body["verified_skills"], json!(["Rust"]));
    assert_eq!(body["version"], 1);
    assert_eq!(
        http.get(&target)
            .header("authorization", format!("bearer {HOST_TOKEN}"))
            .send()
            .await
            .unwrap()
            .status(),
        200
    );
    // An independent connection must see the committed row as soon as HTTP acknowledges.
    let mut observer = connection().await;
    let version: i32 = sqlx::query_scalar("SELECT version FROM candidate_profiles WHERE id=$1")
        .bind(id)
        .fetch_one(&mut observer)
        .await
        .unwrap();
    assert_eq!(version, 1);
    let resume = Uuid::from_u128(12345);
    sqlx::query("UPDATE candidate_profiles SET active_resume_version_id=$1 WHERE id=$2")
        .bind(resume)
        .bind(id)
        .execute(&mut c)
        .await
        .unwrap();
    let no_op = http
        .put(&target)
        .bearer_auth(HOST_TOKEN)
        .json(&profile_body())
        .send()
        .await
        .unwrap();
    assert_eq!(no_op.status(), 200);
    assert_eq!(no_op.headers()["etag"], "\"1\"");
    assert_eq!(
        no_op.json::<Value>().await.unwrap()["updated_at"],
        body["updated_at"]
    );
    let changed = json!({"preferences":{"notice_period_days":0}});
    assert_eq!(
        http.patch(&target)
            .bearer_auth(HOST_TOKEN)
            .json(&json!({}))
            .send()
            .await
            .unwrap()
            .status(),
        422
    );
    assert_eq!(
        http.patch(&target)
            .bearer_auth(HOST_TOKEN)
            .json(&json!({"full_name":null}))
            .send()
            .await
            .unwrap()
            .status(),
        422
    );
    assert_eq!(
        http.patch(&target)
            .bearer_auth(HOST_TOKEN)
            .json(&changed)
            .send()
            .await
            .unwrap()
            .status(),
        428
    );
    assert_eq!(
        http.patch(&target)
            .bearer_auth(HOST_TOKEN)
            .header("if-match", "W/\"1\"")
            .json(&changed)
            .send()
            .await
            .unwrap()
            .status(),
        422
    );
    assert_eq!(
        http.patch(&target)
            .bearer_auth(HOST_TOKEN)
            .header("if-match", "\"1\"")
            .header("if-match", "\"1\"")
            .json(&changed)
            .send()
            .await
            .unwrap()
            .status(),
        422
    );
    let saved = http
        .patch(&target)
        .bearer_auth(HOST_TOKEN)
        .header("if-match", "\"1\"")
        .json(&changed)
        .send()
        .await
        .unwrap();
    assert_eq!(saved.status(), 200);
    assert_eq!(saved.headers()["etag"], "\"2\"");
    let saved: Value = saved.json().await.unwrap();
    assert_eq!(saved["preferences"]["notice_period_days"], 0);
    assert_eq!(saved["preferences"]["target_titles"], json!(["Engineer"]));
    assert_eq!(saved["verified_skills"], json!(["Rust"]));
    assert_eq!(saved["created_at"], body["created_at"]);
    assert!(saved.get("active_resume_version_id").is_none());
    assert_eq!(
        http.patch(&target)
            .bearer_auth(HOST_TOKEN)
            .header("if-match", "\"1\"")
            .json(&changed)
            .send()
            .await
            .unwrap()
            .status(),
        409
    );
    assert_eq!(
        http.patch(&target)
            .bearer_auth(HOST_TOKEN)
            .header("if-match", "\"2\"")
            .json(&json!({"active_resume_version_id":Uuid::new_v4()}))
            .send()
            .await
            .unwrap()
            .status(),
        422
    );
    assert_eq!(
        http.post(&target)
            .bearer_auth(HOST_TOKEN)
            .json(&profile_body())
            .send()
            .await
            .unwrap()
            .status(),
        405
    );
    let unchanged = http
        .patch(&target)
        .bearer_auth(HOST_TOKEN)
        .header("if-match", "\"2\"")
        .json(&changed)
        .send()
        .await
        .unwrap();
    assert_eq!(unchanged.status(), 200);
    assert_eq!(unchanged.headers()["etag"], "\"2\"");
    assert_eq!(
        unchanged.json::<Value>().await.unwrap()["updated_at"],
        saved["updated_at"]
    );
    let retained: Uuid =
        sqlx::query_scalar("SELECT active_resume_version_id FROM candidate_profiles WHERE id=$1")
            .bind(id)
            .fetch_one(&mut c)
            .await
            .unwrap();
    assert_eq!(retained, resume);
    stop.cancel();
    server.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn profile_concurrent_cas_allows_one_save_and_preserves_confirmation_history() {
    let mut c = profile_fixture().await;
    let mut other = connection().await;
    let before: Value = sqlx::query_scalar(
        "SELECT value FROM owner_preferences WHERE key='phase1_profile_confirmation'",
    )
    .fetch_one(&mut c)
    .await
    .unwrap();
    let (a, b) = tokio::join!(
        profile_store::save(
            &mut c,
            json!({"preferences":{"notice_period_days":10}}),
            Some(4),
            true,
            false
        ),
        profile_store::save(
            &mut other,
            json!({"preferences":{"notice_period_days":20}}),
            Some(4),
            true,
            false
        )
    );
    assert_ne!(a.is_ok(), b.is_ok());
    assert_eq!(
        a.err().or(b.err()),
        Some(Failure("profile_version_conflict"))
    );
    let saved = profile_store::get(&mut c).await.unwrap();
    assert_eq!(saved.version, 5);
    assert_eq!(saved.value["verified_skills"], json!(["Rust"]));
    let after: Value = sqlx::query_scalar(
        "SELECT value FROM owner_preferences WHERE key='phase1_profile_confirmation'",
    )
    .fetch_one(&mut c)
    .await
    .unwrap();
    assert_eq!(after, before);
    assert!(knowledge::reviewed_profile(&mut c).await.unwrap().is_none());
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn profile_validation_and_commit_failures_roll_back_before_ack() {
    let mut c = profile_fixture().await;
    sqlx::raw_sql("CREATE OR REPLACE FUNCTION fixture_invalid_profile() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN NEW.email='invalid-email'; RETURN NEW; END $$; CREATE TRIGGER fixture_invalid_profile BEFORE UPDATE ON candidate_profiles FOR EACH ROW EXECUTE FUNCTION fixture_invalid_profile()").execute(&mut c).await.unwrap();
    let result = profile_store::save(
        &mut c,
        json!({"summary":"Verified implementation"}),
        Some(4),
        true,
        false,
    )
    .await;
    assert_eq!(result.err(), Some(Failure("invalid_profile_input")));
    let saved = profile_store::get(&mut c).await.unwrap();
    assert_eq!(saved.version, 4);
    assert!(saved.value["summary"].is_null());
    sqlx::raw_sql("DROP TRIGGER fixture_invalid_profile ON candidate_profiles; CREATE OR REPLACE FUNCTION fixture_profile_commit_refusal() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'fixture_commit_refused'; END $$; CREATE CONSTRAINT TRIGGER fixture_profile_commit_refusal AFTER UPDATE ON candidate_profiles DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION fixture_profile_commit_refusal()").execute(&mut c).await.unwrap();
    let result = profile_store::save(
        &mut c,
        json!({"summary":"Verified implementation"}),
        Some(4),
        true,
        false,
    )
    .await;
    assert_eq!(result.err(), Some(Failure("profile_database_error")));
    let saved = profile_store::get(&mut c).await.unwrap();
    assert_eq!(saved.version, 4);
    assert!(saved.value["summary"].is_null());
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn profile_legacy_normalization_requires_version_and_does_not_silently_rewrite_facts() {
    let mut c = profile_fixture().await;
    sqlx::query("UPDATE candidate_profiles SET full_name='  Fictional   Person  ',updated_at='2026-11-14T03:04:05.123000Z'").execute(&mut c).await.unwrap();
    let original = profile_store::get(&mut c).await.unwrap();
    assert_eq!(original.value["full_name"], "Fictional   Person");
    assert_eq!(original.value["updated_at"], "2026-11-14T03:04:05.123000Z");
    let mut body = original.value.clone();
    for key in ["id", "singleton_key", "version", "created_at", "updated_at"] {
        body.as_object_mut().unwrap().remove(key);
    }
    assert_eq!(
        original.value["preferences"]["current_compensation"]["amount"],
        "999"
    );
    let result = profile_store::save(&mut c, body.clone(), None, false, false).await;
    assert_eq!(result.err(), Some(Failure("profile_version_required")));
    let numeric:bool=sqlx::query_scalar("SELECT jsonb_typeof(preferences->'current_compensation'->'amount')='number' FROM candidate_profiles").fetch_one(&mut c).await.unwrap();
    assert!(numeric);
    let updated = profile_store::save(&mut c, body.clone(), Some(4), false, false)
        .await
        .unwrap();
    assert_eq!(updated.version, 5);
    let unchanged = profile_store::save(&mut c, body, None, false, false)
        .await
        .unwrap();
    assert_eq!(unchanged.version, 5);
    assert_eq!(unchanged.value["updated_at"], updated.value["updated_at"]);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn profile_live_input_and_complete_merged_bound_are_checked_without_saves() {
    let mut c = profile_fixture().await;
    let blocked = profile_store::save(&mut c, json!({"summary":"TODO"}), Some(4), true, true).await;
    assert_eq!(
        blocked.err(),
        Some(Failure("fictional_or_placeholder_profile_rejected"))
    );
    let accepted = profile_store::save(
        &mut c,
        json!({"summary":"Verified implementation"}),
        Some(4),
        true,
        true,
    )
    .await
    .unwrap();
    assert_eq!(accepted.version, 5);
    sqlx::query("UPDATE candidate_profiles SET summary=$1")
        .bind("z".repeat(4000))
        .execute(&mut c)
        .await
        .unwrap();
    let patch = json!({"projects":(0..15).map(|i|json!({"name":format!("Fictional project {i}"),"description":"x".repeat(4000)})).collect::<Vec<_>>()});
    assert!(
        profile_contract::normalize(profile_contract::Operation::Update, patch.clone()).is_ok()
    );
    assert_eq!(
        profile_store::save(&mut c, patch, Some(5), true, false)
            .await
            .err(),
        Some(Failure("profile_payload_limit"))
    );
    let retained = profile_store::get(&mut c).await.unwrap();
    assert_eq!(retained.version, 5);
    assert_eq!(retained.value["projects"], json!([]));
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn pinned_model_policy_blocks_retargeted_intake_and_missing_models_pause_without_spend() {
    use automated_apply_agents::model_policy::Policy;
    let mut c = knowledge_fixture().await;
    let mut observer = connection().await;
    let key = Uuid::new_v4();
    let policy = Policy::Cohere {
        model: "command-a-plus-05-2026".into(),
        roles: vec![Role::Discovery, Role::Review],
    };
    let limits = policy.recommended_limits();
    let saved = lifecycle::intake_policy(&mut c, key, limits.clone(), Some(policy.clone()))
        .await
        .unwrap();
    assert!(matches!(
        lifecycle::intake_policy(&mut c, key, limits.clone(), Some(Policy::Deterministic {})).await,
        Err(Failure("agent_request_key_conflict"))
    ));
    assert_eq!(
        lifecycle::intake_policy(&mut c, key, limits, Some(policy))
            .await
            .unwrap()
            .run
            .id,
        saved.run.id
    );
    let stop = CancellationToken::new();
    let shutdown = stop.clone();
    let worker = automated_apply_agents::worker::serve(&mut c, Wake::default(), shutdown);
    let control = async {
        tokio::time::timeout(Duration::from_secs(3), async {
            loop {
                let current = lifecycle::load(&mut observer, saved.run.id).await.unwrap();
                if current.run.state == State::Paused {
                    assert_eq!(
                        current.run.diagnostic.as_deref(),
                        Some("pinned_model_policy_unavailable")
                    );
                    assert_eq!(current.run.resume_state, Some(State::Ready));
                    assert!(!current.run.paused_by_global);
                    assert_eq!(current.run.usage.model_calls, 0);
                    assert_eq!(current.run.usage.tool_calls, 0);
                    assert_eq!(current.run.usage.reserved_tokens, 0);
                    break;
                }
                tokio::time::sleep(Duration::from_millis(5)).await;
            }
        })
        .await
        .unwrap();
        stop.cancel();
    };
    let (result, ()) = tokio::join!(worker, control);
    result.unwrap();
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn saved_profile_match_http_uses_verified_facts_and_never_persists_candidate_scores() {
    let mut c = profile_fixture().await;
    let job = saved_job(&mut c, 1).await;
    sqlx::raw_sql("ALTER TABLE jobs ADD COLUMN match_score double precision,ADD COLUMN match_explanation text").execute(&mut c).await.unwrap();
    sqlx::query(
        "UPDATE candidate_profiles SET verified_skills='[\" Rust \",\"RUST\",\"FastAPI\"]'",
    )
    .execute(&mut c)
    .await
    .unwrap();
    sqlx::query("UPDATE jobs SET skills_required=ARRAY['Rust','Python','Fast API'] WHERE id=$1")
        .bind(job)
        .execute(&mut c)
        .await
        .unwrap();
    let before:Value=sqlx::query_scalar("SELECT jsonb_build_object('job',(SELECT to_jsonb(j) FROM jobs j),'profile',(SELECT to_jsonb(p) FROM candidate_profiles p),'confirmation',(SELECT value FROM owner_preferences WHERE key='phase1_profile_confirmation'))").fetch_one(&mut c).await.unwrap();
    let (url, stop, server) = http_fixture().await;
    let http = client();
    let target = format!("{url}/api/v1/jobs/{job}/match");
    assert_eq!(
        http.post(&target)
            .json(&json!({}))
            .send()
            .await
            .unwrap()
            .status(),
        401
    );
    let response = http
        .post(&target)
        .header("authorization", format!("bearer {HOST_TOKEN}"))
        .json(&json!({"verified_skills":["Python"],"verified_experience_years":50}))
        .send()
        .await
        .unwrap();
    assert_eq!(response.status(), 200);
    assert!(response.headers().get("etag").is_none());
    let result: Value = response.json().await.unwrap();
    assert_eq!(
        result,
        json!({"job_id":job,"match_score":86.67,"matched_skills":["Rust","FastAPI"],"missing_skills":["Python"],"location_match":true,"title_match":true,"explanation":"Title relevance: 30.0/30. Skills matched (2): Rust, FastAPI. Location/Remote match: Yes (20.0/20). Seniority alignment: 10.0/10."})
    );
    let after:Value=sqlx::query_scalar("SELECT jsonb_build_object('job',(SELECT to_jsonb(j) FROM jobs j),'profile',(SELECT to_jsonb(p) FROM candidate_profiles p),'confirmation',(SELECT value FROM owner_preferences WHERE key='phase1_profile_confirmation'))").fetch_one(&mut c).await.unwrap();
    assert_eq!(before, after);
    for query in [
        "SELECT count(*) FROM rust_agent_runs",
        "SELECT count(*) FROM llm_monthly_usage",
        "SELECT count(*) FROM application_packets",
    ] {
        let count: i64 = sqlx::query_scalar(query).fetch_one(&mut c).await.unwrap();
        assert_eq!(count, 0);
    }
    stop.cancel();
    server.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn saved_profile_match_keeps_unknown_experience_and_preserves_lookup_error_order() {
    let mut c = profile_fixture().await;
    let job = saved_job(&mut c, 1).await;
    sqlx::query("UPDATE candidate_profiles SET verified_experience_years=NULL,verified_skills='[]',preferences='{}'").execute(&mut c).await.unwrap();
    sqlx::query("UPDATE jobs SET skills_required=ARRAY[]::text[] WHERE id=$1")
        .bind(job)
        .execute(&mut c)
        .await
        .unwrap();
    let (url, stop, server) = http_fixture().await;
    let http = client();
    let target = format!("{url}/api/v1/jobs/{job}/match");
    let result: Value = http
        .post(&target)
        .bearer_auth(HOST_TOKEN)
        .send()
        .await
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(result["match_score"], 0.0);
    assert_eq!(result["matched_skills"], json!([]));
    assert!(
        result["explanation"]
            .as_str()
            .unwrap()
            .contains("Experience is unknown; no seniority points awarded.")
    );
    let wrong_method = http
        .put(&target)
        .bearer_auth(HOST_TOKEN)
        .send()
        .await
        .unwrap();
    assert_eq!(wrong_method.status(), 405);
    assert_eq!(wrong_method.headers()["allow"], "GET, POST");
    assert_eq!(
        http.post(format!("{url}/api/v1/jobs/not-a-uuid/match"))
            .bearer_auth(HOST_TOKEN)
            .send()
            .await
            .unwrap()
            .status(),
        422
    );
    sqlx::query("DELETE FROM candidate_profiles")
        .execute(&mut c)
        .await
        .unwrap();
    let no_job = http
        .post(format!("{url}/api/v1/jobs/{}/match", Uuid::new_v4()))
        .bearer_auth(HOST_TOKEN)
        .send()
        .await
        .unwrap();
    assert_eq!(no_job.status(), 404);
    assert_eq!(
        no_job.json::<Value>().await.unwrap()["detail"],
        "Job not found"
    );
    let no_profile = http
        .post(&target)
        .bearer_auth(HOST_TOKEN)
        .send()
        .await
        .unwrap();
    assert_eq!(no_profile.status(), 404);
    assert_eq!(
        no_profile.json::<Value>().await.unwrap()["detail"],
        "No candidate profile saved"
    );
    stop.cancel();
    server.await.unwrap();
}

async fn confirmation_fixture() -> PgConnection {
    let mut c = knowledge_fixture().await;
    sqlx::raw_sql("ALTER TABLE owner_preferences ADD COLUMN created_at timestamptz NOT NULL DEFAULT clock_timestamp(),ADD COLUMN updated_at timestamptz NOT NULL DEFAULT clock_timestamp()").execute(&mut c).await.unwrap();
    c
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn owner_profile_confirmation_commits_exact_version_and_repeated_review_preserves_recheck_progress()
 {
    let mut c = confirmation_fixture().await;
    sqlx::query("DELETE FROM owner_preferences WHERE key='phase1_profile_confirmation'")
        .execute(&mut c)
        .await
        .unwrap();
    sqlx::query("INSERT INTO owner_preferences(key,value) VALUES ('fixture_quotas','{\"hourly\":1,\"lifetime_allowed\":3,\"consumed\":3}')").execute(&mut c).await.unwrap();
    let (url, stop, server) = http_fixture().await;
    let http = client();
    let target = format!("{url}/api/v1/local-agent/profile-confirmation");
    let request = json!({"expected_version":"4.0","owner_confirmed":true});
    assert_eq!(
        http.post(&target)
            .json(&request)
            .send()
            .await
            .unwrap()
            .status(),
        401
    );
    assert_eq!(
        http.post(&target)
            .bearer_auth(HOST_TOKEN)
            .header("x-agent-client", "extension")
            .json(&request)
            .send()
            .await
            .unwrap()
            .status(),
        403
    );
    for bad in [
        json!({"expected_version":4,"owner_confirmed":false}),
        json!({"expected_version":4,"owner_confirmed":"true"}),
        json!({"expected_version":4,"owner_confirmed":true,"submit":true}),
    ] {
        assert_eq!(
            http.post(&target)
                .bearer_auth(HOST_TOKEN)
                .json(&bad)
                .send()
                .await
                .unwrap()
                .status(),
            422
        );
    }
    assert_eq!(
        http.post(&target)
            .bearer_auth(HOST_TOKEN)
            .json(&json!({"expected_version":3,"owner_confirmed":true}))
            .send()
            .await
            .unwrap()
            .status(),
        409
    );
    let response = http
        .post(&target)
        .bearer_auth(HOST_TOKEN)
        .json(&request)
        .send()
        .await
        .unwrap();
    assert_eq!(response.status(), 200);
    let confirmed: Value = response.json().await.unwrap();
    assert_eq!(confirmed["profile_id"], json!(profile_pin().id));
    assert_eq!(confirmed["profile_version"], 4);
    assert!(
        chrono::DateTime::parse_from_rfc3339(confirmed["confirmed_at"].as_str().unwrap()).is_ok()
    );
    let mut observer = connection().await;
    let saved: Value = sqlx::query_scalar(
        "SELECT value FROM owner_preferences WHERE key='phase1_profile_confirmation'",
    )
    .fetch_one(&mut observer)
    .await
    .unwrap();
    assert_eq!(saved, confirmed);
    assert!(
        knowledge::reviewed_profile(&mut observer)
            .await
            .unwrap()
            .is_some()
    );
    let mut recheck: Value =
        sqlx::query_scalar("SELECT value FROM owner_preferences WHERE key='apply_filter_recheck'")
            .fetch_one(&mut observer)
            .await
            .unwrap();
    assert_eq!(recheck["status"], "pending");
    assert_eq!(recheck["reason"], "owner_profile_version_confirmed");
    assert_eq!(recheck["checked"], 0);
    recheck["checked"] = json!(7);
    recheck["fresh_reads"] = json!(3);
    recheck["cursor"] = json!("fixture-progress");
    sqlx::query("UPDATE owner_preferences SET value=$1 WHERE key='apply_filter_recheck'")
        .bind(&recheck)
        .execute(&mut observer)
        .await
        .unwrap();
    let repeat = http
        .post(&target)
        .bearer_auth(HOST_TOKEN)
        .json(&json!({"expected_version":4.0,"owner_confirmed":1}))
        .send()
        .await
        .unwrap();
    assert_eq!(repeat.status(), 200);
    let retained: Value =
        sqlx::query_scalar("SELECT value FROM owner_preferences WHERE key='apply_filter_recheck'")
            .fetch_one(&mut observer)
            .await
            .unwrap();
    assert_eq!(retained, recheck);
    let quotas: Value =
        sqlx::query_scalar("SELECT value FROM owner_preferences WHERE key='fixture_quotas'")
            .fetch_one(&mut observer)
            .await
            .unwrap();
    assert_eq!(
        quotas,
        json!({"hourly":1,"lifetime_allowed":3,"consumed":3})
    );
    for query in [
        "SELECT count(*) FROM application_packets",
        "SELECT count(*) FROM rust_agent_runs",
        "SELECT count(*) FROM llm_monthly_usage",
    ] {
        let count: i64 = sqlx::query_scalar(query)
            .fetch_one(&mut observer)
            .await
            .unwrap();
        assert_eq!(count, 0);
    }
    stop.cancel();
    server.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn owner_profile_confirmation_cannot_confirm_a_version_changed_under_row_lock() {
    use automated_apply_agents::profile_confirmation::{self, Confirmation};
    let mut c = confirmation_fixture().await;
    let mut other = connection().await;
    let original: Value = sqlx::query_scalar(
        "SELECT value FROM owner_preferences WHERE key='phase1_profile_confirmation'",
    )
    .fetch_one(&mut c)
    .await
    .unwrap();
    let mut tx = other.begin().await.unwrap();
    sqlx::query("UPDATE candidate_profiles SET version=5 WHERE singleton_key='primary'")
        .execute(&mut *tx)
        .await
        .unwrap();
    let input: Confirmation =
        serde_json::from_value(json!({"expected_version":4,"owner_confirmed":true})).unwrap();
    let writer = async {
        tokio::time::sleep(Duration::from_millis(20)).await;
        tx.commit().await.unwrap();
    };
    let (result, ()) = tokio::join!(profile_confirmation::confirm(&mut c, input), writer);
    assert_eq!(
        result,
        Err(Failure("profile_changed_review_current_version"))
    );
    let after: Value = sqlx::query_scalar(
        "SELECT value FROM owner_preferences WHERE key='phase1_profile_confirmation'",
    )
    .fetch_one(&mut c)
    .await
    .unwrap();
    assert_eq!(after, original);
    assert!(knowledge::reviewed_profile(&mut c).await.unwrap().is_none());
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn profile_confirmation_and_recheck_roll_back_together_if_recheck_cannot_commit() {
    use automated_apply_agents::profile_confirmation::{self, Confirmation};
    let mut c = confirmation_fixture().await;
    sqlx::raw_sql("DELETE FROM owner_preferences WHERE key='phase1_profile_confirmation';ALTER TABLE owner_preferences ADD CONSTRAINT fixture_recheck_refusal CHECK(key<>'apply_filter_recheck')").execute(&mut c).await.unwrap();
    let input: Confirmation =
        serde_json::from_value(json!({"expected_version":4,"owner_confirmed":true})).unwrap();
    assert_eq!(
        profile_confirmation::confirm(&mut c, input).await,
        Err(Failure("profile_database_error"))
    );
    let count:i64=sqlx::query_scalar("SELECT count(*) FROM owner_preferences WHERE key IN ('phase1_profile_confirmation','apply_filter_recheck')").fetch_one(&mut c).await.unwrap();
    assert_eq!(count, 0);
    let version: i32 =
        sqlx::query_scalar("SELECT version FROM candidate_profiles WHERE singleton_key='primary'")
            .fetch_one(&mut c)
            .await
            .unwrap();
    assert_eq!(version, 4);
}

include!("support/packet_tracking_pg.rs");

include!("support/public_discovery_pg.rs");
include!("support/feed_ingestion_pg.rs");
include!("support/discovery_schedule_pg.rs");

include!("support/local_socket_pg.rs");

include!("support/mailboxes_pg.rs");

include!("support/mail_read_draft_pg.rs");

include!("support/resume_review_pg.rs");
include!("support/browser_profiles_pg.rs");
include!("support/browser_commands_pg.rs");
include!("support/browser_tasks_pg.rs");
include!("support/browser_forms_pg.rs");
include!("support/execution_status_pg.rs");
include!("support/execution_control_pg.rs");
include!("support/execution_queue_pg.rs");
include!("support/execution_submission_pg.rs");
include!("support/execution_preparation_pg.rs");
include!("support/execution_profile_policy_pg.rs");
include!("support/owner_snapshot_pg.rs");

include!("support/profile_sync_work_pg.rs");

include!("support/execution_search_pg.rs");

include!("support/execution_reconsideration_pg.rs");

include!("support/listing_observation_pg.rs");

include!("support/questionnaire_steps_pg.rs");

include!("support/queue_owner_questions_pg.rs");

include!("support/questionnaire_preparation_pg.rs");

include!("support/reconciliation_bounds_pg.rs");

include!("support/naukri_native_pg.rs");

include!("support/queue_schedule_pg.rs");
include!("support/execution_owner_pg.rs");
include!("support/execution_questions_pg.rs");
include!("support/execution_summary_pg.rs");
include!("support/owner_import_pg.rs");
include!("support/legacy_preparation_pg.rs");
include!("support/retained_index_pg.rs");
include!("support/telegram_questions_pg.rs");
include!("support/telegram_owner_commands_pg.rs");
include!("support/telegram_browser_commands_pg.rs");
include!("support/telegram_local_pg.rs");
include!("support/telegram_reconciliation_pg.rs");
include!("support/gmail_history_pg.rs");
include!("support/gmail_accounts_pg.rs");
include!("support/gmail_read_oauth_pg.rs");
include!("support/gmail_sync_pg.rs");
include!("support/gmail_lead_import_pg.rs");
include!("support/gmail_alerts_pg.rs");
include!("support/gmail_workspace_pg.rs");
include!("support/gmail_workspace_account_pg.rs");
include!("support/gmail_workspace_dispatch_pg.rs");
include!("support/gmail_legacy_pg.rs");
include!("support/gmail_legacy_oauth_pg.rs");
include!("support/contacts_pg.rs");
include!("support/contact_correction_pg.rs");
