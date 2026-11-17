use automated_apply_agents::packet_platform::{self, Policy};
use serde_json::{Value, json};
#[test]
fn packet_destinations_match_actual_adapter_rules_without_network_or_action_authority() {
    let corpus: Value =
        serde_json::from_str(include_str!("fixtures/packet-platform-corpus.json")).unwrap();
    let capabilities = packet_platform::capabilities();
    assert!(
        capabilities
            .as_array()
            .unwrap()
            .starts_with(corpus["capabilities"].as_array().unwrap())
    );
    let now = corpus["now"].as_str().unwrap().parse().unwrap();
    let observations = corpus["observations"]
        .as_array()
        .unwrap()
        .iter()
        .map(|v| serde_json::from_value::<Vec<(String, String)>>(v.clone()).unwrap())
        .collect::<Vec<_>>();
    let mut failures = vec![];
    for (i, case) in corpus["cases"].as_array().unwrap().iter().enumerate() {
        let index = |n: usize| case[n].as_u64().unwrap() as usize;
        let raw = &corpus["policies"][index(2)];
        let policy = Policy {
            testing: raw["testing"].as_bool().unwrap(),
            origins: serde_json::from_value(raw["origins"].clone()).unwrap(),
        };
        let actual = packet_platform::select(
            &corpus["jobs"][index(0)],
            &observations[index(1)],
            &policy,
            now,
        )
        .map(|v| json!(v));
        if !actual
            .as_ref()
            .is_ok_and(|v| v == &corpus["results"][index(3)])
        {
            failures.push(format!(
                "{i}: {case} actual{actual:?} expected{}",
                corpus["results"][index(3)]
            ));
        }
    }
    assert!(
        failures.is_empty(),
        "{} differences:\n{}",
        failures.len(),
        failures.into_iter().take(6).collect::<Vec<_>>().join("\n")
    );
}

#[test]
fn expanded_portal_capabilities_offer_packets_for_current_saved_postings() {
    let now = "2026-11-18T12:00:00Z".parse().unwrap();
    let capabilities = packet_platform::capabilities();
    let caps = capabilities.as_array().unwrap();
    for (platform, posting, destination) in [
        (
            "instahyre",
            "https://www.instahyre.com/job-12345-fictional/",
            "https://www.instahyre.com/job-12345-fictional/",
        ),
        (
            "wellfound",
            "https://wellfound.com/jobs/1122-test-role?utm_source=discovery#company",
            "https://wellfound.com/jobs/1122-test-role",
        ),
        (
            "work_at_a_startup",
            "https://www.workatastartup.com/jobs/5544",
            "https://www.workatastartup.com/jobs/5544",
        ),
        (
            "internshala",
            "https://internshala.com/internship/detail/fictional-intern1750000000",
            "https://internshala.com/internship/detail/fictional-intern1750000000",
        ),
        (
            "hiringcafe",
            "https://hiringcafe.com/job/fictional1234567",
            "https://hiringcafe.com/job/fictional1234567",
        ),
    ] {
        let cap = caps.iter().find(|cap| cap["platform"] == platform).unwrap();
        assert_eq!(cap["application_preparation"], "supported");
        assert_eq!(cap["browser_autofill"], "not_implemented");
        assert_eq!(cap["live_verified"], false);
        let job = json!({"source_platform":platform,"job_url":posting,"status":"discovered","source_verification_status":"source_reported"});
        let output = packet_platform::select_at(&job, &[], &Policy::default(), now).unwrap();
        assert_eq!(output.platform, Some(platform));
        assert!(output.preparation_supported);
        assert!(output.destination.valid, "{platform}");
        assert_eq!(
            output.destination.application_url.as_deref(),
            Some(destination)
        );
    }
}

#[test]
fn expanded_postings_require_the_saved_platform_identity_and_current_status() {
    let now = "2026-11-18T12:00:00Z".parse().unwrap();
    let original = "https://wellfound.com/jobs/42-fictional";
    let mut job = json!({"source_platform":"wellfound","job_url":original,"status":"discovered","source_verification_status":"observed"});
    let observations = vec![
        ("wellfound".to_owned(), original.to_owned()),
        (
            "naukri".into(),
            "https://www.naukri.com/job-listings-other-123456789012".into(),
        ),
    ];
    let select = |job: &Value, observations: &[(String, String)]| {
        packet_platform::select_at(job, observations, &Policy::default(), now).unwrap()
    };
    assert!(!select(&job, &[]).destination.valid);
    assert_eq!(select(&job, &observations).platform, Some("wellfound"));
    assert!(select(&job, &observations).destination.valid);
    job["application_url"] = json!("https://www.wellfound.com/jobs/42-new-slug?ref=fetch");
    assert_eq!(
        select(&job, &observations)
            .destination
            .application_url
            .as_deref(),
        Some(original)
    );
    for app in [
        "https://wellfound.com/jobs/43-other-role",
        "https://wellfound.com/jobs/42-%2Fapply",
        "https://wellfound.com/login",
    ] {
        job["application_url"] = json!(app);
        assert!(!select(&job, &observations).destination.valid);
    }
    job["application_url"] = json!("https://jobs.example.org/application/fictional");
    assert_eq!(
        select(&job, &observations)
            .destination
            .application_url
            .as_deref(),
        Some(original)
    );
    job["status"] = json!("applied");
    assert!(!select(&job, &observations).destination.valid);
    job["status"] = json!("discovered");
    job["job_url"] = json!("https://wellfound.com.example.org/jobs/42-fictional");
    assert!(!select(&job, &observations).destination.valid);
}

