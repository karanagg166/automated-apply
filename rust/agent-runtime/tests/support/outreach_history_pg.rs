// Deferred fictional history fixtures. No Gmail credentials, transport or real messages.
use automated_apply_agents::outreach::{self, history as outreach_history};
async fn outreach_history_schema(c: &mut PgConnection) {
    sqlx::raw_sql("DROP TABLE IF EXISTS outreach_send_attempts,outreach_logs CASCADE;CREATE TABLE outreach_logs(id uuid PRIMARY KEY,job_id uuid,contact_id uuid,subject text NOT NULL,body text NOT NULL,resume_version varchar(100),gmail_draft_id varchar(255),gmail_message_id varchar(255),gmail_thread_id varchar(255),approval_status varchar(50) NOT NULL DEFAULT 'pending_approval',approved_at timestamptz,sent_at timestamptz,connected_account_id uuid,draft_revision integer NOT NULL DEFAULT 1,candidate_profile_version integer,recipient_email varchar(254),evidence_snapshot jsonb NOT NULL DEFAULT '{}',evidence_hash varchar(64),approval_hash varchar(64),approved_revision integer,last_edited_at timestamptz,validation_status varchar(30) NOT NULL DEFAULT 'requires_review',generation_metadata jsonb NOT NULL DEFAULT '{}',created_via varchar(20) NOT NULL DEFAULT 'legacy',idempotency_key varchar(100) UNIQUE,request_hash varchar(64),created_at timestamptz NOT NULL DEFAULT clock_timestamp(),updated_at timestamptz NOT NULL DEFAULT clock_timestamp());CREATE TABLE outreach_send_attempts(id uuid PRIMARY KEY,draft_id uuid NOT NULL UNIQUE,connected_account_id uuid,confirmation_hash varchar(64),actor_id varchar(64),draft_revision integer NOT NULL,approval_hash varchar(64),recipient_email varchar(254),sender_email varchar(254),sender_binding varchar(64),subject text NOT NULL,body text NOT NULL,content_digest varchar(64),evidence_digest varchar(64),rfc_message_id varchar(255),idempotency_key varchar(100),request_hash varchar(64),status varchar(30) NOT NULL,gmail_message_id varchar(255),gmail_thread_id varchar(255),attempted_at timestamptz,accepted_at timestamptz,failure_category varchar(64),reconciliation_required boolean NOT NULL DEFAULT false,reconciled_at timestamptz,reconciled_by varchar(64),reconciliation_note text,created_at timestamptz NOT NULL DEFAULT clock_timestamp(),updated_at timestamptz NOT NULL DEFAULT clock_timestamp())").execute(&mut *c).await.unwrap();
}
async fn outreach_history_fixture() -> PgConnection {
    let (mut c, _, _) = contacts_fixture().await;
    outreach_history_schema(&mut c).await;
    for n in 1..=3 {
        sqlx::query("INSERT INTO outreach_logs(id,subject,body,recipient_email,evidence_snapshot,generation_metadata,created_at) VALUES($1,'Fictional local subject','Fictional local body','person@contact-fixture.example','{\"private_snapshot\":\"PRIVATE_OUTREACH_CONTEXT_CANARY\"}','{\"private_model\":\"PRIVATE_GENERATION_CANARY\"}',clock_timestamp()-interval '1 hour')").bind(Uuid::from_u128(940000+n)).execute(&mut c).await.unwrap();
    }
    for (n, status) in [(1, "attempting"), (2, "prepared")] {
        sqlx::query("INSERT INTO outreach_send_attempts(id,draft_id,confirmation_hash,sender_binding,idempotency_key,request_hash,draft_revision,subject,body,status,created_at) VALUES($1,$2,'PRIVATE_CONFIRMATION_CANARY','PRIVATE_BINDING_CANARY','PRIVATE_REQUEST_ID_CANARY','PRIVATE_REQUEST_HASH_CANARY',2,'Fictional attempted subject','Fictional attempted body',$3,clock_timestamp()-interval '1 hour')").bind(Uuid::from_u128(950000+n)).bind(Uuid::from_u128(940000+n)).bind(status).execute(&mut c).await.unwrap();
    }
    c
}
fn outreach_settings() -> outreach::Settings {
    outreach::Settings::from_values(&BTreeMap::new()).unwrap()
}
async fn outreach_history_call(c: &mut PgConnection, query: Option<&str>) -> Result<Value> {
    outreach_history::dispatch(
        c,
        outreach_history::Route::History,
        "GET",
        query,
        &[],
        &outreach_settings(),
    )
    .await
}
async fn outreach_snapshot(c: &mut PgConnection) -> Value {
    sqlx::query_scalar("SELECT jsonb_build_object('drafts',(SELECT jsonb_agg(to_jsonb(d) ORDER BY id) FROM outreach_logs d),'attempts',(SELECT jsonb_agg(to_jsonb(a) ORDER BY id) FROM outreach_send_attempts a))").fetch_one(c).await.unwrap()
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn outreach_history_saved_timeline_has_one_row_per_intent_and_no_private_snapshot_or_grants()
{
    let mut c = outreach_history_fixture().await;
    let before = outreach_snapshot(&mut c).await;
    let result = outreach_history_call(&mut c, None).await.unwrap();
    assert_eq!(result["total"], 3);
    assert_eq!(result["messages"].as_array().unwrap().len(), 3);
    let records = result["messages"].as_array().unwrap();
    assert_eq!(
        records
            .iter()
            .filter(|v| v["status"] == "outcome_unknown")
            .count(),
        1
    );
    assert_eq!(
        records
            .iter()
            .filter(|v| v["status"] == "failed_before_send")
            .count(),
        1
    );
    assert_eq!(
        records
            .iter()
            .filter(|v| v["status"] == "not_attempted")
            .count(),
        1
    );
    for canary in [
        "PRIVATE_OUTREACH_CONTEXT_CANARY",
        "PRIVATE_GENERATION_CANARY",
        "PRIVATE_CONFIRMATION_CANARY",
        "PRIVATE_BINDING_CANARY",
        "PRIVATE_REQUEST_ID_CANARY",
        "PRIVATE_REQUEST_HASH_CANARY",
    ] {
        assert!(!result.to_string().contains(canary));
    }
    assert_eq!(outreach_snapshot(&mut c).await, before);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn outreach_history_qualifies_recent_old_prepared_attempting_and_actual_saved_acceptance_without_get_writes()
 {
    let mut c = outreach_history_fixture().await;
    for (status, age, expected, reconcile) in [
        ("prepared", 3600.0, "failed_before_send", false),
        ("attempting", 3600.0, "outcome_unknown", true),
        ("attempting", 1.0, "attempting", false),
        ("accepted_by_gmail", 3600.0, "accepted_by_gmail", false),
    ] {
        sqlx::query("UPDATE outreach_send_attempts SET status=$1,created_at=clock_timestamp()-($2::double precision*interval '1 second'),attempted_at=NULL,accepted_at=CASE WHEN $1='accepted_by_gmail' THEN clock_timestamp() ELSE NULL END WHERE id=$3").bind(status).bind(age).bind(Uuid::from_u128(950001)).execute(&mut c).await.unwrap();
        let before = outreach_snapshot(&mut c).await;
        let value = outreach_history::dispatch(
            &mut c,
            outreach_history::Route::Attempt(Uuid::from_u128(950001)),
            "GET",
            None,
            &[],
            &outreach_settings(),
        )
        .await
        .unwrap();
        assert_eq!(value["status"], expected);
        assert_eq!(value["reconciliation_required"], reconcile);
        assert_eq!(value["delivery_verified"], false);
        assert_eq!(value["sending_enabled"], false);
        assert_eq!(
            value["accepted_at"].is_null(),
            status != "accepted_by_gmail"
        );
        assert_eq!(outreach_snapshot(&mut c).await, before);
    }
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn outreach_history_reads_do_not_wait_for_the_owner_mutex_and_preserve_owner_state() {
    let mut c = outreach_history_fixture().await;
    let before = browser_snapshot(&mut c).await;
    let mut other = connection().await;
    let mut tx = other.begin().await.unwrap();
    sqlx::query(
        "SELECT key FROM owner_preferences WHERE key='agent_conversation:primary' FOR UPDATE",
    )
    .execute(&mut *tx)
    .await
    .unwrap();
    sqlx::query("SET lock_timeout='100ms'")
        .execute(&mut c)
        .await
        .unwrap();
    assert_eq!(
        outreach_history_call(&mut c, None).await.unwrap()["total"],
        3
    );
    assert_eq!(browser_snapshot(&mut c).await, before);
    tx.rollback().await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn outreach_history_preserves_local_sent_timestamp_as_unverified_and_never_manufactures_acceptance()
 {
    let mut c = outreach_history_fixture().await;
    sqlx::query("UPDATE outreach_logs SET sent_at=clock_timestamp(),gmail_message_id='fictional-legacy-message' WHERE id=$1").bind(Uuid::from_u128(940003)).execute(&mut c).await.unwrap();
    let result = outreach_history_call(&mut c, None).await.unwrap();
    let record = result["messages"]
        .as_array()
        .unwrap()
        .iter()
        .find(|v| v["id"] == Uuid::from_u128(940003).to_string())
        .unwrap();
    assert_eq!(record["status"], "legacy_sent_unverified");
    assert!(record["accepted_at"].is_null());
    assert!(!record["recorded_sent_at"].is_null());
    assert_eq!(record["reconciliation_required"], true);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn outreach_history_paging_is_stable_bounded_and_keeps_the_full_total() {
    let mut c = outreach_history_fixture().await;
    sqlx::query("UPDATE outreach_send_attempts SET created_at='2026-11-17T00:00:00Z'")
        .execute(&mut c)
        .await
        .unwrap();
    sqlx::query("UPDATE outreach_logs SET created_at='2026-11-17T00:00:00Z'")
        .execute(&mut c)
        .await
        .unwrap();
    let all = outreach_history_call(&mut c, None).await.unwrap();
    let page = outreach_history_call(&mut c, Some("limit=1&offset=1"))
        .await
        .unwrap();
    assert_eq!(page["messages"][0], all["messages"][1]);
    assert_eq!(page["total"], 3);
    assert_eq!(
        outreach_history_call(&mut c, Some("offset=100000"))
            .await
            .unwrap()["messages"],
        json!([])
    );
    assert_eq!(
        outreach_history_call(&mut c, Some("limit=101"))
            .await
            .unwrap_err(),
        Failure("invalid_outreach_query")
    );
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn outreach_history_missing_attempt_is_distinct_from_malformed_or_oversized_saved_context() {
    let mut c = outreach_history_fixture().await;
    assert_eq!(
        outreach_history::dispatch(
            &mut c,
            outreach_history::Route::Attempt(Uuid::nil()),
            "GET",
            None,
            &[],
            &outreach_settings()
        )
        .await
        .unwrap_err(),
        Failure("outreach_send_attempt_not_found")
    );
    sqlx::query("UPDATE outreach_logs SET draft_revision=0 WHERE id=$1")
        .bind(Uuid::from_u128(940003))
        .execute(&mut c)
        .await
        .unwrap();
    assert_eq!(
        outreach_history_call(&mut c, None).await.unwrap_err(),
        Failure("invalid_outreach_saved_record")
    );
    sqlx::query("UPDATE outreach_logs SET draft_revision=1,body=repeat('x',140000) WHERE id=$1")
        .bind(Uuid::from_u128(940003))
        .execute(&mut c)
        .await
        .unwrap();
    assert_eq!(
        outreach_history_call(&mut c, None).await.unwrap_err(),
        Failure("invalid_outreach_saved_record")
    );
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn outreach_history_rejects_method_body_and_attempt_queries_before_any_record_work() {
    let mut c = outreach_history_fixture().await;
    let before = outreach_snapshot(&mut c).await;
    assert_eq!(
        outreach_history::dispatch(
            &mut c,
            outreach_history::Route::History,
            "POST",
            None,
            &[],
            &outreach_settings()
        )
        .await
        .unwrap_err(),
        Failure("outreach_method_not_allowed")
    );
    assert_eq!(
        outreach_history::dispatch(
            &mut c,
            outreach_history::Route::History,
            "GET",
            None,
            b"{}",
            &outreach_settings()
        )
        .await
        .unwrap_err(),
        Failure("invalid_outreach_query")
    );
    assert_eq!(
        outreach_history::dispatch(
            &mut c,
            outreach_history::Route::Attempt(Uuid::nil()),
            "GET",
            Some("probe=true"),
            &[],
            &outreach_settings()
        )
        .await
        .unwrap_err(),
        Failure("invalid_outreach_query")
    );
    assert_eq!(outreach_snapshot(&mut c).await, before);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn outreach_history_owner_http_authentication_and_method_errors_preserve_send_refusal() {
    let mut c = outreach_history_fixture().await;
    let before = outreach_snapshot(&mut c).await;
    let (url, stop, task) = http_fixture_values(host_values()).await;
    let http = client();
    let path = format!("{url}{}", outreach_history::PATH);
    assert_eq!(http.get(&path).send().await.unwrap().status(), 401);
    assert_eq!(
        http.get(&path)
            .bearer_auth(HOST_TOKEN)
            .header("x-agent-client", "extension")
            .send()
            .await
            .unwrap()
            .status(),
        403
    );
    assert_eq!(
        http.get(&path)
            .bearer_auth(HOST_TOKEN)
            .send()
            .await
            .unwrap()
            .status(),
        200
    );
    assert_eq!(
        http.post(&path)
            .bearer_auth(HOST_TOKEN)
            .send()
            .await
            .unwrap()
            .status(),
        405
    );
    assert_eq!(
        http.get(format!("{path}?unknown=true"))
            .bearer_auth(HOST_TOKEN)
            .send()
            .await
            .unwrap()
            .status(),
        422
    );
    assert_eq!(
        http.post(format!(
            "{url}/api/v1/outreach/drafts/{}/send",
            Uuid::from_u128(940003)
        ))
        .bearer_auth(HOST_TOKEN)
        .send()
        .await
        .unwrap()
        .status(),
        409
    );
    assert_eq!(outreach_snapshot(&mut c).await, before);
    stop.cancel();
    task.await.unwrap();
}
