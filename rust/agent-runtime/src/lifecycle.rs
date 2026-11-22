//! Owner lifecycle for an authenticated host. Controls fence stale workers without policy changes.
use crate::{
    Failure, Result,
    contracts::*,
    engine,
    knowledge::{self, ProfilePin},
    postgres::Store,
    questions::{self, Question},
};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use sqlx::{Connection, PgConnection, Row};
use uuid::Uuid;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum Mode {
    Stopped,
    Paused,
    Running,
}
impl Mode {
    fn text(self) -> &'static str {
        match self {
            Self::Stopped => "STOPPED",
            Self::Paused => "PAUSED",
            Self::Running => "RUNNING",
        }
    }
}
#[derive(Serialize)]
pub struct Control {
    pub mode: Mode,
    pub revision: i64,
    pub worker_online: bool,
}
#[derive(Debug, Clone, Copy, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Action {
    Pause,
    Resume,
    Stop,
}
pub struct Stored {
    pub run: Run,
    pub revision: i64,
}

pub async fn control(connection: &mut PgConnection) -> Result<Control> {
    let row=sqlx::query("SELECT mode,revision,COALESCE(heartbeat_at>clock_timestamp()-interval '45 seconds',false) AS online FROM rust_agent_control WHERE key='primary'").fetch_one(connection).await.map_err(db)?;
    let raw: String = row.try_get("mode").map_err(db)?;
    let mode = match raw.as_str() {
        "STOPPED" => Mode::Stopped,
        "PAUSED" => Mode::Paused,
        "RUNNING" => Mode::Running,
        _ => return Err(Failure("invalid_worker_control")),
    };
    Ok(Control {
        mode,
        revision: row.try_get("revision").map_err(db)?,
        worker_online: row.try_get("online").map_err(db)?,
    })
}
pub async fn heartbeat(connection: &mut PgConnection) -> Result<()> {
    sqlx::query("UPDATE rust_agent_control SET heartbeat_at=clock_timestamp() WHERE key='primary'")
        .execute(connection)
        .await
        .map_err(db)?;
    Ok(())
}
pub async fn load(connection: &mut PgConnection, id: Uuid) -> Result<Stored> {
    let row =
        sqlx::query("SELECT run,revision FROM rust_agent_runs WHERE id=$1 AND owner='primary'")
            .bind(id)
            .fetch_optional(connection)
            .await
            .map_err(db)?
            .ok_or(Failure("agent_run_not_found"))?;
    decode(row)
}
fn decode(row: sqlx::postgres::PgRow) -> Result<Stored> {
    Ok(Stored {
        run: serde_json::from_value(row.try_get("run").map_err(db)?)
            .map_err(|_| Failure("invalid_agent_record"))?,
        revision: row.try_get("revision").map_err(db)?,
    })
}
async fn persist(connection: &mut PgConnection, stored: &mut Stored) -> Result<()> {
    let body = serde_json::to_value(&stored.run).map_err(|_| Failure("invalid_agent_record"))?;
    let row=sqlx::query("WITH updated AS (UPDATE rust_agent_runs SET run=$1,revision=revision+1,lease_token=NULL,lease_until=NULL,updated_at=clock_timestamp() WHERE id=$2 AND owner='primary' AND revision=$3 RETURNING id,revision) INSERT INTO rust_agent_events(run_id,revision,role,state,model_calls,tool_calls,reserved_tokens,decision_calls,graph_node,graph_iteration,approval_required) SELECT id,revision,$4,$5,$6,$7,$8,$9,$10,$11,$12 FROM updated RETURNING revision")
        .bind(body).bind(stored.run.id).bind(stored.revision).bind(enum_text(stored.run.role)).bind(enum_text(stored.run.state))
        .bind(i32::from(stored.run.usage.model_calls)).bind(i32::from(stored.run.usage.tool_calls)).bind(stored.run.usage.reserved_tokens as i32).bind(i32::from(stored.run.usage.decision_calls))
        .bind(enum_text(crate::graph::node(&stored.run))).bind(i32::from(stored.run.graph.iterations)).bind(stored.run.state==State::WaitingApproval)
        .fetch_optional(connection).await.map_err(db)?.ok_or(Failure("agent_revision_conflict"))?;
    stored.revision = row.try_get("revision").map_err(db)?;
    Ok(())
}
fn enum_text(value: impl Serialize) -> String {
    serde_json::to_value(value)
        .unwrap()
        .as_str()
        .unwrap()
        .to_owned()
}
async fn lock(connection: &mut PgConnection) -> Result<()> {
    sqlx::query("SELECT pg_advisory_xact_lock(166001,50)")
        .execute(connection)
        .await
        .map_err(db)?;
    Ok(())
}

