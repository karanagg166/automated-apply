use automated_apply_agents::resume_review;
async fn resume_review_clean(c: &mut PgConnection) {
    sqlx::raw_sql("DROP TABLE IF EXISTS resume_profile_reviews;DROP TABLE IF EXISTS drive_resume_versions;DROP TABLE IF EXISTS resume_drive_sources;").execute(c).await.unwrap();
}
async fn resume_review_fixture() -> (PgConnection, BTreeMap<String, String>, Uuid) {
    let mut cleanup = connection().await;
    resume_review_clean(&mut cleanup).await;
    drop(cleanup);
    let (mut c, mut values, raw) = private_resume_fixture().await;
    sqlx::raw_sql(include_str!("../fixtures/drafts.sql"))
        .execute(&mut c)
        .await
        .unwrap();
    sqlx::raw_sql(include_str!("../fixtures/resume-review.sql"))
        .execute(&mut c)
        .await
        .unwrap();
    let key = values["RESUME_ENCRYPTION_KEY"].clone();
    let cipher = fernet::Fernet::new(&key).unwrap();
    let private = Uuid::new_v4();
    let version = Uuid::new_v4();
    use sha2::Digest;
    let digest = format!("{:x}", sha2::Sha256::digest(&raw));
    sqlx::query("INSERT INTO private_resumes(id,label,ciphertext,sha256) VALUES($1,'Fictional source PDF',$2,$3)").bind(private).bind(cipher.encrypt(&raw).as_bytes()).bind(&digest).execute(&mut c).await.unwrap();
    let url = "https://drive.google.com/file/d/Fictional_File_123/view?usp=drivesdk";
    sqlx::query("INSERT INTO drive_resume_versions(id,file_id,canonical_url,file_name,sha256,downloaded_at,private_resume_id) VALUES($1,'Fictional_File_123',$2,'Fictional source PDF',$3,clock_timestamp(),$4)").bind(version).bind(url).bind(digest).bind(private).execute(&mut c).await.unwrap();
    let categories = [
        "skills",
        "work_experience",
        "employment_dates",
        "education",
        "projects",
        "professional_links",
        "achievements",
        "other_claims",
    ];
    let sections = categories
        .iter()
        .map(|category| ((*category).into(), json!([])))
        .collect::<serde_json::Map<_, _>>();
    let payload = json!({"facts":{"sections":sections,"suggestions":{"full_name":"Unverified Fictional Person","email":"unverified@example.com","verified_skills":["Python"]},"text":"Fictional encrypted source text - never a verified claim"},"previous_facts":null,"profile_at_detection":null,"differences":[]});
    sqlx::query("INSERT INTO resume_profile_reviews(version_id,base_profile_version,review_ciphertext) VALUES($1,4,$2)").bind(version).bind(cipher.encrypt(payload.to_string().as_bytes()).as_bytes()).execute(&mut c).await.unwrap();
    sqlx::query("INSERT INTO resume_drive_sources(key,file_id,canonical_url,generation,sync_enabled,interval_hours,status,latest_version_id) VALUES('primary','Fictional_File_123',$1,1,false,24,'pending_review',$2)").bind(url).bind(version).execute(&mut c).await.unwrap();
    values.insert("CANDIDATE_RESUME_DRIVE_URL".into(), url.into());
    (c, values, version)
}
fn resume_review_settings(
    values: &BTreeMap<String, String>,
) -> (
    resume_review::Settings,
    automated_apply_agents::private_resume::Settings,
) {
    (
        resume_review::Settings::from_values(values).unwrap(),
        automated_apply_agents::private_resume::Settings::from_values(values).unwrap(),
    )
}
async fn resume_review_input(c: &mut PgConnection) -> Value {
    let mut profile = profile_store::get(c).await.unwrap().value;
    for key in ["id", "singleton_key", "version", "created_at", "updated_at"] {
        profile.as_object_mut().unwrap().remove(key);
    }
    json!({"owner_confirmed":true,"expected_generation":1,"expected_profile_version":4,"profile":profile,"evidence":[{"evidence_type":"other","title":"Explicit owner evidence","content":"Fictional reviewed claim","user_confirmed":true}]})
}
async fn resume_review_snapshot(c: &mut PgConnection) -> Value {
    sqlx::query_scalar("SELECT jsonb_build_object('source',(SELECT jsonb_agg(to_jsonb(s) ORDER BY key) FROM resume_drive_sources s),'profile',(SELECT jsonb_agg(to_jsonb(p) ORDER BY id) FROM candidate_profiles p),'private',(SELECT jsonb_agg(to_jsonb(r) ORDER BY id) FROM private_resumes r),'review',(SELECT jsonb_agg(to_jsonb(r) ORDER BY id) FROM resume_profile_reviews r),'resources',(SELECT jsonb_agg(to_jsonb(r) ORDER BY id) FROM candidate_resources r),'evidence',(SELECT jsonb_agg(to_jsonb(e) ORDER BY id) FROM candidate_evidence e),'answers',(SELECT jsonb_agg(to_jsonb(a) ORDER BY id) FROM application_answer_drafts a),'packets',(SELECT jsonb_agg(to_jsonb(p) ORDER BY id) FROM application_packets p))").fetch_one(c).await.unwrap()
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn resume_review_source_changes_use_cas_keep_history_and_never_enable_deferred_downloads() {
    let (mut c, values, version) = resume_review_fixture().await;
    let (settings, _) = resume_review_settings(&values);
    let state = resume_review::status(&mut c, &settings).await.unwrap();
    assert_eq!(state["latest"]["id"], json!(version));
    assert_eq!(state["download_available"], false);
    assert_eq!(state["scheduler_active"], false);
    let same=resume_review::source_request(json!({"canonical_url":values["CANDIDATE_RESUME_DRIVE_URL"],"expected_generation":1,"interval_hours":168})).unwrap();
    let result = resume_review::save_source(&mut c, same, &settings)
        .await
        .unwrap();
    assert_eq!(result["generation"], 2);
    assert_eq!(result["latest"]["id"], json!(version));
    let before = resume_review_snapshot(&mut c).await;
    let stale = resume_review::source_request(
        json!({"canonical_url":values["CANDIDATE_RESUME_DRIVE_URL"],"expected_generation":1}),
    )
    .unwrap();
    assert_eq!(
        resume_review::save_source(&mut c, stale, &settings)
            .await
            .err(),
        Some(Failure("resume_source_generation_conflict"))
    );
    assert_eq!(resume_review_snapshot(&mut c).await, before);
    let enabled=resume_review::source_request(json!({"canonical_url":values["CANDIDATE_RESUME_DRIVE_URL"],"expected_generation":2,"sync_enabled":true})).unwrap();
    assert_eq!(
        resume_review::save_source(&mut c, enabled, &settings)
            .await
            .err(),
        Some(Failure("drive_oauth_deferred_use_manual_pdf_upload"))
    );
    sqlx::query("UPDATE resume_drive_sources SET active_version_id=$1")
        .bind(version)
        .execute(&mut c)
        .await
        .unwrap();
    let changed=resume_review::source_request(json!({"canonical_url":"https://drive.google.com/file/d/Other_Fictional_123/view","expected_generation":2})).unwrap();
    let result = resume_review::save_source(&mut c, changed, &settings)
        .await
        .unwrap();
    assert_eq!(result["generation"], 3);
    assert!(result["latest"].is_null());
    assert_eq!(result["active"]["id"], json!(version));
    assert_eq!(result["history"].as_array().unwrap().len(), 1);
    resume_review_clean(&mut c).await;
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn resume_review_inspection_keeps_suggestions_unverified_and_changes_no_saved_fact_or_bytes()
{
    let (mut c, values, version) = resume_review_fixture().await;
    let (_, crypto) = resume_review_settings(&values);
    let before = resume_review_snapshot(&mut c).await;
    let review = resume_review::changes(&mut c, version, &crypto)
        .await
        .unwrap();
    assert_eq!(review["expected_profile_version"], 4);
    assert_eq!(
        review["current_profile"]["verified_skills"],
        json!(["Rust"])
    );
    assert_eq!(
        review["proposed_profile"]["verified_skills"],
        json!(["Rust", "Python"])
    );
    assert_eq!(
        review["suggested_identity"]["email"],
        "unverified@example.com"
    );
    assert_eq!(review["stale_answer_count"], 2);
    assert_eq!(resume_review_snapshot(&mut c).await, before);
    resume_review_clean(&mut c).await;
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn resume_review_approval_atomically_binds_pdf_and_profile_once_and_preserves_prior_prose() {
    let (mut c, values, version) = resume_review_fixture().await;
    let (settings, crypto) = resume_review_settings(&values);
    let input = resume_review_input(&mut c).await;
    let before = resume_review_snapshot(&mut c).await;
    let result = resume_review::approve(
        &mut c,
        version,
        resume_review::approval_request(input.clone()).unwrap(),
        &settings,
        &crypto,
        false,
    )
    .await
    .unwrap();
    assert_eq!(result["active"]["id"], json!(version));
    assert_eq!(result["active"]["review_status"], "approved");
    assert_eq!(result["active"]["approved_profile_version"], 5);
    let saved = profile_store::get(&mut c).await.unwrap();
    assert_eq!(saved.version, 5);
    assert_eq!(saved.value["email"], "private-fictional@example.com");
    assert_eq!(saved.value["verified_skills"], json!(["Rust"]));
    let after = resume_review_snapshot(&mut c).await;
    assert_eq!(after["answers"], before["answers"]);
    assert_eq!(after["packets"], before["packets"]);
    assert_eq!(
        after["private"][0]["ciphertext"],
        before["private"][0]["ciphertext"]
    );
    assert_eq!(after["evidence"].as_array().unwrap().len(), 1);
    resume_review::approve(
        &mut c,
        version,
        resume_review::approval_request(input).unwrap(),
        &settings,
        &crypto,
        false,
    )
    .await
    .unwrap();
    assert_eq!(resume_review_snapshot(&mut c).await, after);
    resume_review_clean(&mut c).await;
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn resume_review_stale_generation_profile_skill_and_digest_checks_roll_back_and_release_locks()
 {
    let (mut c, values, version) = resume_review_fixture().await;
    let (settings, crypto) = resume_review_settings(&values);
    let input = resume_review_input(&mut c).await;
    let before = resume_review_snapshot(&mut c).await;
    for (key, value, code) in [
        (
            "expected_generation",
            json!(2),
            "resume_source_generation_conflict",
        ),
        (
            "expected_profile_version",
            json!(3),
            "profile_version_conflict",
        ),
        (
            "expected_sha256",
            json!("0".repeat(64)),
            "private_resume_changed",
        ),
        (
            "expected_primary_resource_id",
            json!(Uuid::new_v4()),
            "canonical_resume_changed",
        ),
    ] {
        let mut request = input.clone();
        request[key] = value;
        assert_eq!(
            resume_review::approve(
                &mut c,
                version,
                resume_review::approval_request(request).unwrap(),
                &settings,
                &crypto,
                false
            )
            .await
            .err()
            .map(|e| e.0),
            Some(code)
        );
        assert_eq!(resume_review_snapshot(&mut c).await, before);
    }
    let mut request = input;
    request["profile"]["verified_skills"] = json!(["Python"]);
    assert_eq!(
        resume_review::approve(
            &mut c,
            version,
            resume_review::approval_request(request).unwrap(),
            &settings,
            &crypto,
            false
        )
        .await
        .err(),
        Some(Failure("resume_skill_removal_confirmation_required"))
    );
    assert_eq!(resume_review_snapshot(&mut c).await, before);
    let mut observer = connection().await;
    sqlx::query(
        "SELECT id FROM candidate_profiles WHERE singleton_key='primary' FOR UPDATE NOWAIT",
    )
    .execute(&mut observer)
    .await
    .unwrap();
    resume_review_clean(&mut c).await;
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn resume_review_suppressed_rewritten_and_deferred_approval_writes_never_acknowledge_partial_state()
 {
    let (mut c, values, version) = resume_review_fixture().await;
    let (settings, crypto) = resume_review_settings(&values);
    let input = resume_review_input(&mut c).await;
    let before = resume_review_snapshot(&mut c).await;
    for table in [
        "private_resumes",
        "resume_profile_reviews",
        "resume_drive_sources",
    ] {
        let sql = match table {
            "private_resumes" => {
                "CREATE OR REPLACE FUNCTION fixture_resume_rewrite() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN NEW.confirmed:=false; RETURN NEW; END $$;CREATE TRIGGER fixture_resume_rewrite BEFORE UPDATE ON private_resumes FOR EACH ROW EXECUTE FUNCTION fixture_resume_rewrite()"
            }
            "resume_profile_reviews" => {
                "CREATE OR REPLACE FUNCTION fixture_resume_rewrite() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN NEW.review_ciphertext:=OLD.review_ciphertext; RETURN NEW; END $$;CREATE TRIGGER fixture_resume_rewrite BEFORE UPDATE ON resume_profile_reviews FOR EACH ROW EXECUTE FUNCTION fixture_resume_rewrite()"
            }
            _ => {
                "CREATE OR REPLACE FUNCTION fixture_resume_rewrite() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN NEW.status:='not_checked'; RETURN NEW; END $$;CREATE TRIGGER fixture_resume_rewrite BEFORE UPDATE ON resume_drive_sources FOR EACH ROW EXECUTE FUNCTION fixture_resume_rewrite()"
            }
        };
        sqlx::raw_sql(sql).execute(&mut c).await.unwrap();
        assert_eq!(
            resume_review::approve(
                &mut c,
                version,
                resume_review::approval_request(input.clone()).unwrap(),
                &settings,
                &crypto,
                false
            )
            .await
            .err(),
            Some(Failure("resume_review_write_ack_failed"))
        );
        assert_eq!(resume_review_snapshot(&mut c).await, before);
        let drop = match table {
            "private_resumes" => "DROP TRIGGER fixture_resume_rewrite ON private_resumes",
            "resume_profile_reviews" => {
                "DROP TRIGGER fixture_resume_rewrite ON resume_profile_reviews"
            }
            _ => "DROP TRIGGER fixture_resume_rewrite ON resume_drive_sources",
        };
        sqlx::raw_sql(drop).execute(&mut c).await.unwrap();
    }
    sqlx::raw_sql("CREATE OR REPLACE FUNCTION fixture_resume_commit_refuse() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'fictional private failure'; END $$;CREATE CONSTRAINT TRIGGER fixture_resume_commit_refuse AFTER UPDATE ON resume_drive_sources DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION fixture_resume_commit_refuse()").execute(&mut c).await.unwrap();
    assert_eq!(
        resume_review::approve(
            &mut c,
            version,
            resume_review::approval_request(input).unwrap(),
            &settings,
            &crypto,
            false
        )
        .await
        .err(),
        Some(Failure("resume_review_commit_outcome_unknown"))
    );
    assert_eq!(resume_review_snapshot(&mut c).await, before);
    resume_review_clean(&mut c).await;
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn resume_review_missing_profile_creation_and_explicit_skill_removal_use_exact_owner_inputs()
{
    let (mut c, values, version) = resume_review_fixture().await;
    let (settings, crypto) = resume_review_settings(&values);
    sqlx::query("DELETE FROM candidate_profiles")
        .execute(&mut c)
        .await
        .unwrap();
    let input = json!({"owner_confirmed":true,"expected_generation":1,"expected_profile_version":null,"profile":{"full_name":"Explicit Fictional Owner","email":"explicit@example.com","verified_skills":["Rust"]}});
    resume_review::approve(
        &mut c,
        version,
        resume_review::approval_request(input).unwrap(),
        &settings,
        &crypto,
        false,
    )
    .await
    .unwrap();
    let profile = profile_store::get(&mut c).await.unwrap();
    assert_eq!(profile.version, 1);
    assert_eq!(profile.value["email"], "explicit@example.com");
    assert_eq!(profile.value["full_name"], "Explicit Fictional Owner");
    assert_eq!(profile.value["verified_skills"], json!(["Rust"]));
    resume_review_clean(&mut c).await;
    let (mut c, values, version) = resume_review_fixture().await;
    let (settings, crypto) = resume_review_settings(&values);
    let mut input = resume_review_input(&mut c).await;
    input["profile"]["verified_skills"] = json!(["Python"]);
    input["allow_skill_removals"] = json!(true);
    resume_review::approve(
        &mut c,
        version,
        resume_review::approval_request(input).unwrap(),
        &settings,
        &crypto,
        false,
    )
    .await
    .unwrap();
    assert_eq!(
        profile_store::get(&mut c).await.unwrap().value["verified_skills"],
        json!(["Python"])
    );
    resume_review_clean(&mut c).await;
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn resume_review_actual_http_contract_enforces_owner_review_and_keeps_sync_deferred() {
    let (mut c, values, version) = resume_review_fixture().await;
    let (url, stop, task) = http_fixture_values(values).await;
    let http = client();
    let root = format!("{url}{}", resume_review::ROOT);
    assert_eq!(http.get(&root).send().await.unwrap().status(), 401);
    assert_eq!(
        http.get(&root)
            .bearer_auth(HOST_TOKEN)
            .header("X-Agent-Client", "extension")
            .send()
            .await
            .unwrap()
            .status(),
        403
    );
    let state: Value = http
        .get(&root)
        .bearer_auth(HOST_TOKEN)
        .send()
        .await
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(state["scheduler_active"], false);
    assert_eq!(state["latest"]["id"], json!(version));
    assert_eq!(
        http.post(format!("{root}/sync"))
            .bearer_auth(HOST_TOKEN)
            .json(&json!({"expected_generation":1}))
            .send()
            .await
            .unwrap()
            .status(),
        409
    );
    assert_eq!(http.put(format!("{root}/source")).bearer_auth(HOST_TOKEN).json(&json!({"canonical_url":"https://attacker.example/file/d/Fictional_File_123/view","expected_generation":1})).send().await.unwrap().status(),422);
    let target = format!("{root}/versions/{version}/approve");
    let mut input = resume_review_input(&mut c).await;
    input["owner_confirmed"] = json!(1);
    assert_eq!(
        http.post(&target)
            .bearer_auth(HOST_TOKEN)
            .json(&input)
            .send()
            .await
            .unwrap()
            .status(),
        422
    );
    let reviewed = http
        .get(format!("{root}/versions/{version}/review"))
        .bearer_auth(HOST_TOKEN)
        .send()
        .await
        .unwrap();
    assert_eq!(reviewed.status(), 200);
    assert_eq!(
        reviewed.json::<Value>().await.unwrap()["expected_profile_version"],
        4
    );
    input["owner_confirmed"] = json!(true);
    let response = http
        .post(&target)
        .bearer_auth(HOST_TOKEN)
        .json(&input)
        .send()
        .await
        .unwrap();
    assert_eq!(response.status(), 200);
    assert_eq!(
        response.json::<Value>().await.unwrap()["active"]["review_status"],
        "approved"
    );
    stop.cancel();
    task.await.unwrap();
    resume_review_clean(&mut c).await;
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn resume_review_batched_history_keeps_older_active_and_latest_pointers_outside_the_fifty_row_page()
 {
    let (mut c, values, latest) = resume_review_fixture().await;
    let (settings, _) = resume_review_settings(&values);
    let cipher = fernet::Fernet::new(&values["RESUME_ENCRYPTION_KEY"]).unwrap();
    let base: Vec<u8> = sqlx::query_scalar("SELECT ciphertext FROM private_resumes LIMIT 1")
        .fetch_one(&mut c)
        .await
        .unwrap();
    let raw = cipher.decrypt(std::str::from_utf8(&base).unwrap()).unwrap();
    let review: Vec<u8> =
        sqlx::query_scalar("SELECT review_ciphertext FROM resume_profile_reviews LIMIT 1")
            .fetch_one(&mut c)
            .await
            .unwrap();
    let mut older = None;
    for index in 0..52i32 {
        use sha2::Digest;
        let private = Uuid::new_v4();
        let version = Uuid::new_v4();
        let mut bytes = raw.clone();
        bytes.extend_from_slice(format!("\n% fictional historical revision {index}\n").as_bytes());
        let digest = format!("{:x}", sha2::Sha256::digest(&bytes));
        sqlx::query("INSERT INTO private_resumes(id,label,ciphertext,sha256) VALUES($1,'Fictional historical PDF',$2,$3)").bind(private).bind(cipher.encrypt(&bytes).as_bytes()).bind(&digest).execute(&mut c).await.unwrap();
        let at = if index == 0 {
            "2020-01-01T00:00:00Z".to_string()
        } else {
            (chrono::Utc::now()
                + chrono::Duration::days(1)
                + chrono::Duration::seconds(index as i64))
            .to_rfc3339()
        };
        sqlx::query("INSERT INTO drive_resume_versions(id,file_id,canonical_url,file_name,sha256,downloaded_at,private_resume_id) VALUES($1,'Fictional_File_123','https://drive.google.com/file/d/Fictional_File_123/view?usp=drivesdk','Fictional historical PDF',$2,$3::text::timestamptz,$4)").bind(version).bind(digest).bind(at).bind(private).execute(&mut c).await.unwrap();
        sqlx::query("INSERT INTO resume_profile_reviews(version_id,review_ciphertext,base_profile_version) VALUES($1,$2,4)").bind(version).bind(&review).execute(&mut c).await.unwrap();
        if index == 0 {
            older = Some(version);
        }
    }
    sqlx::query("UPDATE resume_drive_sources SET active_version_id=$1")
        .bind(older)
        .execute(&mut c)
        .await
        .unwrap();
    let status = resume_review::status(&mut c, &settings).await.unwrap();
    assert_eq!(status["latest"]["id"], json!(latest));
    assert_eq!(status["active"]["id"], json!(older));
    let history = status["history"].as_array().unwrap();
    assert_eq!(history.len(), 50);
    assert!(
        history
            .iter()
            .all(|row| row["id"] != json!(latest) && row["id"] != json!(older))
    );
    assert!(
        !status
            .to_string()
            .contains("Fictional encrypted source text")
    );
    resume_review_clean(&mut c).await;
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn resume_review_uncertain_commit_reconnects_owner_api_without_replaying_approval() {
    let (mut c, values, version) = resume_review_fixture().await;
    let request = resume_review_input(&mut c).await;
    let before = resume_review_snapshot(&mut c).await;
    sqlx::raw_sql("DROP SEQUENCE IF EXISTS fixture_resume_commit_counter;CREATE SEQUENCE fixture_resume_commit_counter;CREATE OR REPLACE FUNCTION fixture_resume_commit_observe() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN PERFORM nextval('fixture_resume_commit_counter');RAISE EXCEPTION 'fictional private failure';END $$;CREATE CONSTRAINT TRIGGER fixture_resume_commit_observe AFTER UPDATE ON resume_drive_sources DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION fixture_resume_commit_observe()").execute(&mut c).await.unwrap();
    let (url, stop, task) = http_fixture_values(values).await;
    let http = client();
    let root = format!("{url}{}", resume_review::ROOT);
    let response = http
        .post(format!("{root}/versions/{version}/approve"))
        .bearer_auth(HOST_TOKEN)
        .json(&request)
        .send()
        .await
        .unwrap();
    assert_eq!(response.status(), 503);
    assert!(
        !response
            .headers()
            .contains_key("X-Automated-Apply-Transaction")
    );
    assert!(
        !response
            .text()
            .await
            .unwrap()
            .contains("fictional private failure")
    );
    assert_eq!(
        http.get(&root)
            .bearer_auth(HOST_TOKEN)
            .send()
            .await
            .unwrap()
            .status(),
        503
    );
    sqlx::raw_sql("DROP TRIGGER fixture_resume_commit_observe ON resume_drive_sources")
        .execute(&mut c)
        .await
        .unwrap();
    tokio::time::timeout(Duration::from_secs(5), async {
        loop {
            if http
                .get(&root)
                .bearer_auth(HOST_TOKEN)
                .send()
                .await
                .unwrap()
                .status()
                == 200
            {
                break;
            }
            tokio::time::sleep(Duration::from_millis(100)).await;
        }
    })
    .await
    .unwrap();
    assert_eq!(
        sqlx::query_scalar::<_, i64>("SELECT last_value FROM fixture_resume_commit_counter")
            .fetch_one(&mut c)
            .await
            .unwrap(),
        1
    );
    assert_eq!(resume_review_snapshot(&mut c).await, before);
    stop.cancel();
    task.await.unwrap();
    resume_review_clean(&mut c).await;
}
