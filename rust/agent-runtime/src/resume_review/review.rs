use super::*;
use crate::{private_resume, profile_contract, profile_store};
use sqlx::Row;
fn text<'a>(raw: &'a Value, key: &str) -> Result<&'a str> {
    raw[key]
        .as_str()
        .ok_or(Failure("invalid_resume_review_record"))
}
fn id(raw: &Value, key: &str) -> Result<Uuid> {
    text(raw, key)?
        .parse()
        .map_err(|_| Failure("invalid_resume_review_record"))
}
async fn review(c: &mut PgConnection, version: Uuid) -> Result<(Value, Value, Vec<u8>)> {
    let version: Option<Value> =
        sqlx::query_scalar("SELECT to_jsonb(v) FROM drive_resume_versions v WHERE id=$1")
            .bind(version)
            .fetch_optional(&mut *c)
            .await
            .map_err(db)?;
    let version = version.ok_or(Failure("resume_review_not_found"))?;
    let row=sqlx::query("SELECT jsonb_build_object('id',id,'status',status,'review_cycle',review_cycle,'base_profile_version',base_profile_version,'approved_profile_version',approved_profile_version,'approved_at',approved_at) AS metadata,review_ciphertext FROM resume_profile_reviews r WHERE version_id=$1").bind(id(&version,"id")?).fetch_optional(c).await.map_err(db)?.ok_or(Failure("resume_review_not_found"))?;
    Ok((version, row.get("metadata"), row.get("review_ciphertext")))
}
fn career(raw: &Value) -> Value {
    let mut raw = raw.clone();
    if let Some(object) = raw.as_object_mut() {
        for key in ["id", "singleton_key", "version", "created_at", "updated_at"] {
            object.remove(key);
        }
    }
    raw
}
fn facts(payload: &Value) -> Result<()> {
    if !payload["facts"].is_object()
        || !payload["facts"]["sections"].is_object()
        || !payload["facts"]["suggestions"].is_object()
        || payload["facts"]["text"]
            .as_str()
            .is_none_or(|s| s.chars().count() > 32000)
        || payload["facts"]["suggestions"]["verified_skills"]
            .as_array()
            .is_none_or(|values| values.iter().any(|s| !s.is_string()))
    {
        return Err(Failure("private_resume_review_invalid"));
    }
    Ok(())
}
pub async fn changes(
    c: &mut PgConnection,
    version_id: Uuid,
    crypto: &private_resume::Settings,
) -> Result<Value> {
    let mut tx = c.begin().await.map_err(db)?;
    sqlx::query("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        .execute(&mut *tx)
        .await
        .map_err(db)?;
    let source = state::source(&mut tx, false)
        .await?
        .ok_or(Failure("resume_source_not_found"))?;
    let (version, _, ciphertext) = review(&mut tx, version_id).await?;
    let payload = private_resume::decrypt_review(crypto, &ciphertext)?;
    facts(&payload)?;
    let profile = match profile_store::get(&mut tx).await {
        Ok(profile) => Some(profile),
        Err(Failure("profile_not_found")) => None,
        Err(error) => return Err(error),
    };
    let current = profile
        .as_ref()
        .map(|profile| career(&profile.value))
        .unwrap_or(Value::Null);
    let mut proposed = if current.is_null() {
        payload["facts"]["suggestions"].clone()
    } else {
        current.clone()
    };
    let mut skills = proposed["verified_skills"]
        .as_array()
        .cloned()
        .unwrap_or_default();
    for skill in payload["facts"]["suggestions"]["verified_skills"]
        .as_array()
        .ok_or(Failure("private_resume_review_invalid"))?
    {
        if !skills.contains(skill) {
            skills.push(skill.clone());
        }
    }
    proposed["verified_skills"] = json!(skills);
    let proposed = profile_contract::normalize(profile_contract::Operation::Create, proposed)
        .unwrap_or(Value::Null);
    let verified_skills = profile
        .as_ref()
        .map(|p| p.value["verified_skills"].clone())
        .unwrap_or(json!([]));
    let mut differences = differences(
        &payload["previous_facts"],
        &payload["facts"],
        &verified_skills,
        &current,
    )?;
    let (mut packets, mut answers) = (0i64, 0i64);
    if let Some(profile) = &profile {
        let owner = id(&profile.value, "id")?;
        packets = sqlx::query_scalar(
            "SELECT count(*) FROM application_packets WHERE candidate_profile_id=$1",
        )
        .bind(owner)
        .fetch_one(&mut *tx)
        .await
        .map_err(db)?;
        answers = sqlx::query_scalar(
            "SELECT count(*) FROM application_answer_drafts WHERE candidate_profile_id=$1",
        )
        .bind(owner)
        .fetch_one(&mut *tx)
        .await
        .map_err(db)?;
        let evidence:Vec<Value>=sqlx::query_scalar("SELECT jsonb_build_object('evidence_type',evidence_type,'title',title,'content',content) FROM candidate_evidence WHERE candidate_profile_id=$1 AND user_confirmed ORDER BY updated_at DESC,id LIMIT 100").bind(owner).fetch_all(&mut *tx).await.map_err(db)?;
        for item in evidence {
            let category = match text(&item, "evidence_type")? {
                "project" => "projects",
                "experience" => "work_experience",
                "achievement" => "achievements",
                _ => "other_claims",
            };
            let line = format!(
                "{}: {}",
                text(&item, "title")?,
                text(&item, "content")?
                    .chars()
                    .take(1000)
                    .collect::<String>()
            );
            let diff = differences
                .as_array_mut()
                .ok_or(Failure("invalid_resume_review_record"))?
                .iter_mut()
                .find(|diff| diff["category"] == category)
                .ok_or(Failure("invalid_resume_review_record"))?;
            diff["current_verified"]
                .as_array_mut()
                .ok_or(Failure("invalid_resume_review_record"))?
                .push(json!(line));
        }
    }
    let warnings = [
        "Section differences are verbatim unverified evidence, not inferred structured facts. Review the source PDF and every date, employer, institution, project, link and claim.",
        "Omitted skills do not remove human-confirmed skills. Explicit removal requires a separate confirmation.",
        "Existing facts and evidence remain unchanged until approval. The editable profile is the exact set of facts you approve.",
        "No PDF or source text was sent to an AI service. Scanned PDFs require manual fact entry.",
        "Approval flags prior answers and packets as stale; approved packet contents and outreach history remain intact.",
    ];
    let output = json!({"version":state::version(&mut tx,id(&version,"id")?).await?,"expected_generation":source["generation"],"expected_profile_version":profile.as_ref().map(|p|p.version),"current_profile":current,"proposed_profile":proposed,"suggested_identity":payload["facts"]["suggestions"],"differences":differences,"text":payload["facts"]["text"],"stale_packet_count":packets,"stale_answer_count":answers,"warnings":warnings});
    tx.commit().await.map_err(db)?;
    Ok(output)
}
pub async fn approve(
    c: &mut PgConnection,
    version_id: Uuid,
    input: Approval,
    settings: &Settings,
    crypto: &private_resume::Settings,
    live: bool,
) -> Result<Value> {
    let mut tx = c.begin().await.map_err(db)?;
    let result = async {
    let source = state::source(&mut tx, true)
        .await?
        .ok_or(Failure("resume_source_not_found"))?;
    if source["generation"] != input.expected {
        return Err(Failure("resume_source_generation_conflict"));
    }
    if source["latest_version_id"] != json!(version_id) {
        return Err(Failure("resume_latest_version_required"));
    }
    let (version, review, ciphertext) = review(&mut tx, version_id).await?;
    sqlx::query("SELECT id FROM candidate_profiles WHERE singleton_key='primary' FOR UPDATE")
        .execute(&mut *tx)
        .await
        .map_err(db)?;
    if source["active_version_id"] == json!(version_id) && review["status"] == "approved" {
        let result = state::status_in(&mut tx, settings).await?;
        return Ok(result);
    }
    let current = match profile_store::get(&mut tx).await {
        Ok(profile) => Some(profile),
        Err(Failure("profile_not_found")) => None,
        Err(error) => return Err(error),
    };
    if current.as_ref().map(|profile| profile.version) != input.expected_profile {
        return Err(Failure("profile_version_conflict"));
    }
    if let Some(current) = &current
        && !input.allow_removals
    {
        let skills = input.profile["verified_skills"]
            .as_array()
            .ok_or_else(invalid)?
            .iter()
            .map(|v| {
                v.as_str()
                    .map(automated_apply_domain::text::folded)
                    .ok_or_else(invalid)
            })
            .collect::<Result<std::collections::BTreeSet<_>>>()?;
        if current.value["verified_skills"]
            .as_array()
            .ok_or(Failure("invalid_profile_record"))?
            .iter()
            .any(|skill| {
                skill
                    .as_str()
                    .is_none_or(|s| !skills.contains(&automated_apply_domain::text::folded(s)))
            })
        {
            return Err(Failure("resume_skill_removal_confirmation_required"));
        }
    }
    let mut payload = private_resume::decrypt_review(crypto, &ciphertext)?;
    facts(&payload)?;
    let private_id = id(&version, "private_resume_id")?;
    let private = sqlx::query(
        "SELECT ciphertext,sha256,resource_id FROM private_resumes WHERE id=$1 FOR UPDATE",
    )
    .bind(private_id)
    .fetch_optional(&mut *tx)
    .await
    .map_err(db)?
    .ok_or(Failure("private_resume_not_found"))?;
    let digest: String = private.get("sha256");
    if version["sha256"] != digest
        || input
            .expected_sha256
            .as_ref()
            .is_some_and(|expected| expected != &digest)
    {
        return Err(Failure("private_resume_changed"));
    }
    crypto.verified(private.get::<Vec<u8>, _>("ciphertext").as_slice(), &digest)?;
    let profile = profile_store::activate_resume_in(
        &mut tx,
        input.profile.clone(),
        input.expected_profile,
        version_id,
        live,
    )
    .await?;
    let owner = id(&profile.value, "id")?;
    let old_primary:Vec<Uuid>=sqlx::query_scalar("SELECT id FROM candidate_resources WHERE candidate_profile_id=$1 AND resource_type='resume' AND is_primary FOR UPDATE").bind(owner).fetch_all(&mut *tx).await.map_err(db)?;
    if old_primary.len() > 1
        || input
            .expected_primary
            .is_some_and(|id| old_primary.first() != Some(&id))
    {
        return Err(Failure("canonical_resume_changed"));
    }
    let existing: Option<Uuid> = private.get("resource_id");
    let resource = if let Some(resource) = existing {
        let correct:bool=sqlx::query_scalar("SELECT EXISTS(SELECT 1 FROM candidate_resources WHERE id=$1 AND candidate_profile_id=$2 AND resource_type='resume' AND source_type='private_upload' AND url=$3)").bind(resource).bind(owner).bind(format!("private-resume:{private_id}")).fetch_one(&mut *tx).await.map_err(db)?;
        if !correct {
            return Err(Failure("private_resume_binding_invalid"));
        }
        resource
    } else {
        Uuid::new_v4()
    };
    sqlx::query("UPDATE candidate_resources SET is_primary=false,updated_at=clock_timestamp() WHERE candidate_profile_id=$1 AND resource_type='resume' AND is_primary AND id<>$2").bind(owner).bind(resource).execute(&mut *tx).await.map_err(db)?;
    let saved: Option<Uuid> = if existing.is_some() {
        sqlx::query_scalar("UPDATE candidate_resources SET is_primary=true,user_confirmed=true,updated_at=clock_timestamp() WHERE id=$1 AND candidate_profile_id=$2 RETURNING id").bind(resource).bind(owner).fetch_optional(&mut *tx).await.map_err(db)?
    } else {
        sqlx::query_scalar("INSERT INTO candidate_resources(id,candidate_profile_id,resource_type,label,url,source_type,user_confirmed,is_primary,created_at,updated_at) VALUES($1,$2,'resume',$3,$4,'private_upload',true,true,clock_timestamp(),clock_timestamp()) RETURNING id").bind(resource).bind(owner).bind(text(&version,"file_name")?).bind(format!("private-resume:{private_id}")).fetch_optional(&mut *tx).await.map_err(db)?
    };
    if saved != Some(resource) {
        return Err(Failure("resume_review_write_ack_failed"));
    }
    let binding:Option<Value>=sqlx::query_scalar("SELECT jsonb_build_object('id',id,'candidate_profile_id',candidate_profile_id,'resource_type',resource_type,'source_type',source_type,'url',url,'user_confirmed',user_confirmed,'is_primary',is_primary) FROM candidate_resources WHERE id=$1").bind(resource).fetch_optional(&mut *tx).await.map_err(db)?;
    if binding!=Some(json!({"id":resource,"candidate_profile_id":owner,"resource_type":"resume","source_type":"private_upload","url":format!("private-resume:{private_id}"),"user_confirmed":true,"is_primary":true})) {return Err(Failure("resume_review_write_ack_failed"))}
    let primaries:Vec<Uuid>=sqlx::query_scalar("SELECT id FROM candidate_resources WHERE candidate_profile_id=$1 AND resource_type='resume' AND is_primary").bind(owner).fetch_all(&mut *tx).await.map_err(db)?;
    if primaries!=vec![resource]{return Err(Failure("resume_review_write_ack_failed"))}
    let updated:Option<(bool,Option<Uuid>)>=sqlx::query_as("UPDATE private_resumes SET confirmed=true,resource_id=$2,updated_at=clock_timestamp() WHERE id=$1 RETURNING confirmed,resource_id").bind(private_id).bind(resource).fetch_optional(&mut *tx).await.map_err(db)?;
    if updated!=Some((true,Some(resource))){return Err(Failure("resume_review_write_ack_failed"))}
    for item in &input.evidence {
        let mut item = item.clone();
        item["source_url"] = version["canonical_url"].clone();
        item["source_description"] =
            json!(format!("Owner-reviewed Drive resume {}", &digest[..12]));
        let evidence_id = Uuid::new_v4();
        let saved:Option<Value>=sqlx::query_scalar("INSERT INTO candidate_evidence(id,candidate_profile_id,evidence_type,title,content,source_url,source_description,user_confirmed,project,created_at,updated_at) VALUES($1,$2,$3::jsonb->>'evidence_type',$3::jsonb->>'title',$3::jsonb->>'content',$3::jsonb->>'source_url',$3::jsonb->>'source_description',true,NULLIF($3::jsonb->'project','null'::jsonb),clock_timestamp(),clock_timestamp()) RETURNING to_jsonb(candidate_evidence)-ARRAY['id','candidate_profile_id','created_at','updated_at']").bind(evidence_id).bind(owner).bind(&item).fetch_optional(&mut *tx).await.map_err(db)?;
        if saved.as_ref() != Some(&item) {
            return Err(Failure("resume_review_write_ack_failed"));
        }
    }
    payload["approved_profile"] = input.profile;
    payload["approved_evidence"] = json!(input.evidence);
    let encrypted = private_resume::encrypt_review(crypto, &payload)?;
    let review_id = id(&review, "id")?;
    let saved:Option<(String,Option<i32>,Vec<u8>,bool)>=sqlx::query_as("UPDATE resume_profile_reviews SET review_ciphertext=$2,status='approved',approved_at=clock_timestamp(),approved_profile_version=$3,updated_at=clock_timestamp() WHERE id=$1 RETURNING status,approved_profile_version,review_ciphertext,approved_at IS NOT NULL").bind(review_id).bind(&encrypted).bind(profile.version).fetch_optional(&mut *tx).await.map_err(db)?;
    if saved!=Some(("approved".into(),Some(profile.version),encrypted,true)){return Err(Failure("resume_review_write_ack_failed"))}
    let saved:Option<Value>=sqlx::query_scalar("UPDATE resume_drive_sources SET active_version_id=$1,status='approved',updated_at=clock_timestamp() WHERE key='primary' AND generation=$2 RETURNING to_jsonb(resume_drive_sources)").bind(version_id).bind(input.expected).fetch_optional(&mut *tx).await.map_err(db)?;
    let mut expected=source.clone();expected["active_version_id"]=json!(version_id);expected["status"]=json!("approved");
    let mut saved=saved.ok_or(Failure("resume_review_write_ack_failed"))?;
    for value in [&mut expected,&mut saved]{value.as_object_mut().ok_or(Failure("invalid_resume_review_record"))?.remove("updated_at");}
    if expected!=saved{return Err(Failure("resume_review_write_ack_failed"))}
    let result = state::status_in(&mut tx, settings).await?;
    Ok(result)
    }.await;
    match result {
        Ok(result) => {
            tx.commit()
                .await
                .map_err(|_| Failure("resume_review_commit_outcome_unknown"))?;
            Ok(result)
        }
        Err(error) => {
            tx.rollback()
                .await
                .map_err(|_| Failure("resume_review_rollback_unconfirmed"))?;
            Err(error)
        }
    }
}
