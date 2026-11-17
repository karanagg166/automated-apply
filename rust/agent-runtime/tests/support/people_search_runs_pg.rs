// Deferred original paid search admissions. No transport is executed by these fixtures.
use automated_apply_agents::people_research::{
    runs as people_search_runs, settings::Settings as PeopleSearchSettings,
};
async fn people_search_fixture() -> PgConnection {
    let (mut c, _) = people_ingest_fixture().await;
    sqlx::raw_sql("DROP TABLE IF EXISTS discovery_budget_reservations,discovery_monthly_budgets")
        .execute(&mut c)
        .await
        .unwrap();
    let source = include_str!("../../../../supabase/fresh_public/001_phase1_public.sql");
    let table = source
        .split("CREATE TABLE IF NOT EXISTS public.discovery_monthly_budgets (")
        .nth(1)
        .unwrap()
        .split("ALTER TABLE public.discovery_runs ENABLE ROW LEVEL SECURITY;")
        .next()
        .unwrap();
    sqlx::raw_sql(sqlx::AssertSqlSafe(format!(
        "CREATE TABLE IF NOT EXISTS public.discovery_monthly_budgets ({table}"
    )))
    .execute(&mut c)
    .await
    .unwrap();
    c
}
fn people_search_values() -> BTreeMap<String, String> {
    BTreeMap::from([
        ("PEOPLE_SEARCH_ENABLED".into(), "true".into()),
        (
            "SERPER_API_KEY".into(),
            "PRIVATE_FICTIONAL_SEARCH_KEY_CANARY".into(),
        ),
        ("PUBLIC_SEARCH_RIGHTS_REVIEWED".into(), "true".into()),
        (
            "PUBLIC_SEARCH_PERMISSION_EVIDENCE_URL".into(),
            "https://search-fixture.example/permission".into(),
        ),
        (
            "PUBLIC_SEARCH_ALLOWED_DOMAINS".into(),
            "{\"contact-fixture.example\":\"https://contact-fixture.example/permission\"}".into(),
        ),
    ])
}
fn people_search_input() -> Value {
    json!({"company_name":"Fictional Contact Employer","company_domain":"contact-fixture.example","research_mode":"official_company","allow_paid":true})
}
async fn people_search_admit(
    c: &mut PgConnection,
    n: u128,
) -> Result<people_search_runs::Admission> {
    people_search_runs::admit(
        c,
        people_search_input(),
        Uuid::from_u128(n),
        &PeopleSearchSettings::from_values(&people_search_values()).unwrap(),
    )
    .await
}
async fn people_search_snapshot(c: &mut PgConnection) -> Value {
    sqlx::query_scalar("SELECT jsonb_build_object('search',(SELECT jsonb_object_agg(key,value) FROM owner_preferences WHERE starts_with(key,'people_search:')),'budgets',(SELECT jsonb_agg(to_jsonb(b) ORDER BY provider,month) FROM discovery_monthly_budgets b),'reservations',(SELECT jsonb_agg(to_jsonb(r) ORDER BY id) FROM discovery_budget_reservations r))").fetch_one(c).await.unwrap()
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn people_search_original_admission_commits_one_local_request_and_replay_does_not_reconstruct_authority()
 {
    let mut c = people_search_fixture().await;
    let first = people_search_admit(&mut c, 20001).await.unwrap();
    let people_search_runs::Admission::Original(original) = first else {
        panic!("one original claim required")
    };
    assert_eq!(original.id(), Uuid::from_u128(20001));
    drop(original);
    let before = people_search_snapshot(&mut c).await;
    let value = people_search_runs::retained(&mut c, Uuid::from_u128(20001))
        .await
        .unwrap();
    assert_eq!(value["provider_post_admissions"], 1);
    assert_eq!(value["reserved_local_requests"], 1);
    assert_eq!(value["budget_unit"], "search_request");
    assert_eq!(value["provider_charge_verified"], false);
    assert_eq!(value["replay_authorized"], false);
    assert_eq!(value["people"], json!([]));
    assert!(
        !value
            .to_string()
            .contains("PRIVATE_FICTIONAL_SEARCH_KEY_CANARY")
    );
    assert!(matches!(
        people_search_admit(&mut c, 20001).await.unwrap(),
        people_search_runs::Admission::Retained(_)
    ));
    assert_eq!(people_search_snapshot(&mut c).await, before);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn people_search_changed_input_and_manual_paid_mode_changes_cannot_reuse_the_original_uuid() {
    let mut c = people_search_fixture().await;
    people_search_admit(&mut c, 20002).await.unwrap();
    let before = people_search_snapshot(&mut c).await;
    let mut changed = people_search_input();
    changed["roles"] = json!(["ceo"]);
    assert_eq!(
        people_search_runs::admit(
            &mut c,
            changed,
            Uuid::from_u128(20002),
            &PeopleSearchSettings::from_values(&people_search_values()).unwrap()
        )
        .await
        .err()
        .unwrap(),
        Failure("public_research_request_conflict")
    );
    assert_eq!(
        people_import(&mut c, people_manual(), 20002)
            .await
            .unwrap_err(),
        Failure("public_research_request_conflict")
    );
    assert_eq!(people_search_snapshot(&mut c).await, before);
    people_import(&mut c, people_manual(), 20003).await.unwrap();
    let before = people_search_snapshot(&mut c).await;
    assert_eq!(
        people_search_admit(&mut c, 20003).await.err().unwrap(),
        Failure("public_research_request_conflict")
    );
    assert_eq!(people_search_snapshot(&mut c).await, before);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn people_search_expired_original_intent_is_unknown_without_get_writes_or_a_new_reservation()
{
    let mut c = people_search_fixture().await;
    people_search_admit(&mut c, 20004).await.unwrap();
    sqlx::query("UPDATE owner_preferences SET value=jsonb_set(jsonb_set(value,'{started_at}',to_jsonb(clock_timestamp()-interval '31 seconds')),'{expires_at}',to_jsonb(clock_timestamp()-interval '2 seconds')) WHERE key=$1").bind(format!("people_search:{}",Uuid::from_u128(20004).simple())).execute(&mut c).await.unwrap();
    let before = people_search_snapshot(&mut c).await;
    let result = people_search_runs::retained(&mut c, Uuid::from_u128(20004))
        .await
        .unwrap();
    assert_eq!(result["status"], "outcome_unknown");
    assert_eq!(result["provider_response_retained"], false);
    assert_eq!(people_search_snapshot(&mut c).await, before);
    assert!(matches!(
        people_search_admit(&mut c, 20004).await.unwrap(),
        people_search_runs::Admission::Retained(_)
    ));
    assert_eq!(people_search_snapshot(&mut c).await, before);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn people_search_saved_rights_credentials_and_paid_approval_fail_before_any_admission_or_reservation()
 {
    let mut c = people_search_fixture().await;
    let before = people_search_snapshot(&mut c).await;
    for missing in [
        "PEOPLE_SEARCH_ENABLED",
        "SERPER_API_KEY",
        "PUBLIC_SEARCH_RIGHTS_REVIEWED",
        "PUBLIC_SEARCH_PERMISSION_EVIDENCE_URL",
        "PUBLIC_SEARCH_ALLOWED_DOMAINS",
    ] {
        let mut values = people_search_values();
        values.remove(missing);
        let settings = PeopleSearchSettings::from_values(&values).unwrap();
        assert!(
            people_search_runs::admit(
                &mut c,
                people_search_input(),
                Uuid::from_u128(20005),
                &settings
            )
            .await
            .is_err()
        );
        assert_eq!(people_search_snapshot(&mut c).await, before);
    }
    let mut input = people_search_input();
    input["allow_paid"] = json!(false);
    assert!(
        people_search_runs::admit(
            &mut c,
            input,
            Uuid::from_u128(20005),
            &PeopleSearchSettings::from_values(&people_search_values()).unwrap()
        )
        .await
        .is_err()
    );
    assert_eq!(people_search_snapshot(&mut c).await, before);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn people_search_local_cap_and_cross_month_cooldown_are_enforced_without_refunding_previous_requests()
 {
    let mut c = people_search_fixture().await;
    let mut values = people_search_values();
    values.insert("SERPER_MONTHLY_LIMIT".into(), "1".into());
    let settings = PeopleSearchSettings::from_values(&values).unwrap();
    people_search_runs::admit(
        &mut c,
        people_search_input(),
        Uuid::from_u128(20006),
        &settings,
    )
    .await
    .unwrap();
    let before = people_search_snapshot(&mut c).await;
    assert_eq!(
        people_search_runs::admit(
            &mut c,
            people_search_input(),
            Uuid::from_u128(20007),
            &settings
        )
        .await
        .err()
        .unwrap(),
        Failure("contact_provider_budget_exhausted")
    );
    assert_eq!(people_search_snapshot(&mut c).await, before);
    sqlx::query("INSERT INTO discovery_monthly_budgets(provider,month,reserved,cooldown_until) VALUES('serper','2020-01',0,clock_timestamp()+interval '1 hour')").execute(&mut c).await.unwrap();
    let before = people_search_snapshot(&mut c).await;
    assert_eq!(
        people_search_admit(&mut c, 20008).await.err().unwrap(),
        Failure("contact_provider_cooling_down")
    );
    assert_eq!(people_search_snapshot(&mut c).await, before);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn people_search_journal_and_budget_post_trigger_corruption_roll_back_the_original_admission()
{
    let mut c = people_search_fixture().await;
    let before = people_search_snapshot(&mut c).await;
    for (table, body, error) in [
        (
            "owner_preferences",
            "IF pg_trigger_depth()=1 AND starts_with(NEW.key,'people_search:') THEN UPDATE owner_preferences SET value=value||'{\"corrupted\":true}'::jsonb WHERE key=NEW.key;END IF;RETURN NEW;",
            "public_research_write_ack_failed",
        ),
        (
            "discovery_budget_reservations",
            "IF pg_trigger_depth()=1 THEN UPDATE discovery_budget_reservations SET reserved=0 WHERE id=NEW.id;END IF;RETURN NEW;",
            "contact_budget_write_ack_failed",
        ),
        (
            "discovery_monthly_budgets",
            "IF pg_trigger_depth()=1 THEN UPDATE discovery_monthly_budgets SET reserved=0 WHERE provider=NEW.provider AND month=NEW.month;END IF;RETURN NEW;",
            "contact_budget_write_ack_failed",
        ),
        (
            "owner_preferences",
            "IF pg_trigger_depth()=1 AND starts_with(NEW.key,'people_search:') THEN UPDATE discovery_budget_reservations SET state='completed';END IF;RETURN NEW;",
            "contact_budget_write_ack_failed",
        ),
    ] {
        sqlx::raw_sql(sqlx::AssertSqlSafe(format!("CREATE FUNCTION fixture_people_budget_corrupt() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN {body} END $$;CREATE TRIGGER fixture_people_budget_corrupt AFTER INSERT ON {table} FOR EACH ROW EXECUTE FUNCTION fixture_people_budget_corrupt()"))).execute(&mut c).await.unwrap();
        assert_eq!(
            people_search_admit(&mut c, 20009).await.err().unwrap(),
            Failure(error)
        );
        assert_eq!(people_search_snapshot(&mut c).await, before);
        sqlx::raw_sql(sqlx::AssertSqlSafe(format!("DROP TRIGGER fixture_people_budget_corrupt ON {table};DROP FUNCTION fixture_people_budget_corrupt()"))).execute(&mut c).await.unwrap();
    }
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn people_search_ambiguous_company_domain_is_refused_before_charge_admission() {
    let mut c = people_search_fixture().await;
    sqlx::query("INSERT INTO companies(id,name,domain,is_catch_all,metadata) VALUES($1,'Fictional Duplicate Employer','contact-fixture.example',false,'{}')").bind(Uuid::from_u128(2001000)).execute(&mut c).await.unwrap();
    let before = people_search_snapshot(&mut c).await;
    assert_eq!(
        people_search_admit(&mut c, 20010).await.err().unwrap(),
        Failure("public_research_company_identity_ambiguous")
    );
    assert_eq!(people_search_snapshot(&mut c).await, before);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn people_search_original_claim_holds_no_transaction_or_owner_fence_after_admission() {
    let mut c = people_search_fixture().await;
    let original = people_search_admit(&mut c, 20011).await.unwrap();
    let mut other = connection().await;
    let mut tx = other.begin().await.unwrap();
    tokio::time::timeout(
        Duration::from_secs(1),
        sqlx::query(
            "SELECT key FROM owner_preferences WHERE key='agent_conversation:primary' FOR UPDATE",
        )
        .fetch_one(&mut *tx),
    )
    .await
    .unwrap()
    .unwrap();
    tx.rollback().await.unwrap();
    drop(original);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn people_search_budget_namespace_and_retained_lookup_do_not_cross_provider_or_request_identity()
 {
    let mut c = people_search_fixture().await;
    for (provider, id) in [
        ("apollo", "people_wrong_provider"),
        ("serper", "contact_wrong_namespace"),
    ] {
        assert_eq!(
            contact_budget::reserve(&mut c, provider, id, 1, 10)
                .await
                .err()
                .unwrap(),
            Failure("invalid_contact_budget")
        );
    }
    assert_eq!(
        people_search_runs::retained(&mut c, Uuid::nil())
            .await
            .unwrap_err(),
        Failure("public_research_request_not_found")
    );
    let before = people_search_snapshot(&mut c).await;
    sqlx::query("INSERT INTO owner_preferences(key,value) VALUES($1,'{\"schema\":1,\"input_hash\":\"untrusted\",\"private\":\"PRIVATE_JOURNAL_CANARY\"}')").bind(format!("people_search:{}",Uuid::from_u128(20012).simple())).execute(&mut c).await.unwrap();
    assert_eq!(
        people_search_runs::retained(&mut c, Uuid::from_u128(20012))
            .await
            .unwrap_err(),
        Failure("invalid_public_research_record")
    );
    assert_ne!(people_search_snapshot(&mut c).await, before);
}
