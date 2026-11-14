//! One durable worker, no pool or model process. The host supplies its existing DB connection.
use crate::{
    Failure, Result,
    contracts::State,
    knowledge_tools::KnowledgeTools,
    lifecycle::{self, Mode},
    planner::{HybridPlanner, SavedReviewPlanner},
    postgres::Store,
    runner,
};
use sqlx::PgConnection;
use std::{sync::Arc, time::Duration};
use tokio::sync::{Notify, broadcast};
use tokio_util::sync::CancellationToken;
use uuid::Uuid;

#[derive(Clone)]
pub struct Wake {
    changed: broadcast::Sender<Option<Uuid>>,
    work: Arc<Notify>,
}
impl Default for Wake {
    fn default() -> Self {
        Self {
            changed: broadcast::channel(64).0,
            work: Arc::new(Notify::new()),
        }
    }
}
impl Wake {
    /// Call only after the owner control transaction commits. Cancels an in-flight wait.
    pub fn controls_changed(&self) {
        let _ = self.changed.send(None);
    }
    pub fn run_changed(&self, id: Uuid) {
        let _ = self.changed.send(Some(id));
    }
    /// Intake does not interrupt another job's already reserved work.
    pub fn work_available(&self) {
        self.work.notify_one();
    }
}

/// No DDL, new connection, provider request, browser, Telegram or application dispatch.
/// A DB error returns a sanitized failure to the host; leases and budgets stay durable.
pub async fn serve(
    connection: &mut PgConnection,
    wake: Wake,
    shutdown: CancellationToken,
) -> Result<()> {
    serve_with_telegram(connection, wake, shutdown, None).await
}
pub async fn serve_with_telegram(
    connection: &mut PgConnection,
    wake: Wake,
    shutdown: CancellationToken,
    telegram: Option<crate::telegram::Settings>,
) -> Result<()> {
    serve_with_model(connection, wake, shutdown, telegram, None).await
}
pub async fn serve_with_model(
    connection: &mut PgConnection,
    wake: Wake,
    shutdown: CancellationToken,
    telegram: Option<crate::telegram::Settings>,
    reviewer: Option<crate::provider::CohereModel>,
) -> Result<()> {
    let mut changes = wake.changed.subscribe();
    let mut last_heartbeat = None;
    loop {
        if shutdown.is_cancelled() {
            return quiesce(connection).await;
        }
        if last_heartbeat
            .is_none_or(|last: tokio::time::Instant| last.elapsed() >= Duration::from_secs(5))
        {
            lifecycle::heartbeat(connection).await?;
            last_heartbeat = Some(tokio::time::Instant::now());
        }
        let control = lifecycle::control(connection).await?;
        if control.mode == Mode::Running {
            lifecycle::reconcile_known_questions(connection).await?;
            let mut store = Store { connection };
            if let Some(mut lease) = store.claim().await? {
                // Old notifications are hints. Every tick checks the persisted lease
                // before dispatch, so a control committed during claim is still fenced.
                for _ in 0..65 {
                    if matches!(
                        changes.try_recv(),
                        Err(broadcast::error::TryRecvError::Empty
                            | broadcast::error::TryRecvError::Closed)
                    ) {
                        break;
                    }
                }
                // Intake always supplies a confirmed pin. Legacy/malformed unpinned work
                // is stopped as a factual question before any tool can run.
                if let Some(profile) = lease.run.profile.clone() {
                    let mut tools = crate::telegram::RuntimeTools {
                        knowledge: KnowledgeTools { profile },
                        telegram: telegram.clone(),
                        run_id: lease.run.id,
                    };
                    let mut model = HybridPlanner {
                        saved: SavedReviewPlanner {
                            notify: telegram.is_some(),
                        },
                        reviewer: reviewer.clone(),
                    };
                    let id = lease.run.id;
                    let tick = runner::tick(&mut store, &mut lease, &mut model, &mut tools);
                    match controlled(tick, id, &mut changes, &shutdown).await {
                        Ok(_) | Err(Failure("agent_lease_or_revision_lost")) => {}
                        Err(error) => return Err(error),
                    }
                } else {
                    lease.run.state = State::WaitingOwner;
                    lease.run.diagnostic = Some("profile_review_required".into());
                    lease.run.question =
                        Some(crate::questions::Question::new("profile_review_required")?);
                    store.save(&mut lease).await?;
                    store.release(&lease).await?;
                }
                // Yield at every boundary; a busy backlog must not starve owner controls.
                tokio::task::yield_now().await;
                continue;
            }
        }
        tokio::select! {
            biased;
            _=shutdown.cancelled()=>{},
            _=changes.recv()=>{},
            _=wake.work.notified()=>{},
            _=tokio::time::sleep(Duration::from_secs(5))=>{},
        }
    }
}
async fn controlled(
    future: impl std::future::Future<Output = Result<()>>,
    id: Uuid,
    changes: &mut broadcast::Receiver<Option<Uuid>>,
    shutdown: &CancellationToken,
) -> Result<bool> {
    tokio::pin!(future);
    loop {
        tokio::select! {
            biased;
            _=shutdown.cancelled()=>return Ok(false),
            change=changes.recv()=>match change {
                Ok(Some(other)) if other!=id=>continue,
                _=>return Ok(false),
            },
            result=&mut future=>return result.map(|()|true),
        }
    }
}
async fn quiesce(connection: &mut PgConnection) -> Result<()> {
    let current = lifecycle::control(connection).await?;
    if current.mode == Mode::Running {
        match lifecycle::set_control(connection, current.revision, Mode::Paused).await {
            Ok(_) | Err(Failure("agent_control_revision_conflict")) => {}
            Err(error) => return Err(error),
        }
    }
    sqlx::query("UPDATE rust_agent_control SET heartbeat_at=NULL WHERE key='primary'")
        .execute(connection)
        .await
        .map_err(|_| Failure("agent_database_error"))?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[tokio::test(flavor = "current_thread")]
    async fn controls_for_another_run_do_not_cancel_reserved_work() {
        let wake = Wake::default();
        let mut changes = wake.changed.subscribe();
        let id = Uuid::new_v4();
        let ready = Notify::new();
        let finish = Notify::new();
        let stop = CancellationToken::new();
        let job = async {
            ready.notify_one();
            finish.notified().await;
            Ok(())
        };
        let owner = async {
            ready.notified().await;
            wake.run_changed(Uuid::new_v4());
            tokio::task::yield_now().await;
            finish.notify_one();
        };
        let (result, ()) = tokio::join!(controlled(job, id, &mut changes, &stop), owner);
        assert_eq!(result, Ok(true));
    }
    #[tokio::test(flavor = "current_thread")]
    async fn global_and_matching_run_controls_cancel_an_inflight_wait() {
        for global in [false, true] {
            let wake = Wake::default();
            let mut changes = wake.changed.subscribe();
            let id = Uuid::new_v4();
            let stop = CancellationToken::new();
            if global {
                wake.controls_changed();
            } else {
                wake.run_changed(id);
            }
            assert_eq!(
                controlled(std::future::pending(), id, &mut changes, &stop).await,
                Ok(false)
            );
        }
    }
}
