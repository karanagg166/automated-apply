//! Atomic owner-imported professional evidence. UUID receipts never confer provider authority.
use crate::{
    Failure, Result,
    contacts::enrichment::{identity, person},
    research_contract::{self, Kind},
};
use chrono::{DateTime, Utc};
use serde_json::{Value, json};
use sqlx::{Connection, PgConnection, Postgres, Transaction};
use uuid::Uuid;
fn db(_: sqlx::Error) -> Failure {
    Failure("public_research_database_error")
}
fn invalid() -> Failure {
    Failure("invalid_public_research_record")
}
fn ack() -> Failure {
    Failure("public_research_write_ack_failed")
}
fn key(id: Uuid) -> String {
    format!("people_import:{}", id.simple())
}
fn time(v: &Value) -> Result<DateTime<Utc>> {
    DateTime::parse_from_rfc3339(v.as_str().ok_or_else(invalid)?)
        .map(|v| v.to_utc())
        .map_err(|_| invalid())
}
async fn stamp(tx: &mut Transaction<'_, Postgres>) -> Result<Value> {
    sqlx::query_scalar("SELECT to_jsonb(clock_timestamp())")
        .fetch_one(&mut **tx)
        .await
        .map_err(db)
}
async fn contact(tx: &mut Transaction<'_, Postgres>, id: Uuid) -> Result<Value> {
    let row:Option<Value>=sqlx::query_scalar("SELECT CASE WHEN octet_length(to_jsonb(c)::text)<=1048576 THEN to_jsonb(c) ELSE NULL END FROM contacts c WHERE id=$1 FOR UPDATE").bind(id).fetch_optional(&mut **tx).await.map_err(db)?.ok_or_else(invalid)?;
    row.ok_or_else(invalid)
}
async fn qualify_contact(
    tx: &mut Transaction<'_, Postgres>,
    result: &Value,
    human: bool,
) -> Result<Option<Value>> {
    let Some(id) = result["contact_id"].as_str() else {
        return Ok(None);
    };
    let id = id.parse().map_err(|_| invalid())?;
    let before = contact(tx, id).await?;
    if !before["metadata"].is_object() {
        return Err(invalid());
    }
    if crate::contacts::rules::truthy(&before["do_not_contact"])
        || crate::contacts::rules::truthy(&before["human_corrected"])
    {
        return Ok(Some(before));
    }
    let mut expected = before.clone();
    let old_human = crate::contacts::rules::truthy(&before["metadata"]["identity_human_confirmed"]);
    let conflict = result["conflicts"]
        .as_array()
        .filter(|a| a.is_empty())
        .is_none();
    let reviewed = human && !conflict && result["requires_review"] == false;
    expected["metadata"]["identity_human_confirmed"] = json!(old_human || reviewed);
    expected["metadata"]["identity_review_required"] = json!(
        crate::contacts::rules::truthy(&before["metadata"]["identity_review_required"])
            || conflict
            || (!reviewed && !old_human)
    );
    if expected["metadata"] == before["metadata"] {
        return Ok(Some(before));
    }
    let at = stamp(tx).await?;
    expected["updated_at"] = at.clone();
    let actual:Option<Value>=sqlx::query_scalar("UPDATE contacts c SET metadata=$1::jsonb->'metadata',updated_at=($1::jsonb->>'updated_at')::timestamptz WHERE id=$2 AND to_jsonb(c)=$3::jsonb RETURNING to_jsonb(c)").bind(&expected).bind(id).bind(&before).fetch_optional(&mut **tx).await.map_err(db)?;
    let actual = actual.ok_or_else(ack)?;
    if actual["updated_at"] != expected["updated_at"] {
        let end = stamp(tx).await?;
        let changed = time(&actual["updated_at"])?;
        if changed < time(&at)? || changed > time(&end)? {
            return Err(ack());
        }
        expected["updated_at"] = actual["updated_at"].clone();
    }
    if actual != expected || contact(tx, id).await? != expected {
        return Err(ack());
    }
    Ok(Some(expected))
}
async fn people_inventory(tx: &mut Transaction<'_, Postgres>, company: Uuid) -> Result<Vec<Value>> {
    let rows:Vec<Option<Value>>=sqlx::query_scalar("SELECT CASE WHEN octet_length(to_jsonb(p)::text)<=65536 THEN to_jsonb(p) ELSE NULL END FROM discovered_company_people p WHERE company_id=$1 ORDER BY id LIMIT 1001 FOR UPDATE").bind(company).fetch_all(&mut **tx).await.map_err(db)?;
    if rows.len() > 1000 {
        return Err(Failure("public_research_inventory_requires_review"));
    }
    let rows = rows
        .into_iter()
        .map(|v| v.ok_or_else(invalid))
        .collect::<Result<Vec<_>>>()?;
    if rows.iter().map(|v| v.to_string().len()).sum::<usize>() > 8 * 1024 * 1024
        || rows.iter().any(|r| {
            r["linkedin_url"]
                .as_str()
                .and_then(crate::contacts::enrichment::lookups::linkedin)
                .is_none()
        })
    {
        return Err(Failure("public_research_inventory_requires_review"));
    }
    Ok(rows)
}
async fn public_person(
    tx: &mut Transaction<'_, Postgres>,
    company: Uuid,
    person: &Value,
    at: &Value,
    inventory: &mut Vec<Value>,
) -> Result<Option<Uuid>> {
    let matched = inventory
        .iter()
        .enumerate()
        .filter(|(_, r)| {
            r["linkedin_url"]
                .as_str()
                .and_then(crate::contacts::enrichment::lookups::linkedin)
                .as_deref()
                == person["linkedin_url"].as_str()
        })
        .map(|(i, _)| i)
        .collect::<Vec<_>>();
    if matched.len() > 1 {
        return Err(Failure("public_research_person_url_ambiguous"));
    }
    let old = matched.first().map(|i| inventory[*i].clone());
    if old.is_none() && inventory.len() >= 1000 {
        return Err(Failure("public_research_inventory_requires_review"));
    }
    if old
        .as_ref()
        .is_some_and(|v| v["verification_status"] == "human_confirmed")
    {
        return Ok(None);
    }
    let id = old
        .as_ref()
        .map(|v| {
            v["id"]
                .as_str()
                .ok_or_else(invalid)?
                .parse::<Uuid>()
                .map_err(|_| invalid())
        })
        .transpose()?
        .unwrap_or_else(Uuid::new_v4);
    let evidence = json!({"text":person["evidence_text"],"outreach_mode":"manual"});
    let expected = if let Some(mut before) = old.clone() {
        before["observed_at"] = at.clone();
        before["evidence"] = evidence;
        before["verification_status"] = person["verification_status"].clone();
        before
    } else {
        json!({"id":id,"company_id":company,"name":person["name"],"role":person["role"],"linkedin_url":person["linkedin_url"],"evidence_url":person["evidence_url"],"source":person["source"],"observed_at":at,"verification_status":person["verification_status"],"evidence":evidence})
    };
    let actual: Option<Value> = if let Some(before) = old {
        sqlx::query_scalar("UPDATE discovered_company_people p SET observed_at=($1::jsonb->>'observed_at')::timestamptz,evidence=$1::jsonb->'evidence',verification_status=$1::jsonb->>'verification_status' WHERE id=$2 AND to_jsonb(p)=$3::jsonb RETURNING to_jsonb(p)").bind(&expected).bind(id).bind(&before).fetch_optional(&mut **tx).await.map_err(db)?
    } else {
        sqlx::query_scalar("INSERT INTO discovered_company_people AS p SELECT x.* FROM jsonb_populate_record(NULL::discovered_company_people,$1) x RETURNING to_jsonb(p)").bind(&expected).fetch_optional(&mut **tx).await.map_err(db)?
    };
    let retained: Option<Value> =
        sqlx::query_scalar("SELECT to_jsonb(p) FROM discovered_company_people p WHERE id=$1")
            .bind(id)
            .fetch_optional(&mut **tx)
            .await
            .map_err(db)?;
    if actual.as_ref() != Some(&expected) || retained.as_ref() != Some(&expected) {
        return Err(ack());
    }
    if let Some(i) = matched.first() {
        inventory[*i] = expected;
    } else {
        inventory.push(expected);
    }
    if inventory.iter().map(|v| v.to_string().len()).sum::<usize>() > 8 * 1024 * 1024 {
        return Err(Failure("public_research_inventory_requires_review"));
    }
    Ok(Some(id))
}
async fn company_in(
    tx: &mut Transaction<'_, Postgres>,
    query: &Value,
    evidence: &Value,
) -> Result<Uuid> {
    let domain = query["company_domain"]
        .as_str()
        .ok_or(Failure("public_research_company_domain_required"))?;
    let company=crate::startup_catalog::identity::resolve_in(tx,&json!({"source":"people_manual","name":query["company_name"],"domain":domain,"source_url":evidence,"source_company_id":null})).await?;
    Ok(company.id)
}
async fn reconcile(
    tx: &mut Transaction<'_, Postgres>,
    company: Uuid,
    observation: Value,
    request: Uuid,
    index: usize,
    settings: &crate::contacts::Settings,
) -> Result<(Value, Option<Value>)> {
    let receipt = crate::startup_catalog::identity::content_hash(
        &json!({"request":request,"index":index,"observation":observation}),
    );
    let human = observation["human_confirmed"] == true;
    let result = identity::reconcile_in(tx, company, observation, &receipt, settings).await?;
    let row = qualify_contact(tx, &result, human).await?;
    Ok((result, row))
}
pub(super) fn visible(
    value: &Value,
    request: Uuid,
    now: DateTime<Utc>,
    source: &str,
) -> Result<Value> {
    if !matches!(source, "manual" | "public_search") {
        return Err(invalid());
    }
    let result = value.as_object().ok_or_else(invalid)?;
    if value.to_string().len() > 131072 || value["people"].as_array().is_none_or(|a| a.len() > 20) {
        return Err(invalid());
    }
    if value["request_id"] != json!(request)
        || !value["company_name"]
            .as_str()
            .is_some_and(|s| s.chars().count() <= 200)
        || !value["status"]
            .as_str()
            .is_some_and(|s| matches!(s, "success" | "partial" | "no_results"))
        || value["provider_calls"] != 0
        || value["outbound_messages_sent"] != 0
        || !value["errors"].as_array().is_some_and(|a| {
            a.len() <= 20
                && a.iter().all(|e| {
                    e.as_str().is_some_and(|s| {
                        matches!(
                            s,
                            "public_research_official_employer_mismatch"
                                | "public_research_published_mailbox_mismatch"
                                | "public_research_identity_requires_review"
                                | "public_search_record_invalid"
                        )
                    })
                })
        })
    {
        return Err(invalid());
    }
    let mut out = json!({});
    for field in [
        "request_id",
        "company_name",
        "status",
        "people",
        "errors",
        "outbound_messages_sent",
        "provider_calls",
    ] {
        out[field] = result.get(field).cloned().ok_or_else(invalid)?;
    }
    let mut people = Vec::new();
    for p in value["people"].as_array().ok_or_else(invalid)? {
        if p.get("contact_id").is_some() {
            let contact = p["contact_id"]
                .as_str()
                .and_then(|s| s.parse::<Uuid>().ok())
                .ok_or_else(invalid)?;
            let url = p["evidence_url"]
                .as_str()
                .and_then(crate::resources::public_https)
                .ok_or_else(invalid)?;
            if !p["verification_status"]
                .as_str()
                .is_some_and(|s| matches!(s, "human_confirmed" | "requires_review"))
                || [
                    "identity_independently_confirmed",
                    "email_known",
                    "suppressed",
                ]
                .iter()
                .any(|k| !p[k].is_boolean())
            {
                return Err(invalid());
            }
            if source == "public_search"
                && (p["identity_independently_confirmed"] != false
                    || p["verification_status"] != "requires_review")
            {
                return Err(invalid());
            }
            people.push(json!({"contact_id":contact,"evidence_url":url,"verification_status":p["verification_status"],"identity_independently_confirmed":p["identity_independently_confirmed"],"email_known":p["email_known"],"suppressed":p["suppressed"]}));
        } else {
            let p = research_contract::normalize(Kind::PublicPerson, p.clone(), now)?;
            if p["source"] != source
                || source == "manual" && p["verification_status"] != "requires_review"
            {
                return Err(invalid());
            }
            people.push(p);
        }
    }
    out["people"] = json!(people);
    Ok(out)
}
pub async fn manual(
    c: &mut PgConnection,
    input: Value,
    request: Uuid,
    settings: &crate::contacts::Settings,
) -> Result<Value> {
    let mut tx = c.begin().await.map_err(db)?;
    sqlx::query("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
        .execute(&mut *tx)
        .await
        .map_err(db)?;
    crate::execution::lock_owner_in(&mut tx).await?;
    let at = stamp(&mut tx).await?;
    let now = time(&at)?;
    let query = research_contract::normalize(Kind::PeopleQuery, input, now)?;
    if query["source"] != "manual" {
        return Err(Failure("public_research_manual_import_required"));
    }
    let hash = crate::startup_catalog::identity::content_hash(&query);
    let paid: bool =
        sqlx::query_scalar("SELECT EXISTS(SELECT 1 FROM owner_preferences WHERE key=$1)")
            .bind(super::runs::key(request))
            .fetch_one(&mut *tx)
            .await
            .map_err(db)?;
    if paid {
        return Err(Failure("public_research_request_conflict"));
    }
    let old:Option<Option<Value>>=sqlx::query_scalar("SELECT CASE WHEN octet_length(value::text)<=262144 THEN value ELSE NULL END FROM owner_preferences WHERE key=$1 FOR UPDATE").bind(key(request)).fetch_optional(&mut *tx).await.map_err(db)?;
    if let Some(old) = old {
        let old = old.ok_or_else(invalid)?;
        if old["schema"] != 1 || old["input_hash"] != hash {
            return Err(Failure("public_research_request_conflict"));
        }
        if old.get("basis").is_some_and(|v| v != "manual") {
            return Err(Failure("public_research_request_conflict"));
        }
        let result = visible(&old["result"], request, now, "manual")?;
        tx.commit().await.map_err(db)?;
        return Ok(result);
    }
    let result = apply_in(
        &mut tx,
        Batch {
            query,
            hash,
            request,
            at,
            now,
            paid: false,
            permission: None,
            errors: Vec::new(),
        },
        settings,
    )
    .await?;
    tx.commit()
        .await
        .map_err(|_| Failure("public_research_commit_outcome_unknown"))?;
    Ok(result)
}
struct Batch {
    query: Value,
    hash: String,
    request: Uuid,
    at: Value,
    now: DateTime<Utc>,
    paid: bool,
    permission: Option<String>,
    errors: Vec<&'static str>,
}
async fn apply_in(
    tx: &mut Transaction<'_, Postgres>,
    batch: Batch,
    settings: &crate::contacts::Settings,
) -> Result<Value> {
    let query = batch.query;
    let hash = batch.hash;
    let request = batch.request;
    let at = batch.at;
    let now = batch.now;
    let paid = batch.paid;
    sqlx::query("SELECT pg_advisory_xact_lock(240204)")
        .execute(&mut **tx)
        .await
        .map_err(db)?;
    let official = query["official_people"].as_array().ok_or_else(invalid)?;
    let limit = query["limit"].as_u64().ok_or_else(invalid)? as usize;
    let mut records = Vec::new();
    let mut errors = batch.errors;
    if !official.is_empty() {
        if query["permission_confirmed"] != true || official.len() > limit {
            return Err(Failure("public_research_official_permission_required"));
        }
        let domain = query["company_domain"]
            .as_str()
            .ok_or(Failure("public_research_company_domain_required"))?;
        let mut company = None;
        for (index, item) in official.iter().enumerate() {
            if !super::rules::official_url(&item["evidence_url"], domain) {
                errors.push("public_research_official_employer_mismatch");
                continue;
            }
            if item["business_email"].as_str().is_some_and(|email| {
                crate::contacts::rules::business_email(email, domain).is_none()
                    || !super::rules::official_url(&item["email_publication_url"], domain)
            }) {
                errors.push("public_research_published_mailbox_mismatch");
                continue;
            }
            let company = match company {
                Some(id) => id,
                None => {
                    let id = company_in(tx, &query, &item["evidence_url"]).await?;
                    company = Some(id);
                    id
                }
            };
            let provider_id = if item["professional_url"].is_null() {
                use sha2::{Digest, Sha256};
                Some(format!(
                    "{:x}",
                    Sha256::digest(
                        format!(
                            "{}{}",
                            item["evidence_url"].as_str().ok_or_else(invalid)?,
                            automated_apply_domain::text::folded(
                                item["full_name"].as_str().ok_or_else(invalid)?
                            )
                        )
                        .as_bytes()
                    )
                ))
            } else {
                None
            };
            let observation = person::normalize(
                person::Kind::Observation,
                json!({"full_name":item["full_name"],"email":item["business_email"],"email_publication_url":item["email_publication_url"],"email_status":"unknown","role_title":item["role_title"],"company_domain":domain,"professional_url":item["professional_url"],"permission_evidence_url":item["permission_evidence_url"],"provider_person_id":provider_id,"evidence_url":item["evidence_url"],"source":if paid{"public_search"}else{"official_company"},"observed_at":item["observed_at"],"evidence_strength":if item["human_confirmed"]==true{"strong"}else{"weak"},"human_confirmed":item["human_confirmed"]}),
            )?;
            let (result, row) =
                reconcile(tx, company, observation, request, index, settings).await?;
            if let Some(row) = row {
                let reviewed =
                    item["human_confirmed"] == true && result["requires_review"] == false;
                records.push(json!({"contact_id":row["id"],"evidence_url":item["evidence_url"],"verification_status":if reviewed{"human_confirmed"}else{"requires_review"},"identity_independently_confirmed":item["human_confirmed"],"email_known":row["email"].as_str().is_some_and(|s|!s.is_empty()),"suppressed":row["do_not_contact"]}));
            } else {
                errors.push("public_research_identity_requires_review")
            }
        }
    } else {
        let people = query["manual_people"]
            .as_array()
            .ok_or_else(invalid)?
            .iter()
            .take(limit)
            .cloned()
            .map(|mut p| {
                if !paid {
                    p["source"] = json!("manual");
                    p["verification_status"] = json!("requires_review");
                }
                p
            })
            .collect::<Vec<_>>();
        let people = super::rules::unique_people(people, now)?;
        if !people.is_empty() {
            let company = company_in(tx, &query, &people[0]["evidence_url"]).await?;
            let mut inventory = people_inventory(tx, company).await?;
            for (index, p) in people.into_iter().enumerate() {
                let id = public_person(tx, company, &p, &at, &mut inventory).await?;
                if let Some(id) = id.filter(|_| {
                    p["name"].as_str().is_some_and(|s| !s.is_empty())
                        && p["role"].as_str().is_some_and(|s| !s.is_empty())
                }) {
                    let observation = person::normalize(
                        person::Kind::Observation,
                        json!({"full_name":p["name"],"role_title":p["role"],"company_domain":query["company_domain"],"linkedin_url":p["linkedin_url"],"evidence_url":p["evidence_url"],"source":if paid{"public_search"}else{"manual"},"permission_evidence_url":batch.permission,"discovered_person_id":id,"evidence_strength":"weak","observed_at":at}),
                    )?;
                    reconcile(tx, company, observation, request, index, settings).await?;
                }
                records.push(p);
            }
        }
    }
    let result = json!({"request_id":request,"company_name":query["company_name"],"status":if !errors.is_empty(){"partial"}else if records.is_empty(){"no_results"}else{"success"},"people":records,"errors":errors,"provider_calls":0,"outbound_messages_sent":0});
    let expected = json!({"schema":1,"input_hash":hash,"basis":if paid{"public_search"}else{"manual"},"result":result});
    let saved:Option<Value>=sqlx::query_scalar("INSERT INTO owner_preferences(key,value,created_at,updated_at) VALUES($1,$2,clock_timestamp(),clock_timestamp()) ON CONFLICT DO NOTHING RETURNING value").bind(key(request)).bind(&expected).fetch_optional(&mut **tx).await.map_err(db)?;
    let actual: Option<Value> =
        sqlx::query_scalar("SELECT value FROM owner_preferences WHERE key=$1")
            .bind(key(request))
            .fetch_optional(&mut **tx)
            .await
            .map_err(db)?;
    if saved.as_ref() != Some(&expected) || actual.as_ref() != Some(&expected) {
        return Err(ack());
    }
    let result = visible(
        &expected["result"],
        request,
        now,
        if paid { "public_search" } else { "manual" },
    )?;
    Ok(result)
}

pub async fn retained(c: &mut PgConnection, request: Uuid) -> Result<Value> {
    let mut tx = c.begin().await.map_err(db)?;
    sqlx::query("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        .execute(&mut *tx)
        .await
        .map_err(db)?;
    let old:Option<Value>=sqlx::query_scalar("SELECT CASE WHEN octet_length(value::text)<=262144 THEN value ELSE NULL END FROM owner_preferences WHERE key=$1").bind(key(request)).fetch_optional(&mut *tx).await.map_err(db)?.ok_or(Failure("public_research_request_not_found"))?;
    let old = old.ok_or_else(invalid)?;
    if old["schema"] != 1 {
        return Err(invalid());
    }
    let at = stamp(&mut tx).await?;
    let result = visible(
        &old["result"],
        request,
        time(&at)?,
        old["basis"].as_str().unwrap_or("manual"),
    )?;
    tx.commit().await.map_err(db)?;
    Ok(result)
}
pub(super) async fn from_finding_in(
    tx: &mut Transaction<'_, Postgres>,
    journal: &Value,
    request: Uuid,
    settings: &crate::contacts::Settings,
    now: DateTime<Utc>,
) -> Result<Value> {
    let stored: Option<Value> =
        sqlx::query_scalar("SELECT value FROM owner_preferences WHERE key=$1")
            .bind(super::runs::key(request))
            .fetch_optional(&mut **tx)
            .await
            .map_err(db)?;
    if stored.as_ref() != Some(journal) || journal["state"] != "finding_retained" {
        return Err(Failure("public_research_finding_context_changed"));
    }
    super::findings::selected(journal, now)?;
    let mut query = research_contract::normalize(Kind::PeopleQuery, journal["input"].clone(), now)?;
    if query["source"] != "public_search"
        || !matches!(
            journal["finding"]["state"].as_str(),
            Some("success" | "partial" | "no_results")
        )
    {
        return Err(Failure("public_research_successful_finding_required"));
    }
    let exists: bool =
        sqlx::query_scalar("SELECT EXISTS(SELECT 1 FROM owner_preferences WHERE key=$1)")
            .bind(key(request))
            .fetch_one(&mut **tx)
            .await
            .map_err(db)?;
    if exists {
        return Err(Failure("public_research_local_receipt_conflict"));
    }
    let official = query["research_mode"] == "official_company";
    let people = journal["finding"]["people"]
        .as_array()
        .ok_or_else(invalid)?
        .clone();
    query[if official {
        "official_people"
    } else {
        "manual_people"
    }] = json!(people);
    query["permission_confirmed"] = json!(true);
    let permission = if official {
        None
    } else {
        journal["retention_permission"].as_str().map(String::from)
    };
    let errors = journal["finding"]["errors"]
        .as_array()
        .ok_or_else(invalid)?
        .iter()
        .map(|_| "public_search_record_invalid")
        .collect();
    apply_in(
        tx,
        Batch {
            query,
            hash: journal["input_hash"].as_str().ok_or_else(invalid)?.into(),
            request,
            at: journal["finding_at"].clone(),
            now,
            paid: true,
            permission,
            errors,
        },
        settings,
    )
    .await
}
pub(super) async fn verify_completed_in(
    tx: &mut Transaction<'_, Postgres>,
    request: Uuid,
    input_hash: &Value,
    result: &Value,
) -> Result<()> {
    let expected =
        json!({"schema":1,"input_hash":input_hash,"basis":"public_search","result":result});
    let actual: Option<Value> =
        sqlx::query_scalar("SELECT value FROM owner_preferences WHERE key=$1")
            .bind(key(request))
            .fetch_optional(&mut **tx)
            .await
            .map_err(db)?;
    if actual.as_ref() != Some(&expected) {
        return Err(ack());
    }
    Ok(())
}