pub fn pause(run: &mut Run, global: bool) -> Result<()> {
    if run.state == State::Paused {
        if !global {
            run.paused_by_global = false;
        }
        return Ok(());
    }
    if matches!(
        run.state,
        State::Completed | State::Failed | State::Stopped | State::OutcomeUnknown
    ) {
        return Err(Failure("invalid_agent_control"));
    }
    engine::recover(run);
    if run.state == State::OutcomeUnknown {
        return Ok(());
    }
    run.resume_state = Some(run.state);
    run.state = State::Paused;
    run.paused_by_global = global;
    Ok(())
}
pub fn resume(run: &mut Run) -> Result<()> {
    if run.state != State::Paused {
        return Err(Failure("invalid_agent_control"));
    }
    let state = run
        .resume_state
        .filter(|s| {
            matches!(
                s,
                State::Ready | State::ToolPending | State::WaitingOwner | State::WaitingApproval
            )
        })
        .ok_or(Failure("agent_reconciliation_required"))?;
    run.state = state;
    run.resume_state = None;
    run.paused_by_global = false;
    Ok(())
}
fn stop(run: &mut Run) {
    if matches!(
        run.state,
        State::Completed | State::Failed | State::Stopped | State::OutcomeUnknown
    ) {
        return;
    }
    if run.state == State::ToolRunning {
        engine::recover(run);
    }
    if run.state != State::OutcomeUnknown {
        crate::graph::cancel_pending(run);
        run.state = State::Stopped;
        run.diagnostic = Some("owner_stopped".into());
        run.question = None;
    }
    run.resume_state = None;
    run.paused_by_global = false;
}

pub async fn set_control(
    connection: &mut PgConnection,
    expected: i64,
    mode: Mode,
) -> Result<Control> {
    if expected < 1 {
        return Err(Failure("invalid_revision"));
    }
    let mut transaction = connection.begin().await.map_err(db)?;
    lock(&mut transaction).await?;
    let current = control(&mut transaction).await?;
    if current.revision != expected {
        return Err(Failure("agent_control_revision_conflict"));
    }
    let rows = if mode == Mode::Running {
        sqlx::query("SELECT run,revision FROM rust_agent_runs WHERE run->>'state'='paused' AND run->'paused_by_global'='true'::jsonb ORDER BY created_at FOR UPDATE").fetch_all(&mut *transaction).await.map_err(db)?
    } else {
        sqlx::query("SELECT run,revision FROM rust_agent_runs WHERE lease_token IS NOT NULL ORDER BY created_at FOR UPDATE").fetch_all(&mut *transaction).await.map_err(db)?
    };
    for row in rows {
        let mut stored = decode(row)?;
        if mode == Mode::Running {
            resume(&mut stored.run)?;
        } else if !matches!(
            stored.run.state,
            State::Completed | State::Failed | State::Stopped | State::OutcomeUnknown
        ) {
            pause(&mut stored.run, true)?;
        }
        persist(&mut transaction, &mut stored).await?;
    }
    sqlx::query("UPDATE rust_agent_control SET mode=$1,revision=revision+1,updated_at=clock_timestamp() WHERE key='primary'").bind(mode.text()).execute(&mut *transaction).await.map_err(db)?;
    sqlx::query("INSERT INTO rust_agent_control_events(revision,mode)VALUES($1,$2)")
        .bind(current.revision + 1)
        .bind(mode.text())
        .execute(&mut *transaction)
        .await
        .map_err(db)?;
    transaction.commit().await.map_err(db)?;
    control(connection).await
}
pub async fn control_run(
    connection: &mut PgConnection,
    id: Uuid,
    expected: i64,
    action: Action,
) -> Result<Stored> {
    let mut transaction = connection.begin().await.map_err(db)?;
    lock(&mut transaction).await?;
    let mut stored = load(&mut transaction, id).await?;
    if stored.revision != expected {
        return Err(Failure("agent_revision_conflict"));
    }
    match action {
        Action::Pause => pause(&mut stored.run, false)?,
        Action::Resume => resume(&mut stored.run)?,
        Action::Stop => stop(&mut stored.run),
    }
    persist(&mut transaction, &mut stored).await?;
    transaction.commit().await.map_err(db)?;
    Ok(stored)
}

