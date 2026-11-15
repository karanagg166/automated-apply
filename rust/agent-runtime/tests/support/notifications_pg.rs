async fn notification_fixture() -> PgConnection {
    let mut c = missing_fixture().await;
    sqlx::raw_sql("DROP TABLE IF EXISTS notification_deliveries,owner_notifications;
        CREATE TABLE owner_notifications(id uuid PRIMARY KEY,dedup_key varchar(200) NOT NULL UNIQUE,kind varchar(50) NOT NULL,title varchar(200) NOT NULL,body text NOT NULL,href varchar(200) NOT NULL,read_at timestamptz,created_at timestamptz NOT NULL DEFAULT clock_timestamp(),updated_at timestamptz NOT NULL DEFAULT clock_timestamp());
        CREATE TABLE notification_deliveries(id uuid PRIMARY KEY,notification_id uuid NOT NULL REFERENCES owner_notifications(id),channel varchar(30) NOT NULL,status varchar(40) NOT NULL,attempt_count integer NOT NULL DEFAULT 0,last_error varchar(100),next_attempt_at timestamptz,created_at timestamptz NOT NULL DEFAULT clock_timestamp(),updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),UNIQUE(notification_id,channel));
        INSERT INTO owner_notifications(id,dedup_key,kind,title,body,href,created_at) SELECT lpad(to_hex(i),32,'0')::uuid,'fixture-private-dedup:'||i,'missing_fact','Review needed','Fictional fact requires review.','/profile','2026-01-01'::timestamptz+i*interval '1 second' FROM generate_series(1,105) i;
        INSERT INTO notification_deliveries(id,notification_id,channel,status,attempt_count,last_error,created_at) SELECT id,id,'in_app','available',0,NULL,created_at FROM owner_notifications;").execute(&mut c).await.unwrap();
    c
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn notification_http_inbox_is_owner_only_bounded_and_stably_paginated() {
    let mut c = notification_fixture().await;
    let (url, stop, server) = http_fixture().await;
    let http = client();
    let root = format!("{url}/api/v1/dashboard/notifications");
    assert_eq!(
        http.get(format!("{root}?offset=invalid"))
            .send()
            .await
            .unwrap()
            .status(),
        401
    );
    assert_eq!(
        http.get(&root)
            .bearer_auth(HOST_TOKEN)
            .header("x-agent-client", "extension")
            .send()
            .await
            .unwrap()
            .status(),
        403
    );
    let first: Value = http
        .get(&root)
        .bearer_auth(HOST_TOKEN)
        .send()
        .await
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(first.as_array().unwrap().len(), 50);
    assert_eq!(first[0]["id"], Uuid::from_u128(105).to_string());
    assert_eq!(first[49]["id"], Uuid::from_u128(56).to_string());
    assert!(first[0]["read_at"].is_null());
    assert!(first[0].get("dedup_key").is_none());
    assert!(first[0].get("updated_at").is_none());
    assert_eq!(first[0].as_object().unwrap().len(), 7);
    let second: Value = http
        .get(format!("{root}?offset=50"))
        .bearer_auth(HOST_TOKEN)
        .send()
        .await
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(second[0]["id"], Uuid::from_u128(55).to_string());
    assert_eq!(second.as_array().unwrap().len(), 50);
    let last: Value = http
        .get(format!("{root}?offset=100"))
        .bearer_auth(HOST_TOKEN)
        .send()
        .await
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(last.as_array().unwrap().len(), 5);
    for query in [
        "offset=-1",
        "offset=100001",
        "offset=1&offset=2",
        "limit=1",
        "other=1",
    ] {
        let response = http
            .get(format!("{root}?{query}"))
            .bearer_auth(HOST_TOKEN)
            .send()
            .await
            .unwrap();
        assert_eq!(response.status(), 422, "{query}");
        assert_eq!(
            response.json::<Value>().await.unwrap()["detail"],
            "Supply offset 0..100000 once; page size is fixed at 50"
        );
    }
    assert_eq!(
        sqlx::query_scalar::<_, i64>(
            "SELECT count(*) FROM owner_notifications WHERE read_at IS NOT NULL"
        )
        .fetch_one(&mut c)
        .await
        .unwrap(),
        0
    );
    stop.cancel();
    server.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn notification_read_receipt_commits_without_delivery_application_or_preference_changes() {
    let mut c = notification_fixture().await;
    let before: Value =
        sqlx::query_scalar("SELECT jsonb_agg(to_jsonb(p) ORDER BY key) FROM owner_preferences p")
            .fetch_one(&mut c)
            .await
            .unwrap();
    let (url, stop, server) = http_fixture().await;
    let http = client();
    let id = Uuid::from_u128(105);
    let target = format!("{url}/api/v1/dashboard/notifications/{id}/read");
    for _ in 0..2 {
        let response = http
            .post(&target)
            .bearer_auth(HOST_TOKEN)
            .send()
            .await
            .unwrap();
        assert_eq!(response.status(), 200);
        assert_eq!(
            response.json::<Value>().await.unwrap(),
            json!({"read":true})
        );
        let mut observer = connection().await;
        let read:bool=sqlx::query_scalar("SELECT read_at IS NOT NULL AND updated_at>=read_at FROM owner_notifications WHERE id=$1").bind(id).fetch_one(&mut observer).await.unwrap();
        assert!(read);
    }
    let get = http
        .get(&target)
        .bearer_auth(HOST_TOKEN)
        .send()
        .await
        .unwrap();
    assert_eq!(get.status(), 405);
    assert_eq!(get.headers()["allow"], "POST");
    assert_eq!(
        http.post(format!(
            "{url}/api/v1/dashboard/notifications/{}/read",
            Uuid::from_u128(999)
        ))
        .bearer_auth(HOST_TOKEN)
        .send()
        .await
        .unwrap()
        .status(),
        404
    );
    assert_eq!(
        http.post(format!(
            "{url}/api/v1/dashboard/notifications/not-a-uuid/read"
        ))
        .bearer_auth(HOST_TOKEN)
        .send()
        .await
        .unwrap()
        .status(),
        422
    );
    let after: Value =
        sqlx::query_scalar("SELECT jsonb_agg(to_jsonb(p) ORDER BY key) FROM owner_preferences p")
            .fetch_one(&mut c)
            .await
            .unwrap();
    assert_eq!(before, after);
    assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM notification_deliveries WHERE attempt_count<>0 OR status<>'available'").fetch_one(&mut c).await.unwrap(),0);
    assert_eq!(
        sqlx::query_scalar::<_, i64>("SELECT count(*) FROM application_packets")
            .fetch_one(&mut c)
            .await
            .unwrap(),
        0
    );
    stop.cancel();
    server.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn notification_delivery_history_has_a_private_projection_and_never_enables_delivery() {
    let mut c = notification_fixture().await;
    let (url, stop, server) = http_fixture().await;
    let http = client();
    let target = format!("{url}/api/v1/dashboard/notification-delivery-history");
    let response = http
        .get(&target)
        .bearer_auth(HOST_TOKEN)
        .send()
        .await
        .unwrap();
    assert_eq!(response.status(), 200);
    let result: Value = response.json().await.unwrap();
    assert_eq!(result["external_delivery_enabled"], false);
    let rows = result["attempts"].as_array().unwrap();
    assert_eq!(rows.len(), 100);
    assert_eq!(rows[0]["id"], Uuid::from_u128(105).to_string());
    assert_eq!(rows[0].as_object().unwrap().len(), 7);
    assert!(rows[0].get("notification_id").is_none());
    assert!(!result.to_string().contains("fixture-private-dedup"));
    assert_eq!(
        sqlx::query_scalar::<_, i64>("SELECT sum(attempt_count) FROM notification_deliveries")
            .fetch_one(&mut c)
            .await
            .unwrap(),
        0
    );
    stop.cancel();
    server.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn notification_write_failure_and_oversized_stored_body_fail_without_private_error_leak() {
    let mut c = notification_fixture().await;
    sqlx::raw_sql("CREATE OR REPLACE FUNCTION fixture_refuse_notification_read() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'fictional-private-error-canary'; END $$; CREATE TRIGGER fixture_refuse_read BEFORE UPDATE ON owner_notifications FOR EACH ROW EXECUTE FUNCTION fixture_refuse_notification_read();").execute(&mut c).await.unwrap();
    let (url, stop, server) = http_fixture().await;
    let http = client();
    let id = Uuid::from_u128(105);
    let root = format!("{url}/api/v1/dashboard/notifications");
    let response = http
        .post(format!("{root}/{id}/read"))
        .bearer_auth(HOST_TOKEN)
        .send()
        .await
        .unwrap();
    assert!(!response.status().is_success());
    assert!(
        !response
            .text()
            .await
            .unwrap()
            .contains("fictional-private-error-canary")
    );
    let count: i64 =
        sqlx::query_scalar("SELECT count(*) FROM owner_notifications WHERE read_at IS NOT NULL")
            .fetch_one(&mut c)
            .await
            .unwrap();
    assert_eq!(count, 0);
    stop.cancel();
    server.await.unwrap();
    sqlx::raw_sql("DROP TRIGGER fixture_refuse_read ON owner_notifications;UPDATE owner_notifications SET body=repeat('x',65537) WHERE id='00000000-0000-0000-0000-000000000069'").execute(&mut c).await.unwrap();
    // The forced DB error correctly puts the first API into reconnect backoff.
    // Use a fresh API to isolate corrupt-record validation from that recovery gate.
    let (url, stop, server) = http_fixture().await;
    let root = format!("{url}/api/v1/dashboard/notifications");
    let response = http
        .get(&root)
        .bearer_auth(HOST_TOKEN)
        .send()
        .await
        .unwrap();
    assert_eq!(response.status(), 422);
    assert!(response.text().await.unwrap().len() < 200);
    let length: i32 =
        sqlx::query_scalar("SELECT length(body) FROM owner_notifications WHERE id=$1")
            .bind(id)
            .fetch_one(&mut c)
            .await
            .unwrap();
    assert_eq!(length, 65537);
    stop.cancel();
    server.await.unwrap();
}
