//! Conservative local identity reconciliation. Provider claims never verify mailboxes.
use super::*;
use sha2::{Digest, Sha256};
fn hash(raw: &str) -> String {
    format!("{:x}", Sha256::digest(raw.as_bytes()))
}
fn ack() -> Failure {
    Failure("contact_identity_write_ack_failed")
}
fn conflict() -> Failure {
    Failure("contact_identity_requires_review")
}
pub fn folded(value: &str) -> String {
    automated_apply_domain::text::folded(value)
        .split(crate::context_contract::python_space)
        .filter(|s| !s.is_empty())
        .collect::<Vec<_>>()
        .join(" ")
}
fn id(value: &Value, key: &str) -> Result<Uuid> {
    value[key]
        .as_str()
        .and_then(|s| s.parse().ok())
        .ok_or_else(invalid)
}
fn truth(value: &Value, key: &str) -> bool {
    rules::truthy(&value[key])
}
fn metadata(contact: &Value) -> Result<&serde_json::Map<String, Value>> {
    contact["metadata"].as_object().ok_or_else(invalid)
}
pub fn identity_keys(
    observation: &Value,
    email: Option<&str>,
    kind: &str,
) -> Result<Vec<(String, String)>> {
    let mut keys = Vec::new();
    for (field, namespace) in [
        ("professional_url", "professional_url"),
        ("linkedin_url", "linkedin"),
    ] {
        if let Some(value) = observation[field].as_str() {
            keys.push((namespace.into(), value.into()));
            keys.push((format!("suppressed_{namespace}"), hash(value)));
        }
    }
    if let Some(value) = observation["provider_person_id"].as_str() {
        let source = observation["source"].as_str().ok_or_else(invalid)?;
        if source.len() > 70 {
            return Err(invalid());
        }
        keys.push((source.into(), value.into()));
        keys.push((format!("suppressed_provider_{source}"), hash(value)));
    }
    if let Some(value) = observation["discovered_person_id"].as_str() {
        keys.push(("discovered_person".into(), value.into()));
    }
    if let Some(email) = email.filter(|_| kind == "person_specific") {
        keys.push(("suppressed_email".into(), hash(email)));
    }
    keys.sort();
    keys.dedup();
    Ok(keys)
}
async fn evidence(tx: &mut Transaction<'_, Postgres>, expected: &Value) -> Result<()> {
    let saved:Option<Value>=sqlx::query_scalar("INSERT INTO contact_evidence(id,contact_id,company_id,source,evidence_type,evidence_url,observed_role,observed_company,provider_verification_claim,strength,collected_at,expires_at,provenance,user_confirmed) SELECT x.id,x.contact_id,x.company_id,x.source,x.evidence_type,x.evidence_url,x.observed_role,x.observed_company,x.provider_verification_claim,x.strength,x.collected_at,x.expires_at,x.provenance,x.user_confirmed FROM jsonb_populate_record(NULL::contact_evidence,$1) x RETURNING to_jsonb(contact_evidence)").bind(expected).fetch_optional(&mut **tx).await.map_err(db)?;
    if saved.as_ref() != Some(expected) {
        return Err(ack());
    }
    Ok(())
}
async fn stamp(tx: &mut Transaction<'_, Postgres>, time: DateTime<Utc>) -> Result<Value> {
    sqlx::query_scalar("SELECT to_jsonb($1::timestamptz)")
        .bind(time)
        .fetch_one(&mut **tx)
        .await
        .map_err(db)
}
async fn receipt(
    tx: &mut Transaction<'_, Postgres>,
    key: &str,
    input_hash: &str,
    result: Value,
) -> Result<Value> {
    let expected = json!({"schema_version":1,"input_sha256":input_hash,"result":result});
    let saved:Option<Value>=sqlx::query_scalar("INSERT INTO owner_preferences(key,value,created_at,updated_at) VALUES($1,$2,clock_timestamp(),clock_timestamp()) ON CONFLICT DO NOTHING RETURNING value").bind(key).bind(&expected).fetch_optional(&mut **tx).await.map_err(db)?;
    if saved.as_ref() != Some(&expected) {
        return Err(ack());
    }
    Ok(expected["result"].clone())
}
async fn update(tx: &mut Transaction<'_, Postgres>, before: &Value, after: &Value) -> Result<()> {
    if before == after {
        return Ok(());
    }
    let actual:Option<Value>=sqlx::query_scalar("UPDATE contacts c SET role_title=$3::jsonb->>'role_title',linkedin_url=$3::jsonb->>'linkedin_url',email=$3::jsonb->>'email',email_status=$3::jsonb->>'email_status',enrichment_source=$3::jsonb->>'enrichment_source',metadata=$3::jsonb->'metadata',last_checked_at=($3::jsonb->>'last_checked_at')::timestamptz,updated_at=($3::jsonb->>'updated_at')::timestamptz WHERE c.id=$1 AND to_jsonb(c)=$2::jsonb RETURNING to_jsonb(c)").bind(id(before,"id")?).bind(before).bind(after).fetch_optional(&mut **tx).await.map_err(db)?;
    if actual.as_ref() != Some(after) {
        return Err(ack());
    }
    Ok(())
}
/// Caller owns a SERIALIZABLE transaction and shared owner fence. No IO occurs here.
pub async fn reconcile_in(
    tx: &mut Transaction<'_, Postgres>,
    company_id: Uuid,
    observation: Value,
    receipt_id: &str,
    settings: &super::super::Settings,
) -> Result<Value> {
    if receipt_id.len() != 64 || !receipt_id.bytes().all(|b| b.is_ascii_hexdigit()) {
        return Err(Failure("invalid_contact_observation_receipt"));
    }
    let observation = person::normalize(person::Kind::Observation, observation)?;
    let input_hash = hash(&json!({"company_id":company_id,"observation":observation}).to_string());
    let receipt_key = format!("cl_obs:{receipt_id}");
    if let Some(saved)=sqlx::query_scalar::<_,Value>("SELECT value FROM owner_preferences WHERE key=$1 AND octet_length(value::text)<=32768 FOR UPDATE").bind(&receipt_key).fetch_optional(&mut **tx).await.map_err(db)?{
        if saved["schema_version"]!=1||saved["input_sha256"]!=input_hash||!saved["result"].is_object(){return Err(Failure("contact_observation_receipt_conflict"));}return Ok(saved["result"].clone());
    }
    // Never use an oversized/invalid existing receipt as an absent admission.
    if sqlx::query_scalar::<_, bool>("SELECT EXISTS(SELECT 1 FROM owner_preferences WHERE key=$1)")
        .bind(&receipt_key)
        .fetch_one(&mut **tx)
        .await
        .map_err(db)?
    {
        return Err(invalid());
    }
    let company:Value=sqlx::query_scalar("SELECT jsonb_build_object('id',id,'name',name,'domain',domain) FROM companies WHERE id=$1 FOR UPDATE").bind(company_id).fetch_optional(&mut **tx).await.map_err(db)?.ok_or(Failure("contact_company_not_found"))?;
    let (at, now): (Value, DateTime<Utc>) = {
        let at: Value = sqlx::query_scalar("SELECT to_jsonb(clock_timestamp())")
            .fetch_one(&mut **tx)
            .await
            .map_err(db)?;
        let now = serde_json::from_value(at.clone()).map_err(|_| invalid())?;
        (at, now)
    };
    let domain = company["domain"].as_str().and_then(person::identity_domain);
    let observed_domain = observation["company_domain"]
        .as_str()
        .and_then(person::identity_domain);
    let domain_conflict = observation["company_domain"].as_str().is_some()
        && (domain.is_none() || observed_domain != domain);
    let email = observation["email"].as_str().and_then(|email| {
        domain
            .as_deref()
            .and_then(|domain| rules::business_email(email, domain))
    });
    let kind = email
        .as_deref()
        .map(rules::email_kind)
        .unwrap_or(observation["email_kind"].as_str().ok_or_else(invalid)?);
    let keys = identity_keys(&observation, email.as_deref(), kind)?;
    let (count,bytes):(i64,i64)=sqlx::query_as("SELECT count(*)::bigint,coalesce(sum(octet_length(to_jsonb(c)::text)),0)::bigint FROM (SELECT * FROM contacts WHERE company_id=$1 ORDER BY id LIMIT 1001) c").bind(company_id).fetch_one(&mut **tx).await.map_err(db)?;
    if count > 1000 || bytes > 8 * 1024 * 1024 {
        return Err(Failure("contact_identity_inventory_requires_review"));
    }
    let rows:Vec<Option<Value>>=sqlx::query_scalar("SELECT CASE WHEN octet_length(c.metadata::text)<=262144 AND jsonb_typeof(c.metadata::jsonb)='object' AND coalesce(octet_length(c.human_review_notes),0)<=10000 AND coalesce(octet_length(c.suppression_reason),0)<=10000 THEN to_jsonb(c) ELSE NULL END FROM contacts c WHERE company_id=$1 ORDER BY id FOR UPDATE").bind(company_id).fetch_all(&mut **tx).await.map_err(db)?;
    let records = rows
        .into_iter()
        .map(|v| v.ok_or_else(invalid))
        .collect::<Result<Vec<_>>>()?;
    let key_values = keys
        .iter()
        .map(|(ns, key)| json!({"namespace":ns,"identity_key":key}))
        .collect::<Vec<_>>();
    let mappings:Vec<Value>=sqlx::query_scalar("SELECT to_jsonb(i) FROM contact_identities i JOIN jsonb_to_recordset($2::jsonb) AS k(namespace text,identity_key text) ON i.namespace=k.namespace AND i.identity_key=k.identity_key WHERE company_id=$1 ORDER BY i.id LIMIT 1001 FOR UPDATE OF i").bind(company_id).bind(json!(key_values)).fetch_all(&mut **tx).await.map_err(db)?;
    if mappings.len() > 1000 {
        return Err(Failure("contact_identity_inventory_requires_review"));
    }
    let mut matched = BTreeSet::new();
    let mut tombstone = false;
    let mut mismatch = domain_conflict;
    for mapping in &mappings {
        let contact = id(mapping, "contact_id")?;
        if !records.iter().any(|r| id(r, "id") == Ok(contact)) {
            return Err(invalid());
        }
        matched.insert(contact);
        if mapping["namespace"]
            .as_str()
            .is_some_and(|s| s.starts_with("suppressed_"))
        {
            tombstone = true;
        }
    }
    for contact in &records {
        let same_url = observation["linkedin_url"].as_str().is_some_and(|s| {
            contact["linkedin_url"]
                .as_str()
                .and_then(lookups::linkedin)
                .as_deref()
                == Some(s)
        });
        let same_email = kind == "person_specific"
            && email.as_ref().is_some_and(|email| {
                contact["email"]
                    .as_str()
                    .is_some_and(|s| automated_apply_domain::text::folded(s) == *email)
            });
        if same_url || same_email {
            matched.insert(id(contact, "id")?);
            if !truth(contact, "human_corrected")
                && folded(contact["full_name"].as_str().ok_or_else(invalid)?)
                    != folded(observation["full_name"].as_str().ok_or_else(invalid)?)
            {
                mismatch = true;
            }
            if same_email
                && observation["linkedin_url"].as_str().is_some()
                && contact["linkedin_url"]
                    .as_str()
                    .and_then(lookups::linkedin)
                    .is_some_and(|s| s != observation["linkedin_url"].as_str().unwrap_or(""))
            {
                mismatch = true;
            }
        }
    }
    if matched.len() > 1 {
        mismatch = true;
    }
    if let Some(existing) = matched
        .iter()
        .next()
        .and_then(|id| records.iter().find(|r| self::id(r, "id") == Ok(*id)))
    {
        if !truth(existing, "do_not_contact")
            && !truth(existing, "human_corrected")
            && folded(existing["full_name"].as_str().ok_or_else(invalid)?)
                != folded(observation["full_name"].as_str().ok_or_else(invalid)?)
        {
            mismatch = true;
        }
    }
    let mut strength = if matched.is_empty() {
        observation["evidence_strength"]
            .as_str()
            .ok_or_else(invalid)?
            .to_owned()
    } else {
        "strong".into()
    };
    if !mismatch && matched.is_empty() {
        if let Some(url) = observation["evidence_url"].as_str() {
            let supports:Vec<Uuid>=sqlx::query_scalar("SELECT DISTINCT contact_id FROM contact_evidence WHERE company_id=$1 AND contact_id IS NOT NULL AND evidence_url=$2 AND user_confirmed=true AND expires_at>$3 AND collected_at<=$3 ORDER BY contact_id LIMIT 1001").bind(company_id).bind(url).bind(now).fetch_all(&mut **tx).await.map_err(db)?;
            if supports.len() > 1000 {
                return Err(Failure("contact_identity_inventory_requires_review"));
            }
            let supported = records
                .iter()
                .filter(|c| {
                    supports.contains(&id(c, "id").unwrap_or(Uuid::nil()))
                        && folded(c["full_name"].as_str().unwrap_or(""))
                            == folded(observation["full_name"].as_str().unwrap_or(""))
                        && folded(c["role_title"].as_str().unwrap_or(""))
                            == folded(observation["role_title"].as_str().unwrap_or(""))
                        && !(observation["linkedin_url"].as_str().is_some()
                            && c["linkedin_url"]
                                .as_str()
                                .and_then(lookups::linkedin)
                                .is_some_and(|p| {
                                    Some(p.as_str()) != observation["linkedin_url"].as_str()
                                }))
                })
                .collect::<Vec<_>>();
            if supported.len() == 1 {
                matched.insert(id(supported[0], "id")?);
                strength = "moderate".into();
            } else if supported.len() > 1 {
                mismatch = true;
                for c in supported {
                    matched.insert(id(c, "id")?);
                }
            }
        }
    }
    let source = observation["source"]
        .as_str()
        .filter(|s| s.len() <= 100)
        .ok_or_else(invalid)?;
    let checked = if observation["observed_at"].is_null() {
        now
    } else {
        crate::gmail_history::contract::timestamp(&observation["observed_at"])
            .map(|t| t.with_timezone(&Utc))
            .or_else(|| rules::timestamp(&observation["observed_at"]))
            .ok_or_else(invalid)?
    };
    if checked > now + chrono::Duration::seconds(5) {
        return Err(Failure("contact_observation_time_requires_review"));
    }
    let collected = stamp(tx, checked).await?;
    let expires = stamp(tx, checked + chrono::Duration::days(settings.cache_days)).await?;
    let evidence_id = Uuid::new_v4();
    if mismatch {
        for contact in records
            .iter()
            .filter(|c| matched.contains(&id(c, "id").unwrap_or(Uuid::nil())))
        {
            if truth(contact, "do_not_contact") {
                continue;
            }
            let mut after = contact.clone();
            after["metadata"]["identity_review_required"] = json!(true);
            after["updated_at"] = at.clone();
            update(tx, contact, &after).await?;
        }
        evidence(tx,&json!({"id":evidence_id,"company_id":company_id,"contact_id":null,"source":source,"evidence_type":"identity_conflict","evidence_url":observation["evidence_url"].as_str().or_else(||observation["linkedin_url"].as_str()),"observed_role":observation["role_title"],"observed_company":observation["company_domain"],"provider_verification_claim":observation["provider_verification_claim"],"strength":"weak","collected_at":collected,"expires_at":expires,"user_confirmed":observation["human_confirmed"],"provenance":{"requires_review":true,"contact_ids":matched,"full_name":observation["full_name"],"email":email,"receipt_id":receipt_id}})).await?;
        return receipt(tx,&receipt_key,&input_hash,json!({"contact_id":null,"created":false,"conflicts":["identity_conflict"],"requires_review":true,"evidence_id":evidence_id,"outbound_messages_sent":0})).await;
    }
    let existing = matched
        .iter()
        .next()
        .and_then(|id| records.iter().find(|r| self::id(r, "id") == Ok(*id)));
    if tombstone || existing.is_some_and(|c| truth(c, "do_not_contact")) {
        return receipt(tx,&receipt_key,&input_hash,json!({"contact_id":existing.map(|c|c["id"].clone()),"created":false,"conflicts":["suppressed"],"requires_review":false,"evidence_id":null,"outbound_messages_sent":0})).await;
    }
    let created = existing.is_none();
    let contact_id = existing
        .map(|c| id(c, "id"))
        .transpose()?
        .unwrap_or_else(Uuid::new_v4);
    let before=existing.cloned().unwrap_or_else(||json!({"id":contact_id,"company_id":company_id,"full_name":observation["full_name"],"first_name":null,"last_name":null,"role_title":observation["role_title"].as_str().unwrap_or("Unknown"),"linkedin_url":observation["linkedin_url"],"email":null,"email_status":"unknown","confidence_score":0.0,"enrichment_source":source,"last_verified_at":null,"metadata":{},"do_not_contact":false,"suppression_reason":null,"last_reviewed_at":null,"last_checked_at":null,"human_review_notes":null,"human_corrected":false,"created_at":at,"updated_at":at}));
    let mut after = before.clone();
    let mut issues = Vec::new();
    let mut email_added = false;
    let corrected = truth(&before, "human_corrected");
    if let Some(email) = email
        .as_deref()
        .filter(|_| kind == "person_specific" && observation["email_kind"] == "person_specific")
    {
        let old = before["email"].as_str().filter(|s| !s.is_empty());
        if old.is_some_and(|s| automated_apply_domain::text::folded(s) != email) {
            issues.push("conflicting_email");
        } else if !corrected && old.is_none() {
            after["email"] = json!(email);
            email_added = true;
            after["enrichment_source"] = json!(source);
            after["email_status"] = json!(match observation["email_status"].as_str() {
                Some("verified" | "provider_reported") => "provider_reported",
                Some("candidate") => "candidate",
                Some(s) => s,
                None => return Err(invalid()),
            });
        } else if !corrected
            && before["email_status"] == "candidate"
            && observation["email_status"] == "provider_reported"
        {
            after["email_status"] = json!("provider_reported");
            after["enrichment_source"] = json!(source);
            email_added = true;
        }
        if !corrected
            && after["email"] == email
            && matches!(
                observation["email_status"].as_str(),
                Some("provider_reported" | "verified")
            )
        {
            email_added = true;
            if before["email_status"] == "invalid" {
                issues.push("conflicting_email_validity");
            }
        }
    }
    let owner_identity = metadata(&before)?
        .get("identity_human_confirmed")
        .is_some_and(rules::truthy);
    let can_update_identity =
        !corrected && (!owner_identity || observation["human_confirmed"] == true);
    let previous = rules::timestamp(&before["last_checked_at"]);
    if can_update_identity {
        if observation["role_title"].as_str().is_some() && previous.is_none_or(|t| checked >= t) {
            after["role_title"] = observation["role_title"].clone();
        }
        if before["linkedin_url"].as_str().is_none()
            && observation["linkedin_url"].as_str().is_some()
        {
            after["linkedin_url"] = observation["linkedin_url"].clone();
        }
        if previous.is_none_or(|t| checked > t) {
            after["last_checked_at"] = collected.clone();
        }
    }
    if email_added {
        after["metadata"]["email_observed_at"] = json!(checked.to_rfc3339());
        after["metadata"]["email_source"] = json!(source);
    }
    if email.as_ref().is_some_and(|email| after["email"] == *email)
        && source == "official_company"
        && observation["human_confirmed"] == true
        && issues.is_empty()
    {
        if let Some(url) = observation["email_publication_url"].as_str() {
            let host = reqwest::Url::parse(url)
                .ok()
                .and_then(|u| u.host_str().map(str::to_owned));
            if host.as_deref().is_some_and(|h| {
                domain.as_deref() == Some(h)
                    || domain.as_ref().is_some_and(|d| h == format!("www.{d}"))
            }) {
                after["metadata"]["email_publication_url"] = json!(url);
                after["metadata"]["email_publication_confirmed"] = json!(true);
                after["metadata"]["email_publication_digest"] =
                    json!(hash(email.as_deref().unwrap_or("")));
            }
        }
    }
    after["metadata"]["evidence_strength"] = json!(strength);
    after["metadata"]["identity_review_required"] = json!(
        !issues.is_empty()
            || metadata(&before)?
                .get("identity_review_required")
                .is_some_and(rules::truthy)
    );
    after["updated_at"] = at;
    if created {
        let actual:Option<Value>=sqlx::query_scalar("INSERT INTO contacts SELECT x.* FROM jsonb_populate_record(NULL::contacts,$1) x RETURNING to_jsonb(contacts)").bind(&after).fetch_optional(&mut **tx).await.map_err(db)?;
        if actual.as_ref() != Some(&after) {
            return Err(ack());
        }
    } else {
        update(tx, &before, &after).await?;
    }
    for (namespace, key) in keys.iter().filter(|(ns, _)| !ns.starts_with("suppressed_")) {
        if let Some(mapping) = mappings
            .iter()
            .find(|m| m["namespace"] == *namespace && m["identity_key"] == *key)
        {
            if mapping["contact_id"] != contact_id.to_string() {
                return Err(conflict());
            }
            continue;
        }
        let map_id = Uuid::new_v4();
        let expected = json!({"id":map_id,"company_id":company_id,"contact_id":contact_id,"namespace":namespace,"identity_key":key,"discovered_person_id":observation["discovered_person_id"]});
        let actual:Option<Value>=sqlx::query_scalar("INSERT INTO contact_identities(id,company_id,contact_id,namespace,identity_key,discovered_person_id) VALUES($1,$2,$3,$4,$5,$6) ON CONFLICT DO NOTHING RETURNING to_jsonb(contact_identities)").bind(map_id).bind(company_id).bind(contact_id).bind(namespace).bind(key).bind(observation["discovered_person_id"].as_str().and_then(|s|s.parse::<Uuid>().ok())).fetch_optional(&mut **tx).await.map_err(db)?;
        if actual.as_ref() != Some(&expected) {
            return Err(ack());
        }
    }
    evidence(tx,&json!({"id":evidence_id,"company_id":company_id,"contact_id":if kind=="person_specific"{Some(contact_id)}else{None},"source":source,"evidence_type":if kind=="person_specific"{"professional_observation"}else{"company_business_inbox"},"evidence_url":observation["evidence_url"].as_str().or_else(||observation["linkedin_url"].as_str()),"observed_role":observation["role_title"],"observed_company":company["domain"],"provider_verification_claim":observation["provider_verification_claim"],"strength":strength,"collected_at":collected,"expires_at":expires,"user_confirmed":observation["human_confirmed"],"provenance":{"permission_evidence_url":observation["permission_evidence_url"],"professional_url":observation["professional_url"],"email":email,"email_kind":kind,"email_status":observation["email_status"],"conflicts":issues,"provider_person_id":observation["provider_person_id"],"discovered_person_id":observation["discovered_person_id"],"receipt_id":receipt_id}})).await?;
    receipt(tx,&receipt_key,&input_hash,json!({"contact_id":contact_id,"created":created,"conflicts":issues,"requires_review":after["metadata"]["identity_review_required"],"evidence_id":evidence_id,"outbound_messages_sent":0})).await
}
pub async fn reconcile(
    c: &mut PgConnection,
    company: Uuid,
    observation: Value,
    receipt: &str,
    settings: &super::super::Settings,
) -> Result<Value> {
    let mut tx = c.begin().await.map_err(db)?;
    sqlx::query("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
        .execute(&mut *tx)
        .await
        .map_err(db)?;
    crate::execution::lock_owner_in(&mut tx).await?;
    let result = reconcile_in(&mut tx, company, observation, receipt, settings).await?;
    tx.commit()
        .await
        .map_err(|_| Failure("contact_identity_commit_outcome_unknown"))?;
    Ok(result)
}
