use automated_apply_agents::browser_profiles::pin_replacement::{
    Review as BravePinReview, replace as replace_brave_pin,
};

async fn brave_pin_fixture() -> (PgConnection, BravePinReview) {
    let mut c = resource_fixture().await;
    sqlx::raw_sql(
        "CREATE TABLE agent_operations(key varchar(180) PRIMARY KEY,actor varchar(120) NOT NULL,
            command varchar(50) NOT NULL,payload_hash varchar(64) NOT NULL,result jsonb NOT NULL,
            created_at timestamptz NOT NULL DEFAULT clock_timestamp());
         CREATE TABLE private_resumes(id uuid PRIMARY KEY,resource_id uuid NOT NULL,sha256 text NOT NULL,confirmed bool NOT NULL);
         UPDATE rust_agent_control SET mode='STOPPED';",
    ).execute(&mut c).await.unwrap();
    let old = browser_context();
    let target = browser_context();
    browser_connect(&mut c, &old).await;
    browser_connect(&mut c, &target).await;
    browser_call(
        &mut c,
        BrowserRoute::Select,
        json!({
            "expected_version":0,"profile_binding_id":old["profile_binding_id"],
        }),
    )
    .await
    .unwrap();
    let old_binding = old["profile_binding_id"].as_str().unwrap().parse().unwrap();
    let new_binding = target["profile_binding_id"]
        .as_str()
        .unwrap()
        .parse()
        .unwrap();
    browser_save(
        &mut c,
        "chr_fixed_profile",
        json!({
            "profile_binding_id":old_binding,"verified_via":"owner_selected_chrome_version_page",
            "chrome_profile_path":"/fictional/Chrome/Profile 8","automatic_launch_enabled":true,
        }),
    )
    .await;
    browser_save(
        &mut c,
        "application_queue_policy",
        json!({"state":"STOPPED","revision":162}),
    )
    .await;
    browser_save(
        &mut c,
        "naukri_automation",
        json!({"state":"STOPPED","revision":100}),
    )
    .await;
    let account_hash = "a".repeat(64);
    let pin = profile_pin();
    browser_save(
        &mut c,
        "naukri_account_binding",
        json!({
            "revision":1,"approved":true,"candidate_profile_id":pin.id,
            "profile_binding_id":old_binding,"account_sha256":account_hash,
        }),
    )
    .await;
    let resume = Uuid::new_v4();
    let resource = Uuid::new_v4();
    let resume_hash = "b".repeat(64);
    sqlx::query("UPDATE candidate_resources SET is_primary=false")
        .execute(&mut c)
        .await
        .unwrap();
    sqlx::query("INSERT INTO candidate_resources(id,candidate_profile_id,resource_type,label,url,
      user_confirmed,is_primary,source_type) VALUES($1,$2,'resume','Fictional reviewed PDF',$3,true,true,'private_upload')")
        .bind(resource).bind(pin.id).bind(format!("private-resume:{resume}"))
        .execute(&mut c).await.unwrap();
    sqlx::query("INSERT INTO private_resumes VALUES($1,$2,$3,true)")
        .bind(resume)
        .bind(resource)
        .bind(&resume_hash)
        .execute(&mut c)
        .await
        .unwrap();
    let review = BravePinReview {
        old_binding,
        new_binding,
        selection_version: 1,
        old_profile_version: 1,
        new_profile_version: 1,
        browser_session_id: target["browser_session_id"]
            .as_str()
            .unwrap()
            .parse()
            .unwrap(),
        window_id: 10,
        account_revision: 1,
        candidate_profile_version: 4,
        account_sha256: account_hash,
        resume_sha256: resume_hash,
        evidence_sha256: "c".repeat(64),
        observed_at: chrono::Utc::now(),
        profile_directory: "/fictional/dedicated-brave".into(),
        owner_confirmed: true,
    };
    (c, review)
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn brave_pin_replacement_preview_and_commit_preserve_account_history_and_stop() {
    let (mut c, review) = brave_pin_fixture().await;
    let task = browser_seed_task(
        &mut c,
        &json!({
            "profile_binding_id":review.old_binding,"browser_session_id":Uuid::new_v4()
        }),
        "PAUSED",
    )
    .await;
    let mut paused = browser_pref(&mut c, &task).await;
    paused["plan_id"] = Value::Null;
    paused["authorization_id"] = Value::Null;
    browser_save(&mut c, &task, paused).await;
    let work = format!("apply_work:{}", Uuid::new_v4());
    browser_save(
        &mut c,
        &work,
        json!({"stage":"SUBMISSION_UNKNOWN","status":"unknown",
        "form_pending":true,"admitted_actions":["apply"],"reason":"preserved"}),
    )
    .await;
    let before = browser_snapshot(&mut c).await;
    let preview = replace_brave_pin(&mut c, &review, false).await.unwrap();
    assert_eq!(preview["applied"], false);
    assert_eq!(browser_snapshot(&mut c).await, before);
    let applied = replace_brave_pin(&mut c, &review, true).await.unwrap();
    assert_eq!(
        applied,
        json!({"applied":true,"proposed_selection_version":2,
        "account_reapproval_required":true,"submission_dispatched":false})
    );
    let after = browser_snapshot(&mut c).await;
    assert_eq!(
        after["chr_fixed_profile"]["profile_binding_id"],
        json!(review.new_binding)
    );
    assert_eq!(
        after["chr_fixed_profile"]["automatic_launch_enabled"],
        false
    );
    assert_eq!(
        after["chr_selection"],
        json!({"version":2,"profile_binding_id":review.new_binding})
    );
    assert_eq!(
        after["chr_pin_backup:1"]["previous_pin"],
        before["chr_fixed_profile"]
    );
    let old = format!("chr_prof:{}", review.old_binding);
    assert_eq!(after[&old]["connected"], false);
    assert_eq!(after[&old]["commands_enabled"], false);
    let new = format!("chr_prof:{}", review.new_binding);
    for key in [
        &new,
        "naukri_account_binding",
        "application_queue_policy",
        "naukri_automation",
        &work,
    ] {
        assert_eq!(after[key], before[key], "{key}");
    }
    assert_eq!(after[&task]["state"], "PAUSED");
    assert_eq!(after[&task]["reason"], "global_stop");
    assert_eq!(after[&task]["authorization_id"], Value::Null);
    assert_eq!(
        replace_brave_pin(&mut c, &review, true).await,
        Err(Failure("legacy_chrome_pin_changed"))
    );
    assert_eq!(browser_snapshot(&mut c).await, after);
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn brave_pin_replacement_refuses_unreviewed_identity_wrong_pdf_and_changed_session() {
    let (mut c, mut review) = brave_pin_fixture().await;
    let before = browser_snapshot(&mut c).await;
    review.owner_confirmed = false;
    assert_eq!(
        replace_brave_pin(&mut c, &review, true).await,
        Err(Failure("fresh_owner_brave_review_required"))
    );
    review.owner_confirmed = true;
    review.account_sha256 = "e".repeat(64);
    assert_eq!(
        replace_brave_pin(&mut c, &review, true).await,
        Err(Failure("reviewed_naukri_account_changed"))
    );
    review.account_sha256 = "a".repeat(64);
    review.resume_sha256 = "e".repeat(64);
    assert_eq!(
        replace_brave_pin(&mut c, &review, true).await,
        Err(Failure("reviewed_canonical_resume_changed"))
    );
    review.resume_sha256 = "b".repeat(64);
    review.browser_session_id = Uuid::new_v4();
    assert_eq!(
        replace_brave_pin(&mut c, &review, true).await,
        Err(Failure("reviewed_browser_binding_changed"))
    );
    assert_eq!(browser_snapshot(&mut c).await, before);
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn brave_pin_replacement_refuses_running_controls_and_retains_claimed_work() {
    let (mut c, review) = brave_pin_fixture().await;
    browser_save(&mut c, "naukri_automation", json!({"state":"RUNNING"})).await;
    let before = browser_snapshot(&mut c).await;
    assert_eq!(
        replace_brave_pin(&mut c, &review, true).await,
        Err(Failure("brave_pin_replacement_requires_stop"))
    );
    assert_eq!(browser_snapshot(&mut c).await, before);
    browser_save(&mut c, "naukri_automation", json!({"state":"STOPPED"})).await;
    browser_save(
        &mut c,
        "apply_work:fictional",
        json!({"status":"leased","stage":"PREPARING"}),
    )
    .await;
    let before = browser_snapshot(&mut c).await;
    assert_eq!(
        replace_brave_pin(&mut c, &review, true).await,
        Err(Failure("brave_pin_replacement_has_active_work"))
    );
    assert_eq!(browser_snapshot(&mut c).await, before);
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn brave_pin_replacement_rolls_back_and_one_concurrent_write_wins() {
    let (mut c, review) = brave_pin_fixture().await;
    sqlx::raw_sql(
        "CREATE FUNCTION fail_repin_fixture() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN IF NEW.key='chr_selection' THEN RETURN NULL; END IF; RETURN NEW; END $$;
        CREATE TRIGGER fail_repin_fixture BEFORE UPDATE ON owner_preferences
            FOR EACH ROW EXECUTE FUNCTION fail_repin_fixture();",
    )
    .execute(&mut c)
    .await
    .unwrap();
    let before = browser_snapshot(&mut c).await;
    assert_eq!(
        replace_brave_pin(&mut c, &review, true).await,
        Err(Failure("browser_profile_write_ack_failed"))
    );
    assert_eq!(browser_snapshot(&mut c).await, before);
    sqlx::query("DROP TRIGGER fail_repin_fixture ON owner_preferences")
        .execute(&mut c)
        .await
        .unwrap();
    let mut another = connection().await;
    let (first, second) = tokio::join!(
        replace_brave_pin(&mut c, &review, true),
        replace_brave_pin(&mut another, &review, true)
    );
    assert_ne!(first.is_ok(), second.is_ok());
    assert_eq!(
        first.err().or(second.err()),
        Some(Failure("legacy_chrome_pin_changed"))
    );
    assert_eq!(browser_pref(&mut c, "chr_selection").await["version"], 2);
}
