use crate::{Failure, Result, contracts::Run};
use sqlx::{Connection, PgConnection, Row};
use uuid::Uuid;

pub struct Lease {
    pub run: Run,
    pub(crate) revision: i64,
    token: Uuid,
}
/// Borrow a single existing connection. No extra live pool, background thread or migration.
pub struct Store<'a> {
    pub connection: &'a mut PgConnection,
}
impl Store<'_> {
    pub async fn create(&mut self, run: &Run) -> Result<Uuid> {
        let value = serde_json::to_value(run).map_err(|_| Failure("invalid_agent_record"))?;
        let row=sqlx::query("INSERT INTO rust_agent_runs (id,request_key,run) VALUES ($1,$2,$3) ON CONFLICT (request_key) DO UPDATE SET request_key=EXCLUDED.request_key WHERE ('{\"human_review\":false,\"replans\":2}'::jsonb || (rust_agent_runs.run->'limits'))=('{\"human_review\":false,\"replans\":2}'::jsonb || (EXCLUDED.run->'limits')) AND COALESCE(rust_agent_runs.run->'profile','null'::jsonb)=COALESCE(EXCLUDED.run->'profile','null'::jsonb) RETURNING id")
            .bind(run.id).bind(run.request_key).bind(value).fetch_optional(&mut *self.connection).await.map_err(db_failure)?.ok_or(Failure("agent_request_key_conflict"))?;
        row.try_get("id").map_err(db_failure)
    }
    pub async fn claim(&mut self) -> Result<Option<Lease>> {
        let token = Uuid::new_v4();
        let mut transaction = self.connection.begin().await.map_err(db_failure)?;
        // Serialize admission across processes; a single active lease bounds total AI/browser work.
        sqlx::query("SELECT pg_advisory_xact_lock(166001,50)")
            .execute(&mut *transaction)
            .await
            .map_err(db_failure)?;
        sqlx::query("UPDATE rust_agent_runs SET lease_token=NULL,lease_until=NULL WHERE lease_until<clock_timestamp() AND run->>'state' NOT IN ('ready','model_running','tool_pending','tool_running')").execute(&mut *transaction).await.map_err(db_failure)?;
        let row=sqlx::query("UPDATE rust_agent_runs SET lease_token=$1,lease_until=clock_timestamp()+interval '90 seconds',revision=revision+1 WHERE id=(SELECT id FROM rust_agent_runs WHERE run->>'state' IN ('ready','model_running','tool_pending','tool_running') AND COALESCE((run->'graph'->>'not_before')::bigint,0)<=EXTRACT(EPOCH FROM clock_timestamp()) AND (lease_until IS NULL OR lease_until<clock_timestamp()) AND EXISTS(SELECT 1 FROM rust_agent_control WHERE key='primary' AND mode='RUNNING') AND NOT EXISTS (SELECT 1 FROM rust_agent_runs WHERE lease_until>clock_timestamp()) ORDER BY (lease_token IS NULL),created_at FOR UPDATE SKIP LOCKED LIMIT 1) RETURNING run,revision")
            .bind(token).fetch_optional(&mut *transaction).await.map_err(db_failure)?;
        transaction.commit().await.map_err(db_failure)?;
        row.map(|row| {
            Ok(Lease {
                run: serde_json::from_value(row.try_get("run").map_err(db_failure)?)
                    .map_err(|_| Failure("invalid_agent_record"))?,
                revision: row.try_get("revision").map_err(db_failure)?,
                token,
            })
        })
        .transpose()
    }
    pub async fn save(&mut self, lease: &mut Lease) -> Result<()> {
        let value =
            serde_json::to_value(&lease.run).map_err(|_| Failure("invalid_agent_record"))?;
        let role = serde_json::to_value(lease.run.role)
            .unwrap()
            .as_str()
            .unwrap()
            .to_owned();
        let state = serde_json::to_value(lease.run.state)
            .unwrap()
            .as_str()
            .unwrap()
            .to_owned();
        // State/budget/effect intent and sanitized audit event share the same transaction.
        let row=sqlx::query("WITH updated AS (UPDATE rust_agent_runs SET run=$1,revision=revision+1,updated_at=clock_timestamp() WHERE id=$2 AND revision=$3 AND lease_token=$4 AND lease_until>clock_timestamp() AND EXISTS(SELECT 1 FROM rust_agent_control WHERE key='primary' AND mode='RUNNING') RETURNING id,revision) INSERT INTO rust_agent_events (run_id,revision,role,state,model_calls,tool_calls,reserved_tokens,decision_calls,graph_node,graph_iteration,approval_required) SELECT id,revision,$5,$6,$7,$8,$9,$10,$11,$12,$13 FROM updated RETURNING revision")
            .bind(value).bind(lease.run.id).bind(lease.revision).bind(lease.token).bind(role).bind(state)
            .bind(i32::from(lease.run.usage.model_calls)).bind(i32::from(lease.run.usage.tool_calls)).bind(lease.run.usage.reserved_tokens as i32).bind(i32::from(lease.run.usage.decision_calls))
            .bind(serde_json::to_value(crate::graph::node(&lease.run)).unwrap().as_str().unwrap()).bind(i32::from(lease.run.graph.iterations)).bind(lease.run.state==crate::contracts::State::WaitingApproval)
            .fetch_optional(&mut *self.connection).await.map_err(db_failure)?.ok_or(Failure("agent_lease_or_revision_lost"))?;
        lease.revision = row.try_get("revision").map_err(db_failure)?;
        Ok(())
    }
    pub async fn release(&mut self, lease: &Lease) -> Result<()> {
        let rows=sqlx::query("UPDATE rust_agent_runs SET lease_token=NULL,lease_until=NULL WHERE id=$1 AND revision=$2 AND lease_token=$3 AND lease_until>clock_timestamp()")
            .bind(lease.run.id).bind(lease.revision).bind(lease.token).execute(&mut *self.connection).await.map_err(db_failure)?.rows_affected();
        if rows != 1 {
            return Err(Failure("agent_lease_or_revision_lost"));
        }
        Ok(())
    }
}
fn db_failure(_: sqlx::Error) -> Failure {
    Failure("agent_database_error")
}
