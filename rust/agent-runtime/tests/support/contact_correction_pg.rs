//! Deferred fictional owner corrections. Provider calls and real contact records are excluded.
async fn correction_fixture() -> (PgConnection, Uuid, Uuid) {
    let (mut c, company, job) = contacts_fixture().await;
    sqlx::raw_sql("CREATE TABLE contact_identities(id uuid PRIMARY KEY,company_id uuid NOT NULL,contact_id uuid NOT NULL,namespace text NOT NULL,identity_key text NOT NULL)").execute(&mut c).await.unwrap();
    (c, company, job)
}
async fn contact_version(c: &mut PgConnection, id: u128) -> String {
    contacts_call(c, &contact_detail_path(id), None)
        .await
        .unwrap()["review_version"]
        .as_str()
        .unwrap()
        .to_owned()
}
async fn contact_correct(
    c: &mut PgConnection,
    id: u128,
    version: &str,
    input: Value,
) -> Result<Value> {
    contacts::correction::correct(
        c,
        Uuid::from_u128(id),
        Some(version),
        &serde_json::to_vec(&input).unwrap(),
        &contact_settings(),
    )
    .await
}
async fn correction_snapshot(c: &mut PgConnection) -> Value {
    sqlx::query_scalar("SELECT jsonb_build_object('contacts',(SELECT jsonb_agg(to_jsonb(c) ORDER BY id) FROM contacts c),'evidence',(SELECT jsonb_agg(to_jsonb(e) ORDER BY id) FROM contact_evidence e),'identities',(SELECT jsonb_agg(to_jsonb(i) ORDER BY id) FROM contact_identities i))").fetch_one(c).await.unwrap()
}
async fn mailbox_evidence(c: &mut PgConnection, company: Uuid) -> Uuid {
    let id = Uuid::from_u128(810001);
    sqlx::query("INSERT INTO contact_evidence(id,contact_id,company_id,source,evidence_type,strength,collected_at,expires_at,provenance,user_confirmed) VALUES($1,$2,$3,'manual','mailbox_verification','strong',clock_timestamp()-interval '1 day',clock_timestamp()+interval '2 days','{\"email\":\"person2@contact-fixture.example\",\"result\":\"deliverable\",\"method\":\"owner_confirmation\"}',true)").bind(id).bind(Uuid::from_u128(502)).bind(company).execute(c).await.unwrap();
    id
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn contact_correction_requires_exact_review_version_and_preserves_unrelated_state() {
    let (mut c, _, _) = correction_fixture().await;
    let before = correction_snapshot(&mut c).await;
    assert_eq!(
        contacts::correction::correct(
            &mut c,
            Uuid::from_u128(501),
            None,
            b"{}",
            &contact_settings()
        )
        .await
        .unwrap_err(),
        Failure("contact_review_precondition_required")
    );
    assert_eq!(
        contact_correct(
            &mut c,
            501,
            "stale",
            json!({"role_title":"Owner reviewed role"})
        )
        .await
        .unwrap_err(),
        Failure("contact_review_version_conflict")
    );
    assert_eq!(correction_snapshot(&mut c).await, before);
    let owner = browser_snapshot(&mut c).await;
    let version = contact_version(&mut c, 501).await;
    let result=contact_correct(&mut c,501,&version,json!({"role_title":"  Owner reviewed role  ","human_review_notes":"Fictional documented review"})).await.unwrap();
    assert_eq!(result["role_title"], "Owner reviewed role");
    assert_ne!(result["review_version"], version);
    assert_eq!(result["email_send_ready"], false);
    assert_eq!(browser_snapshot(&mut c).await, owner);
    let provenance: Value = sqlx::query_scalar(
        "SELECT provenance FROM contact_evidence WHERE evidence_type='human_correction'",
    )
    .fetch_one(&mut c)
    .await
    .unwrap();
    assert_eq!(provenance["previous_values"]["role_title"], "CTO");
    assert_eq!(
        provenance["changed_fields"],
        json!(["human_review_notes", "role_title"])
    );
    assert!(!result.to_string().contains("PRIVATE_CONTACT_VENDOR_CANARY"));
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn contact_correction_lost_response_cannot_replay_same_version_or_append_duplicate_evidence()
{
    let (mut c, _, _) = correction_fixture().await;
    let version = contact_version(&mut c, 501).await;
    let input = json!({"do_not_contact":true,"suppression_reason":"Owner exclusion"});
    let saved = contact_correct(&mut c, 501, &version, input.clone())
        .await
        .unwrap();
    assert_eq!(saved["priority"], "suppressed");
    assert_eq!(saved["manual_outreach_review_available"], false);
    let before = correction_snapshot(&mut c).await;
    assert_eq!(
        contact_correct(&mut c, 501, &version, input)
            .await
            .unwrap_err(),
        Failure("contact_review_version_conflict")
    );
    assert_eq!(correction_snapshot(&mut c).await, before);
    assert_eq!(
        sqlx::query_scalar::<_, i64>(
            "SELECT count(*) FROM contact_evidence WHERE evidence_type='human_correction'"
        )
        .fetch_one(&mut c)
        .await
        .unwrap(),
        1
    );
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn contact_correction_null_required_fields_fail_without_writes_but_nullable_notes_can_clear()
{
    let (mut c, _, _) = correction_fixture().await;
    let version = contact_version(&mut c, 501).await;
    let before = correction_snapshot(&mut c).await;
    for key in [
        "full_name",
        "role_title",
        "company_id",
        "email_status",
        "do_not_contact",
    ] {
        assert_eq!(
            contact_correct(&mut c, 501, &version, json!({(key):Value::Null}))
                .await
                .unwrap_err(),
            Failure("contact_required_field_null")
        );
    }
    assert_eq!(correction_snapshot(&mut c).await, before);
    let result = contact_correct(
        &mut c,
        501,
        &version,
        json!({"human_review_notes":null,"suppression_reason":null}),
    )
    .await
    .unwrap();
    assert!(result["human_review_notes"].is_null());
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn contact_correction_provider_and_identity_claims_cannot_create_verified_mailbox() {
    let (mut c, _, _) = correction_fixture().await;
    let version = contact_version(&mut c, 502).await;
    let before = correction_snapshot(&mut c).await;
    for evidence in [
        Value::Null,
        json!(Uuid::from_u128(600003)),
        json!(Uuid::new_v4()),
    ] {
        assert_eq!(
            contact_correct(
                &mut c,
                502,
                &version,
                json!({"email_status":"verified","verification_evidence_id":evidence})
            )
            .await
            .unwrap_err(),
            Failure("contact_current_mailbox_evidence_required")
        );
    }
    assert_eq!(correction_snapshot(&mut c).await, before);
    let version = contact_version(&mut c, 503).await;
    assert_eq!(
        contact_correct(
            &mut c,
            503,
            &version,
            json!({"email_status":"provider_reported"})
        )
        .await
        .unwrap_err(),
        Failure("contact_mailbox_missing")
    );
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn contact_correction_current_exact_mailbox_evidence_is_required_and_preserved() {
    let (mut c, company, _) = correction_fixture().await;
    let evidence = mailbox_evidence(&mut c, company).await;
    let version = contact_version(&mut c, 502).await;
    let before: Value =
        sqlx::query_scalar("SELECT to_jsonb(e) FROM contact_evidence e WHERE id=$1")
            .bind(evidence)
            .fetch_one(&mut c)
            .await
            .unwrap();
    let result = contact_correct(
        &mut c,
        502,
        &version,
        json!({"email_status":"verified","verification_evidence_id":evidence}),
    )
    .await
    .unwrap();
    assert_eq!(
        result["email_evidence_status"],
        "verified_using_authorized_method"
    );
    assert_eq!(result["email_send_ready"], false);
    assert_eq!(
        sqlx::query_scalar::<_, Value>("SELECT to_jsonb(e) FROM contact_evidence e WHERE id=$1")
            .bind(evidence)
            .fetch_one(&mut c)
            .await
            .unwrap(),
        before
    );
    assert_eq!(
        sqlx::query_scalar::<_, bool>(
            "SELECT last_verified_at=last_reviewed_at AND human_corrected FROM contacts WHERE id=$1"
        )
        .bind(Uuid::from_u128(502))
        .fetch_one(&mut c)
        .await
        .unwrap(),
        true
    );
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn contact_correction_rejects_expired_future_cross_company_mailbox_or_unauthorized_method_evidence()
 {
    let (mut c, company, _) = correction_fixture().await;
    let evidence = mailbox_evidence(&mut c, company).await;
    let version = contact_version(&mut c, 502).await;
    let original: Value =
        sqlx::query_scalar("SELECT to_jsonb(e) FROM contact_evidence e WHERE id=$1")
            .bind(evidence)
            .fetch_one(&mut c)
            .await
            .unwrap();
    for sql in [
        "expires_at=clock_timestamp()-interval '1 second'",
        "collected_at=clock_timestamp()+interval '1 day'",
        "company_id='33333333-3333-4333-8333-333333333333'",
        "user_confirmed=false",
        "provenance=jsonb_set(provenance::jsonb,'{email}','\"other@contact-fixture.example\"')",
        "provenance=jsonb_set(provenance::jsonb,'{method}','\"provider_claim\"')",
        "provenance=jsonb_set(provenance::jsonb,'{result}','\"unknown\"')",
    ] {
        sqlx::query("UPDATE contact_evidence SET company_id=($2::jsonb->>'company_id')::uuid,collected_at=($2::jsonb->>'collected_at')::timestamptz,expires_at=($2::jsonb->>'expires_at')::timestamptz,provenance=$2::jsonb->'provenance',user_confirmed=($2::jsonb->>'user_confirmed')::boolean WHERE id=$1").bind(evidence).bind(&original).execute(&mut c).await.unwrap();
        sqlx::query(&format!("UPDATE contact_evidence SET {sql} WHERE id=$1"))
            .bind(evidence)
            .execute(&mut c)
            .await
            .unwrap();
        let before = correction_snapshot(&mut c).await;
        assert_eq!(
            contact_correct(
                &mut c,
                502,
                &version,
                json!({"email_status":"verified","verification_evidence_id":evidence})
            )
            .await
            .unwrap_err(),
            Failure("contact_current_mailbox_evidence_required")
        );
        assert_eq!(correction_snapshot(&mut c).await, before);
    }
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn contact_correction_company_change_requires_email_review_and_clears_only_matching_identities()
 {
    let (mut c, company, _) = correction_fixture().await;
    let other = Uuid::from_u128(820001);
    sqlx::query("INSERT INTO companies(id,name,domain,metadata) VALUES($1,'Fictional Second Employer','second-contact-fixture.example','{}')").bind(other).execute(&mut c).await.unwrap();
    for n in [501, 503] {
        sqlx::query("INSERT INTO contact_identities VALUES($1,$2,$3,'manual',$4)")
            .bind(Uuid::from_u128(830000 + n))
            .bind(company)
            .bind(Uuid::from_u128(n))
            .bind(format!("fictional:{n}"))
            .execute(&mut c)
            .await
            .unwrap();
    }
    let version = contact_version(&mut c, 501).await;
    assert_eq!(
        contact_correct(&mut c, 501, &version, json!({"company_id":other}))
            .await
            .unwrap_err(),
        Failure("contact_affiliation_mailbox_review_required")
    );
    let version = contact_version(&mut c, 503).await;
    let result = contact_correct(&mut c, 503, &version, json!({"company_id":other}))
        .await
        .unwrap();
    assert_eq!(result["company_id"], other.to_string());
    assert_eq!(result["company"], "Fictional Second Employer");
    assert_eq!(
        sqlx::query_scalar::<_, Vec<Uuid>>(
            "SELECT array_agg(contact_id ORDER BY contact_id) FROM contact_identities"
        )
        .fetch_one(&mut c)
        .await
        .unwrap(),
        vec![Uuid::from_u128(501)]
    );
    assert_eq!(
        sqlx::query_scalar::<_, Uuid>(
            "SELECT company_id FROM contact_evidence WHERE evidence_type='human_correction'"
        )
        .fetch_one(&mut c)
        .await
        .unwrap(),
        other
    );
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn contact_correction_suppressed_or_altered_update_ack_rolls_back_every_change() {
    let (mut c, _, _) = correction_fixture().await;
    let version = contact_version(&mut c, 501).await;
    let before = correction_snapshot(&mut c).await;
    for behavior in ["RETURN NULL;", "NEW.email_status:='invalid';RETURN NEW;"] {
        sqlx::raw_sql(sqlx::AssertSqlSafe(format!("CREATE FUNCTION fixture_contact_update() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN {behavior} END $$;CREATE TRIGGER fixture_contact_update BEFORE UPDATE ON contacts FOR EACH ROW EXECUTE FUNCTION fixture_contact_update()"))).execute(&mut c).await.unwrap();
        assert_eq!(
            contact_correct(
                &mut c,
                501,
                &version,
                json!({"role_title":"Reviewed change"})
            )
            .await
            .unwrap_err(),
            Failure("contact_write_ack_failed")
        );
        assert_eq!(correction_snapshot(&mut c).await, before);
        sqlx::raw_sql("DROP TRIGGER fixture_contact_update ON contacts;DROP FUNCTION fixture_contact_update()").execute(&mut c).await.unwrap();
    }
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn contact_correction_evidence_ack_failure_rolls_back_contact_and_identity_deletion() {
    let (mut c, company, _) = correction_fixture().await;
    let other = Uuid::from_u128(840001);
    sqlx::query("INSERT INTO companies(id,name,domain,metadata) VALUES($1,'Fictional Second Employer','second-contact-fixture.example','{}')").bind(other).execute(&mut c).await.unwrap();
    sqlx::query("INSERT INTO contact_identities VALUES($1,$2,$3,'manual','fictional-identity')")
        .bind(Uuid::new_v4())
        .bind(company)
        .bind(Uuid::from_u128(503))
        .execute(&mut c)
        .await
        .unwrap();
    let version = contact_version(&mut c, 503).await;
    let before = correction_snapshot(&mut c).await;
    for behavior in ["RETURN NULL;", "NEW.user_confirmed:=false;RETURN NEW;"] {
        sqlx::raw_sql(sqlx::AssertSqlSafe(format!("CREATE FUNCTION fixture_contact_evidence() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN {behavior} END $$;CREATE TRIGGER fixture_contact_evidence BEFORE INSERT ON contact_evidence FOR EACH ROW EXECUTE FUNCTION fixture_contact_evidence()"))).execute(&mut c).await.unwrap();
        assert_eq!(
            contact_correct(&mut c, 503, &version, json!({"company_id":other}))
                .await
                .unwrap_err(),
            Failure("contact_write_ack_failed")
        );
        assert_eq!(correction_snapshot(&mut c).await, before);
        sqlx::raw_sql("DROP TRIGGER fixture_contact_evidence ON contact_evidence;DROP FUNCTION fixture_contact_evidence()").execute(&mut c).await.unwrap();
    }
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn contact_correction_identity_delete_ack_failure_is_atomic() {
    let (mut c, company, _) = correction_fixture().await;
    let other = Uuid::from_u128(850001);
    sqlx::query("INSERT INTO companies(id,name,domain,metadata) VALUES($1,'Fictional Second Employer','second-contact-fixture.example','{}')").bind(other).execute(&mut c).await.unwrap();
    sqlx::query("INSERT INTO contact_identities VALUES($1,$2,$3,'manual','fictional-identity')")
        .bind(Uuid::new_v4())
        .bind(company)
        .bind(Uuid::from_u128(503))
        .execute(&mut c)
        .await
        .unwrap();
    let version = contact_version(&mut c, 503).await;
    let before = correction_snapshot(&mut c).await;
    sqlx::raw_sql("CREATE FUNCTION fixture_contact_delete() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RETURN NULL; END $$;CREATE TRIGGER fixture_contact_delete BEFORE DELETE ON contact_identities FOR EACH ROW EXECUTE FUNCTION fixture_contact_delete()").execute(&mut c).await.unwrap();
    assert_eq!(
        contact_correct(&mut c, 503, &version, json!({"company_id":other}))
            .await
            .unwrap_err(),
        Failure("contact_write_ack_failed")
    );
    assert_eq!(correction_snapshot(&mut c).await, before);
    sqlx::raw_sql("DROP TRIGGER fixture_contact_delete ON contact_identities;DROP FUNCTION fixture_contact_delete()").execute(&mut c).await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn contact_correction_owner_http_requires_precondition_and_native_clients_are_denied() {
    let (mut c, _, _) = correction_fixture().await;
    let version = contact_version(&mut c, 501).await;
    let (url, stop, task) = http_fixture().await;
    let endpoint = format!("{url}{}", contact_detail_path(501));
    let http = client();
    assert_eq!(
        http.patch(&endpoint)
            .bearer_auth(HOST_TOKEN)
            .json(&json!({"do_not_contact":true}))
            .send()
            .await
            .unwrap()
            .status(),
        428
    );
    assert_eq!(
        http.patch(&endpoint)
            .bearer_auth(HOST_TOKEN)
            .header("x-agent-client", "extension")
            .header("if-match", &version)
            .json(&json!({"do_not_contact":true}))
            .send()
            .await
            .unwrap()
            .status(),
        403
    );
    let response = http
        .patch(&endpoint)
        .bearer_auth(HOST_TOKEN)
        .header("if-match", &version)
        .json(&json!({"do_not_contact":true}))
        .send()
        .await
        .unwrap();
    assert_eq!(response.status(), 200);
    assert_eq!(
        response.json::<Value>().await.unwrap()["priority"],
        "suppressed"
    );
    assert_eq!(
        http.patch(&endpoint)
            .bearer_auth(HOST_TOKEN)
            .header("if-match", version)
            .json(&json!({"do_not_contact":false}))
            .send()
            .await
            .unwrap()
            .status(),
        412
    );
    stop.cancel();
    task.await.unwrap();
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn contact_correction_concurrent_same_version_allows_only_one_complete_correction() {
    let (mut c, _, _) = correction_fixture().await;
    let version = contact_version(&mut c, 501).await;
    let mut other = connection().await;
    let (a, b) = tokio::join!(
        contact_correct(
            &mut c,
            501,
            &version,
            json!({"role_title":"Fictional review one"})
        ),
        contact_correct(
            &mut other,
            501,
            &version,
            json!({"role_title":"Fictional review two"})
        )
    );
    assert_ne!(a.is_ok(), b.is_ok());
    let error = if let Err(e) = a { e } else { b.unwrap_err() };
    assert!(matches!(
        error.0,
        "contact_review_version_conflict" | "contact_database_error" | "execution_database_error"
    ));
    assert_eq!(
        sqlx::query_scalar::<_, i64>(
            "SELECT count(*) FROM contact_evidence WHERE evidence_type='human_correction'"
        )
        .fetch_one(&mut c)
        .await
        .unwrap(),
        1
    );
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn contact_correction_owner_fence_ack_failure_rolls_back_and_preserves_private_conversation_json()
 {
    let (mut c, _, _) = correction_fixture().await;
    let version = contact_version(&mut c, 501).await;
    let before = correction_snapshot(&mut c).await;
    let owner = browser_snapshot(&mut c).await;
    sqlx::raw_sql("CREATE FUNCTION fixture_contact_owner() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.key='agent_conversation:primary' THEN RETURN NULL; END IF;RETURN NEW;END $$;CREATE TRIGGER fixture_contact_owner BEFORE UPDATE ON owner_preferences FOR EACH ROW EXECUTE FUNCTION fixture_contact_owner()").execute(&mut c).await.unwrap();
    assert_eq!(
        contact_correct(&mut c, 501, &version, json!({"do_not_contact":true}))
            .await
            .unwrap_err(),
        Failure("execution_write_ack_failed")
    );
    assert_eq!(correction_snapshot(&mut c).await, before);
    assert_eq!(browser_snapshot(&mut c).await, owner);
    sqlx::raw_sql("DROP TRIGGER fixture_contact_owner ON owner_preferences;DROP FUNCTION fixture_contact_owner()").execute(&mut c).await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn contact_correction_identity_inventory_limit_refuses_without_partial_cleanup() {
    let (mut c, company, _) = correction_fixture().await;
    let other = Uuid::from_u128(860001);
    sqlx::query("INSERT INTO companies(id,name,domain,metadata) VALUES($1,'Fictional Second Employer','second-contact-fixture.example','{}')").bind(other).execute(&mut c).await.unwrap();
    sqlx::query("INSERT INTO contact_identities SELECT lpad(to_hex(1000000+n),32,'0')::uuid,$1,$2,'manual',n::text FROM generate_series(1,10001) n").bind(company).bind(Uuid::from_u128(503)).execute(&mut c).await.unwrap();
    let version = contact_version(&mut c, 503).await;
    let before = correction_snapshot(&mut c).await;
    assert_eq!(
        contact_correct(&mut c, 503, &version, json!({"company_id":other}))
            .await
            .unwrap_err(),
        Failure("contact_identity_inventory_limit")
    );
    assert_eq!(correction_snapshot(&mut c).await, before);
}
