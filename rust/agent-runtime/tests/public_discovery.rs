use automated_apply_agents::public_discovery::{self, Platform};
use serde_json::json;

fn job() -> serde_json::Value {
    json!({"guid":"fictional-job-1","title":"Rust Engineer","companyName":"Example Company","applicationLink":"https://himalayas.app/companies/example/jobs/rust-engineer?utm_source=test","description":"Untrusted listing description","pubDate":1794690000,"expiryDate":1795900000,"locationRestrictions":[{"alpha2":"IN","name":"India"}],"timezoneRestrictions":["+05:30"],"categories":["Engineering"],"employmentType":"Full Time"})
}
#[test]
fn official_json_feed_preserves_unknown_counts_and_restrictions_without_authorizing_apps() {
    let bytes =
        serde_json::to_vec(&json!({"jobs":[job()],"nextCursor":"opaque-source-token"})).unwrap();
    let batch = public_discovery::himalayas(&bytes).unwrap();
    assert_eq!(batch.jobs.len(), 1);
    assert!(batch.has_more);
    assert_eq!(batch.jobs[0].applicant_count, None);
    assert_eq!(
        batch.jobs[0].source_url,
        "https://himalayas.app/companies/example/jobs/rust-engineer"
    );
    assert_eq!(batch.jobs[0].location_restrictions[0]["alpha2"], "IN");
}
#[test]
fn source_url_conflicts_are_rejected_and_identical_urls_deduplicate() {
    let mut bad = job();
    bad["applicationLink"] = json!("https://evil.example/jobs/1");
    assert!(
        public_discovery::himalayas(&serde_json::to_vec(&json!({"jobs":[bad.clone()]})).unwrap())
            .is_err()
    );
    let batch = public_discovery::himalayas(
        &serde_json::to_vec(&json!({"jobs":[job(),job(),bad]})).unwrap(),
    )
    .unwrap();
    assert_eq!(batch.jobs.len(), 1);
    assert_eq!(batch.duplicate_count, 1);
    assert_eq!(batch.skipped_invalid, 1);
}
#[test]
fn application_links_remain_exact_while_source_identity_deduplicates_tracking_variants() {
    let mut first = job();
    let original =
        "https://himalayas.app/companies/example/jobs/rust-engineer?utm_source=API&ref=a%2Fb#apply";
    first["applicationLink"] = json!(original);
    let mut duplicate = first.clone();
    duplicate["applicationLink"] =
        json!("https://himalayas.app/companies/example/jobs/rust-engineer?ref=another");
    let batch = public_discovery::himalayas(
        &serde_json::to_vec(&json!({"jobs":[first,duplicate]})).unwrap(),
    )
    .unwrap();
    assert_eq!(batch.jobs.len(), 1);
    assert_eq!(batch.duplicate_count, 1);
    assert_eq!(batch.jobs[0].application_url, original);
    assert_ne!(batch.jobs[0].source_url, original);
    let encoded = serde_json::to_value(&batch).unwrap();
    assert_eq!(encoded["jobs"][0]["application_url"], original);
}
#[test]
fn himalayas_update_time_cannot_establish_posting_age() {
    let batch = public_discovery::himalayas(&serde_json::to_vec(&json!({"jobs":[job()]})).unwrap())
        .unwrap();
    assert_eq!(batch.jobs[0].published_at, None);
    assert_eq!(
        batch.jobs[0].source_updated_at.as_deref(),
        Some("2026-11-14T21:00:00+00:00")
    );
    assert!(batch.jobs[0].expires_at.is_some());
}
#[test]
fn original_application_links_cannot_hide_control_or_space_normalization() {
    for link in [
        " https://himalayas.app/companies/example/jobs/role",
        "https://himalayas.app/companies/example/jobs/ro\nle",
        "https://himalayas.app/companies/example/jobs/role\t",
        "https://himalayas.app/companies/example/jobs/role with spaces",
    ] {
        let mut row = job();
        row["applicationLink"] = json!(link);
        assert!(
            public_discovery::himalayas(&serde_json::to_vec(&json!({"jobs":[row]})).unwrap())
                .is_err()
        );
    }
}
#[test]
fn official_rss_handles_cdata_entities_and_rfc_dates_without_executing_content() {
    let feed=br#"<?xml version="1.0"?><rss><channel><item><title>Example &amp; Co: Rust Engineer</title><link>https://weworkremotely.com/remote-jobs/example-rust-engineer</link><guid>fixture-job-1</guid><pubDate>Sun, 15 Nov 2026 12:00:00 +0000</pubDate><description><![CDATA[<p>Website text <script>alert('untrusted')</script></p>]]></description></item></channel></rss>"#;
    let batch = public_discovery::we_work_remotely(feed).unwrap();
    assert_eq!(batch.jobs[0].company_name.as_deref(), Some("Example & Co"));
    assert_eq!(
        batch.jobs[0].published_at.as_deref(),
        Some("2026-11-15T12:00:00+00:00")
    );
    assert!(batch.jobs[0].description.contains("<script>"));
    assert_eq!(batch.jobs[0].location_restrictions, serde_json::Value::Null);
    assert!(!batch.jobs[0].description_truncated);
}
#[test]
fn oversized_rss_description_keeps_a_marked_unicode_preview_and_other_valid_items() {
    let description = "文".repeat(500_000);
    let feed = format!(
        "<rss><channel><item><title>Example: Role</title><link>https://weworkremotely.com/remote-jobs/example-role</link><description><![CDATA[{description}]]></description></item><item><title>Example: Next Role</title><link>https://weworkremotely.com/remote-jobs/next-role</link><description>Complete preview</description></item></channel></rss>"
    );
    let batch = public_discovery::we_work_remotely(feed.as_bytes()).unwrap();
    assert_eq!(batch.jobs.len(), 2);
    assert_eq!(batch.jobs[0].description.chars().count(), 2048);
    assert!(batch.jobs[0].description_truncated);
    assert!(!batch.jobs[1].description_truncated);
    assert_eq!(batch.jobs[1].description, "Complete preview");
    let split = format!(
        "<rss><channel><item><title>Role</title><link>https://weworkremotely.com/remote-jobs/split</link><description>{}&amp;<![CDATA[β]]></description></item></channel></rss>",
        "a".repeat(2047)
    );
    let batch = public_discovery::we_work_remotely(split.as_bytes()).unwrap();
    assert_eq!(batch.jobs[0].description, format!("{}&", "a".repeat(2047)));
    assert!(batch.jobs[0].description_truncated);
    assert_eq!(
        public_discovery::we_work_remotely(&vec![b'x'; 4 * 1024 * 1024 + 1])
            .err()
            .unwrap()
            .0,
        "public_feed_response_too_large"
    );
}
#[test]
fn rss_refuses_doctype_malformed_documents_foreign_links_and_unbounded_depth() {
    for feed in [
        "<!DOCTYPE rss [<!ENTITY x SYSTEM 'file:///etc/passwd'>]><rss/>",
        "<rss><channel>",
        "<rss><channel><item><title>Role</title><link>https://evil.example/remote-jobs/1</link></item></channel></rss>",
        "<html>login page</html>",
    ] {
        assert!(
            public_discovery::we_work_remotely(feed.as_bytes()).is_err(),
            "{feed}"
        );
    }
    let nested = format!("<rss>{}{}</rss>", "<x>".repeat(30), "</x>".repeat(30));
    assert!(public_discovery::we_work_remotely(nested.as_bytes()).is_err());
}
#[test]
fn public_feed_input_cannot_select_arbitrary_targets_or_exceed_caps() {
    assert!(public_discovery::request(b"{}").is_ok());
    for input in [
        br#"{"limit":0}"#.as_slice(),
        br#"{"limit":21}"#,
        br#"{"url":"https://evil.example"}"#,
        br#"{"limit":1,"token":"injected"}"#,
    ] {
        assert!(public_discovery::request(input).is_err());
    }
    assert!(Platform::parse("hiringcafe").is_err());
    assert_eq!(
        public_discovery::route("/api/v1/rust-agent/platforms/himalayas/discover"),
        Some("himalayas")
    );
    assert!(
        public_discovery::route("/api/v1/rust-agent/platforms/himalayas/discover/extra").is_none()
    );
}
