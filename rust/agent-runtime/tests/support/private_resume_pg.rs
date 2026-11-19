// Existing encryption/HTTP contract, entirely fictional PDF bytes and local PostgreSQL.
async fn private_resume_fixture() -> (PgConnection, BTreeMap<String, String>, Vec<u8>) {
    let mut c = resource_fixture().await;
    sqlx::raw_sql("DROP TABLE IF EXISTS drive_resume_versions; DROP TABLE IF EXISTS private_resumes; CREATE TABLE private_resumes(id uuid PRIMARY KEY,label varchar(200) NOT NULL,ciphertext bytea NOT NULL,sha256 varchar(64) NOT NULL,confirmed bool NOT NULL DEFAULT false,resource_id uuid,created_at timestamptz NOT NULL DEFAULT clock_timestamp(),updated_at timestamptz NOT NULL DEFAULT clock_timestamp()); CREATE TABLE drive_resume_versions(id uuid PRIMARY KEY,private_resume_id uuid UNIQUE);")
        .execute(&mut c).await.unwrap();
    let corpus: Value = serde_json::from_str(include_str!("../../../document-worker/tests/fixtures/pdf-corpus.json")).unwrap();
    let raw = serde_json::from_value(corpus["pdfs"].as_array().unwrap().iter().find(|v| v["name"]=="text").unwrap()["bytes"].clone()).unwrap();
    let mut values = host_values();
    values.insert("RESUME_ENCRYPTION_KEY".into(), corpus["fernet"]["key"].as_str().unwrap().into());
    values.insert("RUST_DOCUMENT_WORKER".into(), std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../target/debug/automated-apply-documents").canonicalize().expect("build workspace binaries before PDF integration tests").to_string_lossy().into());
    (c, values, raw)
}
async fn upload_fixture_pdf(url: &str, raw: Vec<u8>) -> Value {
    let response = client().post(format!("{url}/api/v1/dashboard/resumes?label=Fictional+PDF"))
        .bearer_auth(HOST_TOKEN).header("content-type","application/pdf").body(raw).send().await.unwrap();
    assert_eq!(response.status(),201,"{}",response.text().await.unwrap_or_default());
    // The response is consumed above only on failure (assert arguments are lazy).
    response.json().await.unwrap()
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn private_pdf_http_upload_decrypt_download_preserves_profile_and_private_bytes() {
    let (mut c, values, raw) = private_resume_fixture().await;
    let before = profile_store::get(&mut c).await.unwrap().value;
    let (url, stop, server) = http_fixture_values(values).await;
    let saved = upload_fixture_pdf(&url, raw.clone()).await;
    assert_eq!(saved["confirmed"],false);
    assert_eq!(saved["suggestions"]["full_name"],"Fictional Person");
    assert_eq!(saved["suggestions"]["email"],"fictional@example.com");
    assert_eq!(saved["suggestions"]["verified_skills"],json!(["Python","PostgreSQL"]));
    let id:Uuid = saved["id"].as_str().unwrap().parse().unwrap();
    let mut observer = connection().await;
    let ciphertext:Vec<u8> = sqlx::query_scalar("SELECT ciphertext FROM private_resumes WHERE id=$1").bind(id).fetch_one(&mut observer).await.unwrap();
    assert!(!ciphertext.starts_with(b"%PDF-"));
    let response = client().get(format!("{url}/api/v1/dashboard/resumes/{id}")).bearer_auth(HOST_TOKEN).send().await.unwrap();
    assert_eq!(response.status(),200);
    assert_eq!(response.headers()["content-type"],"application/pdf");
    assert_eq!(response.headers()["cache-control"],"private, no-store");
    assert_eq!(response.bytes().await.unwrap().to_vec(),raw);
    assert_eq!(profile_store::get(&mut c).await.unwrap().value,before);
    assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM application_packets").fetch_one(&mut c).await.unwrap(),0);
    stop.cancel();server.await.unwrap();
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn private_pdf_confirmation_checks_version_digest_primary_binding_and_reuses_resource() {
    let (mut c, values, raw) = private_resume_fixture().await;
    let (url, stop, server) = http_fixture_values(values).await;
    let saved = upload_fixture_pdf(&url, raw).await;
    let id = saved["id"].as_str().unwrap();
    let target=format!("{url}/api/v1/dashboard/resumes/{id}/confirm");
    let body=json!({"owner_confirmed":true,"primary":true,"expected_profile_version":4,"expected_primary_resource_id":"10000000-0000-0000-0000-000000000001"});
    let mut stale=body.clone(); stale["expected_profile_version"]=json!(3);
    assert_eq!(client().post(&target).bearer_auth(HOST_TOKEN).json(&stale).send().await.unwrap().status(),409);
    let mut wrong=body.clone();wrong["expected_sha256"]=json!("0".repeat(64));
    assert_eq!(client().post(&target).bearer_auth(HOST_TOKEN).json(&wrong).send().await.unwrap().status(),409);
    let response=client().post(&target).bearer_auth(HOST_TOKEN).json(&body).send().await.unwrap();
    assert_eq!(response.status(),200);let first:Value=response.json().await.unwrap();
    let response=client().post(&target).bearer_auth(HOST_TOKEN).json(&body).send().await.unwrap();
    assert_eq!(response.status(),200);assert_eq!(response.json::<Value>().await.unwrap(),first);
    let current:Uuid=sqlx::query_scalar("SELECT id FROM candidate_resources WHERE candidate_profile_id=$1 AND is_primary").bind(profile_pin().id).fetch_one(&mut c).await.unwrap();
    assert_eq!(json!(current),first["resource_id"]);
    assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM candidate_resources WHERE url=$1").bind(format!("private-resume:{id}")).fetch_one(&mut c).await.unwrap(),1);
    let confirmation:Value=sqlx::query_scalar("SELECT value FROM owner_preferences WHERE key='phase1_profile_confirmation'").fetch_one(&mut c).await.unwrap();
    assert_eq!(confirmation["reason"],"canonical_resume_changed");
    assert_eq!(profile_store::get(&mut c).await.unwrap().version,4);
    stop.cancel();server.await.unwrap();
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn private_pdf_integrity_drive_and_deferred_commit_failures_never_save_partial_bindings() {
    let (mut c, values, raw) = private_resume_fixture().await;
    let (url, stop, server) = http_fixture_values(values).await;
    let saved=upload_fixture_pdf(&url,raw).await;
    let id:Uuid=saved["id"].as_str().unwrap().parse().unwrap();
    let target=format!("{url}/api/v1/dashboard/resumes/{id}/confirm");
    let body=json!({"owner_confirmed":true,"primary":true,"expected_profile_version":4,"expected_primary_resource_id":"10000000-0000-0000-0000-000000000001"});
    sqlx::query("INSERT INTO drive_resume_versions VALUES($1,$2)").bind(Uuid::new_v4()).bind(id).execute(&mut c).await.unwrap();
    assert_eq!(client().post(&target).bearer_auth(HOST_TOKEN).json(&body).send().await.unwrap().status(),409);
    sqlx::query("DELETE FROM drive_resume_versions").execute(&mut c).await.unwrap();
    sqlx::raw_sql("CREATE OR REPLACE FUNCTION reject_pdf_commit() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'fictional rejection'; END $$; CREATE CONSTRAINT TRIGGER reject_pdf_commit AFTER UPDATE ON private_resumes DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION reject_pdf_commit();").execute(&mut c).await.unwrap();
    assert_eq!(client().post(&target).bearer_auth(HOST_TOKEN).json(&body).send().await.unwrap().status(),503);
    assert!(!sqlx::query_scalar::<_,bool>("SELECT confirmed FROM private_resumes WHERE id=$1").bind(id).fetch_one(&mut c).await.unwrap());
    assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM candidate_resources WHERE url=$1").bind(format!("private-resume:{id}")).fetch_one(&mut c).await.unwrap(),0);
    sqlx::raw_sql("DROP TRIGGER reject_pdf_commit ON private_resumes").execute(&mut c).await.unwrap();
    sqlx::query("UPDATE private_resumes SET ciphertext='tampered'::bytea WHERE id=$1").bind(id).execute(&mut c).await.unwrap();
    assert_eq!(client().get(format!("{url}/api/v1/dashboard/resumes/{id}")).bearer_auth(HOST_TOKEN).send().await.unwrap().status(),409);
    // The deliberate commit failure closed the shared API connection. Downloads
    // have their own connection; confirmation correctly respects reconnect backoff.
    tokio::time::sleep(Duration::from_millis(1100)).await;
    assert_eq!(client().post(&target).bearer_auth(HOST_TOKEN).json(&body).send().await.unwrap().status(),409);
    stop.cancel();server.await.unwrap();
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn private_pdf_http_auth_limits_worker_configuration_and_input_fail_closed() {
    let (mut c, mut values, raw) = private_resume_fixture().await;
    values.insert("RUST_DOCUMENT_WORKER".into(),"/missing/fictional-worker".into());
    let (url, stop, server)=http_fixture_values(values).await;
    let target=format!("{url}/api/v1/dashboard/resumes");
    assert_eq!(client().post(&target).body(raw.clone()).send().await.unwrap().status(),401);
    assert_eq!(client().post(&target).bearer_auth(HOST_TOKEN).header("x-agent-client","extension").body(raw.clone()).send().await.unwrap().status(),403);
    assert_eq!(client().post(&target).bearer_auth(HOST_TOKEN).body(raw.clone()).send().await.unwrap().status(),415);
    for label in ["", "label=", "label=x&extra=y"] {
        let uri = if label.is_empty(){target.clone()}else{format!("{target}?{label}")};
        let status=client().post(uri).bearer_auth(HOST_TOKEN).header("content-type","application/pdf").body(raw.clone()).send().await.unwrap().status();
        assert_eq!(status,if label.is_empty(){503}else{422});
    }
    assert_eq!(client().post(&target).bearer_auth(HOST_TOKEN).header("content-type","application/pdf").body(vec![b'x';5*1024*1024+1]).send().await.unwrap().status(),413);
    assert_eq!(client().post(&target).bearer_auth(HOST_TOKEN).header("content-type","application/pdf").body("not a PDF").send().await.unwrap().status(),422);
    assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM private_resumes").fetch_one(&mut c).await.unwrap(),0);
    stop.cancel();server.await.unwrap();
}
