async fn catalog_fixture() -> PgConnection {
    let mut c = narrative_fixture().await;
    sqlx::raw_sql("ALTER TABLE jobs ADD COLUMN salary_range text,ADD COLUMN match_score numeric(5,2),ADD COLUMN match_explanation text,ADD COLUMN updated_at timestamptz NOT NULL DEFAULT '2026-01-01T00:00:00Z';
        INSERT INTO jobs(id,title,job_url,status,created_at,updated_at) SELECT lpad(to_hex(i),32,'0')::uuid,'Rust Developer','https://jobs.fictional.invalid/'||i,CASE WHEN i%2=0 THEN 'reviewed' ELSE 'discovered' END,'2026-01-01'::timestamptz+i*interval '1 second','2026-01-01'::timestamptz FROM generate_series(1,105)i;
        UPDATE jobs SET salary_range='Fictional range',match_score=75.25,match_explanation='Saved explanation',date_posted='2026-01-01T01:02:03.123000Z',description='Fictional public description',discovery_metadata='{\"private_internal_canary\":true}' WHERE id='00000000-0000-0000-0000-000000000069';").execute(&mut c).await.unwrap();
    c
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn catalog_http_full_job_dto_pagination_and_status_work_without_candidate_profile() {
    let mut c = catalog_fixture().await;
    sqlx::query("DELETE FROM candidate_profiles")
        .execute(&mut c)
        .await
        .unwrap();
    let (url, stop, server) = http_fixture().await;
    let http = client();
    let root = format!("{url}/api/v1/jobs");
    let response = http
        .get(&root)
        .bearer_auth(HOST_TOKEN)
        .send()
        .await
        .unwrap();
    assert_eq!(response.status(), 200);
    let page: Value = response.json().await.unwrap();
    assert_eq!(page.as_array().unwrap().len(), 50);
    let first = &page[0];
    assert_eq!(first["id"], Uuid::from_u128(105).to_string());
    assert_eq!(first.as_object().unwrap().len(), 17);
    assert_eq!(first["match_score"], 75.25);
    assert_eq!(first["skills_required"], json!(["Rust"]));
    assert_eq!(first["date_posted"], "2026-01-01T01:02:03.123000Z");
    assert_eq!(first["created_at"], "2026-01-01T00:01:45Z");
    assert!(!first.to_string().contains("private_internal_canary"));
    let detail: Value = http
        .get(format!("{root}/{}", Uuid::from_u128(105)))
        .bearer_auth(HOST_TOKEN)
        .send()
        .await
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(&detail, first);
    let page: Value = http
        .get(format!("{root}?limit=1&offset=1&status=reviewed"))
        .bearer_auth(HOST_TOKEN)
        .send()
        .await
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(page.as_array().unwrap().len(), 1);
    assert_eq!(page[0]["id"], Uuid::from_u128(102).to_string());
    assert!(page[0]["match_score"].is_null());
    assert!(page[0]["salary_range"].is_null());
    let duplicate: Value = http
        .get(format!("{root}?limit=1&limit=2&unused=ignored"))
        .bearer_auth(HOST_TOKEN)
        .send()
        .await
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(duplicate.as_array().unwrap().len(), 2);
    let absent = http
        .get(format!("{root}/{}", Uuid::from_u128(999)))
        .bearer_auth(HOST_TOKEN)
        .send()
        .await
        .unwrap();
    assert_eq!(absent.status(), 404);
    assert_eq!(
        absent.json::<Value>().await.unwrap()["detail"],
        "Saved record or candidate profile not found"
    );
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
async fn catalog_query_and_stored_dto_validation_preserve_legacy_error_classes_and_auth_first() {
    let mut c = catalog_fixture().await;
    let (url, stop, server) = http_fixture().await;
    let http = client();
    let root = format!("{url}/api/v1/jobs");
    assert_eq!(
        http.get(format!("{root}?limit=bad"))
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
    for query in [
        "limit=0",
        "limit=101",
        "offset=-1",
        "offset=100001",
        "limit=bad",
    ] {
        let r = http
            .get(format!("{root}?{query}"))
            .bearer_auth(HOST_TOKEN)
            .send()
            .await
            .unwrap();
        assert_eq!(r.status(), 422);
        assert_eq!(
            r.json::<Value>().await.unwrap()["detail"],
            "Invalid request"
        );
    }
    for status in ["", "unknown", "Reviewed", "%20reviewed"] {
        let r = http
            .get(format!("{root}?status={status}"))
            .bearer_auth(HOST_TOKEN)
            .send()
            .await
            .unwrap();
        assert_eq!(r.status(), 400);
        assert_eq!(
            r.json::<Value>().await.unwrap(),
            json!({"detail":"Invalid argument","error_type":"invalid_argument"})
        );
    }
    assert_eq!(
        http.get(format!("{root}/not-a-uuid"))
            .bearer_auth(HOST_TOKEN)
            .send()
            .await
            .unwrap()
            .status(),
        422
    );
    for sql in [
        "UPDATE jobs SET title='' WHERE id='00000000-0000-0000-0000-000000000069'",
        "UPDATE jobs SET title='Valid',match_score=101 WHERE id='00000000-0000-0000-0000-000000000069'",
        "UPDATE jobs SET match_score=50,skills_required=ARRAY[NULL]::text[] WHERE id='00000000-0000-0000-0000-000000000069'",
    ] {
        sqlx::query(sql).execute(&mut c).await.unwrap();
        assert_eq!(
            http.get(&root)
                .bearer_auth(HOST_TOKEN)
                .send()
                .await
                .unwrap()
                .status(),
            400
        );
    }
    stop.cancel();
    server.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn catalog_shortlist_commits_preserves_noop_timestamps_and_rejects_progressed_jobs() {
    let mut c = catalog_fixture().await;
    let before: Value = sqlx::query_scalar("SELECT to_jsonb(p) FROM candidate_profiles p")
        .fetch_one(&mut c)
        .await
        .unwrap();
    let (url, stop, server) = http_fixture().await;
    let http = client();
    let id = Uuid::from_u128(105);
    let target = format!("{url}/api/v1/dashboard/jobs/{id}/shortlist");
    for status in [
        "discovered",
        "reviewed",
        "shortlisted",
        "applied",
        "rejected",
        "archived",
    ] {
        sqlx::query("UPDATE jobs SET status=$2,updated_at='2026-01-01T00:00:00Z' WHERE id=$1")
            .bind(id)
            .bind(status)
            .execute(&mut c)
            .await
            .unwrap();
        let r = http
            .post(&target)
            .bearer_auth(HOST_TOKEN)
            .send()
            .await
            .unwrap();
        let accepted = matches!(status, "discovered" | "reviewed" | "shortlisted");
        assert_eq!(r.status().as_u16(), if accepted { 200 } else { 409 });
        if accepted {
            assert_eq!(
                r.json::<Value>().await.unwrap(),
                json!({"id":id,"status":"shortlisted"})
            );
        }
        let mut observer = connection().await;
        let actual: (String, bool) =
            sqlx::query_as("SELECT status,updated_at='2026-01-01T00:00:00Z' FROM jobs WHERE id=$1")
                .bind(id)
                .fetch_one(&mut observer)
                .await
                .unwrap();
        assert_eq!(actual.0, if accepted { "shortlisted" } else { status });
        assert_eq!(actual.1, !matches!(status, "discovered" | "reviewed"));
    }
    assert_eq!(
        http.post(format!(
            "{url}/api/v1/dashboard/jobs/{}/shortlist",
            Uuid::from_u128(999)
        ))
        .bearer_auth(HOST_TOKEN)
        .send()
        .await
        .unwrap()
        .status(),
        404
    );
    let after: Value = sqlx::query_scalar("SELECT to_jsonb(p) FROM candidate_profiles p")
        .fetch_one(&mut c)
        .await
        .unwrap();
    assert_eq!(before, after);
    assert_eq!(
        sqlx::query_scalar::<_, i64>("SELECT count(*) FROM application_packets")
            .fetch_one(&mut c)
            .await
            .unwrap(),
        0
    );
    sqlx::raw_sql("UPDATE jobs SET status='reviewed' WHERE id='00000000-0000-0000-0000-000000000069';CREATE OR REPLACE FUNCTION fixture_suppress_shortlist() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RETURN NULL; END $$;CREATE TRIGGER suppress_shortlist BEFORE UPDATE ON jobs FOR EACH ROW EXECUTE FUNCTION fixture_suppress_shortlist();").execute(&mut c).await.unwrap();
    let suppressed = http
        .post(&target)
        .bearer_auth(HOST_TOKEN)
        .send()
        .await
        .unwrap();
    assert_eq!(suppressed.status(), 409);
    assert_eq!(
        sqlx::query_scalar::<_, String>("SELECT status FROM jobs WHERE id=$1")
            .bind(id)
            .fetch_one(&mut c)
            .await
            .unwrap(),
        "reviewed"
    );
    sqlx::raw_sql("DROP TRIGGER suppress_shortlist ON jobs;CREATE OR REPLACE FUNCTION fixture_refuse_shortlist() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'fictional-private-shortlist-error'; END $$;CREATE TRIGGER refuse_shortlist BEFORE UPDATE ON jobs FOR EACH ROW EXECUTE FUNCTION fixture_refuse_shortlist();").execute(&mut c).await.unwrap();
    let r = http
        .post(&target)
        .bearer_auth(HOST_TOKEN)
        .send()
        .await
        .unwrap();
    assert_eq!(r.status(), 503);
    assert!(
        !r.text()
            .await
            .unwrap()
            .contains("fictional-private-shortlist-error")
    );
    assert_eq!(
        sqlx::query_scalar::<_, String>("SELECT status FROM jobs WHERE id=$1")
            .bind(id)
            .fetch_one(&mut c)
            .await
            .unwrap(),
        "reviewed"
    );
    stop.cancel();
    server.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn catalog_shortlist_waits_for_row_lock_and_cannot_overwrite_a_concurrent_progression() {
    let mut c = catalog_fixture().await;
    let (url, stop, server) = http_fixture().await;
    let http = client();
    let id = Uuid::from_u128(105);
    let mut tx = c.begin().await.unwrap();
    sqlx::query("UPDATE jobs SET status='applied' WHERE id=$1")
        .bind(id)
        .execute(&mut *tx)
        .await
        .unwrap();
    let mut request = tokio::spawn(async move {
        http.post(format!("{url}/api/v1/dashboard/jobs/{id}/shortlist"))
            .bearer_auth(HOST_TOKEN)
            .send()
            .await
            .unwrap()
    });
    assert!(
        tokio::time::timeout(Duration::from_millis(150), &mut request)
            .await
            .is_err()
    );
    tx.commit().await.unwrap();
    assert_eq!(request.await.unwrap().status(), 409);
    assert_eq!(
        sqlx::query_scalar::<_, String>("SELECT status FROM jobs WHERE id=$1")
            .bind(id)
            .fetch_one(&mut c)
            .await
            .unwrap(),
        "applied"
    );
    stop.cancel();
    server.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn catalog_match_get_and_post_share_scoring_preserve_lookup_order_and_do_not_write() {
    let mut c = catalog_fixture().await;
    let (url, stop, server) = http_fixture().await;
    let http = client();
    let id = Uuid::from_u128(105);
    let target = format!("{url}/api/v1/jobs/{id}/match");
    let before: Value = sqlx::query_scalar("SELECT to_jsonb(j) FROM jobs j WHERE id=$1")
        .bind(id)
        .fetch_one(&mut c)
        .await
        .unwrap();
    let get = http
        .get(&target)
        .bearer_auth(HOST_TOKEN)
        .send()
        .await
        .unwrap();
    assert_eq!(get.status(), 200);
    let get: Value = get.json().await.unwrap();
    let post: Value = http
        .post(&target)
        .bearer_auth(HOST_TOKEN)
        .send()
        .await
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(get, post);
    assert_eq!(get.as_object().unwrap().len(), 7);
    let after: Value = sqlx::query_scalar("SELECT to_jsonb(j) FROM jobs j WHERE id=$1")
        .bind(id)
        .fetch_one(&mut c)
        .await
        .unwrap();
    assert_eq!(before, after);
    assert_eq!(
        sqlx::query_scalar::<_, i64>("SELECT count(*) FROM llm_monthly_usage")
            .fetch_one(&mut c)
            .await
            .unwrap(),
        0
    );
    let unsupported = http
        .put(&target)
        .bearer_auth(HOST_TOKEN)
        .send()
        .await
        .unwrap();
    assert_eq!(unsupported.status(), 405);
    assert_eq!(unsupported.headers()["allow"], "GET, POST");
    sqlx::raw_sql("DELETE FROM jobs;DELETE FROM candidate_profiles")
        .execute(&mut c)
        .await
        .unwrap();
    assert_eq!(
        automated_apply_agents::saved_match::read_calculate(&mut c, id).await,
        Err(Failure("profile_not_found"))
    );
    assert_eq!(
        automated_apply_agents::saved_match::calculate(&mut c, id).await,
        Err(Failure("job_not_found"))
    );
    let get = http
        .get(&target)
        .bearer_auth(HOST_TOKEN)
        .send()
        .await
        .unwrap();
    assert_eq!(get.status(), 404);
    assert_eq!(
        get.json::<Value>().await.unwrap()["detail"],
        "Saved record or candidate profile not found"
    );
    let post = http
        .post(&target)
        .bearer_auth(HOST_TOKEN)
        .send()
        .await
        .unwrap();
    assert_eq!(post.status(), 404);
    assert_eq!(
        post.json::<Value>().await.unwrap()["detail"],
        "Job not found"
    );
    stop.cancel();
    server.await.unwrap();
}
