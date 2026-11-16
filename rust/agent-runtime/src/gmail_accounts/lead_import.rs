//! Exact selected-message link intake; all imported vacancies remain unverified and local.
use super::*;
fn conflict() -> Failure {
    Failure("gmail_lead_identity_requires_review")
}
fn id(value: &Value) -> Result<Uuid> {
    value
        .as_str()
        .and_then(|s| s.parse().ok())
        .ok_or_else(invalid)
}
fn label(raw: &str) -> String {
    automated_apply_domain::text::folded(
        &raw.split(crate::context_contract::python_space)
            .filter(|s| !s.is_empty())
            .collect::<Vec<_>>()
            .join(" "),
    )
}
fn hint_label(raw: &str) -> String {
    static TAGS: std::sync::LazyLock<regex::Regex> =
        std::sync::LazyLock::new(|| regex::Regex::new(r"<[^>]*>").unwrap());
    label(&TAGS.replace_all(raw, " "))
}

pub fn normalized(input: &Value, now: DateTime<Utc>) -> Result<Value> {
    let url = input["job_url"].as_str().ok_or_else(invalid)?;
    let canonical =
        crate::job_urls::canonical(url).map_err(|_| Failure("invalid_gmail_read_contract"))?;
    let source_id = format!("reviewed_email_{:x}", Sha256::digest(url.as_bytes()));
    let domain = if let Some(raw) = input["company_domain"].as_str() {
        let domain = raw.to_lowercase().trim().trim_end_matches('.').to_owned();
        if !regex::Regex::new(r"^[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$")
            .unwrap()
            .is_match(&domain)
            || crate::resources::public_https(&format!("https://{domain}")).is_none()
        {
            return Err(Failure("invalid_gmail_read_contract"));
        }
        json!(domain)
    } else {
        Value::Null
    };
    let company = input["company_name"].as_str().filter(|s| !s.is_empty());
    let mut out = json!({"source_name":"gmail_alert","source_job_id":source_id,"original_url":url,"canonical_url":canonical,"application_url":null,"company_name":company,"company_domain":domain,"title":input["title"],"description":null,"location":null,"country":null,"region":null,"is_remote":null,"remote_type":"unknown","employment_type":null,"experience_level":null,"experience_min_years":null,"experience_max_years":null,"salary_raw":null,"salary_min":null,"salary_max":null,"salary_currency":null,"salary_period":null,"equity":null,"skills_required":[],"skills_preferred":[],"date_posted":null,"first_observed_date":now,"last_observed_date":now,"retrieved_at":now,"data_provenance":{"method":"owner_reviewed_email_lead"},"company_intelligence":{},"source_verification_status":"requires_review","quality_flags":if company.is_none(){vec!["company_unknown"]}else{vec![]},"is_confirmed_current":false});
    for key in ["first_observed_date", "last_observed_date", "retrieved_at"] {
        out[key] = json!(now.to_rfc3339_opts(
            if now.timestamp_subsec_micros() == 0 {
                chrono::SecondsFormat::Secs
            } else {
                chrono::SecondsFormat::Micros
            },
            true
        ));
    }
    Ok(out)
}
async fn company(tx: &mut Transaction<'_, Postgres>, item: &Value) -> Result<Option<Uuid>> {
    let Some(name) = item["company_name"].as_str() else {
        return Ok(None);
    };
    let domain = item["company_domain"].as_str();
    if let Some(domain) = domain {
        let rows: Vec<Value> = sqlx::query_scalar(
            "SELECT to_jsonb(c) FROM companies c WHERE domain=$1 ORDER BY id LIMIT 2 FOR UPDATE",
        )
        .bind(domain)
        .fetch_all(&mut **tx)
        .await
        .map_err(db)?;
        if rows.len() > 1 {
            return Err(conflict());
        }
        if let Some(row) = rows.first() {
            return Ok(Some(id(&row["id"])?));
        }
    }
    let names:Vec<Value>=sqlx::query_scalar("SELECT to_jsonb(c) FROM companies c WHERE lower(name)=lower($1) ORDER BY id LIMIT 2 FOR UPDATE").bind(name).fetch_all(&mut **tx).await.map_err(db)?;
    let ambiguous = names.len() > 1;
    let candidate = if ambiguous && domain.is_none() {
        let rows:Vec<Value>=sqlx::query_scalar("SELECT to_jsonb(c) FROM companies c WHERE lower(name)=lower($1) AND domain IS NULL ORDER BY id LIMIT 2 FOR UPDATE").bind(name).fetch_all(&mut **tx).await.map_err(db)?;
        if rows.len() == 1 {
            rows.into_iter().next()
        } else {
            None
        }
    } else if names.len() == 1 {
        names.into_iter().next()
    } else {
        None
    };
    if let Some(row) = candidate {
        if (domain.is_none() || row["domain"].is_null() || row["domain"].as_str() == domain)
            && !(domain.is_some() && row["metadata"]["identity_review_required"] == true)
        {
            let identity = id(&row["id"])?;
            if let Some(domain) = domain.filter(|_| row["domain"].is_null()) {
                let ack: Option<Uuid> = sqlx::query_scalar(
                    "UPDATE companies SET domain=$2 WHERE id=$1 AND domain IS NULL RETURNING id",
                )
                .bind(identity)
                .bind(domain)
                .fetch_optional(&mut **tx)
                .await
                .map_err(db)?;
                if ack != Some(identity) {
                    return Err(Failure("gmail_read_write_ack_failed"));
                }
            }
            return Ok(Some(identity));
        }
    }
    let identity = Uuid::new_v4();
    let metadata = if ambiguous && domain.is_none() {
        json!({"identity_review_required":true,"identity_resolution":"ambiguous_name_without_domain"})
    } else {
        json!({})
    };
    let ack:Option<Uuid>=sqlx::query_scalar("INSERT INTO companies(id,name,domain,is_catch_all,metadata) VALUES($1,$2,$3,false,$4) RETURNING id").bind(identity).bind(name).bind(domain).bind(metadata).fetch_optional(&mut **tx).await.map_err(db)?;
    if ack != Some(identity) {
        return Err(Failure("gmail_read_write_ack_failed"));
    }
    Ok(Some(identity))
}
async fn resolve(
    tx: &mut Transaction<'_, Postgres>,
    item: &Value,
    observation: &str,
) -> Result<(Option<Value>, &'static str)> {
    let observed: Option<Uuid> = sqlx::query_scalar(
        "SELECT job_id FROM job_source_observations WHERE source='gmail_alert' AND identity_key=$1",
    )
    .bind(observation)
    .fetch_optional(&mut **tx)
    .await
    .map_err(db)?;
    if let Some(identity) = observed {
        let row: Option<Value> =
            sqlx::query_scalar("SELECT to_jsonb(j) FROM jobs j WHERE id=$1 FOR UPDATE")
                .bind(identity)
                .fetch_optional(&mut **tx)
                .await
                .map_err(db)?;
        return Ok((Some(row.ok_or_else(conflict)?), "source_identity"));
    }
    let url = item["canonical_url"].as_str().ok_or_else(invalid)?;
    let exact:Vec<Value>=sqlx::query_scalar("SELECT to_jsonb(j) FROM jobs j WHERE canonical_key=$1 OR job_url=$1 ORDER BY id LIMIT 2 FOR UPDATE").bind(url).fetch_all(&mut **tx).await.map_err(db)?;
    if exact.len() > 1 {
        return Err(conflict());
    }
    if let Some(row) = exact.into_iter().next() {
        return Ok((Some(row), "canonical_url"));
    }
    let legacy:Vec<Value>=sqlx::query_scalar("SELECT to_jsonb(j) FROM jobs j WHERE canonical_key IS NULL ORDER BY id LIMIT 10001 FOR UPDATE").fetch_all(&mut **tx).await.map_err(db)?;
    if legacy.len() > 10000 {
        return Err(Failure("gmail_lead_legacy_inventory_limit"));
    }
    let mut matching = legacy.into_iter().filter(|row| {
        row["job_url"]
            .as_str()
            .and_then(|url| crate::job_urls::canonical(url).ok())
            .as_deref()
            == Some(url)
    });
    let first = matching.next();
    if matching.next().is_some() {
        return Err(conflict());
    }
    Ok((first, "legacy_canonical_url"))
}
async fn save(
    tx: &mut Transaction<'_, Postgres>,
    item: &Value,
    now: DateTime<Utc>,
) -> Result<(Uuid, bool, Vec<String>)> {
    sqlx::query("SELECT pg_advisory_xact_lock(240204)")
        .execute(&mut **tx)
        .await
        .map_err(db)?;
    let observation = format!(
        "{:x}",
        Sha256::digest(
            format!(
                "id::{}",
                item["source_job_id"].as_str().ok_or_else(invalid)?
            )
            .as_bytes()
        )
    );
    let (existing, mut reason) = resolve(tx, item, &observation).await?;
    let company = if let Some(existing) = existing
        .as_ref()
        .filter(|job| !job["company_id"].is_null() && item["company_domain"].is_null())
    {
        let identity = id(&existing["company_id"])?;
        let canonical: Option<Value> =
            sqlx::query_scalar("SELECT to_jsonb(c) FROM companies c WHERE id=$1 FOR SHARE")
                .bind(identity)
                .fetch_optional(&mut **tx)
                .await
                .map_err(db)?;
        let canonical = canonical.ok_or_else(conflict)?;
        if item["company_name"]
            .as_str()
            .is_some_and(|name| label(name) != label(canonical["name"].as_str().unwrap_or("")))
        {
            return Err(conflict());
        }
        Some(identity)
    } else {
        company(tx, item).await?
    };
    if let (Some(existing), Some(company)) = (&existing, company) {
        if !existing["company_id"].is_null() && existing["company_id"] != json!(company) {
            return Err(conflict());
        }
    }
    let created = existing.is_none();
    let identity = if let Some(existing) = &existing {
        id(&existing["id"])?
    } else {
        let identity = Uuid::new_v4();
        let ack:Option<Uuid>=sqlx::query_scalar("INSERT INTO jobs(id,title,job_url,source_platform,company_id,is_remote,skills_required,status,canonical_key,remote_type,experience_level,first_observed_at,last_observed_at,source_verification_status,discovery_metadata,created_at) VALUES($1,$2,$3,'gmail_alert',$4,false,ARRAY[]::text[],'discovered',$3,'unknown',NULL,$5,$5,'requires_review',$6,clock_timestamp()) RETURNING id").bind(identity).bind(item["title"].as_str().ok_or_else(invalid)?).bind(item["canonical_url"].as_str().unwrap()).bind(company).bind(now).bind(item).fetch_optional(&mut **tx).await.map_err(db)?;
        if ack != Some(identity) {
            return Err(Failure("gmail_read_write_ack_failed"));
        }
        reason = "new";
        identity
    };
    let expected_company = existing
        .as_ref()
        .filter(|v| !v["company_id"].is_null())
        .map(|v| id(&v["company_id"]))
        .transpose()?
        .or(company);
    if !created {
        let ack:Option<Uuid>=sqlx::query_scalar("UPDATE jobs SET company_id=coalesce(company_id,$2),canonical_key=coalesce(canonical_key,$3),first_observed_at=coalesce(first_observed_at,$4),last_observed_at=greatest(last_observed_at,$4) WHERE id=$1 RETURNING id").bind(identity).bind(company).bind(item["canonical_url"].as_str().unwrap()).bind(now).fetch_optional(&mut **tx).await.map_err(db)?;
        if ack != Some(identity) {
            return Err(Failure("gmail_read_write_ack_failed"));
        }
    }
    let mut provenance = item["data_provenance"].clone();
    provenance["deduplication"] = json!(reason);
    provenance["quality_flags"] = item["quality_flags"].clone();
    let ack:Option<Uuid>=sqlx::query_scalar("INSERT INTO job_source_observations(id,job_id,source,identity_key,source_job_id,original_url,first_observed_at,last_observed_at,provenance,verification_status) VALUES($1,$2,'gmail_alert',$3,$4,$5,$6,$6,$7,'requires_review') ON CONFLICT(source,identity_key) DO UPDATE SET last_observed_at=greatest(job_source_observations.last_observed_at,excluded.last_observed_at),provenance=excluded.provenance,verification_status=excluded.verification_status,original_url=excluded.original_url WHERE job_source_observations.job_id=excluded.job_id RETURNING job_id").bind(Uuid::new_v4()).bind(identity).bind(observation).bind(item["source_job_id"].as_str().unwrap()).bind(item["original_url"].as_str().unwrap()).bind(now).bind(provenance).fetch_optional(&mut **tx).await.map_err(db)?;
    if ack != Some(identity) {
        return Err(Failure("gmail_read_write_ack_failed"));
    }
    let final_row: Value = sqlx::query_scalar("SELECT to_jsonb(j) FROM jobs j WHERE id=$1")
        .bind(identity)
        .fetch_one(&mut **tx)
        .await
        .map_err(db)?;
    if final_row["company_id"] != expected_company.map(|id| json!(id)).unwrap_or(Value::Null) {
        return Err(Failure("gmail_read_write_ack_failed"));
    }
    if created
        && (final_row["title"] != item["title"]
            || final_row["job_url"] != item["canonical_url"]
            || final_row["canonical_key"] != item["canonical_url"]
            || final_row["source_platform"] != "gmail_alert"
            || final_row["status"] != "discovered"
            || final_row["source_verification_status"] != "requires_review"
            || final_row["discovery_metadata"] != *item)
    {
        return Err(Failure("gmail_read_write_ack_failed"));
    }
    if let Some(old) = existing {
        for field in [
            "title",
            "status",
            "match_score",
            "match_explanation",
            "source_platform",
            "job_url",
            "description",
            "skills_required",
            "discovery_metadata",
        ] {
            if final_row[field] != old[field] {
                return Err(Failure("gmail_read_write_ack_failed"));
            }
        }
    }
    let mut possible = Vec::new();
    if created {
        if let Some(company) = company {
            let candidates: Vec<(Uuid, String)> = sqlx::query_as(
                "SELECT id,title FROM jobs WHERE company_id=$1 AND id!=$2 ORDER BY id LIMIT 500",
            )
            .bind(company)
            .bind(identity)
            .fetch_all(&mut **tx)
            .await
            .map_err(db)?;
            for (id, title) in candidates {
                if hint_label(&title) == hint_label(item["title"].as_str().unwrap()) {
                    possible.push(id.to_string());
                    if possible.len() == 20 {
                        break;
                    }
                }
            }
        }
    }
    Ok((identity, created, possible))
}
pub(super) async fn import_in(
    tx: &mut Transaction<'_, Postgres>,
    account: Uuid,
    evidence: &str,
    input: &Value,
    now: DateTime<Utc>,
) -> Result<Value> {
    account_in(tx, account, true).await?;
    let key = format!("gmail_msg:{evidence}");
    let message: Option<Value> =
        sqlx::query_scalar("SELECT value FROM owner_preferences WHERE key=$1 FOR UPDATE")
            .bind(&key)
            .fetch_optional(&mut **tx)
            .await
            .map_err(db)?;
    let mut message = message.ok_or(Failure("gmail_evidence_not_found"))?;
    if message["account_id"] != json!(account)
        || !crate::gmail_history::contract::timestamp(&message["expires_at"])
            .is_some_and(|at| at > now)
    {
        return Err(Failure("gmail_evidence_not_found"));
    }
    let url = input["job_url"].as_str().ok_or_else(invalid)?;
    if !message["links"]
        .as_array()
        .ok_or_else(invalid)?
        .contains(&json!(url))
    {
        return Err(Failure("gmail_lead_not_in_selected_evidence"));
    }
    let item = normalized(input, now)?;
    let (identity, created, possible) = save(tx, &item, now).await?;
    let mut imports = message
        .get("imported_leads")
        .map(|v| v.as_object().cloned().ok_or_else(invalid))
        .transpose()?
        .unwrap_or_default();
    imports.insert(url.into(), json!([identity]));
    message["imported_leads"] = Value::Object(imports);
    let mut all = message
        .get("imported_job_ids")
        .map(|v| v.as_array().ok_or_else(invalid))
        .transpose()?
        .into_iter()
        .flatten()
        .map(|v| v.as_str().map(str::to_owned).ok_or_else(invalid))
        .collect::<Result<BTreeSet<_>>>()?;
    all.insert(identity.to_string());
    message["imported_job_ids"] = json!(all);
    put(tx, &key, &message).await?;
    let mut hints = serde_json::Map::new();
    if !possible.is_empty() {
        hints.insert(identity.to_string(), json!(possible));
    }
    Ok(
        json!({"total_received":1,"inserted_count":usize::from(created),"updated_count":usize::from(!created),"duplicate_count":usize::from(!created),"rejected_count":0,"failed_count":0,"skipped_count":0,"job_ids":[identity],"possible_duplicates":hints,"errors":[]}),
    )
}
