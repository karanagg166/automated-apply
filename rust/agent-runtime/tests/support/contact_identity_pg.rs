// Deferred fictional identity reconciliation, suppression and complete-ACK fixtures.
use automated_apply_agents::contacts::enrichment::identity as contact_identity;
async fn contact_identity_fixture() -> (PgConnection, Uuid) {
    let (mut c, company, _) = contacts_fixture().await;
    sqlx::raw_sql("CREATE TABLE contact_identities(id uuid PRIMARY KEY,company_id uuid NOT NULL,contact_id uuid NOT NULL,namespace varchar(100) NOT NULL,identity_key varchar(2048) NOT NULL,discovered_person_id uuid,UNIQUE(company_id,namespace,identity_key))").execute(&mut c).await.unwrap();
    (c, company)
}
fn contact_identity_observation(n: u128) -> Value {
    json!({"full_name":format!("Fictional Contact {n}"),"role_title":"Observed engineering lead","company_domain":"contact-fixture.example","linkedin_url":format!("https://www.linkedin.com/in/fictional-contact-{n}/"),"email":format!("person{n}@contact-fixture.example"),"source":"apollo","provider_person_id":format!("fictional-person-{n}"),"email_status":"verified","provider_verification_claim":"verified","evidence_strength":"moderate"})
}
async fn contact_identity_call(
    c: &mut PgConnection,
    company: Uuid,
    observation: Value,
    n: u64,
) -> Result<Value> {
    contact_identity::reconcile(
        c,
        company,
        observation,
        &format!("{n:064x}"),
        &contact_settings(),
    )
    .await
}
async fn contact_identity_row(c: &mut PgConnection, id: Uuid) -> Value {
    sqlx::query_scalar("SELECT to_jsonb(c) FROM contacts c WHERE id=$1")
        .bind(id)
        .fetch_one(c)
        .await
        .unwrap()
}
async fn contact_identity_snapshot(c: &mut PgConnection) -> Value {
    sqlx::query_scalar("SELECT jsonb_build_object('contacts',(SELECT jsonb_agg(to_jsonb(c) ORDER BY id) FROM contacts c),'evidence',(SELECT jsonb_agg(to_jsonb(e) ORDER BY id) FROM contact_evidence e),'identities',(SELECT jsonb_agg(to_jsonb(i) ORDER BY id) FROM contact_identities i),'receipts',(SELECT jsonb_object_agg(key,value) FROM owner_preferences WHERE starts_with(key,'cl_obs:')))").fetch_one(c).await.unwrap()
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn contact_identity_existing_profile_reconciles_without_creating_verified_mailbox() {
    let (mut c, company) = contact_identity_fixture().await;
    let result = contact_identity_call(&mut c, company, contact_identity_observation(5), 1)
        .await
        .unwrap();
    assert_eq!(result["contact_id"], Uuid::from_u128(505).to_string());
    assert_eq!(result["created"], false);
    let row = contact_identity_row(&mut c, Uuid::from_u128(505)).await;
    assert_eq!(row["role_title"], "Observed engineering lead");
    assert_eq!(row["full_name"], "Fictional Contact 5");
    assert_eq!(row["metadata"]["evidence_strength"], "strong");
    assert!(!row["last_checked_at"].is_null());
    // Already-saved verified status stays saved; new observation never updates its verification time.
    let mut observation = contact_identity_observation(3);
    observation["linkedin_url"] = Value::Null;
    let result = contact_identity_call(&mut c, company, observation, 2)
        .await
        .unwrap();
    let id: Uuid = result["contact_id"].as_str().unwrap().parse().unwrap();
    let row = contact_identity_row(&mut c, id).await;
    assert_eq!(row["email_status"], "provider_reported");
    assert!(row["last_verified_at"].is_null());
    assert_eq!(row["confidence_score"], 0.0);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn contact_identity_exact_receipt_replay_preserves_timestamps_rows_and_evidence_count() {
    let (mut c, company) = contact_identity_fixture().await;
    let input = contact_identity_observation(5);
    let result = contact_identity_call(&mut c, company, input.clone(), 10)
        .await
        .unwrap();
    let before = contact_identity_snapshot(&mut c).await;
    assert_eq!(
        contact_identity_call(&mut c, company, input.clone(), 10)
            .await
            .unwrap(),
        result
    );
    assert_eq!(contact_identity_snapshot(&mut c).await, before);
    let mut changed = input;
    changed["role_title"] = json!("Different role");
    assert_eq!(
        contact_identity_call(&mut c, company, changed, 10)
            .await
            .unwrap_err(),
        Failure("contact_observation_receipt_conflict")
    );
    assert_eq!(contact_identity_snapshot(&mut c).await, before);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn contact_identity_owner_corrected_facts_verification_and_freshness_remain_unchanged() {
    let (mut c, company) = contact_identity_fixture().await;
    sqlx::query("UPDATE contacts SET human_corrected=true,human_review_notes='Owner retained facts' WHERE id=$1").bind(Uuid::from_u128(505)).execute(&mut c).await.unwrap();
    let before = contact_identity_row(&mut c, Uuid::from_u128(505)).await;
    let mut input = contact_identity_observation(5);
    input["full_name"] = json!("Different vendor name");
    input["email"] = json!("other@contact-fixture.example");
    let result = contact_identity_call(&mut c, company, input, 11)
        .await
        .unwrap();
    assert_eq!(result["requires_review"], true);
    let after = contact_identity_row(&mut c, Uuid::from_u128(505)).await;
    for key in [
        "full_name",
        "role_title",
        "email",
        "email_status",
        "last_verified_at",
        "last_reviewed_at",
        "last_checked_at",
        "human_review_notes",
        "human_corrected",
        "do_not_contact",
    ] {
        assert_eq!(after[key], before[key], "{key}");
    }
    assert_eq!(after["metadata"]["identity_review_required"], true);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn contact_identity_suppressed_profile_or_hashed_tombstone_cannot_be_recreated() {
    let (mut c, company) = contact_identity_fixture().await;
    let before = contact_identity_row(&mut c, Uuid::from_u128(504)).await;
    let result = contact_identity_call(&mut c, company, contact_identity_observation(4), 12)
        .await
        .unwrap();
    assert_eq!(result["conflicts"], json!(["suppressed"]));
    assert_eq!(
        contact_identity_row(&mut c, Uuid::from_u128(504)).await,
        before
    );
    assert!(result["evidence_id"].is_null());
    use sha2::Digest as _;
    let profile = "https://www.linkedin.com/in/tombstoned-fictional-contact/";
    let hash = format!("{:x}", sha2::Sha256::digest(profile.as_bytes()));
    sqlx::query("INSERT INTO contact_identities VALUES($1,$2,$3,'suppressed_linkedin',$4,NULL)")
        .bind(Uuid::new_v4())
        .bind(company)
        .bind(Uuid::from_u128(504))
        .bind(hash)
        .execute(&mut c)
        .await
        .unwrap();
    let mut input = contact_identity_observation(77);
    input["linkedin_url"] = json!(profile);
    let result = contact_identity_call(&mut c, company, input, 13)
        .await
        .unwrap();
    assert_eq!(result["conflicts"], json!(["suppressed"]));
    assert_eq!(result["created"], false);
    assert_eq!(
        sqlx::query_scalar::<_, i64>("SELECT count(*) FROM contacts")
            .fetch_one(&mut c)
            .await
            .unwrap(),
        5
    );
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn contact_identity_incompatible_names_or_multiple_profile_email_matches_are_quarantined() {
    let (mut c, company) = contact_identity_fixture().await;
    let before = contact_identity_row(&mut c, Uuid::from_u128(501)).await;
    let mut input = contact_identity_observation(1);
    input["full_name"] = json!("Conflicting vendor name");
    let result = contact_identity_call(&mut c, company, input, 14)
        .await
        .unwrap();
    assert_eq!(result["requires_review"], true);
    assert!(result["contact_id"].is_null());
    let row = contact_identity_row(&mut c, Uuid::from_u128(501)).await;
    for key in [
        "full_name",
        "role_title",
        "email",
        "email_status",
        "last_checked_at",
    ] {
        assert_eq!(row[key], before[key]);
    }
    let mut input = contact_identity_observation(5);
    input["email"] = json!("person1@contact-fixture.example");
    let result = contact_identity_call(&mut c, company, input, 15)
        .await
        .unwrap();
    assert_eq!(result["requires_review"], true);
    assert_eq!(
        sqlx::query_scalar::<_, i64>("SELECT count(*) FROM contacts")
            .fetch_one(&mut c)
            .await
            .unwrap(),
        5
    );
    assert_eq!(
        contact_identity_row(&mut c, Uuid::from_u128(505)).await["metadata"]["identity_review_required"],
        true
    );
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn contact_identity_name_only_observation_does_not_merge_without_current_exact_owner_source_support()
 {
    let (mut c, company) = contact_identity_fixture().await;
    let input = json!({"full_name":"Fictional Contact 3","role_title":"Rust Engineer","source":"public_search","company_domain":"contact-fixture.example","evidence_url":"https://contact-fixture.example/team"});
    let first = contact_identity_call(&mut c, company, input.clone(), 16)
        .await
        .unwrap();
    assert_eq!(first["created"], true);
    assert_ne!(first["contact_id"], Uuid::from_u128(503).to_string());
    sqlx::query("INSERT INTO contact_evidence(id,company_id,contact_id,source,evidence_type,evidence_url,strength,collected_at,expires_at,user_confirmed,provenance) VALUES($1,$2,$3,'manual','human_correction','https://contact-fixture.example/confirmed-team','strong',clock_timestamp()-interval '1 day',clock_timestamp()+interval '1 day',true,'{}')").bind(Uuid::new_v4()).bind(company).bind(Uuid::from_u128(503)).execute(&mut c).await.unwrap();
    let mut supported = input;
    supported["evidence_url"] = json!("https://contact-fixture.example/confirmed-team");
    let result = contact_identity_call(&mut c, company, supported, 17)
        .await
        .unwrap();
    assert_eq!(result["contact_id"], Uuid::from_u128(503).to_string());
    assert_eq!(result["created"], false);
    assert_eq!(
        contact_identity_row(&mut c, Uuid::from_u128(503)).await["metadata"]["evidence_strength"],
        "moderate"
    );
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn contact_identity_role_mailbox_is_company_evidence_and_never_person_specific_email() {
    let (mut c, company) = contact_identity_fixture().await;
    let mut input = contact_identity_observation(5);
    input["email"] = json!("HR@contact-fixture.example");
    input["email_kind"] = json!("role_based");
    let before = contact_identity_row(&mut c, Uuid::from_u128(505)).await;
    let result = contact_identity_call(&mut c, company, input, 18)
        .await
        .unwrap();
    let after = contact_identity_row(&mut c, Uuid::from_u128(505)).await;
    assert_eq!(after["email"], before["email"]);
    let evidence: Value =
        sqlx::query_scalar("SELECT to_jsonb(e) FROM contact_evidence e WHERE id=$1")
            .bind(
                result["evidence_id"]
                    .as_str()
                    .unwrap()
                    .parse::<Uuid>()
                    .unwrap(),
            )
            .fetch_one(&mut c)
            .await
            .unwrap();
    assert!(evidence["contact_id"].is_null());
    assert_eq!(evidence["evidence_type"], "company_business_inbox");
    assert_eq!(evidence["provenance"]["email_kind"], "role_based");
    assert_eq!(
        evidence["provenance"]["email"],
        "hr@contact-fixture.example"
    );
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn contact_identity_company_conflict_records_review_evidence_without_creating_or_reaffiliating_people()
 {
    let (mut c, company) = contact_identity_fixture().await;
    let mut input = contact_identity_observation(77);
    input["company_domain"] = json!("other.example");
    let result = contact_identity_call(&mut c, company, input, 19)
        .await
        .unwrap();
    assert_eq!(result["requires_review"], true);
    assert!(result["contact_id"].is_null());
    assert_eq!(
        sqlx::query_scalar::<_, i64>("SELECT count(*) FROM contacts")
            .fetch_one(&mut c)
            .await
            .unwrap(),
        5
    );
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn contact_identity_new_email_claim_is_provider_reported_and_invalid_existing_status_requires_review()
 {
    let (mut c, company) = contact_identity_fixture().await;
    sqlx::query(
        "UPDATE contacts SET email=NULL,email_status='unknown',last_verified_at=NULL WHERE id=$1",
    )
    .bind(Uuid::from_u128(505))
    .execute(&mut c)
    .await
    .unwrap();
    let result = contact_identity_call(&mut c, company, contact_identity_observation(5), 20)
        .await
        .unwrap();
    assert_eq!(result["requires_review"], false);
    let after = contact_identity_row(&mut c, Uuid::from_u128(505)).await;
    assert_eq!(after["email_status"], "provider_reported");
    assert!(after["last_verified_at"].is_null());
    sqlx::query("UPDATE contacts SET email_status='invalid' WHERE id=$1")
        .bind(Uuid::from_u128(505))
        .execute(&mut c)
        .await
        .unwrap();
    let result = contact_identity_call(&mut c, company, contact_identity_observation(5), 21)
        .await
        .unwrap();
    assert_eq!(result["requires_review"], true);
    assert_eq!(
        contact_identity_row(&mut c, Uuid::from_u128(505)).await["email_status"],
        "invalid"
    );
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn contact_identity_current_confirmed_official_publication_binds_exact_email_digest_and_host()
{
    let (mut c, company) = contact_identity_fixture().await;
    let mut input = contact_identity_observation(5);
    input["source"] = json!("official_company");
    input["human_confirmed"] = json!(true);
    input["email_publication_url"] = json!("https://contact-fixture.example/team");
    contact_identity_call(&mut c, company, input, 22)
        .await
        .unwrap();
    let row = contact_identity_row(&mut c, Uuid::from_u128(505)).await;
    assert_eq!(row["metadata"]["email_publication_confirmed"], true);
    use sha2::Digest as _;
    assert_eq!(
        row["metadata"]["email_publication_digest"],
        format!(
            "{:x}",
            sha2::Sha256::digest(b"person5@contact-fixture.example")
        )
    );
    let mut input = contact_identity_observation(1);
    input["source"] = json!("official_company");
    input["human_confirmed"] = json!(true);
    input["email_publication_url"] = json!("https://unrelated.example/team");
    contact_identity_call(&mut c, company, input, 23)
        .await
        .unwrap();
    assert!(contact_identity_row(&mut c,Uuid::from_u128(501)).await["metadata"]["email_publication_confirmed"].is_null());
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn contact_identity_update_or_insert_ack_faults_roll_back_every_business_row() {
    let (mut c, company) = contact_identity_fixture().await;
    let before = contact_identity_snapshot(&mut c).await;
    for (table, event, behavior, n) in [
        ("contacts", "UPDATE", "RETURN NULL;", 5),
        (
            "contacts",
            "UPDATE",
            "NEW.email_status:='invalid';RETURN NEW;",
            5,
        ),
        ("contacts", "INSERT", "RETURN NULL;", 77),
        (
            "contacts",
            "INSERT",
            "NEW.full_name:='Altered name';RETURN NEW;",
            77,
        ),
    ] {
        sqlx::raw_sql(sqlx::AssertSqlSafe(format!("CREATE FUNCTION fixture_identity_ack() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN {behavior} END $$;CREATE TRIGGER fixture_identity_ack BEFORE {event} ON {table} FOR EACH ROW EXECUTE FUNCTION fixture_identity_ack()"))).execute(&mut c).await.unwrap();
        assert_eq!(
            contact_identity_call(&mut c, company, contact_identity_observation(n), 24)
                .await
                .unwrap_err(),
            Failure("contact_identity_write_ack_failed")
        );
        assert_eq!(contact_identity_snapshot(&mut c).await, before);
        sqlx::raw_sql(sqlx::AssertSqlSafe(format!(
            "DROP TRIGGER fixture_identity_ack ON {table};DROP FUNCTION fixture_identity_ack()"
        )))
        .execute(&mut c)
        .await
        .unwrap();
    }
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn contact_identity_mapping_evidence_and_receipt_ack_faults_are_atomic() {
    let (mut c, company) = contact_identity_fixture().await;
    let before = contact_identity_snapshot(&mut c).await;
    for (table, behavior) in [
        ("contact_identities", "RETURN NULL;"),
        ("contact_identities", "NEW.namespace:='altered';RETURN NEW;"),
        ("contact_evidence", "RETURN NULL;"),
        ("contact_evidence", "NEW.user_confirmed:=true;RETURN NEW;"),
        (
            "owner_preferences",
            "IF starts_with(NEW.key,'cl_obs:') THEN RETURN NULL;END IF;RETURN NEW;",
        ),
    ] {
        sqlx::raw_sql(sqlx::AssertSqlSafe(format!("CREATE FUNCTION fixture_identity_evidence() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN {behavior} END $$;CREATE TRIGGER fixture_identity_evidence BEFORE INSERT ON {table} FOR EACH ROW EXECUTE FUNCTION fixture_identity_evidence()"))).execute(&mut c).await.unwrap();
        assert_eq!(
            contact_identity_call(&mut c, company, contact_identity_observation(77), 25)
                .await
                .unwrap_err(),
            Failure("contact_identity_write_ack_failed")
        );
        assert_eq!(contact_identity_snapshot(&mut c).await, before);
        sqlx::raw_sql(sqlx::AssertSqlSafe(format!("DROP TRIGGER fixture_identity_evidence ON {table};DROP FUNCTION fixture_identity_evidence()"))).execute(&mut c).await.unwrap();
    }
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn contact_identity_future_observation_and_oversized_inventory_fail_without_partial_findings()
{
    let (mut c, company) = contact_identity_fixture().await;
    let before = contact_identity_snapshot(&mut c).await;
    let mut input = contact_identity_observation(5);
    input["observed_at"] = json!((chrono::Utc::now() + chrono::Duration::days(1)).to_rfc3339());
    assert_eq!(
        contact_identity_call(&mut c, company, input, 26)
            .await
            .unwrap_err(),
        Failure("contact_observation_time_requires_review")
    );
    assert_eq!(contact_identity_snapshot(&mut c).await, before);
    sqlx::query("INSERT INTO contacts(id,company_id,full_name,role_title,email_status,metadata) SELECT lpad(to_hex(1600000+n),32,'0')::uuid,$1,'Fictional inventory contact','Engineer','unknown','{}' FROM generate_series(1,1001) n").bind(company).execute(&mut c).await.unwrap();
    let before = contact_identity_snapshot(&mut c).await;
    assert_eq!(
        contact_identity_call(&mut c, company, contact_identity_observation(5), 27)
            .await
            .unwrap_err(),
        Failure("contact_identity_inventory_requires_review")
    );
    assert_eq!(contact_identity_snapshot(&mut c).await, before);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn contact_identity_concurrent_same_receipt_can_append_only_one_observation() {
    let (mut c, company) = contact_identity_fixture().await;
    let mut other = connection().await;
    let observation = contact_identity_observation(77);
    let (a, b) = tokio::join!(
        contact_identity_call(&mut c, company, observation.clone(), 28),
        contact_identity_call(&mut other, company, observation, 28)
    );
    assert!(a.is_ok() || b.is_ok());
    assert_eq!(
        sqlx::query_scalar::<_, i64>(
            "SELECT count(*) FROM owner_preferences WHERE starts_with(key,'cl_obs:')"
        )
        .fetch_one(&mut c)
        .await
        .unwrap(),
        1
    );
    assert_eq!(
        sqlx::query_scalar::<_, i64>(
            "SELECT count(*) FROM contacts WHERE full_name='Fictional Contact 77'"
        )
        .fetch_one(&mut c)
        .await
        .unwrap(),
        1
    );
}
