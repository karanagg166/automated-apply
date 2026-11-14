//! One durable worker, no pool or model process. The host supplies its existing DB connection.
use crate::{
    Failure, Result,
    contracts::State,
    knowledge_tools::KnowledgeTools,
    lifecycle::{self, Mode},
    planner::SavedReviewPlanner,
    postgres::Store,
    runner,
};
use sqlx::PgConnection;
use std::{sync::Arc, time::Duration};
use tokio::sync::{Notify, watch};
use tokio_util::sync::CancellationToken;

#[derive(Clone)]
pub struct Wake {
    changed: watch::Sender<()>,
    work: Arc<Notify>,
}
impl Default for Wake {
    fn default() -> Self {
        Self {
            changed: watch::channel(()).0,
            work: Arc::new(Notify::new()),
        }
    }
}
impl Wake {
    /// Call only after the owner control transaction commits. Cancels an in-flight wait.
    pub fn controls_changed(&self) {
        self.changed.send_replace(());
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
    let mut changes = wake.changed.subscribe();
    let mut last_heartbeat = None;
    loop {
        changes.borrow_and_update();
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
                // Intake always supplies a confirmed pin. Legacy/malformed unpinned work
                // is stopped as a factual question before any tool can run.
                if let Some(profile) = lease.run.profile.clone() {
                    let mut tools = KnowledgeTools { profile };
                    let mut model = SavedReviewPlanner;
                    let tick = runner::tick(&mut store, &mut lease, &mut model, &mut tools);
                    tokio::select! {
                        biased;
                        _=shutdown.cancelled()=>{},
                        _=changes.changed()=>{},
                        result=tick=>match result {
                            Ok(())|Err(Failure("agent_lease_or_revision_lost"))=>{},
                            Err(error)=>return Err(error),
                        }
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
            _=changes.changed()=>{},
            _=wake.work.notified()=>{},
            _=tokio::time::sleep(Duration::from_secs(5))=>{},
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