pub async fn intake(
    connection: &mut PgConnection,
    request_key: Uuid,
    limits: Limits,
) -> Result<Stored> {
    intake_policy(connection, request_key, limits, None).await
}
pub async fn intake_policy(
    connection: &mut PgConnection,
    request_key: Uuid,
    limits: Limits,
    policy: Option<crate::model_policy::Policy>,
) -> Result<Stored> {
    intake_mode(connection, request_key, limits, policy, false, None).await
}

pub(crate) async fn intake_mode(
    connection: &mut PgConnection,
    request_key: Uuid,
    mut limits: Limits,
    policy: Option<crate::model_policy::Policy>,
    prepare_packet: bool,
    target_job_id: Option<Uuid>,
) -> Result<Stored> {
    if target_job_id.is_some_and(|job| !prepare_packet || job.is_nil()) {
        return Err(Failure("invalid_job_id"));
    }
    if let Some(policy) = &policy {
        policy.validate()?;
    }
    if prepare_packet {
        limits.human_review = true;
    }
    let mut run = Run::new(request_key, limits)?;
    run.prepare_packet = prepare_packet;
    run.target_job_id = target_job_id;
    run.model_policy = if prepare_packet {
        Some(crate::model_policy::Policy::Deterministic {})
    } else {
        policy
    };
    if let Some(profile) = knowledge::reviewed_profile(connection).await? {
        run.profile = Some(profile.pin);
    } else {
        run.state = State::WaitingOwner;
        run.diagnostic = Some("profile_review_required".into());
        run.question = Some(Question::new("profile_review_required")?);
    }
    let id = Store { connection }.create(&run).await?;
    load(connection, id).await
}
pub fn summary(stored: &Stored) -> Value {
    json!({"id":stored.run.id,"revision":stored.revision,"state":stored.run.state,"role":stored.run.role,"usage":stored.run.usage,"limits":stored.run.limits,"profile":stored.run.profile,"diagnostic":stored.run.diagnostic,"known_jobs":stored.run.known_jobs,"question":questions::public_question(&stored.run,stored.revision),"graph":crate::graph::summary(&stored.run),"model_policy":stored.run.model_policy,"prepare_packet":stored.run.prepare_packet,"target_job_id":stored.run.target_job_id,"scope":"saved_job_review_no_application_dispatch"})
}
pub async fn listing(connection: &mut PgConnection) -> Result<Vec<Value>> {
    let rows=sqlx::query("SELECT run,revision FROM rust_agent_runs WHERE owner='primary' ORDER BY created_at DESC,id LIMIT 50").fetch_all(connection).await.map_err(db)?;
    rows.into_iter()
        .map(|row| decode(row).map(|stored| summary(&stored)))
        .collect()
}
pub async fn events(connection: &mut PgConnection, id: Uuid) -> Result<Vec<Value>> {
    load(connection, id).await?;
    sqlx::query_scalar("SELECT to_jsonb(e) FROM (SELECT revision,role,state,model_calls,tool_calls,reserved_tokens,decision_calls,graph_node,graph_iteration,approval_required,created_at FROM rust_agent_events WHERE run_id=$1 ORDER BY revision DESC LIMIT 100) e")
        .bind(id).fetch_all(connection).await.map_err(db)
}
fn reset_after_fact(run: &mut Run, profile: ProfilePin) -> Result<()> {
    if run.profile.as_ref().is_some_and(|old| old.id != profile.id) {
        return Err(Failure("verified_profile_identity_changed"));
    }
    if run.context.iter().any(|c| !c.tool.repeatable())
        || run
            .pending
            .as_ref()
            .is_some_and(|e| !e.call.name.repeatable())
    {
        return Err(Failure("agent_reconciliation_required"));
    }
    run.profile = Some(profile);
    crate::graph::cancel_pending(run);
    run.graph.revision = run
        .graph
        .revision
        .checked_add(1)
        .ok_or(Failure("agent_replan_limit"))?;
    run.graph.node = crate::graph::Node::Planning;
    run.role = Role::Discovery;
    run.state = State::Ready;
    run.question = None;
    run.pending = None;
    run.diagnostic = None;
    run.context.clear();
    run.evidence.clear();
    run.known_jobs.clear();
    Ok(())
}
pub async fn resolve_question(
    connection: &mut PgConnection,
    id: Uuid,
    expected: i64,
    question_id: Uuid,
    profile: &ProfilePin,
) -> Result<Stored> {
    let mut transaction = connection.begin().await.map_err(db)?;
    lock(&mut transaction).await?;
    let mut stored = load(&mut transaction, id).await?;
    if stored.revision != expected {
        return Err(Failure("agent_revision_conflict"));
    }
    let question = stored
        .run
        .question
        .as_ref()
        .filter(|q| q.id == question_id && stored.run.state == State::WaitingOwner)
        .ok_or(Failure("agent_question_not_pending"))?;
    let known = questions::known(&mut transaction, question)
        .await?
        .ok_or(Failure("owner_fact_not_confirmed"))?;
    if &known != profile {
        return Err(Failure("verified_profile_context_changed"));
    }
    reset_after_fact(&mut stored.run, known)?;
    persist(&mut transaction, &mut stored).await?;
    transaction.commit().await.map_err(db)?;
    Ok(stored)
}
pub async fn pending_questions(connection: &mut PgConnection) -> Result<Vec<Value>> {
    let rows=sqlx::query("SELECT run,revision FROM rust_agent_runs WHERE run->>'state'='waiting_owner' ORDER BY created_at,id LIMIT 50").fetch_all(&mut *connection).await.map_err(db)?;
    let mut pending = Vec::new();
    for row in rows {
        let stored = decode(row)?;
        if let Some(question) = &stored.run.question
            && questions::known(connection, question).await?.is_none()
            && let Some(public) = questions::public_question(&stored.run, stored.revision)
        {
            pending.push(public);
        }
    }
    Ok(pending)
}
/// Existing confirmed facts can unblock a read-only workflow without asking the owner again.
pub async fn reconcile_known_questions(connection: &mut PgConnection) -> Result<usize> {
    if control(connection).await?.mode != Mode::Running {
        return Ok(0);
    }
    let rows=sqlx::query("SELECT run,revision FROM rust_agent_runs WHERE run->>'state'='waiting_owner' ORDER BY question_checked_at NULLS FIRST,created_at,id LIMIT 10").fetch_all(&mut *connection).await.map_err(db)?;
    let mut count = 0;
    for row in rows {
        let stored = decode(row)?;
        // Only scheduling metadata changes here; no budget, fact or authority is altered.
        sqlx::query("UPDATE rust_agent_runs SET question_checked_at=clock_timestamp() WHERE id=$1 AND revision=$2")
            .bind(stored.run.id).bind(stored.revision).execute(&mut *connection).await.map_err(db)?;
        if let Some(question) = &stored.run.question
            && let Some(profile) = questions::known(connection, question).await?
        {
            match resolve_question(
                connection,
                stored.run.id,
                stored.revision,
                question.id,
                &profile,
            )
            .await
            {
                Ok(_) => count += 1,
                Err(Failure(
                    "agent_revision_conflict"
                    | "agent_reconciliation_required"
                    | "verified_profile_identity_changed"
                    | "agent_question_not_pending"
                    | "verified_profile_context_changed"
                    | "owner_fact_not_confirmed",
                )) => {}
                Err(error) => return Err(error),
            }
        }
    }
    Ok(count)
}
fn db(_: sqlx::Error) -> Failure {
    Failure("agent_database_error")
}
pub async fn approve(
    connection: &mut PgConnection,
    id: Uuid,
    expected: i64,
    approval_id: Uuid,
    decision: crate::graph::Decision,
    actor: crate::graph::Actor,
) -> Result<Stored> {
    let mut tx = connection.begin().await.map_err(db)?;
    lock(&mut tx).await?;
    let mut stored = load(&mut tx, id).await?;
    if stored.revision != expected {
        return Err(Failure("agent_revision_conflict"));
    }
    if matches!(decision, crate::graph::Decision::Approve) {
        let current = knowledge::reviewed_profile(&mut tx)
            .await?
            .ok_or(Failure("profile_review_required"))?;
        if stored.run.profile.as_ref() != Some(&current.pin) {
            return Err(Failure("agent_approval_context_changed"));
        }
    }
    let now: i64 = sqlx::query_scalar("SELECT EXTRACT(EPOCH FROM clock_timestamp())::bigint")
        .fetch_one(&mut *tx)
        .await
        .map_err(db)?;
    crate::graph::decide(&mut stored.run, approval_id, decision, actor, now)?;
    persist(&mut tx, &mut stored).await?;
    tx.commit().await.map_err(db)?;
    Ok(stored)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn stop_preserves_terminal_history_and_failure_diagnostics() {
        for state in [
            State::Completed,
            State::Failed,
            State::Stopped,
            State::OutcomeUnknown,
        ] {
            let mut run = Run::new(Uuid::new_v4(), Limits::default()).unwrap();
            run.state = state;
            run.diagnostic = Some("retained_history".into());
            stop(&mut run);
            assert_eq!(run.state, state);
            assert_eq!(run.diagnostic.as_deref(), Some("retained_history"));
        }
    }
}
