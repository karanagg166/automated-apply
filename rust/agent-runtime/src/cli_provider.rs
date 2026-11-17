//! One explicitly selected tool-free CLI writer. No login, workspace trust, setting edits or retry.
mod process;
mod protocol;
mod settings;
#[cfg(test)]
mod tests;
use crate::{
    Failure, monthly,
    provider::{WritingAttempt, writing_payload},
};
use serde_json::json;
pub(crate) use settings::CliModel;
use sqlx::PgConnection;
use std::time::Duration;
use tokio::time::Instant;
impl CliModel {
    fn arguments(&self, scratch: &std::path::Path, remaining: Duration) -> Vec<String> {
        vec![
            "--agent".into(),
            "automated-apply-answer".into(),
            "--sandbox".into(),
            "--mode".into(),
            "plan".into(),
            "--disable-slash-commands".into(),
            "--model".into(),
            self.model.clone(),
            "--effort".into(),
            self.effort.clone(),
            "--input-format".into(),
            "stream-json".into(),
            "--output-format".into(),
            "stream-json".into(),
            "--json-schema".into(),
            scratch
                .join("answer.schema.json")
                .to_string_lossy()
                .into_owned(),
            "--print-timeout".into(),
            format!("{}s", remaining.as_secs().saturating_sub(5).max(1)),
            "--log-file".into(),
            scratch.join("cli.log").to_string_lossy().into_owned(),
        ]
    }
    pub(crate) async fn write_answer(
        &self,
        connection: &mut PgConnection,
        question: &str,
        context: &serde_json::Value,
        instructions: &serde_json::Value,
        original_deadline: Option<Instant>,
    ) -> WritingAttempt {
        let mut attempt = WritingAttempt {
            attempted: false,
            content: None,
            error: None,
            input: None,
            output: None,
            retry_after: None,
        };
        let mut reservation = None;
        let result = async {
            let payload = serde_json::to_string(&writing_payload(question, context, instructions))
                .map_err(|_| Failure("invalid_answer_request"))?;
            if payload.len() > self.input {
                return Err(Failure("input_size_exceeded"));
            }
            let wire = serde_json::to_vec(&json!({"event":"user","message":{"content":payload}}))
                .map_err(|_| Failure("invalid_answer_request"))?;
            let mut wire = wire;
            wire.push(b'\n');
            let _permit = self
                .gate
                .clone()
                .try_acquire_owned()
                .map_err(|_| Failure("provider_busy"))?;
            self.verify()?;
            let month = monthly::reserve_cli(connection, self.requests).await?;
            attempt.attempted = true;
            reservation = Some(month);
            let local_deadline = Instant::now() + self.timeout + Duration::from_secs(5);
            let deadline = original_deadline
                .map(|d| d.min(local_deadline))
                .unwrap_or(local_deadline);
            let scratch = settings::scratch(self)?;
            settings::write_schema(&scratch.join("answer.schema.json"))?;
            process::discover(self, deadline.saturating_duration_since(Instant::now())).await?;
            self.verify()?;
            let remaining = deadline
                .checked_duration_since(Instant::now())
                .filter(|d| *d > Duration::from_secs(1))
                .ok_or(Failure("timeout"))?;
            let args = self.arguments(&scratch, remaining);
            let answer = process::generate(self, &args, wire, remaining).await?;
            attempt.input = answer.input;
            attempt.output = answer.output;
            monthly::tokens(
                connection,
                reservation.as_ref().expect("reserved"),
                answer.input,
                answer.output,
            )
            .await?;
            if answer.input.is_some_and(|v| v as usize > self.input)
                || answer.output.is_some_and(|v| v > self.output)
            {
                return Err(Failure("provider_usage_exceeds_reservation"));
            }
            Ok(answer.content)
        }
        .await;
        match result {
            Ok(content) => attempt.content = Some(content),
            Err(error) => {
                if error.0 == "rate_limited" {
                    attempt.retry_after = Some(60);
                    if let Some(month) = reservation.as_ref() {
                        if let Err(failure) = monthly::cooldown(connection, month, 60).await {
                            attempt.error = Some(failure);
                            return attempt;
                        }
                    }
                } else if error.0 == "provider_busy" {
                    attempt.retry_after = Some(1);
                }
                attempt.error = Some(error);
            }
        }
        attempt
    }
}
