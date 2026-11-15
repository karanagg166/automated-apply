async fn tracking_call(
    c: &mut PgConnection,
    packet: Uuid,
    action: &str,
    body: Value,
) -> Result<Value> {
    automated_apply_agents::packet_service::dispatch(
        c,
        if action == "tracking" {
            "PATCH"
        } else {
            "POST"
        },
        &format!("/api/v1/application-packets/{packet}/{action}"),
        None,
        body.to_string().as_bytes(),
        &packet_settings(),
        &answer_settings(),
    )
    .await
    .map(|v| v.0)
}
fn report_request(revision: i32) -> Value {
    json!({"expected_revision":revision,"idempotency_key":"fictional-native-report-01","human_confirmed":true,"confirmation":"I submitted this application on the official website","receipt_reference":"fictional-owner-note","note":"Fictional manual report, never a worker receipt"})
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn packet_tracking_manual_report_is_idempotent_unverified_and_keeps_job_status() {
    let (mut c, job, original) = packet_review_fixture().await;
    let packet = original["id"].as_str().unwrap().parse::<Uuid>().unwrap();
    let request = report_request(1);
    let first = tracking_call(&mut c, packet, "report-submission", request.clone())
        .await
        .unwrap();
    assert_eq!(first["confirmation_source"], "user_reported");
    assert_eq!(first["evidence_confidence"], "self_reported_unverified");
    assert_eq!(first["packet_revision"], 2);
    assert_eq!(
        tracking_call(&mut c, packet, "report-submission", request.clone())
            .await
            .unwrap(),
        first
    );
    let mut changed = request.clone();
    changed["note"] = json!("different attestation");
    assert_eq!(
        tracking_call(&mut c, packet, "report-submission", changed)
            .await
            .unwrap_err()
            .0,
        "packet_submission_already_reported"
    );
    assert_eq!(
        sqlx::query_scalar::<_, String>("SELECT status FROM jobs WHERE id=$1")
            .bind(job)
            .fetch_one(&mut c)
            .await
            .unwrap(),
        "discovered"
    );
    assert_eq!(
        sqlx::query_scalar::<_, i64>("SELECT count(*) FROM application_submission_evidence")
            .fetch_one(&mut c)
            .await
            .unwrap(),
        1
    );
    assert_eq!(
        sqlx::query_scalar::<_, i64>(
            "SELECT count(*) FROM application_events WHERE event_type='user_reported_submission'"
        )
        .fetch_one(&mut c)
        .await
        .unwrap(),
        1
    );
    let state = tracking_call(
        &mut c,
        packet,
        "tracking",
        json!({"expected_revision":2,"tracking_state":"interview_scheduled"}),
    )
    .await
    .unwrap();
    assert_eq!(state["revision"], 3);
    assert_eq!(state["lifecycle_state"], "user_reported_submitted");
    assert_eq!(state["approved_revision"], Value::Null);
    for next in ["not_applied", "application_incomplete", "applied_verified"] {
        assert!(
            tracking_call(
                &mut c,
                packet,
                "tracking",
                json!({"expected_revision":3,"tracking_state":next})
            )
            .await
            .is_err()
        );
    }
    assert_eq!(
        packet_archive_value(&mut c, packet, 2).await["lifecycle_state"],
        "user_reported_submitted"
    );
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn packet_tracking_carries_unchanged_approval_and_rejects_unsubmitted_outcomes() {
    let (mut c, _job, original) = packet_review_fixture().await;
    let packet = original["id"].as_str().unwrap().parse::<Uuid>().unwrap();
    assert_eq!(
        tracking_call(
            &mut c,
            packet,
            "tracking",
            json!({"expected_revision":1,"tracking_state":"offer_received"})
        )
        .await
        .unwrap_err()
        .0,
        "packet_tracking_submission_required"
    );
    let approved = review_packet(
        &mut c,
        packet,
        review_request(&original, 1, true),
        &packet_settings(),
    )
    .await
    .unwrap();
    assert_eq!(approved["approved_revision"], 2);
    let opened=tracking_call(&mut c,packet,"tracking",json!({"expected_revision":2,"lifecycle_state":"external_application_opened","note":"Fictional owner handoff"})).await.unwrap();
    assert_eq!(opened["approved_revision"], 3);
    assert_eq!(opened["lifecycle_state"], "external_application_opened");
    let archived = tracking_call(
        &mut c,
        packet,
        "tracking",
        json!({"expected_revision":3,"tracking_state":"archived"}),
    )
    .await
    .unwrap();
    assert_eq!(archived["approved_revision"], 4);
    let abandoned = tracking_call(
        &mut c,
        packet,
        "tracking",
        json!({"expected_revision":4,"lifecycle_state":"abandoned"}),
    )
    .await
    .unwrap();
    assert_eq!(abandoned["approved_revision"], Value::Null);
    assert!(
        tracking_call(
            &mut c,
            packet,
            "tracking",
            json!({"expected_revision":5,"lifecycle_state":"external_application_opened"})
        )
        .await
        .is_err()
    );
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn packet_tracking_suppressed_evidence_rolls_back_revision_archive_and_events() {
    let (mut c, _job, original) = packet_review_fixture().await;
    let packet = original["id"].as_str().unwrap().parse::<Uuid>().unwrap();
    sqlx::raw_sql("CREATE FUNCTION suppress_manual_evidence() RETURNS trigger LANGUAGE plpgsql AS $$BEGIN RETURN NULL; END$$; CREATE TRIGGER suppress_manual_evidence BEFORE INSERT ON application_submission_evidence FOR EACH ROW EXECUTE FUNCTION suppress_manual_evidence()").execute(&mut c).await.unwrap();
    assert!(
        tracking_call(&mut c, packet, "report-submission", report_request(1))
            .await
            .is_err()
    );
    assert_eq!(
        sqlx::query_scalar::<_, i32>("SELECT revision FROM application_packets WHERE id=$1")
            .bind(packet)
            .fetch_one(&mut c)
            .await
            .unwrap(),
        1
    );
    assert_eq!(
        sqlx::query_scalar::<_, i64>(
            "SELECT count(*) FROM owner_preferences WHERE starts_with(key,'prv:')"
        )
        .fetch_one(&mut c)
        .await
        .unwrap(),
        0
    );
    assert_eq!(
        sqlx::query_scalar::<_, i64>("SELECT count(*) FROM application_events")
            .fetch_one(&mut c)
            .await
            .unwrap(),
        1
    );
    sqlx::raw_sql("DROP TRIGGER suppress_manual_evidence ON application_submission_evidence; DROP FUNCTION suppress_manual_evidence()").execute(&mut c).await.unwrap();
}
