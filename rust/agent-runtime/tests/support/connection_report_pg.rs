fn report_row<'a>(rows: &'a [Value], name: &str) -> &'a Value {
    rows.iter().find(|row| row["name"] == name).unwrap()
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn owner_connection_report_uses_evidence_without_taking_the_owner_fence() {
    use sha2::{Digest, Sha256};
    let (mut c, mut values, raw) = private_resume_fixture().await;
    values.extend(
        browser_values()
            .into_iter()
            .filter(|(key, _)| key.starts_with("CHROME_")),
    );
    values.extend(telegram_values("http://127.0.0.1:54321"));
    values.insert("GEMINI_API_KEY".into(), "PRIVATE_PROVIDER_CANARY".into());
    let (_settings, _identity) = telegram_question_binding(&mut c).await;
    sqlx::raw_sql(
        "ALTER TABLE owner_preferences ADD COLUMN IF NOT EXISTS created_at timestamptz NOT NULL DEFAULT clock_timestamp();
         UPDATE candidate_profiles SET preferences=jsonb_set(jsonb_set(preferences,'{target_titles}','[\"private-profile-title-canary\"]'),'{preferred_locations}','[\"private-location-canary\"]'), verified_experience_years=1;
         UPDATE owner_preferences SET value=jsonb_build_object('profile_id',p.id,'profile_version',p.version,'confirmed_at',clock_timestamp())
         FROM candidate_profiles p WHERE key='phase1_profile_confirmation' AND p.singleton_key='primary';
         UPDATE agent_telegram_state SET last_poll_at=clock_timestamp() WHERE key='primary'",
    ).execute(&mut c).await.unwrap();
    let context = browser_context();
    browser_connect(&mut c, &context).await;
    browser_call(
        &mut c,
        BrowserRoute::Select,
        json!({"expected_version":0,"profile_binding_id":context["profile_binding_id"]}),
    )
    .await
    .unwrap();
    browser_save(&mut c, "portal_instahyre", json!({"state":"browser_session_observed",
        "last_verification_time":"2026-11-01T00:00:00Z","evidence_type":"extension_gesture_dom_indicator",
        "identity_canary":"private-portal-identity-canary","manual_capability_accepted":true})).await;

    let resource = Uuid::new_v4();
    let pdf_id = Uuid::new_v4();
    sqlx::query("UPDATE candidate_resources SET is_primary=false WHERE resource_type='resume'")
        .execute(&mut c)
        .await
        .unwrap();
    sqlx::query("INSERT INTO candidate_resources(id,candidate_profile_id,resource_type,label,url,user_confirmed,is_primary,source_type)
        SELECT $1,id,'resume','private-pdf-label-canary',$2,true,true,'private_upload'
        FROM candidate_profiles WHERE singleton_key='primary'").bind(resource).bind(format!("private-resume:{pdf_id}")).execute(&mut c).await.unwrap();
    let cipher = fernet::Fernet::new(values.get("RESUME_ENCRYPTION_KEY").unwrap()).unwrap();
    sqlx::query(
        "INSERT INTO private_resumes(id,label,ciphertext,sha256,confirmed,resource_id)
        VALUES ($1,'private-pdf-label-canary',$2,$3,true,$4)",
    )
    .bind(pdf_id)
    .bind(cipher.encrypt(&raw).into_bytes())
    .bind(format!("{:x}", Sha256::digest(&raw)))
    .bind(resource)
    .execute(&mut c)
    .await
    .unwrap();
    let (base, stop, service) = http_fixture_values(values).await;
    let url = format!("{base}/api/v1/local-agent/connections");
    let client = client();
    assert_eq!(client.get(&url).send().await.unwrap().status(), 401);
    assert_eq!(
        client
            .get(&url)
            .bearer_auth(HOST_TOKEN)
            .header("x-agent-client", BROWSER_EXTENSION)
            .send()
            .await
            .unwrap()
            .status(),
        403
    );
    let mut holder = connection().await;
    let mut fence = holder.begin().await.unwrap();
    let held: String = sqlx::query_scalar(
        "SELECT key FROM owner_preferences WHERE key='agent_conversation:primary' FOR UPDATE",
    )
    .fetch_one(&mut *fence)
    .await
    .unwrap();
    assert_eq!(held, "agent_conversation:primary");
    let rows: Vec<Value> = client
        .get(&url)
        .bearer_auth(HOST_TOKEN)
        .send()
        .await
        .unwrap()
        .error_for_status()
        .unwrap()
        .json()
        .await
        .unwrap();
    fence.rollback().await.unwrap();
    assert_eq!(
        report_row(&rows, "Supabase PostgreSQL")["actual_evidence_type"],
        "disposable_test"
    );
    assert_eq!(
        report_row(&rows, "Brave extension")["state"],
        "authenticated"
    );
    assert_eq!(
        report_row(&rows, "Instahyre")["state"],
        "browser_session_observed"
    );
    assert_eq!(
        report_row(&rows, "Telegram worker")["actual_evidence_type"],
        "simulated_transport"
    );
    assert_eq!(
        report_row(&rows, "Telegram worker")["capability_verification"],
        "unverified"
    );
    assert_eq!(
        report_row(&rows, "Gemini")["state"],
        "credentials_configured"
    );
    assert_eq!(
        report_row(&rows, "Candidate profile")["state"],
        "capability_verified"
    );
    assert_eq!(
        report_row(&rows, "Resume")["capability_verification"],
        "decrypted_pdf_hash_verified"
    );
    let payload = serde_json::to_string(&rows).unwrap();
    for forbidden in [
        "private-profile-title-canary",
        "private-location-canary",
        "private-portal-identity-canary",
        "private-pdf-label-canary",
        "PRIVATE_PROVIDER_CANARY",
        "123:abcdefghijklmnopqrstuvwx",
        "%PDF-",
    ] {
        assert!(!payload.contains(forbidden));
    }
    sqlx::raw_sql("UPDATE owner_preferences SET value=jsonb_set(value,'{last_heartbeat}',to_jsonb(clock_timestamp()-INTERVAL '5 minutes')) WHERE starts_with(key,'chr_prof:');
        UPDATE candidate_profiles SET version=version+1; UPDATE private_resumes SET sha256=repeat('0',64)")
        .execute(&mut c).await.unwrap();
    let stale: Vec<Value> = client
        .get(&url)
        .bearer_auth(HOST_TOKEN)
        .send()
        .await
        .unwrap()
        .error_for_status()
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(
        report_row(&stale, "Brave extension")["state"],
        "owner_action_required"
    );
    assert_eq!(
        report_row(&stale, "Candidate profile")["state"],
        "owner_action_required"
    );
    assert_eq!(report_row(&stale, "Resume")["state"], "degraded");
    stop.cancel();
    service.await.unwrap();
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn owner_connection_report_private_setup_receipts_require_owner_files_and_project_pin() {
    use std::os::unix::{fs::PermissionsExt, fs::symlink};
    let _c = knowledge_fixture().await;
    let directory = tempfile::tempdir().unwrap();
    let actual = directory.path().join("supabase-cli.private.json");
    std::fs::write(&actual, json!({"project_ref":"luvdmwnlwaqgvfwlmlom","cli_account_access_verified":true,
        "status":"ACTIVE_HEALTHY","verified_at":"2026-01-01T00:00:00Z","private_receipt_canary":"EXTERNAL_SECRET_CANARY"}).to_string()).unwrap();
    std::fs::set_permissions(&actual, std::fs::Permissions::from_mode(0o600)).unwrap();
    symlink(&actual, directory.path().join("mcp.private.json")).unwrap();
    let mut values = host_values();
    values.insert(
        "RUST_CONNECTION_EVIDENCE_DIR".into(),
        directory.path().to_string_lossy().into_owned(),
    );
    let (base, stop, service) = http_fixture_values(values).await;
    let url = format!("{base}/api/v1/local-agent/connections");
    let client = client();
    let rows: Vec<Value> = client
        .get(&url)
        .bearer_auth(HOST_TOKEN)
        .send()
        .await
        .unwrap()
        .error_for_status()
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(
        report_row(&rows, "Supabase CLI")["actual_evidence_type"],
        "saved_isolated_cli_project_list"
    );
    assert_eq!(
        report_row(&rows, "Codex Supabase MCP")["state"],
        "owner_authorization_required"
    );
    assert!(
        !serde_json::to_string(&rows)
            .unwrap()
            .contains("EXTERNAL_SECRET_CANARY")
    );
    std::fs::set_permissions(&actual, std::fs::Permissions::from_mode(0o644)).unwrap();
    let rejected: Vec<Value> = client
        .get(&url)
        .bearer_auth(HOST_TOKEN)
        .send()
        .await
        .unwrap()
        .error_for_status()
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(
        report_row(&rejected, "Supabase CLI")["state"],
        "owner_authorization_required"
    );
    stop.cancel();
    service.await.unwrap();
}
