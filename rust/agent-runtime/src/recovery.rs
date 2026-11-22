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
        "execution_database_error"
            | "execution_commit_outcome_unknown"
            | "execution_read_commit_failed"
            | "execution_rollback_unconfirmed"
            | "browser_profile_database_error"
            | "browser_profile_commit_outcome_unknown"
            | "browser_profile_rollback_unconfirmed"
            | "resume_review_database_error"
            | "resume_review_commit_outcome_unknown"
            | "resume_review_rollback_unconfirmed"
            | "public_feed_database_error"
            | "public_feed_commit_outcome_unknown"
            | "telegram_database_error"
            | "packet_database_error"
            | "packet_commit_outcome_unknown"
            | "notification_preferences_outcome_unknown"
            | "provider_ledger_unavailable"
            | "profile_database_error"
            | "agent_database_error"
            | "owner_fact_database_error"
            | "verified_context_database_error"
            | "saved_jobs_database_error"
            | "dashboard_database_error"
            | "dashboard_commit_outcome_unknown"
            | "application_history_database_error"
            | "gmail_history_database_error"
            | "gmail_history_commit_outcome_unknown"
            | "gmail_history_rollback_unconfirmed"
            | "agent_database_unavailable"
            | "agent_schema_unavailable"
            | "database_host_unavailable"
    )
}
pub(crate) async fn close(connection: PgConnection) {
    let _ = tokio::time::timeout(Duration::from_secs(2), connection.close()).await;
}
/// Idle reuse threshold and bound for a retained connection's liveness probe.
pub(crate) const IDLE_PROBE_AFTER: Duration = Duration::from_secs(10);
pub(crate) const DATABASE_STALL: Duration = Duration::from_secs(15);
pub(crate) const DATABASE_BATCH_STALL: Duration = Duration::from_secs(90);
/// Bound a database step so a half-open socket (for example after the laptop's
/// network address changes) becomes a reconnectable failure instead of an
/// unbounded hang that holds the shared connection lock.
pub(crate) async fn bounded<T>(
    limit: Duration,
    step: impl std::future::Future<Output = Result<T>>,
) -> Result<T> {
    tokio::time::timeout(limit, step)
        .await
        .map_err(|_| Failure("agent_database_unavailable"))?
}
/// Cheap bounded round trip before reusing an idle retained connection.
pub(crate) async fn alive(connection: &mut PgConnection) -> Result<()> {
    bounded(DATABASE_STALL, async {
        connection
            .ping()
            .await
            .map_err(|_| Failure("agent_database_unavailable"))
    })
    .await
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
                    if let Err(error) =
                        bounded(DATABASE_STALL, server::readiness(&mut next, config)).await
                    {
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
        let result =
            worker::serve_configured(&mut current, wake.clone(), shutdown.clone(), config).await;
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

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test(flavor = "current_thread")]
    async fn stalled_database_step_becomes_reconnectable_failure() {
        let started = Instant::now();
        let result: Result<()> = bounded(Duration::from_millis(25), std::future::pending()).await;
        assert_eq!(result, Err(Failure("agent_database_unavailable")));
        assert!(database_failure(result.unwrap_err()));
        assert!(started.elapsed() < Duration::from_secs(2));
    }

    #[tokio::test(flavor = "current_thread")]
    async fn completed_database_step_passes_through_unchanged() {
        assert_eq!(
            bounded(Duration::from_secs(1), async { Ok(7) }).await,
            Ok(7)
        );
        assert_eq!(
            bounded::<()>(Duration::from_secs(1), async {
                Err(Failure("execution_database_error"))
            })
            .await,
            Err(Failure("execution_database_error"))
        );
    }

    #[test]
    fn idle_probe_precedes_stall_bound() {
        assert!(IDLE_PROBE_AFTER < DATABASE_STALL);
        assert!(DATABASE_STALL <= Duration::from_secs(30));
        assert!(DATABASE_STALL < DATABASE_BATCH_STALL);
        assert!(DATABASE_BATCH_STALL <= Duration::from_secs(120));
    }

    #[test]
    fn database_failure_classifies_gmail_history_failures() {
        for code in [
            "gmail_history_database_error",
            "gmail_history_commit_outcome_unknown",
            "gmail_history_rollback_unconfirmed",
        ] {
            assert!(database_failure(Failure(code)));
        }
    }
}
