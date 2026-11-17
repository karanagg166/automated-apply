// Deferred local professional imports against the real public-person/identity table definitions.
use automated_apply_agents::people_research::ingest as people_ingest;
async fn people_ingest_fixture() -> (PgConnection, Uuid) {
    let mut c = startup_run_fixture().await;
    let source = include_str!("../../../../supabase/fresh_public/001_phase1_public.sql");
    let table = source
        .split("CREATE TABLE IF NOT EXISTS public.contact_identities (")
        .nth(1)
        .unwrap()
        .split("CREATE INDEX IF NOT EXISTS idx_contact_identity_contact")
        .next()
        .unwrap();
    sqlx::raw_sql(sqlx::AssertSqlSafe(format!(
        "CREATE TABLE IF NOT EXISTS public.contact_identities ({table}"
    )))
    .execute(&mut c)
    .await
    .unwrap();
    let company: Uuid =
        sqlx::query_scalar("SELECT id FROM companies WHERE domain='contact-fixture.example'")
            .fetch_one(&mut c)
            .await
            .unwrap();
    (c, company)
}
fn people_manual() -> Value {
    json!({"company_name":"Fictional Contact Employer","company_domain":"contact-fixture.example","source":"manual","manual_people":[{"name":"Fictional Imported Professional","role":"cto","linkedin_url":"https://linkedin.com/in/fictional-manual-professional","evidence_url":"https://contact-fixture.example/team","verification_status":"source_reported"}]})
}
fn people_official(human: bool) -> Value {
    json!({"company_name":"Fictional Contact Employer","company_domain":"contact-fixture.example","source":"manual","research_mode":"official_company","permission_confirmed":true,"official_people":[{"full_name":"Fictional Official Professional","role_title":"CTO","evidence_url":"https://contact-fixture.example/team","permission_evidence_url":"https://contact-fixture.example/permission","observed_at":"2026-11-15T12:00:00Z","human_confirmed":human,"business_email":"published-person@contact-fixture.example","email_publication_url":"https://contact-fixture.example/contact"}]})
}
async fn people_import(c: &mut PgConnection, v: Value, n: u128) -> Result<Value> {
    people_ingest::manual(c, v, Uuid::from_u128(n), &contact_settings()).await
}
async fn people_ingest_snapshot(c: &mut PgConnection) -> Value {
    sqlx::query_scalar("SELECT jsonb_build_object('companies',(SELECT jsonb_agg(to_jsonb(c) ORDER BY id) FROM companies c),'people',(SELECT jsonb_agg(to_jsonb(p) ORDER BY id) FROM discovered_company_people p),'contacts',(SELECT jsonb_agg(to_jsonb(c) ORDER BY id) FROM contacts c),'evidence',(SELECT jsonb_agg(to_jsonb(e) ORDER BY id) FROM contact_evidence e),'identities',(SELECT jsonb_agg(to_jsonb(i) ORDER BY id) FROM contact_identities i),'receipts',(SELECT jsonb_object_agg(key,value) FROM owner_preferences WHERE starts_with(key,'cl_obs:') OR starts_with(key,'people_import:')))").fetch_one(c).await.unwrap()
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn people_manual_import_deduplicates_actual_public_table_and_keeps_contact_identity_unverified()
 {
    let (mut c, company) = people_ingest_fixture().await;
    let before = people_ingest_snapshot(&mut c).await;
    let mut input = people_manual();
    let mut duplicate = input["manual_people"][0].clone();
    duplicate["linkedin_url"] =
        json!("https://www.linkedin.com/in/fictional-manual-professional/?utm_source=fixture");
    input["manual_people"]
        .as_array_mut()
        .unwrap()
        .push(duplicate);
    let result = people_import(&mut c, input, 10001).await.unwrap();
    assert_eq!(result["status"], "success");
    assert_eq!(result["people"].as_array().unwrap().len(), 1);
    assert_eq!(
        result["people"][0]["verification_status"],
        "requires_review"
    );
    let row: Value = sqlx::query_scalar(
        "SELECT to_jsonb(c) FROM contacts c WHERE full_name='Fictional Imported Professional'",
    )
    .fetch_one(&mut c)
    .await
    .unwrap();
    assert_eq!(row["metadata"]["identity_review_required"], true);
    assert_eq!(row["metadata"]["identity_human_confirmed"], false);
    assert!(row["email"].is_null());
    assert!(row["last_verified_at"].is_null());
    let saved = company_saved_call(&mut c, company, "people", None)
        .await
        .unwrap();
    assert!(
        saved["people"]
            .as_array()
            .unwrap()
            .iter()
            .any(|p| p["name"] == "Fictional Imported Professional")
    );
    let after = people_ingest_snapshot(&mut c).await;
    assert_eq!(after["companies"], before["companies"]);
    assert_eq!(result["provider_calls"], 0);
    assert_eq!(result["outbound_messages_sent"], 0);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn people_import_uuid_replay_and_retained_read_preserve_exact_original_evidence_and_conflict_on_change()
 {
    let (mut c, _) = people_ingest_fixture().await;
    let input = people_manual();
    let first = people_import(&mut c, input.clone(), 10002).await.unwrap();
    let before = people_ingest_snapshot(&mut c).await;
    assert_eq!(
        people_import(&mut c, input.clone(), 10002).await.unwrap(),
        first
    );
    assert_eq!(
        people_ingest::retained(&mut c, Uuid::from_u128(10002))
            .await
            .unwrap(),
        first
    );
    let mut changed = input;
    changed["manual_people"][0]["role"] = json!("founder");
    assert_eq!(
        people_import(&mut c, changed, 10002).await.unwrap_err(),
        Failure("public_research_request_conflict")
    );
    assert_eq!(people_ingest_snapshot(&mut c).await, before);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn people_official_unconfirmed_publication_is_unknown_mailbox_and_requires_identity_review() {
    let (mut c, _) = people_ingest_fixture().await;
    let result = people_import(&mut c, people_official(false), 10003)
        .await
        .unwrap();
    assert_eq!(result["status"], "success");
    assert_eq!(
        result["people"][0]["verification_status"],
        "requires_review"
    );
    assert_eq!(
        result["people"][0]["identity_independently_confirmed"],
        false
    );
    let id: Uuid = result["people"][0]["contact_id"]
        .as_str()
        .unwrap()
        .parse()
        .unwrap();
    let row = contact_identity_row(&mut c, id).await;
    assert_eq!(row["email_status"], "unknown");
    assert!(row["last_verified_at"].is_null());
    assert_eq!(row["metadata"]["identity_review_required"], true);
    assert_ne!(row["metadata"]["email_publication_confirmed"], true);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn people_official_owner_confirmation_preserves_attributable_fact_source_without_mailbox_verification_or_sending()
 {
    let (mut c, _) = people_ingest_fixture().await;
    let result = people_import(&mut c, people_official(true), 10004)
        .await
        .unwrap();
    let id: Uuid = result["people"][0]["contact_id"]
        .as_str()
        .unwrap()
        .parse()
        .unwrap();
    let row = contact_identity_row(&mut c, id).await;
    assert_eq!(
        result["people"][0]["verification_status"],
        "human_confirmed"
    );
    assert_eq!(row["metadata"]["identity_human_confirmed"], true);
    assert_eq!(row["metadata"]["email_publication_confirmed"], true);
    assert_eq!(row["metadata"]["identity_review_required"], false);
    assert_eq!(row["email_status"], "unknown");
    assert!(row["last_verified_at"].is_null());
    assert_eq!(result["outbound_messages_sent"], 0);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn people_official_foreign_employer_and_unattributable_published_mailboxes_are_rejected_before_company_creation()
 {
    let (mut c, _) = people_ingest_fixture().await;
    let mut input = people_official(true);
    input["official_people"][0]["evidence_url"] = json!("https://other-fixture.example/team");
    let mut second = people_official(true)["official_people"][0].clone();
    second["email_publication_url"] = json!("https://other-fixture.example/contact");
    input["official_people"]
        .as_array_mut()
        .unwrap()
        .push(second);
    let before = people_ingest_snapshot(&mut c).await;
    let result = people_import(&mut c, input, 10005).await.unwrap();
    assert_eq!(result["status"], "partial");
    assert_eq!(result["people"], json!([]));
    assert_eq!(result["errors"].as_array().unwrap().len(), 2);
    let after = people_ingest_snapshot(&mut c).await;
    for key in ["companies", "people", "contacts", "evidence", "identities"] {
        assert_eq!(after[key], before[key]);
    }
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn people_manual_nonempty_import_needs_explicit_domain_and_official_rights_and_refuses_public_source()
 {
    let (mut c, _) = people_ingest_fixture().await;
    let before = people_ingest_snapshot(&mut c).await;
    let mut missing = people_manual();
    missing["company_domain"] = Value::Null;
    assert_eq!(
        people_import(&mut c, missing, 10006).await.unwrap_err(),
        Failure("public_research_company_domain_required")
    );
    let mut no_rights = people_official(true);
    no_rights["permission_confirmed"] = json!(false);
    assert_eq!(
        people_import(&mut c, no_rights, 10006).await.unwrap_err(),
        Failure("public_research_official_permission_required")
    );
    let mut public = people_manual();
    public["source"] = json!("public_search");
    assert!(people_import(&mut c, public, 10006).await.is_err());
    assert_eq!(people_ingest_snapshot(&mut c).await, before);
    let empty = people_import(
        &mut c,
        json!({"company_name":"Fictional","source":"manual"}),
        10007,
    )
    .await
    .unwrap();
    assert_eq!(empty["status"], "no_results");
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn people_manual_cannot_overwrite_human_confirmed_public_rows_or_bridge_them_as_new_claims() {
    let (mut c, _) = people_ingest_fixture().await;
    let id = Uuid::from_u128(990001);
    let before: Value =
        sqlx::query_scalar("SELECT to_jsonb(p) FROM discovered_company_people p WHERE id=$1")
            .bind(id)
            .fetch_one(&mut c)
            .await
            .unwrap();
    let contacts_before = contact_identity_snapshot(&mut c).await;
    let mut input = people_manual();
    input["manual_people"][0]["linkedin_url"] =
        json!("https://linkedin.com/in/fictional-professional-1");
    people_import(&mut c, input, 10008).await.unwrap();
    let after: Value =
        sqlx::query_scalar("SELECT to_jsonb(p) FROM discovered_company_people p WHERE id=$1")
            .bind(id)
            .fetch_one(&mut c)
            .await
            .unwrap();
    assert_eq!(after, before);
    assert_eq!(contact_identity_snapshot(&mut c).await, contacts_before);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn people_manual_preserves_existing_suppression_and_owner_corrected_contact_facts() {
    let (mut c, _) = people_ingest_fixture().await;
    for (n, field) in [(504, "do_not_contact"), (505, "human_corrected")] {
        sqlx::query(sqlx::AssertSqlSafe(format!(
            "UPDATE contacts SET {field}=true WHERE id=$1"
        )))
        .bind(Uuid::from_u128(n))
        .execute(&mut c)
        .await
        .unwrap();
        let before = contact_identity_row(&mut c, Uuid::from_u128(n)).await;
        let mut input = people_manual();
        input["manual_people"][0]["linkedin_url"] = json!(format!(
            "https://linkedin.com/in/fictional-contact-{}",
            n - 500
        ));
        input["manual_people"][0]["name"] = before["full_name"].clone();
        people_import(&mut c, input, n + 10000).await.unwrap();
        let after = contact_identity_row(&mut c, Uuid::from_u128(n)).await;
        for key in [
            "full_name",
            "role_title",
            "email",
            "email_status",
            "last_verified_at",
            "human_corrected",
            "do_not_contact",
            "suppression_reason",
            "human_review_notes",
        ] {
            assert_eq!(after[key], before[key], "protected {key}");
        }
        if n == 504 {
            assert_eq!(after, before)
        }
    }
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn people_import_public_row_complete_ack_failure_rolls_back_earlier_contact_and_whole_batch()
{
    let (mut c, _) = people_ingest_fixture().await;
    let before = people_ingest_snapshot(&mut c).await;
    for (timing, body) in [
        (
            "BEFORE",
            "IF NEW.name='Second Fictional Professional' THEN RETURN NULL;END IF;RETURN NEW;",
        ),
        (
            "AFTER",
            "IF pg_trigger_depth()=1 AND NEW.name='Second Fictional Professional' THEN UPDATE discovered_company_people SET role='Corrupted role' WHERE id=NEW.id;END IF;RETURN NEW;",
        ),
    ] {
        sqlx::raw_sql(sqlx::AssertSqlSafe(format!("CREATE FUNCTION fixture_people_corrupt() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN {body} END $$;CREATE TRIGGER fixture_people_corrupt {timing} INSERT ON discovered_company_people FOR EACH ROW EXECUTE FUNCTION fixture_people_corrupt()"))).execute(&mut c).await.unwrap();
        let mut input = people_manual();
        let mut second = input["manual_people"][0].clone();
        second["name"] = json!("Second Fictional Professional");
        second["linkedin_url"] = json!("https://linkedin.com/in/fictional-second-import");
        input["manual_people"].as_array_mut().unwrap().push(second);
        assert_eq!(
            people_import(&mut c, input, 10009).await.unwrap_err(),
            Failure("public_research_write_ack_failed")
        );
        assert_eq!(people_ingest_snapshot(&mut c).await, before);
        sqlx::raw_sql("DROP TRIGGER fixture_people_corrupt ON discovered_company_people;DROP FUNCTION fixture_people_corrupt()").execute(&mut c).await.unwrap();
    }
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn people_import_shared_identity_post_trigger_evidence_mapping_and_receipt_drift_roll_back() {
    let (mut c, _) = people_ingest_fixture().await;
    let before = people_ingest_snapshot(&mut c).await;
    for (table, body) in [
        (
            "contact_evidence",
            "IF pg_trigger_depth()=1 THEN UPDATE contact_evidence SET observed_role='Corrupted role' WHERE id=NEW.id;END IF;RETURN NEW;",
        ),
        (
            "contact_identities",
            "IF pg_trigger_depth()=1 THEN UPDATE contact_identities SET identity_key='Corrupted identity' WHERE id=NEW.id;END IF;RETURN NEW;",
        ),
        (
            "owner_preferences",
            "IF pg_trigger_depth()=1 AND starts_with(NEW.key,'cl_obs:') THEN UPDATE owner_preferences SET value=value||'{\"corrupted\":true}'::jsonb WHERE key=NEW.key;END IF;RETURN NEW;",
        ),
    ] {
        sqlx::raw_sql(sqlx::AssertSqlSafe(format!("CREATE FUNCTION fixture_identity_corrupt() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN {body} END $$;CREATE TRIGGER fixture_identity_corrupt AFTER INSERT ON {table} FOR EACH ROW EXECUTE FUNCTION fixture_identity_corrupt()"))).execute(&mut c).await.unwrap();
        assert_eq!(
            people_import(&mut c, people_manual(), 10010)
                .await
                .unwrap_err(),
            Failure("contact_identity_write_ack_failed")
        );
        assert_eq!(people_ingest_snapshot(&mut c).await, before);
        sqlx::raw_sql(sqlx::AssertSqlSafe(format!("DROP TRIGGER fixture_identity_corrupt ON {table};DROP FUNCTION fixture_identity_corrupt()"))).execute(&mut c).await.unwrap();
    }
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn people_import_retained_receipts_exclude_unknown_nested_private_data_and_do_not_write() {
    let (mut c, _) = people_ingest_fixture().await;
    people_import(&mut c, people_official(false), 10011)
        .await
        .unwrap();
    sqlx::query("UPDATE owner_preferences SET value=jsonb_set(value,'{result,people,0,private_vendor}',to_jsonb('PRIVATE_NESTED_RESEARCH_CANARY'::text)) WHERE key=$1").bind(format!("people_import:{}",Uuid::from_u128(10011).simple())).execute(&mut c).await.unwrap();
    let before = people_ingest_snapshot(&mut c).await;
    let v = people_ingest::retained(&mut c, Uuid::from_u128(10011))
        .await
        .unwrap();
    assert!(!v.to_string().contains("PRIVATE_NESTED_RESEARCH_CANARY"));
    assert_eq!(people_ingest_snapshot(&mut c).await, before);
    assert_eq!(
        people_ingest::retained(&mut c, Uuid::nil())
            .await
            .unwrap_err(),
        Failure("public_research_request_not_found")
    );
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn people_import_concurrent_same_uuid_keeps_one_original_result_and_one_public_person() {
    let (mut c, _) = people_ingest_fixture().await;
    let mut other = connection().await;
    let input = people_manual();
    let (a, b) = tokio::join!(
        people_import(&mut c, input.clone(), 10012),
        people_import(&mut other, input, 10012)
    );
    let first = a.or(b).unwrap();
    assert_eq!(
        people_ingest::retained(&mut c, Uuid::from_u128(10012))
            .await
            .unwrap(),
        first
    );
    let count:i64=sqlx::query_scalar("SELECT count(*)::bigint FROM discovered_company_people WHERE linkedin_url='https://www.linkedin.com/in/fictional-manual-professional/'").fetch_one(&mut c).await.unwrap();
    assert_eq!(count, 1);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn people_import_contact_qualification_after_trigger_drift_rolls_back_every_coupled_row() {
    let (mut c, _) = people_ingest_fixture().await;
    let before = people_ingest_snapshot(&mut c).await;
    sqlx::raw_sql("CREATE FUNCTION fixture_people_contact_corrupt() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF pg_trigger_depth()=1 AND NEW.full_name='Fictional Imported Professional' AND NEW.metadata->'identity_review_required'='true'::jsonb THEN UPDATE contacts SET email='corrupt-fixture@contact-fixture.example' WHERE id=NEW.id;END IF;RETURN NEW;END $$;CREATE TRIGGER fixture_people_contact_corrupt AFTER UPDATE ON contacts FOR EACH ROW EXECUTE FUNCTION fixture_people_contact_corrupt()").execute(&mut c).await.unwrap();
    assert_eq!(
        people_import(&mut c, people_manual(), 10013)
            .await
            .unwrap_err(),
        Failure("public_research_write_ack_failed")
    );
    assert_eq!(people_ingest_snapshot(&mut c).await, before);
    sqlx::raw_sql("DROP TRIGGER fixture_people_contact_corrupt ON contacts;DROP FUNCTION fixture_people_contact_corrupt()").execute(&mut c).await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn people_import_duplicate_legacy_canonical_urls_require_review_without_creating_a_third_person()
 {
    let (mut c, company) = people_ingest_fixture().await;
    sqlx::query("INSERT INTO discovered_company_people(id,company_id,name,role,linkedin_url,evidence_url,source,observed_at,verification_status) VALUES($1,$2,'Fictional Duplicate','CTO','https://www.linkedin.com/in/fictional-professional-1/?utm_source=fixture','https://contact-fixture.example/team','manual',clock_timestamp(),'requires_review')").bind(Uuid::from_u128(1001400)).bind(company).execute(&mut c).await.unwrap();
    let mut input = people_manual();
    input["manual_people"][0]["linkedin_url"] =
        json!("https://linkedin.com/in/fictional-professional-1");
    let before = people_ingest_snapshot(&mut c).await;
    assert_eq!(
        people_import(&mut c, input, 10014).await.unwrap_err(),
        Failure("public_research_person_url_ambiguous")
    );
    assert_eq!(people_ingest_snapshot(&mut c).await, before);
}
