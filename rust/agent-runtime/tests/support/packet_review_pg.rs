async fn packet_review_fixture() -> (PgConnection, Uuid, Value) {
    let (mut c, job) = packet_service_fixture().await;
    sqlx::raw_sql("DROP TABLE IF EXISTS rust_telegram_outbox,notification_deliveries,owner_notifications,agent_telegram_deliveries; ALTER TABLE candidate_resources ADD FOREIGN KEY(candidate_profile_id) REFERENCES candidate_profiles(id); ALTER TABLE candidate_evidence ADD FOREIGN KEY(candidate_profile_id) REFERENCES candidate_profiles(id); ALTER TABLE job_source_observations ADD FOREIGN KEY(job_id) REFERENCES jobs(id)").execute(&mut c).await.unwrap();
    let source = include_str!("../../../../supabase/fresh_public/001_phase1_public.sql");
    let notices = source
        .split("CREATE TABLE IF NOT EXISTS public.owner_notifications (")
        .nth(1)
        .unwrap()
        .split("\nDO $$\nDECLARE table_name text; client_role text;")
        .next()
        .unwrap();
    sqlx::raw_sql(sqlx::AssertSqlSafe(format!(
        "CREATE TABLE IF NOT EXISTS public.owner_notifications ({notices}"
    )))
    .execute(&mut c)
    .await
    .unwrap();
    let telegram = source
        .lines()
        .find(|line| line.starts_with("CREATE TABLE public.agent_telegram_deliveries ("))
        .unwrap();
    sqlx::raw_sql(sqlx::AssertSqlSafe(telegram))
        .execute(&mut c)
        .await
        .unwrap();
    let packet = packet_create(&mut c, job, "fictional-packet-review", json!([]))
        .await
        .unwrap();
    (c, job, packet)
}
fn review_fields(packet: &Value) -> Vec<Value> {
    packet["fields"]
        .as_array()
        .unwrap()
        .iter()
        .filter(|f| {
            f["validation_status"] == "draft_ready"
                && f["effective_answer"]
                    .as_str()
                    .is_some_and(|s| !s.is_empty())
        })
        .map(|f| f["id"].clone())
        .collect()
}
fn review_request(packet: &Value, revision: i32, approve: bool) -> Value {
    json!({"expected_revision":revision,"action":if approve{"approve"}else{"review"},"reviewed_field_ids":review_fields(packet),"confirm_resume":approve,"confirm_destination":approve})
}
async fn review_packet(
    c: &mut PgConnection,
    packet: Uuid,
    request: Value,
    settings: &automated_apply_agents::packet_service::Settings,
) -> Result<Value> {
    automated_apply_agents::packet_service::dispatch(
        c,
        "POST",
        &format!("/api/v1/application-packets/{packet}/review"),
        None,
        request.to_string().as_bytes(),
        settings,
        &answer_settings(),
    )
    .await
    .map(|(v, created)| {
        assert!(!created);
        v
    })
}
async fn bind_review_execution(c: &mut PgConnection, packet: &Value) -> String {
    let id = Uuid::from_u128(777);
    let key = format!("exec:{id}");
    let value = json!({"id":id,"packet_id":packet["id"],"job_id":packet["job_id"],"platform":"naukri","state":"READY_FOR_REVIEW","revision":8,"fence":11,"cancelled":false,"automation_revision":3,"approved_answer_revisions":{},"private_keep":"fictional retained value"});
    sqlx::query("INSERT INTO owner_preferences(key,value) VALUES($1,$2)")
        .bind(&key)
        .bind(value)
        .execute(&mut *c)
        .await
        .unwrap();
    sqlx::query("INSERT INTO owner_preferences(key,value) VALUES('naukri_automation',$1)")
        .bind(json!({"revision":3,"state":"RUNNING","policy":{"telegram_questions":true}}))
        .execute(&mut *c)
        .await
        .unwrap();
    key
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn packet_review_http_marks_exact_revision_and_handoff_is_manual_with_no_submission() {
    let (mut c, _job, original) = packet_review_fixture().await;
    let packet = original["id"].as_str().unwrap().parse::<Uuid>().unwrap();
    let (url, stop, server) = http_fixture().await;
    let http = client();
    let root = format!("{url}/api/v1/application-packets/{packet}");
    assert_eq!(
        http.get(format!("{root}/handoff"))
            .bearer_auth(HOST_TOKEN)
            .send()
            .await
            .unwrap()
            .status(),
        409
    );
    let response = http
        .post(format!("{root}/review"))
        .bearer_auth(HOST_TOKEN)
        .json(&review_request(&original, 1, false))
        .send()
        .await
        .unwrap();
    let status = response.status();
    let reviewed: Value = response.json().await.unwrap();
    assert_eq!(status, 200, "{reviewed}");
    assert_eq!(reviewed["revision"], 2);
    assert_eq!(reviewed["lifecycle_state"], "reviewed");
    assert!(reviewed["approved_revision"].is_null());
    let response = http
        .post(format!("{root}/review"))
        .bearer_auth(HOST_TOKEN)
        .json(&review_request(&reviewed, 2, true))
        .send()
        .await
        .unwrap();
    let status = response.status();
    let approved: Value = response.json().await.unwrap();
    assert_eq!(status, 200, "{approved}");
    assert_eq!(approved["revision"], 3);
    assert_eq!(approved["approved_revision"], 3);
    assert_eq!(approved["readiness"]["state"], "ready_for_manual_handoff");
    assert_eq!(approved["lifecycle_state"], "approved_for_manual_handoff");
    let response = http
        .get(format!("{root}/handoff"))
        .bearer_auth(HOST_TOKEN)
        .send()
        .await
        .unwrap();
    let status = response.status();
    let handoff: Value = response.json().await.unwrap();
    assert_eq!(status, 200, "{handoff}");
    assert_eq!(handoff["packet_id"], original["id"]);
    assert_eq!(handoff["revision"], 3);
    assert_eq!(handoff["approved_revision"], 3);
    assert_eq!(handoff["submitted"], false);
    assert_eq!(handoff["submission_mode"], "manual_handoff");
    assert_eq!(handoff["fields"], approved["fields"]);
    assert!(
        handoff["manual_steps"]
            .as_array()
            .unwrap()
            .iter()
            .any(|s| s.as_str().unwrap().contains("upload the actual file"))
    );
    assert_eq!(
        packet_archive_value(&mut c, packet, 1).await["fields"],
        original["fields"]
    );
    assert_eq!(
        packet_archive_value(&mut c, packet, 2).await["fields"],
        reviewed["fields"]
    );
    let events: Vec<String> =
        sqlx::query_scalar("SELECT event_type FROM application_events ORDER BY packet_revision")
            .fetch_all(&mut c)
            .await
            .unwrap();
    assert_eq!(
        events,
        vec!["packet_created", "packet_reviewed", "packet_approved"]
    );
    assert_eq!(
        sqlx::query_scalar::<_, i64>("SELECT count(*) FROM owner_notifications")
            .fetch_one(&mut c)
            .await
            .unwrap(),
        2
    );
    assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM notification_deliveries WHERE channel='in_app' AND status='available_in_app' AND attempt_count=1").fetch_one(&mut c).await.unwrap(),2);
    assert_eq!(
        sqlx::query_scalar::<_, i64>("SELECT count(*) FROM agent_telegram_deliveries")
            .fetch_one(&mut c)
            .await
            .unwrap(),
        0
    );
    assert_eq!(
        sqlx::query_scalar::<_, i64>("SELECT count(*) FROM application_submission_evidence")
            .fetch_one(&mut c)
            .await
            .unwrap(),
        0
    );
    assert_eq!(
        sqlx::query_scalar::<_, String>("SELECT status FROM jobs WHERE id=$1")
            .bind(
                original["job_id"]
                    .as_str()
                    .unwrap()
                    .parse::<Uuid>()
                    .unwrap()
            )
            .fetch_one(&mut c)
            .await
            .unwrap(),
        "discovered"
    );
    assert_eq!(
        http.post(format!("{root}/review"))
            .json(&review_request(&approved, 3, true))
            .send()
            .await
            .unwrap()
            .status(),
        401
    );
    assert_eq!(
        http.post(format!("{root}/review"))
            .bearer_auth(HOST_TOKEN)
            .header("X-Agent-Client", "model")
            .json(&review_request(&approved, 3, true))
            .send()
            .await
            .unwrap()
            .status(),
        403
    );
    stop.cancel();
    server.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn packet_review_execution_fence_updates_only_reviewed_answer_map_and_owner_bound_outbox() {
    let (mut c, _job, original) = packet_review_fixture().await;
    let packet = original["id"].as_str().unwrap().parse().unwrap();
    let key = bind_review_execution(&mut c, &original).await;
    let before: Value = sqlx::query_scalar("SELECT value FROM owner_preferences WHERE key=$1")
        .bind(&key)
        .fetch_one(&mut c)
        .await
        .unwrap();
    let mut settings = packet_settings();
    settings.telegram_notices = true;
    let approved = review_packet(
        &mut c,
        packet,
        review_request(&original, 1, true),
        &settings,
    )
    .await
    .unwrap();
    assert_eq!(approved["approved_revision"], 2);
    let after: Value = sqlx::query_scalar("SELECT value FROM owner_preferences WHERE key=$1")
        .bind(&key)
        .fetch_one(&mut c)
        .await
        .unwrap();
    let mut expected = before;
    expected["approved_answer_revisions"] = Value::Object(
        approved["fields"]
            .as_array()
            .unwrap()
            .iter()
            .filter(|f| f["review_status"] == "reviewed")
            .map(|f| {
                (
                    f["id"].as_str().unwrap().to_owned(),
                    f["answer_revision"].clone(),
                )
            })
            .collect(),
    );
    assert_eq!(after, expected);
    let notice:Value=sqlx::query_scalar("SELECT jsonb_build_object('dedup_key',dedup_key,'body',body,'href',href) FROM owner_notifications").fetch_one(&mut c).await.unwrap();
    assert!(
        notice["body"]
            .as_str()
            .unwrap()
            .contains("No application has been sent.")
    );
    assert_eq!(notice["href"], format!("/applications/{packet}"));
    let proposed = automated_apply_agents::packet_notice::propose(
        &approved,
        Some(&after),
        &json!({"revision":3,"state":"RUNNING","policy":{"telegram_questions":true}}),
        None,
        &automated_apply_agents::notification_preferences::normalize(json!({})).unwrap(),
        true,
        chrono::Utc::now(),
    )
    .unwrap()
    .unwrap();
    let delivery:Value=sqlx::query_scalar("SELECT jsonb_build_object('update_id',update_id,'state',state,'reply',reply) FROM agent_telegram_deliveries").fetch_one(&mut c).await.unwrap();
    assert_eq!(Some(delivery), proposed.telegram);
    assert_eq!(
        sqlx::query_scalar::<_, Value>(
            "SELECT value FROM owner_preferences WHERE key='agent_conversation:primary'"
        )
        .fetch_one(&mut c)
        .await
        .unwrap(),
        json!({})
    );
    assert_eq!(
        review_packet(
            &mut c,
            packet,
            review_request(&original, 1, true),
            &settings
        )
        .await
        .unwrap_err(),
        Failure("packet_revision_conflict")
    );
    assert_eq!(
        sqlx::query_scalar::<_, i64>("SELECT count(*) FROM owner_notifications")
            .fetch_one(&mut c)
            .await
            .unwrap(),
        1
    );
    assert_eq!(
        sqlx::query_scalar::<_, i64>("SELECT count(*) FROM agent_telegram_deliveries")
            .fetch_one(&mut c)
            .await
            .unwrap(),
        1
    );
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn packet_review_rejects_duplicate_foreign_unanswered_upload_and_unconfirmed_approval() {
    let (mut c, _job, original) = packet_review_fixture().await;
    let packet = original["id"].as_str().unwrap().parse().unwrap();
    let ids = review_fields(&original);
    for (fields, expected) in [
        (
            vec![ids[0].clone(), ids[0].clone()],
            Failure("packet_review_fields_invalid"),
        ),
        (
            vec![json!(Uuid::new_v4())],
            Failure("packet_review_fields_invalid"),
        ),
        (
            vec![original["fields"][6]["id"].clone()],
            Failure("packet_review_answer_invalid"),
        ),
    ] {
        let input = json!({"expected_revision":1,"reviewed_field_ids":fields});
        assert_eq!(
            review_packet(&mut c, packet, input, &packet_settings())
                .await
                .unwrap_err(),
            expected
        );
    }
    let mut input = review_request(&original, 1, true);
    input["confirm_destination"] = json!(false);
    assert_eq!(
        review_packet(&mut c, packet, input, &packet_settings())
            .await
            .unwrap_err(),
        Failure("packet_review_confirmation_required")
    );
    let added = packet_edit(
        &mut c,
        packet,
        "/questions",
        json!({"expected_revision":1,"questions":[{"question":"Describe a project"}]}),
    )
    .await
    .unwrap();
    assert_eq!(
        review_packet(
            &mut c,
            packet,
            review_request(&added, 2, true),
            &packet_settings()
        )
        .await
        .unwrap_err(),
        Failure("packet_approval_blocked")
    );
    assert_eq!(
        sqlx::query_scalar::<_, i64>("SELECT count(*) FROM owner_notifications")
            .fetch_one(&mut c)
            .await
            .unwrap(),
        0
    );
    assert_eq!(
        sqlx::query_scalar::<_, i64>("SELECT count(*) FROM agent_telegram_deliveries")
            .fetch_one(&mut c)
            .await
            .unwrap(),
        0
    );
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn packet_review_waiting_on_owner_fence_observes_stop_and_newly_inserted_pause_preferences() {
    for pause_preferences in [false, true] {
        let (mut c, _job, original) = packet_review_fixture().await;
        let packet = original["id"].as_str().unwrap().parse().unwrap();
        bind_review_execution(&mut c, &original).await;
        sqlx::query(
            "INSERT INTO owner_preferences(key,value) VALUES('agent_conversation:primary','{}')",
        )
        .execute(&mut c)
        .await
        .unwrap();
        let mut reviewer = connection().await;
        let pid: i32 = sqlx::query_scalar("SELECT pg_backend_pid()")
            .fetch_one(&mut reviewer)
            .await
            .unwrap();
        let mut observer = connection().await;
        let mut operator = c.begin().await.unwrap();
        sqlx::query(
            "SELECT key FROM owner_preferences WHERE key='agent_conversation:primary' FOR UPDATE",
        )
        .fetch_one(&mut *operator)
        .await
        .unwrap();
        if pause_preferences {
            sqlx::query("INSERT INTO owner_preferences(key,value) VALUES('notifications','{\"paused\":true}')").execute(&mut *operator).await.unwrap();
        } else {
            sqlx::query("UPDATE owner_preferences SET value=jsonb_set(jsonb_set(value,'{state}','\"STOPPED\"'),'{revision}','4') WHERE key='naukri_automation'").execute(&mut *operator).await.unwrap();
        }
        let input = review_request(&original, 1, true);
        let mut settings = packet_settings();
        settings.telegram_notices = true;
        let task =
            tokio::spawn(
                async move { review_packet(&mut reviewer, packet, input, &settings).await },
            );
        let start = std::time::Instant::now();
        loop {
            if sqlx::query_scalar::<_, bool>("SELECT cardinality(pg_blocking_pids($1))>0")
                .bind(pid)
                .fetch_one(&mut observer)
                .await
                .unwrap()
            {
                break;
            }
            assert!(start.elapsed() < Duration::from_secs(2));
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
        assert!(!task.is_finished());
        operator.commit().await.unwrap();
        let approved = tokio::time::timeout(Duration::from_secs(3), task)
            .await
            .unwrap()
            .unwrap()
            .unwrap();
        assert_eq!(approved["approved_revision"], 2);
        assert_eq!(
            sqlx::query_scalar::<_, i64>("SELECT count(*) FROM owner_notifications")
                .fetch_one(&mut c)
                .await
                .unwrap(),
            0
        );
        assert_eq!(
            sqlx::query_scalar::<_, i64>("SELECT count(*) FROM notification_deliveries")
                .fetch_one(&mut c)
                .await
                .unwrap(),
            0
        );
        assert_eq!(
            sqlx::query_scalar::<_, i64>("SELECT count(*) FROM agent_telegram_deliveries")
                .fetch_one(&mut c)
                .await
                .unwrap(),
            0
        );
        if pause_preferences {
            assert_eq!(
                sqlx::query_scalar::<_, Value>(
                    "SELECT value FROM owner_preferences WHERE key='notifications'"
                )
                .fetch_one(&mut c)
                .await
                .unwrap(),
                json!({"paused":true})
            );
        } else {
            assert_eq!(
                sqlx::query_scalar::<_, String>(
                    "SELECT value->>'state' FROM owner_preferences WHERE key='naukri_automation'"
                )
                .fetch_one(&mut c)
                .await
                .unwrap(),
                "STOPPED"
            );
        }
    }
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn packet_review_handoff_material_lock_blocks_resource_phantoms_and_later_changes_are_stale()
{
    let (mut c, _job, original) = packet_review_fixture().await;
    let packet = original["id"].as_str().unwrap().parse().unwrap();
    let owner = original["candidate_profile_id"]
        .as_str()
        .unwrap()
        .parse::<Uuid>()
        .unwrap();
    review_packet(
        &mut c,
        packet,
        review_request(&original, 1, true),
        &packet_settings(),
    )
    .await
    .unwrap();
    let mut writer = connection().await;
    let pid: i32 = sqlx::query_scalar("SELECT pg_backend_pid()")
        .fetch_one(&mut writer)
        .await
        .unwrap();
    let mut observer = connection().await;
    let mut tx = c.begin().await.unwrap();
    let handoff =
        automated_apply_agents::packet_review::handoff_in(&mut tx, packet, &packet_settings())
            .await
            .unwrap();
    assert_eq!(handoff["submitted"], false);
    let task = tokio::spawn(async move {
        sqlx::query("INSERT INTO candidate_resources(id,candidate_profile_id,resource_type,label,url,user_confirmed,is_primary,source_type) VALUES($1,$2,'resume','New fictional resource','https://example.com/other-resume.pdf',false,false,'user')").bind(Uuid::new_v4()).bind(owner).execute(&mut writer).await.unwrap();
    });
    let start = std::time::Instant::now();
    loop {
        if sqlx::query_scalar::<_, bool>("SELECT cardinality(pg_blocking_pids($1))>0")
            .bind(pid)
            .fetch_one(&mut observer)
            .await
            .unwrap()
        {
            break;
        }
        assert!(start.elapsed() < Duration::from_secs(2));
        tokio::time::sleep(Duration::from_millis(10)).await;
    }
    assert!(!task.is_finished());
    tx.commit().await.unwrap();
    tokio::time::timeout(Duration::from_secs(3), task)
        .await
        .unwrap()
        .unwrap();
    assert_eq!(
        automated_apply_agents::packet_service::dispatch(
            &mut c,
            "GET",
            &format!("/api/v1/application-packets/{packet}/handoff"),
            None,
            b"",
            &packet_settings(),
            &answer_settings()
        )
        .await
        .unwrap_err(),
        Failure("packet_handoff_incomplete")
    );
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn packet_review_and_handoff_recheck_expiry_after_waiting_for_material_locks() {
    for handoff in [false, true] {
        let (mut c, _job, original) = packet_review_fixture().await;
        let packet = original["id"].as_str().unwrap().parse().unwrap();
        sqlx::query("UPDATE application_packets SET lifecycle_state='preparing' WHERE id=$1")
            .bind(packet)
            .execute(&mut c)
            .await
            .unwrap();
        sqlx::query("UPDATE application_packet_fields SET provenance=provenance||jsonb_build_object('answer_expires_at',clock_timestamp()+interval '2 seconds') WHERE packet_id=$1 AND position=0").bind(packet).execute(&mut c).await.unwrap();
        sqlx::query("UPDATE application_packets SET lifecycle_state='created' WHERE id=$1")
            .bind(packet)
            .execute(&mut c)
            .await
            .unwrap();
        if handoff {
            review_packet(
                &mut c,
                packet,
                review_request(&original, 1, true),
                &packet_settings(),
            )
            .await
            .unwrap();
        }
        let mut requester = connection().await;
        let pid: i32 = sqlx::query_scalar("SELECT pg_backend_pid()")
            .fetch_one(&mut requester)
            .await
            .unwrap();
        let mut observer = connection().await;
        let mut operator = c.begin().await.unwrap();
        sqlx::query("SELECT id FROM candidate_profiles WHERE singleton_key='primary' FOR UPDATE")
            .fetch_one(&mut *operator)
            .await
            .unwrap();
        let input = review_request(&original, 1, true);
        let task = tokio::spawn(async move {
            if handoff {
                automated_apply_agents::packet_service::dispatch(
                    &mut requester,
                    "GET",
                    &format!("/api/v1/application-packets/{packet}/handoff"),
                    None,
                    b"",
                    &packet_settings(),
                    &answer_settings(),
                )
                .await
                .map(|(v, _)| v)
            } else {
                review_packet(&mut requester, packet, input, &packet_settings()).await
            }
        });
        let start = std::time::Instant::now();
        loop {
            if sqlx::query_scalar::<_, bool>("SELECT cardinality(pg_blocking_pids($1))>0")
                .bind(pid)
                .fetch_one(&mut observer)
                .await
                .unwrap()
            {
                break;
            }
            assert!(start.elapsed() < Duration::from_secs(2));
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
        tokio::time::sleep(Duration::from_millis(2100)).await;
        operator.commit().await.unwrap();
        assert_eq!(
            task.await.unwrap().unwrap_err(),
            if handoff {
                Failure("packet_handoff_incomplete")
            } else {
                Failure("packet_approval_blocked")
            }
        );
    }
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn packet_review_suppressed_writes_rollback_fields_approval_archive_execution_notices_and_outbox()
 {
    for stage in [
        "archive",
        "field",
        "packet",
        "event",
        "execution",
        "notification",
        "delivery",
        "telegram",
    ] {
        let (mut c, _job, original) = packet_review_fixture().await;
        let packet = original["id"].as_str().unwrap().parse().unwrap();
        let key = bind_review_execution(&mut c, &original).await;
        let execution: Value =
            sqlx::query_scalar("SELECT value FROM owner_preferences WHERE key=$1")
                .bind(&key)
                .fetch_one(&mut c)
                .await
                .unwrap();
        sqlx::raw_sql("CREATE FUNCTION fixture_review_suppress() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF TG_TABLE_NAME='owner_preferences' THEN IF NOT starts_with(NEW.key,'exec:') AND NOT starts_with(NEW.key,'prv:') THEN RETURN NEW; END IF; ELSIF TG_TABLE_NAME='application_packets' THEN IF NEW.lifecycle_state<>'approved_for_manual_handoff' THEN RETURN NEW; END IF; END IF; RETURN NULL; END $$").execute(&mut c).await.unwrap();
        let (table, operation) = match stage {
            "archive" => ("owner_preferences", "INSERT"),
            "field" => ("application_packet_fields", "UPDATE"),
            "packet" => ("application_packets", "UPDATE"),
            "event" => ("application_events", "INSERT"),
            "execution" => ("owner_preferences", "UPDATE"),
            "notification" => ("owner_notifications", "INSERT"),
            "delivery" => ("notification_deliveries", "INSERT"),
            "telegram" => ("agent_telegram_deliveries", "INSERT"),
            _ => unreachable!(),
        };
        sqlx::raw_sql(sqlx::AssertSqlSafe(format!("CREATE TRIGGER fixture_review_suppress BEFORE {operation} ON {table} FOR EACH ROW EXECUTE FUNCTION fixture_review_suppress()"))).execute(&mut c).await.unwrap();
        let mut settings = packet_settings();
        settings.telegram_notices = true;
        assert_eq!(
            review_packet(
                &mut c,
                packet,
                review_request(&original, 1, true),
                &settings
            )
            .await
            .unwrap_err(),
            Failure("packet_write_ack_failed"),
            "{stage}"
        );
        let current = automated_apply_agents::packet_service::dispatch(
            &mut c,
            "GET",
            &format!("/api/v1/application-packets/{packet}"),
            None,
            b"",
            &packet_settings(),
            &answer_settings(),
        )
        .await
        .unwrap()
        .0;
        assert_eq!(current, original, "{stage}");
        assert_eq!(
            sqlx::query_scalar::<_, Value>("SELECT value FROM owner_preferences WHERE key=$1")
                .bind(&key)
                .fetch_one(&mut c)
                .await
                .unwrap(),
            execution,
            "{stage}"
        );
        for (query, count) in [
            ("SELECT count(*) FROM application_events", 1),
            (
                "SELECT count(*) FROM owner_preferences WHERE starts_with(key,'prv:')",
                0,
            ),
            ("SELECT count(*) FROM owner_notifications", 0),
            ("SELECT count(*) FROM notification_deliveries", 0),
            ("SELECT count(*) FROM agent_telegram_deliveries", 0),
        ] {
            assert_eq!(
                sqlx::query_scalar::<_, i64>(sqlx::AssertSqlSafe(query))
                    .fetch_one(&mut c)
                    .await
                    .unwrap(),
                count,
                "{stage}"
            );
        }
        sqlx::raw_sql(sqlx::AssertSqlSafe(format!("DROP TRIGGER fixture_review_suppress ON {table}; DROP FUNCTION fixture_review_suppress()"))).execute(&mut c).await.unwrap();
    }
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn packet_review_preserves_existing_notice_and_uncertain_telegram_delivery_without_replay() {
    for existing_notice in [false, true] {
        let (mut c, _job, original) = packet_review_fixture().await;
        let packet = original["id"].as_str().unwrap().parse().unwrap();
        let key = bind_review_execution(&mut c, &original).await;
        let execution: Value =
            sqlx::query_scalar("SELECT value FROM owner_preferences WHERE key=$1")
                .bind(&key)
                .fetch_one(&mut c)
                .await
                .unwrap();
        let mut future = original.clone();
        future["revision"] = json!(2);
        future["approved_revision"] = json!(2);
        future["lifecycle_state"] = json!("approved_for_manual_handoff");
        future["readiness"]["state"] = json!("ready_for_manual_handoff");
        let notice = automated_apply_agents::packet_notice::propose(
            &future,
            Some(&execution),
            &json!({"revision":3,"state":"RUNNING","policy":{"telegram_questions":true}}),
            None,
            &automated_apply_agents::notification_preferences::normalize(json!({})).unwrap(),
            true,
            chrono::Utc::now(),
        )
        .unwrap()
        .unwrap();
        let update = notice.telegram.as_ref().unwrap()["update_id"]
            .as_i64()
            .unwrap();
        if existing_notice {
            sqlx::query("INSERT INTO owner_notifications(id,dedup_key,kind,title,body,href) VALUES($1,$2,'application_ready','Historical notice','Kept historical body',$3)").bind(Uuid::new_v4()).bind(notice.notification["dedup_key"].as_str().unwrap()).bind(format!("/applications/{packet}")).execute(&mut c).await.unwrap();
        } else {
            sqlx::query("INSERT INTO agent_telegram_deliveries(update_id,state,reply) VALUES($1,'sending','Historical uncertain send')").bind(update).execute(&mut c).await.unwrap();
        }
        let mut settings = packet_settings();
        settings.telegram_notices = true;
        let approved = review_packet(
            &mut c,
            packet,
            review_request(&original, 1, true),
            &settings,
        )
        .await
        .unwrap();
        assert_eq!(approved["approved_revision"], 2);
        if existing_notice {
            assert_eq!(
                sqlx::query_scalar::<_, String>("SELECT body FROM owner_notifications")
                    .fetch_one(&mut c)
                    .await
                    .unwrap(),
                "Kept historical body"
            );
            assert_eq!(
                sqlx::query_scalar::<_, i64>("SELECT count(*) FROM notification_deliveries")
                    .fetch_one(&mut c)
                    .await
                    .unwrap(),
                0
            );
            assert_eq!(
                sqlx::query_scalar::<_, i64>("SELECT count(*) FROM agent_telegram_deliveries")
                    .fetch_one(&mut c)
                    .await
                    .unwrap(),
                0
            );
        } else {
            let row: (String, String) = sqlx::query_as(
                "SELECT state,reply FROM agent_telegram_deliveries WHERE update_id=$1",
            )
            .bind(update)
            .fetch_one(&mut c)
            .await
            .unwrap();
            assert_eq!(row, ("sending".into(), "Historical uncertain send".into()));
            assert_eq!(
                sqlx::query_scalar::<_, i64>("SELECT count(*) FROM notification_deliveries")
                    .fetch_one(&mut c)
                    .await
                    .unwrap(),
                1
            );
        }
    }
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn packet_review_rejects_ambiguous_execution_binding_and_never_restarts_cancelled_execution()
{
    let (mut c, _job, original) = packet_review_fixture().await;
    let packet = original["id"].as_str().unwrap().parse().unwrap();
    let key = bind_review_execution(&mut c, &original).await;
    let duplicate = Uuid::from_u128(778);
    sqlx::query("INSERT INTO owner_preferences(key,value) SELECT $1,jsonb_set(value,'{id}',to_jsonb($2::text)) FROM owner_preferences WHERE key=$3").bind(format!("exec:{duplicate}")).bind(duplicate.to_string()).bind(&key).execute(&mut c).await.unwrap();
    assert_eq!(
        review_packet(
            &mut c,
            packet,
            review_request(&original, 1, true),
            &packet_settings()
        )
        .await
        .unwrap_err(),
        Failure("packet_execution_binding_conflict")
    );
    assert_eq!(
        sqlx::query_scalar::<_, i64>("SELECT count(*) FROM application_events")
            .fetch_one(&mut c)
            .await
            .unwrap(),
        1
    );
    sqlx::query("DELETE FROM owner_preferences WHERE key=$1")
        .bind(format!("exec:{duplicate}"))
        .execute(&mut c)
        .await
        .unwrap();
    sqlx::query("UPDATE owner_preferences SET value=jsonb_set(jsonb_set(value,'{state}','\"PAUSED\"'),'{cancelled}','true') WHERE key=$1").bind(&key).execute(&mut c).await.unwrap();
    let mut settings = packet_settings();
    settings.telegram_notices = true;
    let approved = review_packet(
        &mut c,
        packet,
        review_request(&original, 1, true),
        &settings,
    )
    .await
    .unwrap();
    assert_eq!(approved["approved_revision"], 2);
    let row: Value = sqlx::query_scalar("SELECT value FROM owner_preferences WHERE key=$1")
        .bind(&key)
        .fetch_one(&mut c)
        .await
        .unwrap();
    assert_eq!(row["cancelled"], true);
    assert_eq!(row["state"], "PAUSED");
    assert_eq!(row["revision"], 8);
    assert_eq!(row["fence"], 11);
    assert_eq!(
        sqlx::query_scalar::<_, i64>("SELECT count(*) FROM owner_notifications")
            .fetch_one(&mut c)
            .await
            .unwrap(),
        0
    );
    assert_eq!(
        sqlx::query_scalar::<_, i64>("SELECT count(*) FROM agent_telegram_deliveries")
            .fetch_one(&mut c)
            .await
            .unwrap(),
        0
    );
}
