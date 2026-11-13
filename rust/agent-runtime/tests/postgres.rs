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
    sqlx::raw_sql("DROP TABLE IF EXISTS rust_agent_events; DROP TABLE IF EXISTS rust_agent_runs;")
        .execute(&mut c)
        .await
        .unwrap();
    sqlx::raw_sql(include_str!("../sql/001_runtime.sql"))
        .execute(&mut c)
        .await
        .unwrap();
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
    engine::begin_model(&mut r).unwrap();
    engine::accept(
        &mut r,
        Proposal::Tool {
            call: ToolCall {
                name: ToolName::OpenBrowser,
                job_id: Some(Uuid::new_v4()),
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
    async fn authority(&mut self, _: &ToolCall) -> Result<Authority> {
        Ok(Authority {
            prepare: true,
            inactive_owned_browser: true,
            fill: false,
            telegram_paired: false,
        })
    }
    async fn execute(&mut self, effect: &Effect) -> Result<Observation> {
        self.calls.push(effect.call.name);
        Ok(Observation {
            evidence: vec![Uuid::new_v4()],
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