#[test]
fn hiringcafe_connector_slug_links_bind_by_the_full_posting_id() {
    let now = "2026-11-18T12:00:00Z".parse().unwrap();
    let canonical = "https://hiringcafe.com/job/rust-engineer-fictional-abc123abc123abcd";
    let observed = format!("{canonical}?utm_source=claude&utm_medium=mcp");
    let mut job = json!({
        "source_platform":"hiringcafe","job_url":canonical,"status":"discovered",
        "source_verification_status":"requires_review",
        "discovery_metadata":{"source_name":"hiringcafe","data_provenance":{"import_mode":"manual"}}
    });
    let evidence = [("hiringcafe".into(), observed)];
    let select =
        |job: &Value| packet_platform::select_at(job, &evidence, &Policy::default(), now).unwrap();
    assert_eq!(
        select(&job).destination.application_url.as_deref(),
        Some(canonical)
    );
    job["application_url"] = json!("https://hiringcafe.com/job/fresh-slug-abc123abc123abcd");
    assert!(select(&job).destination.valid);
    for mismatch in [
        "https://hiringcafe.com/job/other-abc123abc123abce",
        "https://hiringcafe.com/job/path%2Fother-abc123abc123abcd",
        "https://hiringcafe.com/jobs/not-a-listing-abc123abc123abcd",
    ] {
        job["application_url"] = json!(mismatch);
        assert!(!select(&job).destination.valid, "{mismatch}");
    }
}

#[test]
fn public_feed_handoff_preserves_exact_attribution_and_application_links() {
    let now = "2026-11-18T12:00:00Z".parse().unwrap();
    for (platform, canonical, raw) in [
        (
            "himalayas",
            "https://himalayas.app/companies/fictional/jobs/engineer",
            "https://himalayas.app/companies/fictional/jobs/engineer?utm_source=partner%2Btesting#apply",
        ),
        (
            "we_work_remotely",
            "https://weworkremotely.com/remote-jobs/fictional-engineer",
            "https://weworkremotely.com/remote-jobs/fictional-engineer?ref=job-feed#apply",
        ),
    ] {
        let mut job = json!({"source_platform":platform,"job_url":canonical,"application_url":raw,
            "status":"discovered","source_verification_status":"source_reported","discovery_metadata":{
                "source_name":platform,"source_job_id":"fictional-id","original_url":raw,"expires_at":"2026-11-18T12:01:00Z"}});
        let observations = vec![(platform.to_owned(), raw.to_owned())];
        let selected =
            packet_platform::select_at(&job, &observations, &Policy::default(), now).unwrap();
        assert!(selected.destination.valid);
        assert_eq!(selected.destination.application_url.as_deref(), Some(raw));
        assert!(
            !packet_platform::select_at(&job, &[], &Policy::default(), now)
                .unwrap()
                .destination
                .valid
        );
        let expired = packet_platform::select_at(
            &job,
            &observations,
            &Policy::default(),
            "2026-11-18T12:01:00Z".parse().unwrap(),
        )
        .unwrap();
        assert_eq!(expired.destination.kind, "expired_or_invalid");
        assert!(expired.destination.application_url.is_none());
        job["application_url"] = json!(canonical);
        assert!(
            !packet_platform::select_at(&job, &observations, &Policy::default(), now)
                .unwrap()
                .destination
                .valid
        );
    }
}

#[test]
fn packet_context_fingerprint_changes_when_a_saved_feed_destination_expires() {
    let corpus: Value =
        serde_json::from_str(include_str!("fixtures/packet-context-corpus.json")).unwrap();
    let mut record = corpus["records"][0].clone();
    let canonical = "https://weworkremotely.com/remote-jobs/fictional-engineer";
    let link = "https://weworkremotely.com/remote-jobs/fictional-engineer?ref=feed";
    record["job"]["source_platform"] = json!("we_work_remotely");
    record["job"]["job_url"] = json!(canonical);
    record["job"]["application_url"] = json!(link);
    record["job"]["status"] = json!("discovered");
    record["job"]["source_verification_status"] = json!("source_reported");
    record["job"]["discovery_metadata"] = json!({"source_name":"we_work_remotely","original_url":link,
        "source_job_id":"fictional-id","expires_at":"2026-11-18T12:01:00Z"});
    record["observations"] = json!([["we_work_remotely", link]]);
    let at = |time: &str| {
        automated_apply_agents::packet_context::build(
            record.clone(),
            &Policy::default(),
            time.parse().unwrap(),
        )
        .unwrap()
        .snapshot
    };
    let saved = at("2026-11-18T12:00:00Z");
    let expired = at("2026-11-18T12:01:00Z");
    assert_eq!(saved["original_job_url"], canonical);
    assert_eq!(saved["destination"]["application_url"], link);
    assert_eq!(expired["destination"]["valid"], false);
    assert_ne!(saved["context_digest"], expired["context_digest"]);
}
