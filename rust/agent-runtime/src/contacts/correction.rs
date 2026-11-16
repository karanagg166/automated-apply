//! Owner corrections are local atomic changes. No provider action or sending grant.
use super::*;
const VERSION: &str = "c.xmin::text||':'||extract(epoch from c.updated_at)::text";
fn conflict() -> Failure {
    Failure("contact_review_version_conflict")
}
fn ack() -> Failure {
    Failure("contact_write_ack_failed")
}

pub async fn correct(
    c: &mut PgConnection,
    id: Uuid,
    expected: Option<&str>,
    body: &[u8],
    settings: &Settings,
) -> Result<Value> {
    let expected = expected
        .filter(|s| !s.is_empty() && s.len() <= 128)
        .ok_or(Failure("contact_review_precondition_required"))?;
    let input = contract::normalize(
        serde_json::from_slice(body).map_err(|_| Failure("invalid_contact_correction"))?,
    )?;
    let mut values = input.as_object().unwrap().clone();
    let verification = values.remove("verification_evidence_id");
    for key in [
        "full_name",
        "role_title",
        "company_id",
        "email_status",
        "do_not_contact",
    ] {
        if values.get(key) == Some(&Value::Null) {
            return Err(Failure("contact_required_field_null"));
        }
    }
    let mut tx = c.begin().await.map_err(db)?;
    sqlx::query("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
        .execute(&mut *tx)
        .await
        .map_err(db)?;
    crate::execution::lock_owner_in(&mut tx).await?;
    let old_company: Uuid = sqlx::query_scalar("SELECT company_id FROM contacts WHERE id=$1")
        .bind(id)
        .fetch_optional(&mut *tx)
        .await
        .map_err(db)?
        .ok_or(Failure("contact_not_found"))?;
    let next_company = values
        .get("company_id")
        .and_then(Value::as_str)
        .map(str::parse::<Uuid>)
        .transpose()
        .map_err(|_| Failure("invalid_contact_correction"))?
        .unwrap_or(old_company);
    let mut companies = vec![old_company, next_company];
    companies.sort();
    companies.dedup();
    let locked: Vec<Uuid> =
        sqlx::query_scalar("SELECT id FROM companies WHERE id=ANY($1) ORDER BY id FOR UPDATE")
            .bind(&companies)
            .fetch_all(&mut *tx)
            .await
            .map_err(db)?;
    if locked != companies {
        return Err(Failure("contact_company_not_found"));
    }
    let (before, version): (Option<Value>, String) = sqlx::query_as(&format!(
        "SELECT CASE WHEN octet_length(c.metadata::text)<=262144 AND coalesce(octet_length(c.human_review_notes),0)<=10000 AND coalesce(octet_length(c.suppression_reason),0)<=10000 THEN to_jsonb(c) ELSE NULL END,{VERSION} FROM contacts c WHERE c.id=$1 FOR UPDATE"
    ))
    .bind(id)
    .fetch_optional(&mut *tx)
    .await
    .map_err(db)?
    .ok_or(Failure("contact_not_found"))?;
    let before = before.ok_or_else(invalid)?;
    if version != expected || before["company_id"] != old_company.to_string() {
        return Err(conflict());
    }
    if before.to_string().len() > 300000 || !before["metadata"].is_object() {
        return Err(invalid());
    }
    let at: Value = sqlx::query_scalar("SELECT to_jsonb(clock_timestamp())")
        .fetch_one(&mut *tx)
        .await
        .map_err(db)?;
    let now: DateTime<Utc> = serde_json::from_value(at.clone()).map_err(|_| invalid())?;
    let mut after = before.clone();
    if values.get("email_status") == Some(&json!("verified")) {
        let evidence_id = verification
            .as_ref()
            .and_then(Value::as_str)
            .and_then(|s| s.parse::<Uuid>().ok())
            .ok_or(Failure("contact_current_mailbox_evidence_required"))?;
        let supported:Option<bool>=sqlx::query_scalar("SELECT true FROM contact_evidence WHERE id=$1 AND contact_id=$2 AND company_id=$3 AND evidence_type='mailbox_verification' AND user_confirmed=true AND expires_at>$4 AND collected_at<=$4 AND provenance::jsonb->>'email'=$5 AND provenance::jsonb->>'result'='deliverable' AND provenance::jsonb->>'method' IN ('authorized_mailbox_verifier','owner_confirmation') FOR SHARE").bind(evidence_id).bind(id).bind(old_company).bind(now).bind(before["email"].as_str()).fetch_optional(&mut *tx).await.map_err(db)?;
        if supported != Some(true) || before["email"].as_str().is_none_or(str::is_empty) {
            return Err(Failure("contact_current_mailbox_evidence_required"));
        }
        after["last_verified_at"] = at.clone();
    } else if values.get("email_status") == Some(&json!("provider_reported"))
        && before["email"].as_str().is_none_or(str::is_empty)
    {
        return Err(Failure("contact_mailbox_missing"));
    }
    if next_company != old_company {
        if before["email"].as_str().is_some_and(|s| !s.is_empty()) {
            return Err(Failure("contact_affiliation_mailbox_review_required"));
        }
        let identities:Vec<Uuid>=sqlx::query_scalar("SELECT id FROM contact_identities WHERE contact_id=$1 ORDER BY id LIMIT 10001 FOR UPDATE").bind(id).fetch_all(&mut *tx).await.map_err(db)?;
        if identities.len() > 10000 {
            return Err(Failure("contact_identity_inventory_limit"));
        }
        let mut removed: Vec<Uuid> = sqlx::query_scalar(
            "DELETE FROM contact_identities WHERE contact_id=$1 AND id=ANY($2) RETURNING id",
        )
        .bind(id)
        .bind(&identities)
        .fetch_all(&mut *tx)
        .await
        .map_err(db)?;
        removed.sort();
        if removed != identities {
            return Err(ack());
        }
    }
    let mut previous = serde_json::Map::new();
    for (key, value) in &values {
        let old = &before[key];
        // Historical provenance records the previous value; it never establishes a new fact.
        previous.insert(
            key.clone(),
            if old.is_null() {
                Value::Null
            } else if let Some(s) = old.as_str() {
                json!(s)
            } else if let Some(b) = old.as_bool() {
                json!(if b { "True" } else { "False" })
            } else {
                json!(old.to_string())
            },
        );
        after[key] = value.clone();
    }
    after["human_corrected"] = json!(true);
    after["last_reviewed_at"] = at.clone();
    after["updated_at"] = at.clone();
    let written:Option<Value>=sqlx::query_scalar(&format!("UPDATE contacts c SET full_name=$2::jsonb->>'full_name',role_title=$2::jsonb->>'role_title',company_id=($2::jsonb->>'company_id')::uuid,email_status=$2::jsonb->>'email_status',do_not_contact=($2::jsonb->>'do_not_contact')::boolean,suppression_reason=$2::jsonb->>'suppression_reason',human_review_notes=$2::jsonb->>'human_review_notes',last_verified_at=($2::jsonb->>'last_verified_at')::timestamptz,human_corrected=true,last_reviewed_at=$3,updated_at=$3 WHERE c.id=$1 AND {VERSION}=$4 RETURNING to_jsonb(c)")).bind(id).bind(&after).bind(now).bind(expected).fetch_optional(&mut *tx).await.map_err(db)?;
    if written.as_ref() != Some(&after) {
        return Err(ack());
    }
    let evidence_id = Uuid::new_v4();
    let expires = now + chrono::Duration::days(settings.retention_days);
    let provenance = json!({"previous_values":previous,"changed_fields":values.keys().collect::<Vec<_>>(),"reviewed_version":expected,"verification_evidence_id":verification});
    let retained:Option<Value>=sqlx::query_scalar("INSERT INTO contact_evidence(id,contact_id,company_id,source,evidence_type,evidence_url,observed_role,observed_company,provider_verification_claim,strength,collected_at,expires_at,provenance,user_confirmed) VALUES($1,$2,$3,'manual','human_correction',NULL,NULL,NULL,NULL,'strong',$4,$5,$6,true) RETURNING jsonb_build_object('id',id,'contact_id',contact_id,'company_id',company_id,'source',source,'evidence_type',evidence_type,'evidence_url',evidence_url,'observed_role',observed_role,'observed_company',observed_company,'provider_verification_claim',provider_verification_claim,'strength',strength,'collected_at',collected_at=$4,'expires_at',expires_at=$5,'provenance',provenance,'user_confirmed',user_confirmed)").bind(evidence_id).bind(id).bind(next_company).bind(now).bind(expires).bind(&provenance).fetch_optional(&mut *tx).await.map_err(db)?;
    if retained
        != Some(
            json!({"id":evidence_id,"contact_id":id,"company_id":next_company,"source":"manual","evidence_type":"human_correction","evidence_url":null,"observed_role":null,"observed_company":null,"provider_verification_claim":null,"strength":"strong","collected_at":true,"expires_at":true,"provenance":provenance,"user_confirmed":true}),
        )
    {
        return Err(ack());
    }
    let result = detail(&mut tx, id, settings, now).await?;
    tx.commit()
        .await
        .map_err(|_| Failure("contact_commit_outcome_unknown"))?;
    Ok(result)
}
