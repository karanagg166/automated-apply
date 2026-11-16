//! Saved local evidence ingestion only; submitted URLs are never fetched.
use super::*;
use sha2::{Digest, Sha256};
fn digest(value: &Value) -> String {
    format!("{:x}", Sha256::digest(value.to_string().as_bytes()))
}
async fn begin(c: &mut PgConnection) -> Result<Transaction<'_, Postgres>> {
    let mut tx = c.begin().await.map_err(db)?;
    sqlx::query("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
        .execute(&mut *tx)
        .await
        .map_err(db)?;
    crate::execution::lock_owner_in(&mut tx).await?;
    Ok(tx)
}
async fn commit(tx: Transaction<'_, Postgres>) -> Result<()> {
    tx.commit()
        .await
        .map_err(|_| Failure("contact_local_commit_outcome_unknown"))
}
pub struct Local {
    pub selected: Vec<Uuid>,
    pub errors: Vec<&'static str>,
}
pub async fn lookup_needed(
    c: &mut PgConnection,
    run: &runs::Run,
    id: Uuid,
    settings: &Settings,
    contacts_settings: &super::super::Settings,
) -> Result<bool> {
    let mut tx = begin(c).await?;
    runs::guard_in(&mut tx, run, settings).await?;
    let now: DateTime<Utc> = sqlx::query_scalar("SELECT clock_timestamp()")
        .fetch_one(&mut *tx)
        .await
        .map_err(db)?;
    let contact: Value = sqlx::query_scalar(&format!(
        "SELECT {CONTACT} FROM contacts c WHERE c.id=$1 AND c.company_id=$3 FOR UPDATE"
    ))
    .bind(id)
    .bind(json!({}))
    .bind(run.company())
    .fetch_optional(&mut *tx)
    .await
    .map_err(db)?
    .ok_or(Failure("contact_not_found"))?;
    let needed = policy::role_matches(
        contact["role_title"].as_str(),
        run.input()["target_roles"].as_array().ok_or_else(invalid)?,
    ) && policy::needs_lookup(&contact, contacts_settings.cache_days, now);
    commit(tx).await?;
    Ok(needed)
}
pub async fn collect(
    c: &mut PgConnection,
    run: &runs::Run,
    settings: &Settings,
    contacts_settings: &super::super::Settings,
) -> Result<Local> {
    let mut tx = begin(c).await?;
    let company = runs::guard_in(&mut tx, run, settings).await?;
    let now: DateTime<Utc> = sqlx::query_scalar("SELECT clock_timestamp()")
        .fetch_one(&mut *tx)
        .await
        .map_err(db)?;
    let preview = super::preview(
        &mut tx,
        run.company(),
        run.input(),
        settings,
        contacts_settings,
        now,
    )
    .await?;
    if preview["contact_inventory_truncated"] == true
        || preview["people_inventory_truncated"] == true
    {
        return Err(Failure("contact_local_inventory_requires_review"));
    }
    let maximum = run.input()["max_people"]
        .as_i64()
        .ok_or_else(invalid)?
        .min(settings.max_people) as usize;
    let mut selected = preview["cached_contacts"]
        .as_array()
        .ok_or_else(invalid)?
        .iter()
        .take(maximum)
        .map(|c| {
            c["id"]
                .as_str()
                .and_then(|s| s.parse::<Uuid>().ok())
                .ok_or_else(invalid)
        })
        .collect::<Result<Vec<_>>>()?;
    let people:Vec<Option<Value>>=sqlx::query_scalar("SELECT CASE WHEN octet_length(to_jsonb(p)::text)<=262144 THEN jsonb_build_object('id',id,'company_id',company_id,'name',name,'role',role,'linkedin_url',linkedin_url,'evidence_url',evidence_url,'source',source,'observed_at',observed_at,'verification_status',verification_status) ELSE NULL END FROM discovered_company_people p WHERE company_id=$1 ORDER BY observed_at DESC,id LIMIT 101").bind(run.company()).fetch_all(&mut *tx).await.map_err(db)?;
    if people.len() > 100 {
        return Err(Failure("contact_local_inventory_requires_review"));
    }
    let people = people
        .into_iter()
        .map(|v| v.ok_or_else(invalid))
        .collect::<Result<Vec<_>>>()?;
    commit(tx).await?;
    let mut errors = Vec::new();
    let roles = run.input()["target_roles"].as_array().ok_or_else(invalid)?;
    for source in people
        .iter()
        .filter(|p| policy::role_matches(p["role"].as_str(), roles))
        .take(maximum)
    {
        if source["name"].as_str().is_none_or(str::is_empty)
            || source["verification_status"] == "requires_review"
        {
            continue;
        }
        let observation = person::normalize(
            person::Kind::Observation,
            json!({"full_name":source["name"],"role_title":source["role"],"company_domain":company["domain"],"linkedin_url":source["linkedin_url"],"source":source["source"],"evidence_url":source["evidence_url"],"observed_at":source["observed_at"],"discovered_person_id":source["id"],"evidence_strength":"moderate"}),
        );
        let observation = match observation {
            Ok(v) => v,
            Err(_) => {
                errors.push("contact_discovered_evidence_requires_review");
                continue;
            }
        };
        let mut tx = begin(c).await?;
        runs::guard_in(&mut tx, run, settings).await?;
        let current:Option<Value>=sqlx::query_scalar("SELECT jsonb_build_object('id',id,'company_id',company_id,'name',name,'role',role,'linkedin_url',linkedin_url,'evidence_url',evidence_url,'source',source,'observed_at',observed_at,'verification_status',verification_status) FROM discovered_company_people WHERE id=$1 FOR SHARE").bind(source["id"].as_str().and_then(|s|s.parse::<Uuid>().ok()).ok_or_else(invalid)?).fetch_optional(&mut *tx).await.map_err(db)?;
        if current.as_ref() != Some(source) {
            return Err(Failure("contact_local_evidence_context_changed"));
        }
        if selected.len() >= maximum {
            let existing:bool=sqlx::query_scalar("SELECT EXISTS(SELECT 1 FROM contacts WHERE id=ANY($1) AND linkedin_url IS NOT NULL AND regexp_replace(linkedin_url,'/+$','')=$2)").bind(&selected).bind(observation["linkedin_url"].as_str().map(|s|s.trim_end_matches('/'))).fetch_one(&mut *tx).await.map_err(db)?;
            if !existing {
                continue;
            }
        }
        let receipt = digest(
            &json!({"run_id":run.id(),"source":"saved_discovered_person","source_record":source}),
        );
        let finding = identity::reconcile_in(
            &mut tx,
            run.company(),
            observation,
            &receipt,
            contacts_settings,
        )
        .await?;
        if finding["requires_review"] == true {
            errors.push("contact_discovered_identity_requires_review");
        }
        if let Some(id) = finding["contact_id"]
            .as_str()
            .and_then(|s| s.parse::<Uuid>().ok())
        {
            if selected.len() < maximum && !selected.contains(&id) {
                selected.push(id);
            }
        }
        commit(tx).await?;
    }
    for contact_id in &selected {
        let mut tx = begin(c).await?;
        runs::guard_in(&mut tx, run, settings).await?;
        let contact:Value=sqlx::query_scalar("SELECT jsonb_build_object('id',id,'full_name',full_name,'role_title',role_title,'linkedin_url',linkedin_url,'human_corrected',human_corrected,'do_not_contact',do_not_contact) FROM contacts WHERE id=$1 AND company_id=$2 FOR UPDATE").bind(contact_id).bind(run.company()).fetch_optional(&mut *tx).await.map_err(db)?.ok_or(Failure("contact_not_found"))?;
        if contact["human_corrected"] == true || contact["do_not_contact"] == true {
            continue;
        }
        let public:Vec<Option<Value>>=sqlx::query_scalar("SELECT CASE WHEN octet_length(provenance::text)<=262144 THEN to_jsonb(e) ELSE NULL END FROM contact_evidence e WHERE contact_id=$1 AND company_id=$2 AND evidence_type='public_business_contact' AND user_confirmed=true AND expires_at>clock_timestamp() AND collected_at<=clock_timestamp() ORDER BY collected_at DESC,id LIMIT 10 FOR SHARE").bind(contact_id).bind(run.company()).fetch_all(&mut *tx).await.map_err(db)?;
        for evidence in public {
            let evidence = evidence.ok_or_else(invalid)?;
            let email = evidence["provenance"]["email"].as_str().and_then(|s| {
                company["domain"]
                    .as_str()
                    .and_then(|domain| rules::business_email(s, domain))
            });
            if email.is_none() || evidence["provenance"]["email_kind"] != "person_specific" {
                continue;
            }
            let observation = person::normalize(
                person::Kind::Observation,
                json!({"full_name":contact["full_name"],"role_title":contact["role_title"],"company_domain":company["domain"],"linkedin_url":contact["linkedin_url"],"email":email,"email_status":"provider_reported","source":"public_evidence","evidence_url":evidence["evidence_url"],"observed_at":evidence["collected_at"],"evidence_strength":evidence["strength"]}),
            )?;
            let receipt = digest(
                &json!({"run_id":run.id(),"source":"saved_public_business_evidence","evidence":evidence}),
            );
            let finding = identity::reconcile_in(
                &mut tx,
                run.company(),
                observation,
                &receipt,
                contacts_settings,
            )
            .await?;
            if finding["requires_review"] == true {
                errors.push("contact_public_mailbox_evidence_requires_review");
            }
            break;
        }
        commit(tx).await?;
    }
    errors.sort();
    errors.dedup();
    Ok(Local { selected, errors })
}
