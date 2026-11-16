//! Deferred fictional credit accounting; no provider request is issued by these cases.
use automated_apply_agents::contacts::enrichment::budget as contact_budget;
async fn contact_budget_fixture() -> PgConnection {
    let (mut c, _) = enrichment_preview_fixture().await;
    sqlx::raw_sql("DROP TABLE IF EXISTS discovery_budget_reservations;CREATE TABLE discovery_budget_reservations(id varchar(100) PRIMARY KEY,provider varchar(50) NOT NULL,month varchar(7) NOT NULL,reserved numeric(16,6) NOT NULL,provider_run_id varchar(255),reported_actual numeric(16,6),state varchar(50) NOT NULL,created_at timestamptz NOT NULL)").execute(&mut c).await.unwrap();
    c
}
async fn contact_budget_snapshot(c: &mut PgConnection) -> Value {
    sqlx::query_scalar("SELECT jsonb_build_object('budget',(SELECT jsonb_agg(to_jsonb(b) ORDER BY provider,month) FROM discovery_monthly_budgets b),'reservations',(SELECT jsonb_agg(to_jsonb(r) ORDER BY id) FROM discovery_budget_reservations r))").fetch_one(c).await.unwrap()
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn contact_budget_reservation_is_durable_exact_and_actuals_never_refund_full_cap() {
    let mut c = contact_budget_fixture().await;
    sqlx::query("INSERT INTO discovery_monthly_budgets VALUES('apollo',to_char(clock_timestamp(),'YYYY-MM'),2.000001,NULL)").execute(&mut c).await.unwrap();
    let reservation = contact_budget::reserve(&mut c, "apollo", "contact_fixture_exact", 2, 10)
        .await
        .unwrap();
    assert_eq!(reservation.amount(), 2);
    assert_eq!(reservation.provider(), "apollo");
    let mut other = connection().await;
    assert_eq!(
        sqlx::query_scalar::<_, String>(
            "SELECT reserved::text FROM discovery_monthly_budgets WHERE provider='apollo'"
        )
        .fetch_one(&mut other)
        .await
        .unwrap(),
        "4.000001"
    );
    let result = contact_budget::finish(&mut c, &reservation, "completed", Some(0), None)
        .await
        .unwrap();
    assert_eq!(result["accounting"], "full_cap_retained");
    assert_eq!(result["reserved_credits"], 2);
    assert_eq!(
        sqlx::query_scalar::<_, String>(
            "SELECT reserved::text FROM discovery_monthly_budgets WHERE provider='apollo'"
        )
        .fetch_one(&mut c)
        .await
        .unwrap(),
        "4.000001"
    );
    assert_eq!(
        sqlx::query_scalar::<_, String>(
            "SELECT reported_actual::text FROM discovery_budget_reservations WHERE id=$1"
        )
        .bind(reservation.id())
        .fetch_one(&mut c)
        .await
        .unwrap(),
        "0.000000"
    );
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn contact_budget_single_use_reservation_cannot_repeat_after_response_loss_terminal_or_provider_change()
 {
    let mut c = contact_budget_fixture().await;
    let reservation = contact_budget::reserve(&mut c, "apollo", "contact_fixture_spent", 2, 10)
        .await
        .unwrap();
    let before = contact_budget_snapshot(&mut c).await;
    assert_eq!(
        contact_budget::reserve(&mut c, "apollo", reservation.id(), 2, 10)
            .await
            .err()
            .unwrap(),
        Failure("contact_reservation_already_used")
    );
    assert_eq!(
        contact_budget::reserve(&mut c, "signalhire", reservation.id(), 1, 10)
            .await
            .err()
            .unwrap(),
        Failure("contact_reservation_already_used")
    );
    assert_eq!(contact_budget_snapshot(&mut c).await, before);
    contact_budget::finish(&mut c, &reservation, "billing_uncertain", None, None)
        .await
        .unwrap();
    let before = contact_budget_snapshot(&mut c).await;
    let result = contact_budget::finish(&mut c, &reservation, "billing_uncertain", None, None)
        .await
        .unwrap();
    assert_eq!(result["record_basis"], "retained_budget_finding");
    assert_eq!(
        contact_budget::finish(&mut c, &reservation, "completed", Some(0), None)
            .await
            .unwrap_err(),
        Failure("contact_reservation_terminal_conflict")
    );
    assert_eq!(contact_budget_snapshot(&mut c).await, before);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn contact_budget_over_cap_and_cross_month_cooldown_refuse_without_partial_reservations() {
    let mut c = contact_budget_fixture().await;
    let reservation = contact_budget::reserve(&mut c, "apollo", "contact_fixture_cap_one", 4, 5)
        .await
        .unwrap();
    let before = contact_budget_snapshot(&mut c).await;
    assert_eq!(
        contact_budget::reserve(&mut c, "apollo", "contact_fixture_cap_two", 2, 5)
            .await
            .err()
            .unwrap(),
        Failure("contact_provider_budget_exhausted")
    );
    assert_eq!(contact_budget_snapshot(&mut c).await, before);
    sqlx::query("INSERT INTO discovery_monthly_budgets VALUES('apollo','2020-01',0,clock_timestamp()+interval '1 day')").execute(&mut c).await.unwrap();
    let before = contact_budget_snapshot(&mut c).await;
    assert_eq!(
        contact_budget::reserve(&mut c, "apollo", "contact_fixture_cooling", 1, 10)
            .await
            .err()
            .unwrap(),
        Failure("contact_provider_cooling_down")
    );
    assert_eq!(contact_budget_snapshot(&mut c).await, before);
    assert_eq!(reservation.amount(), 4);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn contact_budget_concurrent_requests_cannot_overspend_the_monthly_cap() {
    let mut c = contact_budget_fixture().await;
    let mut other = connection().await;
    let (a, b) = tokio::join!(
        contact_budget::reserve(&mut c, "apollo", "contact_fixture_parallel_one", 4, 4),
        contact_budget::reserve(&mut other, "apollo", "contact_fixture_parallel_two", 4, 4)
    );
    assert_ne!(a.is_ok(), b.is_ok());
    let error = if let Err(e) = a { e } else { b.err().unwrap() };
    assert!(matches!(
        error.0,
        "contact_provider_budget_exhausted" | "contact_database_error" | "execution_database_error"
    ));
    assert_eq!(
        sqlx::query_scalar::<_, String>(
            "SELECT reserved::text FROM discovery_monthly_budgets WHERE provider='apollo'"
        )
        .fetch_one(&mut c)
        .await
        .unwrap(),
        "4.000000"
    );
    assert_eq!(
        sqlx::query_scalar::<_, i64>("SELECT count(*) FROM discovery_budget_reservations")
            .fetch_one(&mut c)
            .await
            .unwrap(),
        1
    );
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn contact_budget_suppressed_or_altered_reservation_insert_ack_rolls_back_monthly_accounting()
{
    let mut c = contact_budget_fixture().await;
    let before = contact_budget_snapshot(&mut c).await;
    for behavior in ["RETURN NULL;", "NEW.reserved:=NEW.reserved+1;RETURN NEW;"] {
        sqlx::raw_sql(sqlx::AssertSqlSafe(format!("CREATE FUNCTION fixture_contact_reservation() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN {behavior} END $$;CREATE TRIGGER fixture_contact_reservation BEFORE INSERT ON discovery_budget_reservations FOR EACH ROW EXECUTE FUNCTION fixture_contact_reservation()"))).execute(&mut c).await.unwrap();
        assert_eq!(
            contact_budget::reserve(&mut c, "apollo", "contact_fixture_ack", 1, 10)
                .await
                .err()
                .unwrap(),
            Failure("contact_budget_write_ack_failed")
        );
        assert_eq!(contact_budget_snapshot(&mut c).await, before);
        sqlx::raw_sql("DROP TRIGGER fixture_contact_reservation ON discovery_budget_reservations;DROP FUNCTION fixture_contact_reservation()").execute(&mut c).await.unwrap();
    }
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn contact_budget_monthly_update_ack_covers_amount_provider_month_and_cooldown() {
    let mut c = contact_budget_fixture().await;
    sqlx::query("INSERT INTO discovery_monthly_budgets VALUES('apollo',to_char(clock_timestamp(),'YYYY-MM'),1,clock_timestamp()-interval '1 day')").execute(&mut c).await.unwrap();
    let before = contact_budget_snapshot(&mut c).await;
    for behavior in [
        "RETURN NULL;",
        "NEW.reserved:=9;RETURN NEW;",
        "NEW.provider:='signalhire';RETURN NEW;",
        "NEW.month:='2000-01';RETURN NEW;",
        "NEW.cooldown_until:=clock_timestamp()+interval '1 day';RETURN NEW;",
    ] {
        sqlx::raw_sql(sqlx::AssertSqlSafe(format!("CREATE FUNCTION fixture_contact_month() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN {behavior} END $$;CREATE TRIGGER fixture_contact_month BEFORE UPDATE ON discovery_monthly_budgets FOR EACH ROW EXECUTE FUNCTION fixture_contact_month()"))).execute(&mut c).await.unwrap();
        assert_eq!(
            contact_budget::reserve(&mut c, "apollo", "contact_fixture_month_ack", 1, 10)
                .await
                .err()
                .unwrap(),
            Failure("contact_budget_write_ack_failed")
        );
        assert_eq!(contact_budget_snapshot(&mut c).await, before);
        sqlx::raw_sql("DROP TRIGGER fixture_contact_month ON discovery_monthly_budgets;DROP FUNCTION fixture_contact_month()").execute(&mut c).await.unwrap();
    }
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn contact_budget_finish_ack_failure_preserves_reserved_state_and_all_credit_reservations() {
    let mut c = contact_budget_fixture().await;
    let reservation =
        contact_budget::reserve(&mut c, "signalhire", "contact_fixture_finish_ack", 2, 5)
            .await
            .unwrap();
    let before = contact_budget_snapshot(&mut c).await;
    for behavior in [
        "RETURN NULL;",
        "NEW.reserved:=9;RETURN NEW;",
        "NEW.reported_actual:=8;RETURN NEW;",
    ] {
        sqlx::raw_sql(sqlx::AssertSqlSafe(format!("CREATE FUNCTION fixture_contact_finish() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN {behavior} END $$;CREATE TRIGGER fixture_contact_finish BEFORE UPDATE ON discovery_budget_reservations FOR EACH ROW EXECUTE FUNCTION fixture_contact_finish()"))).execute(&mut c).await.unwrap();
        assert_eq!(
            contact_budget::finish(
                &mut c,
                &reservation,
                "completed",
                Some(1),
                Some("fictional-provider-reference")
            )
            .await
            .unwrap_err(),
            Failure("contact_budget_write_ack_failed")
        );
        assert_eq!(contact_budget_snapshot(&mut c).await, before);
        sqlx::raw_sql("DROP TRIGGER fixture_contact_finish ON discovery_budget_reservations;DROP FUNCTION fixture_contact_finish()").execute(&mut c).await.unwrap();
    }
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn contact_budget_cooldown_preserves_longer_prior_deadlines_and_creates_current_month_without_charges()
 {
    let mut c = contact_budget_fixture().await;
    sqlx::query("INSERT INTO discovery_monthly_budgets VALUES('apollo','2020-01',3,clock_timestamp()+interval '2 days')").execute(&mut c).await.unwrap();
    let old: chrono::DateTime<chrono::Utc> = sqlx::query_scalar(
        "SELECT cooldown_until FROM discovery_monthly_budgets WHERE provider='apollo'",
    )
    .fetch_one(&mut c)
    .await
    .unwrap();
    let value = contact_budget::cooldown(&mut c, "apollo", 60)
        .await
        .unwrap();
    assert_eq!(value["months_updated"], 2);
    assert_eq!(value["credits_refunded"], 0);
    assert_eq!(
        sqlx::query_scalar::<_, chrono::DateTime<chrono::Utc>>(
            "SELECT cooldown_until FROM discovery_monthly_budgets WHERE month='2020-01'"
        )
        .fetch_one(&mut c)
        .await
        .unwrap(),
        old
    );
    assert_eq!(sqlx::query_scalar::<_,String>("SELECT reserved::text FROM discovery_monthly_budgets WHERE month=to_char(clock_timestamp(),'YYYY-MM')").fetch_one(&mut c).await.unwrap(),"0.000000");
    assert_eq!(
        contact_budget::reserve(&mut c, "apollo", "contact_fixture_after_cooldown", 1, 10)
            .await
            .err()
            .unwrap(),
        Failure("contact_provider_cooling_down")
    );
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn contact_budget_cooldown_ack_refuses_shorter_prior_deadline_or_changed_reserved_amount() {
    let mut c = contact_budget_fixture().await;
    sqlx::query("INSERT INTO discovery_monthly_budgets VALUES('apollo',to_char(clock_timestamp(),'YYYY-MM'),3,clock_timestamp()+interval '2 days')").execute(&mut c).await.unwrap();
    let before = contact_budget_snapshot(&mut c).await;
    for behavior in [
        "NEW.cooldown_until:=clock_timestamp()+interval '1 day';RETURN NEW;",
        "NEW.reserved:=0;RETURN NEW;",
    ] {
        sqlx::raw_sql(sqlx::AssertSqlSafe(format!("CREATE FUNCTION fixture_contact_cooldown() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN {behavior} END $$;CREATE TRIGGER fixture_contact_cooldown BEFORE UPDATE ON discovery_monthly_budgets FOR EACH ROW EXECUTE FUNCTION fixture_contact_cooldown()"))).execute(&mut c).await.unwrap();
        assert_eq!(
            contact_budget::cooldown(&mut c, "apollo", 60)
                .await
                .unwrap_err(),
            Failure("contact_budget_write_ack_failed")
        );
        assert_eq!(contact_budget_snapshot(&mut c).await, before);
        sqlx::raw_sql("DROP TRIGGER fixture_contact_cooldown ON discovery_monthly_budgets;DROP FUNCTION fixture_contact_cooldown()").execute(&mut c).await.unwrap();
    }
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn contact_budget_invalid_inputs_and_owner_ack_failure_have_no_partial_accounting() {
    let mut c = contact_budget_fixture().await;
    let before = contact_budget_snapshot(&mut c).await;
    for (provider, id, amount, cap) in [
        ("unknown", "contact_fixture_invalid", 1, 5),
        ("apollo", "wrong_namespace", 1, 5),
        ("apollo", "contact_fixture_invalid", 0, 5),
        ("apollo", "contact_fixture_invalid", 1, 0),
        ("apollo", "contact_fixture_invalid", 101, 200),
    ] {
        assert_eq!(
            contact_budget::reserve(&mut c, provider, id, amount, cap)
                .await
                .err()
                .unwrap(),
            Failure("invalid_contact_budget")
        );
    }
    sqlx::raw_sql("CREATE FUNCTION fixture_contact_credit_owner() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.key='agent_conversation:primary' THEN RETURN NULL; END IF;RETURN NEW;END $$;CREATE TRIGGER fixture_contact_credit_owner BEFORE UPDATE ON owner_preferences FOR EACH ROW EXECUTE FUNCTION fixture_contact_credit_owner()").execute(&mut c).await.unwrap();
    assert_eq!(
        contact_budget::reserve(&mut c, "apollo", "contact_fixture_owner_ack", 1, 5)
            .await
            .err()
            .unwrap(),
        Failure("execution_write_ack_failed")
    );
    assert_eq!(contact_budget_snapshot(&mut c).await, before);
    sqlx::raw_sql("DROP TRIGGER fixture_contact_credit_owner ON owner_preferences;DROP FUNCTION fixture_contact_credit_owner()").execute(&mut c).await.unwrap();
}
