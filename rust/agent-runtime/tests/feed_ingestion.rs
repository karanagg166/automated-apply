use automated_apply_agents::{
    feed_ingestion,
    public_discovery::{self, Platform},
};
use serde_json::json;
#[test]
fn intake_requires_a_batch_token_and_cannot_accept_jobs_or_application_authority() {
    assert!(
        feed_ingestion::request(br#"{"batch_token":"00000000-0000-0000-0000-000000000001"}"#)
            .is_ok()
    );
    for value in [
        json!({}),
        json!({"batch_token":"bad"}),
        json!({"batch_token":"00000000-0000-0000-0000-000000000001","jobs":[]}),
        json!({"batch_token":"00000000-0000-0000-0000-000000000001","apply":true}),
    ] {
        assert!(feed_ingestion::request(value.to_string().as_bytes()).is_err());
    }
    assert_eq!(
        feed_ingestion::route("/api/v1/rust-agent/platforms/himalayas/ingest"),
        Some("himalayas")
    );
    assert!(feed_ingestion::route("/api/v1/rust-agent/platforms/himalayas/ingest/extra").is_none());
}
#[test]
fn saved_batch_validation_rejects_forged_destination_and_posting_age() {
    let mut batch=public_discovery::himalayas(br#"{"jobs":[{"guid":"fixture","title":"Engineer","applicationLink":"https://himalayas.app/companies/example/jobs/role"}]}"#).unwrap();
    let job = &mut batch.jobs[0];
    assert!(public_discovery::validate_saved_job(Platform::Himalayas, job).is_ok());
    job.published_at = Some("2026-11-16T00:00:00Z".into());
    assert!(public_discovery::validate_saved_job(Platform::Himalayas, job).is_err());
    job.published_at = None;
    job.application_url = "https://evil.example/job".into();
    assert!(public_discovery::validate_saved_job(Platform::Himalayas, job).is_err());
}
