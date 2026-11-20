//! One durable worker, no pool or model process. The host supplies its existing DB connection.
use crate::{
    Failure, Result,
    contracts::State,
    discovery_schedule::{self, ScheduledFetch},
    knowledge_tools::KnowledgeTools,
    lifecycle::{self, Mode},
    planner::HybridPlanner,
    postgres::{Lease, Store},
    provider::DecisionResponse,
    public_discovery::{self, Batch},
    runner,
};
use sqlx::PgConnection;
use std::{sync::Arc, time::Duration};
use tokio::sync::{Notify, broadcast};
use tokio::task::{JoinError, JoinSet};
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

/// No DDL or new connection. Explicitly enabled public discovery uses fixed endpoints;
/// it never opens a browser or dispatches applications. Owner notices retain their relay.
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
    models: Option<crate::model_policy::Models>,
) -> Result<()> {
    serve_internal(connection, wake, shutdown, telegram, models, None).await
}
pub(crate) async fn serve_configured(
    connection: &mut PgConnection,
    wake: Wake,
    shutdown: CancellationToken,
    config: &crate::configuration::Configuration,
) -> Result<()> {
    serve_internal(
        connection,
        wake,
        shutdown,
        config.telegram.clone(),
        config.models.clone(),
        Some(config),
    )
    .await
}
async fn serve_internal(
    connection: &mut PgConnection,
    wake: Wake,
    shutdown: CancellationToken,
    telegram: Option<crate::telegram::Settings>,
    models: Option<crate::model_policy::Models>,
    config: Option<&crate::configuration::Configuration>,
) -> Result<()> {
    let mut last_application_tick: Option<tokio::time::Instant> = None;
    let mut changes = wake.changed.subscribe();
    let mut last_heartbeat = None;
    let mut last_discovery: Option<tokio::time::Instant> = None;
    let mut discovery = JoinSet::new();
    let mut decisions = JoinSet::new();
    loop {
        if shutdown.is_cancelled() {
            discovery.shutdown().await;
            decisions.shutdown().await;
            return quiesce(connection).await;
        }
        if last_heartbeat
            .is_none_or(|last: tokio::time::Instant| last.elapsed() >= Duration::from_secs(5))
        {
            crate::recovery::bounded(
                crate::recovery::DATABASE_STALL,
                lifecycle::heartbeat(connection),
            )
            .await?;
            last_heartbeat = Some(tokio::time::Instant::now());
        }
        if let Some(config) = config
            && last_application_tick.is_none_or(|at| at.elapsed() >= Duration::from_secs(5))
        {
            last_application_tick = Some(tokio::time::Instant::now());
            match crate::execution::schedule::tick(connection, config).await {
                Ok(_) => {}
                Err(error) if crate::recovery::database_failure(error) => return Err(error),
                Err(error) => {
                    crate::execution::schedule::record(
                        connection,
                        "apply_schedule:naukri",
                        Some(error),
                        None,
                    )
                    .await?;
                }
            }
        }
        if let Some(finished) = discovery.try_join_next() {
            finish_discovery(connection, finished).await?;
        }
        if let Some(finished) = decisions.try_join_next() {
            finish_inference(connection, finished).await?;
        }
        let control = lifecycle::control(connection).await?;
        if control.mode == Mode::Running
            && discovery.is_empty()
            && last_discovery.is_none_or(|at| at.elapsed() >= Duration::from_secs(30))
        {
            last_discovery = Some(tokio::time::Instant::now());
            // Subscribe before reserving so a simultaneous global control change
            // also cancels the network-only task. Reservation/commit are never cancelled.
            let mut feed_changes = changes.resubscribe();
            match discovery_schedule::begin(connection).await {
                Ok(Some(fetch)) => {
                    let stop = shutdown.clone();
                    discovery.spawn(async move {
                        let result = controlled(
                            public_discovery::fetch(fetch.platform),
                            Uuid::nil(),
                            &mut feed_changes,
                            &stop,
                        )
                        .await?;
                        Some((fetch, result))
                    });
                }
                Ok(None) => {}
                Err(error) => record_discovery_error(connection, error).await?,
            }
            // Re-read persisted control before taking unrelated work.
            continue;
        }
        if control.mode == Mode::Running && decisions.is_empty() {
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
                    let mut model = match HybridPlanner::for_run(
                        lease.run.model_policy.as_ref(),
                        models.as_ref(),
                        telegram.is_some(),
                    ) {
                        Ok(model) => model,
                        Err(error) => {
                            // Restore configuration, then explicitly resume. Never silently
                            // downgrade a pinned model role or replay an uncertain effect.
                            lifecycle::pause(&mut lease.run, false)?;
                            if lease.run.state == State::Paused {
                                lease.run.diagnostic = Some(error.0.into());
                            }
                            store.save(&mut lease).await?;
                            store.release(&lease).await?;
                            continue;
                        }
                    };
                    let mut decision_changes = changes.resubscribe();
                    match runner::begin_tick(&mut store, &mut lease, &mut model, &mut tools).await {
                        Ok(Some(dispatch)) => {
                            let stop = shutdown.clone();
                            let id = lease.run.id;
                            decisions.spawn(async move {
                                let response =
                                    controlled(dispatch.send(), id, &mut decision_changes, &stop)
                                        .await?;
                                Some((lease, response))
                            });
                        }
                        Ok(None) | Err(Failure("agent_lease_or_revision_lost")) => {}
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
            _=wake.work.notified()=>{last_application_tick=None;},
            finished=discovery.join_next(), if !discovery.is_empty()=>{
                if let Some(finished)=finished {
                    finish_discovery(connection, finished).await?;
                }
            },
            finished=decisions.join_next(), if !decisions.is_empty()=>{
                if let Some(finished)=finished {
                    finish_inference(connection, finished).await?;
                }
            },
            _=tokio::time::sleep(Duration::from_secs(5))=>{},
        }
    }
}
async fn finish_inference(
    connection: &mut PgConnection,
    finished: std::result::Result<Option<(Lease, DecisionResponse)>, JoinError>,
) -> Result<()> {
    let Some((mut lease, response)) = finished.map_err(|_| Failure("agent_model_task_failed"))?
    else {
        return Ok(());
    };
    let mut store = Store { connection };
    match runner::finish_decision(&mut store, &mut lease, response).await {
        Ok(()) | Err(Failure("agent_lease_or_revision_lost")) => Ok(()),
        Err(error) => Err(error),
    }
}

type DiscoveryCompletion = Option<(ScheduledFetch, Result<Batch>)>;

async fn finish_discovery(
    connection: &mut PgConnection,
    finished: std::result::Result<DiscoveryCompletion, JoinError>,
) -> Result<()> {
    let result = match finished {
        Ok(Some((fetch, result))) => discovery_schedule::complete(connection, fetch, result).await,
        Ok(None) => Ok(()),
        Err(_) => Err(Failure("public_feed_fetch_task_failed")),
    };
    match result {
        Ok(()) => Ok(()),
        Err(error) => record_discovery_error(connection, error).await,
    }
}

async fn record_discovery_error(connection: &mut PgConnection, error: Failure) -> Result<()> {
    if crate::recovery::database_failure(error) {
        return Err(error);
    }
    discovery_schedule::record_status(connection, Some(error)).await
}

async fn controlled<T>(
    future: impl std::future::Future<Output = T>,
    id: Uuid,
    changes: &mut broadcast::Receiver<Option<Uuid>>,
    shutdown: &CancellationToken,
) -> Option<T> {
    tokio::pin!(future);
    loop {
        tokio::select! {
            biased;
            _=shutdown.cancelled()=>return None,
            change=changes.recv()=>match change {
                Ok(Some(other)) if other!=id=>continue,
                _=>return None,
            },
            result=&mut future=>return Some(result),
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
        };
        let owner = async {
            ready.notified().await;
            wake.run_changed(Uuid::new_v4());
            tokio::task::yield_now().await;
            finish.notify_one();
        };
        let (result, ()) = tokio::join!(controlled(job, id, &mut changes, &stop), owner);
        assert_eq!(result, Some(()));
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
                controlled(std::future::pending::<()>(), id, &mut changes, &stop).await,
                None
            );
        }
    }
}
