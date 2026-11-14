//! Shared bounded reconnect policy. A failed operation is never replayed here.
use crate::{
    Failure, Result,
    configuration::Configuration,
    server,
    worker::{self, Wake},
};
use sqlx::{Connection, PgConnection};
use std::time::Duration;
use tokio::time::Instant;
use tokio_util::sync::CancellationToken;

#[derive(Default)]
pub(crate) struct Backoff {
    failures: u32,
    until: Option<Instant>,
}
impl Backoff {
    pub fn failed(&mut self) {
        let seconds = 1u64 << self.failures.min(5);
        self.until = Some(Instant::now() + Duration::from_secs(seconds.min(30)));
        self.failures = self.failures.saturating_add(1);
    }
    pub fn reset(&mut self) {
        *self = Self::default();
    }
    pub fn remaining(&self) -> Duration {
        self.until
            .map(|until| until.saturating_duration_since(Instant::now()))
            .unwrap_or_default()
    }
}
pub(crate) fn database_failure(error: Failure) -> bool {
    matches!(
        error.0,
        "telegram_database_error"
            | "agent_database_error"
            | "owner_fact_database_error"
            | "verified_context_database_error"
            | "saved_jobs_database_error"
            | "application_history_database_error"
            | "agent_database_unavailable"
            | "agent_schema_unavailable"
            | "database_host_unavailable"
    )
}
pub(crate) async fn close(connection: PgConnection) {
    let _ = tokio::time::timeout(Duration::from_secs(2), connection.close()).await;
}
/// Replace a lost execution connection in place. No extra pool, quota reset, migration
/// or tool/model replay; fresh claims still wait for durable lease expiry and recovery.
pub async fn supervise(
    config: &Configuration,
    initial: PgConnection,
    wake: Wake,
    shutdown: CancellationToken,
) -> Result<()> {
    let mut connection = Some(initial);
    let mut backoff = Backoff::default();
    loop {
        if shutdown.is_cancelled() {
            return Ok(());
        }
        if connection.is_none() {
            tokio::select! {biased;_=shutdown.cancelled()=>return Ok(()),_=tokio::time::sleep(backoff.remaining())=>{}}
            let next = tokio::select! {biased;_=shutdown.cancelled()=>return Ok(()),result=config.connect(true)=>result};
            match next {
                Ok(mut next) => {
                    if let Err(error) = server::readiness(&mut next, config).await {
                        close(next).await;
                        if !database_failure(error) {
                            return Err(error);
                        }
                        backoff.failed();
                        continue;
                    }
                    connection = Some(next);
                }
                Err(error) => {
                    if !database_failure(error) {
                        return Err(error);
                    }
                    backoff.failed();
                    continue;
                }
            }
        }
        let mut current = connection
            .take()
            .ok_or(Failure("agent_database_unavailable"))?;
        let started = Instant::now();
        let result = worker::serve_with_telegram(
            &mut current,
            wake.clone(),
            shutdown.clone(),
            config.telegram.clone(),
        )
        .await;
        close(current).await;
        match result {
            Ok(()) => return Ok(()),
            Err(error) if database_failure(error) => {
                if started.elapsed() >= Duration::from_secs(30) {
                    backoff.reset();
                }
                backoff.failed();
            }
            Err(error) => return Err(error),
        }
    }
}
