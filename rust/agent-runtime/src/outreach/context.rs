//! Current reviewed facts from one bounded snapshot. No mail, browser, DNS or provider IO.
use super::*;
use crate::contacts::rules;
use automated_apply_domain::text::folded;
use sqlx::{Postgres, Transaction};
#[derive(Clone)]
pub struct Context {
    pub(super) profile: Value,
    pub(super) contact: Value,
    pub(super) company: Value,
    pub(super) job: Option<Value>,
    pub(super) facts: Vec<Value>,
    pub(super) links: Vec<String>,
    pub(super) blockers: Vec<&'static str>,
    pub(super) warnings: Vec<&'static str>,
    pub(super) snapshot: Value,
}
fn snapshot_bound(rows: &[Value]) -> Result<()> {
    if rows.len() > 10000
        || rows
            .iter()
            .any(|v| !v.is_object() || v.to_string().len() > 1048576)
        || rows.iter().map(|v| v.to_string().len()).sum::<usize>() > 8 * 1024 * 1024
    {
        return Err(Failure("outreach_context_inventory_limit"));
    }
    Ok(())
}
async fn inventory(
    tx: &mut Transaction<'_, Postgres>,
    table: &str,
    profile: Uuid,
    lock: bool,
) -> Result<Vec<Value>> {
    // Only internal constant table names can reach this helper.
    if !matches!(table, "candidate_evidence" | "candidate_resources") {
        return Err(invalid());
    }
    let rows:Vec<Option<Value>>=sqlx::query_scalar(&format!("SELECT CASE WHEN octet_length(to_jsonb(r)::text)<=1048576 THEN to_jsonb(r) ELSE NULL END FROM {table} r WHERE candidate_profile_id=$1 ORDER BY id LIMIT 10001{}",if lock{" FOR SHARE"}else{""})).bind(profile).fetch_all(&mut **tx).await.map_err(db)?;
    let rows = rows
        .into_iter()
        .map(|v| v.ok_or_else(invalid))
        .collect::<Result<Vec<_>>>()?;
    snapshot_bound(&rows)?;
    Ok(rows)
}
fn fresh_past(value: &Value, days: i64, now: DateTime<Utc>) -> bool {
    rules::timestamp(value).is_some_and(|at| at <= now && rules::fresh(value, days, now))
}
fn public_link(value: &Value) -> Option<String> {
    let link = value.as_str()?;
    if link.chars().any(char::is_control) {
        return None;
    }
    crate::resources::public_https(link)
}
impl Context {
    pub fn digest(&self) -> String {
        fingerprint(&self.snapshot)
    }
    pub fn summary(&self) -> Value {
        json!({"context_hash":self.digest(),"missing_information":self.blockers,"warnings":self.warnings,"fact_count":self.facts.len(),"public_link_count":self.links.len(),"requires_review":true,"sending_enabled":false})
    }
    pub async fn load(
        c: &mut PgConnection,
        input: Value,
        settings: &crate::contacts::Settings,
    ) -> Result<Self> {
        let input = contract::normalize(contract::Kind::Input, input)?;
        let mut tx = c.begin().await.map_err(db)?;
        sqlx::query("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            .execute(&mut *tx)
            .await
            .map_err(db)?;
        let context = Self::load_in(&mut tx, &input, settings, false).await?;
        tx.commit().await.map_err(db)?;
        Ok(context)
    }
    pub(super) async fn load_in(
        tx: &mut Transaction<'_, Postgres>,
        input: &Value,
        settings: &crate::contacts::Settings,
        lock: bool,
    ) -> Result<Self> {
        let isolation: String =
            sqlx::query_scalar("SELECT current_setting('transaction_isolation')")
                .fetch_one(&mut **tx)
                .await
                .map_err(db)?;
        if !matches!(isolation.as_str(), "repeatable read" | "serializable") {
            return Err(Failure("outreach_context_snapshot_required"));
        }
        if lock && isolation != "serializable" {
            return Err(Failure("outreach_context_snapshot_required"));
        }
        let id = input["contact_id"]
            .as_str()
            .and_then(|s| s.parse::<Uuid>().ok())
            .ok_or(Failure("invalid_outreach_contract"))?;
        let company_id: Uuid = sqlx::query_scalar("SELECT company_id FROM contacts WHERE id=$1")
            .bind(id)
            .fetch_optional(&mut **tx)
            .await
            .map_err(db)?
            .ok_or(Failure("outreach_contact_not_found"))?;
        let company:Option<Value>=sqlx::query_scalar(&format!("SELECT CASE WHEN octet_length(to_jsonb(c)::text)<=1048576 THEN to_jsonb(c) ELSE NULL END FROM companies c WHERE id=$1{}",if lock{" FOR SHARE"}else{""})).bind(company_id).fetch_optional(&mut **tx).await.map_err(db)?.ok_or(Failure("outreach_contact_employer_missing"))?;
        let company = company.ok_or_else(invalid)?;
        let contact:Option<Value>=sqlx::query_scalar(&format!("SELECT CASE WHEN octet_length(to_jsonb(c)::text)<=1048576 THEN jsonb_set(to_jsonb(c),'{{metadata_}}',coalesce(c.metadata::jsonb,'{{}}'::jsonb)) ELSE NULL END FROM contacts c WHERE id=$1{}",if lock{" FOR SHARE"}else{""})).bind(id).fetch_optional(&mut **tx).await.map_err(db)?.ok_or(Failure("outreach_contact_not_found"))?;
        let contact = contact.ok_or_else(invalid)?;
        if contact["company_id"] != json!(company_id) {
            return Err(Failure("outreach_context_changed"));
        }
        let job = if let Some(id) = input["job_id"].as_str() {
            let id = id.parse::<Uuid>().map_err(|_| invalid())?;
            let found: Option<Uuid> = sqlx::query_scalar(&format!(
                "SELECT id FROM jobs WHERE id=$1{}",
                if lock { " FOR SHARE" } else { "" }
            ))
            .bind(id)
            .fetch_optional(&mut **tx)
            .await
            .map_err(db)?;
            if found.is_none() {
                return Err(Failure("outreach_job_employer_mismatch"));
            }
            let reviewed = crate::job_context::Reviewed::load_in(tx, id)
                .await?
                .ok_or(Failure("outreach_job_employer_mismatch"))?;
            if reviewed.job_view()["company_id"] != json!(company_id) {
                return Err(Failure("outreach_job_employer_mismatch"));
            }
            Some((reviewed.job_view().clone(), reviewed.digest()?))
        } else {
            None
        };
        if lock {
            sqlx::query(
                "SELECT id FROM candidate_profiles WHERE singleton_key='primary' FOR SHARE",
            )
            .execute(&mut **tx)
            .await
            .map_err(db)?;
        }
        let profile = match crate::profile_store::get(tx).await {
            Ok(p) => p.value,
            Err(e) if e.0 == "profile_not_found" => Value::Null,
            Err(e) => return Err(e),
        };
        let profile_id = profile["id"].as_str().and_then(|s| s.parse::<Uuid>().ok());
        let confirmation:Option<Value>=sqlx::query_scalar(&format!("SELECT CASE WHEN octet_length(value::text)<=32768 THEN value ELSE NULL END FROM owner_preferences WHERE key='phase1_profile_confirmation'{}",if lock{" FOR SHARE"}else{""})).fetch_optional(&mut **tx).await.map_err(db)?.flatten();
        let confirmation = confirmation.unwrap_or(Value::Null);
        let evidence = if let Some(id) = profile_id {
            inventory(tx, "candidate_evidence", id, lock).await?
        } else {
            vec![]
        };
        let resources = if let Some(id) = profile_id {
            inventory(tx, "candidate_resources", id, lock).await?
        } else {
            vec![]
        };
        let contact_evidence:Vec<Option<Value>>=sqlx::query_scalar(&format!("SELECT CASE WHEN octet_length(to_jsonb(e)::text)<=1048576 THEN to_jsonb(e) ELSE NULL END FROM contact_evidence e WHERE contact_id=$1 ORDER BY id LIMIT 10001{}",if lock{" FOR SHARE"}else{""})).bind(id).fetch_all(&mut **tx).await.map_err(db)?;
        let contact_evidence = contact_evidence
            .into_iter()
            .map(|v| v.ok_or_else(invalid))
            .collect::<Result<Vec<_>>>()?;
        snapshot_bound(&contact_evidence)?;
        if lock {
            let keys:Vec<String>=sqlx::query_scalar("SELECT key FROM owner_preferences WHERE key='candidate_configuration_v1' OR starts_with(key,'candidate_') OR starts_with(key,'document_') ORDER BY key LIMIT 10001 FOR SHARE").fetch_all(&mut **tx).await.map_err(db)?;
            if keys.len() > 10000 {
                return Err(Failure("outreach_context_inventory_limit"));
            }
        }
        let projects = crate::project_context::Snapshot::load_in(tx).await?;
        let now: Value = sqlx::query_scalar("SELECT to_jsonb(clock_timestamp())")
            .fetch_one(&mut **tx)
            .await
            .map_err(db)?;
        let now = DateTime::parse_from_rfc3339(now.as_str().ok_or_else(invalid)?)
            .map_err(|_| invalid())?
            .to_utc();
        let query = format!(
            "{} {} {}",
            job.as_ref()
                .and_then(|(j, _)| j["title"].as_str())
                .unwrap_or(""),
            job.as_ref()
                .and_then(|(j, _)| j["description"].as_str())
                .unwrap_or(""),
            contact["role_title"].as_str().unwrap_or("")
        )
        .chars()
        .take(2000)
        .collect::<String>();
        let mut facts = if profile_id.is_some() {
            projects.answer_evidence(&query, "project_explanation")?
        } else {
            vec![]
        };
        if facts.is_empty() {
            if let Some(id) = profile_id {
                let selected = crate::answer_context::relevant_evidence(tx, id, &query).await?;
                facts = crate::evidence_retrieval::retrieve(
                    &profile,
                    &selected,
                    &query,
                    "project_explanation",
                )?
                .into_iter()
                .map(|f| serde_json::to_value(f).map_err(|_| invalid()))
                .collect::<Result<Vec<_>>>()?;
            }
        }
        let mut blockers = vec![];
        let mut warnings = vec![];
        if profile_id.is_none() {
            blockers.push("candidate_profile_required");
        } else if confirmation["profile_id"] != profile["id"]
            || confirmation["profile_version"] != profile["version"]
            || !fresh_past(&confirmation["confirmed_at"], 365000, now)
        {
            blockers.push("current_confirmed_profile_required");
        }
        if contact["do_not_contact"] != false {
            blockers.push("contact_suppressed");
        }
        if rules::truthy(&contact["metadata_"]["identity_review_required"]) {
            blockers.push("identity_conflict");
        }
        let role = contact["role_title"].as_str().ok_or_else(invalid)?;
        let name = company["name"].as_str().ok_or_else(invalid)?;
        let domain = company["domain"].as_str().unwrap_or("");
        let current = contact_evidence
            .iter()
            .filter(|e| {
                e["company_id"] == json!(company_id)
                    && fresh_past(&e["collected_at"], 365000, now)
                    && rules::timestamp(&e["expires_at"]).is_some_and(|at| at > now)
            })
            .collect::<Vec<_>>();
        if !current.iter().any(|e| {
            e["observed_role"]
                .as_str()
                .is_some_and(|r| folded(&line(r)) == folded(&line(role)))
                && e["observed_company"].as_str().is_some_and(|c| {
                    folded(c) == folded(name) || !domain.is_empty() && folded(c) == folded(domain)
                })
        }) {
            blockers.push("current_employer_evidence_required");
        }
        if !fresh_past(&contact["last_checked_at"], settings.cache_days, now) {
            blockers.push("contact_evidence_expired");
        }
        let email = contact["email"]
            .as_str()
            .and_then(|s| crate::profile_contract::email(s).ok());
        if email
            .as_deref()
            .and_then(|s| rules::business_email(s, domain))
            .is_none()
        {
            blockers.push("business_email_required");
        } else if email
            .as_deref()
            .is_some_and(|s| rules::email_kind(s) != "person_specific")
        {
            blockers.push("person_specific_business_email_required");
        }
        if !matches!(
            contact["email_status"].as_str(),
            Some("verified" | "provider_reported")
        ) {
            blockers.push("unreliable_or_speculative_recipient");
        }
        if !fresh_past(
            &rules::email_observed_at(&contact),
            settings.cache_days,
            now,
        ) {
            blockers.push("email_evidence_expired");
        }
        if contact["email_status"] == "provider_reported" {
            warnings.push("provider_reported_email_is_not_verified");
        }
        if facts.is_empty() {
            blockers.push("verified_project_contribution_required");
        }
        let mut links = Vec::new();
        for key in ["github_url", "linkedin_url", "portfolio_url"] {
            if let Some(link) = public_link(&profile[key]) {
                if !links.contains(&link) {
                    links.push(link);
                }
            }
        }
        let primary = resources
            .iter()
            .filter(|r| {
                r["resource_type"] == "resume"
                    && r["is_primary"] == true
                    && r["user_confirmed"] == true
            })
            .collect::<Vec<_>>();
        if primary.len() > 1 {
            blockers.push("primary_public_resume_ambiguous");
        } else if let Some(link) = primary.first().and_then(|r| public_link(&r["url"])) {
            if !links.contains(&link) {
                links.push(link);
            }
        }
        let snapshot = json!({"schema":"native_outreach_context_v1","profile":profile,"profile_confirmation":confirmation,"facts":facts,"candidate_evidence":evidence,"candidate_resources":resources,"links":links,"contact":contact,"contact_evidence":contact_evidence,"company":company,"job":job.as_ref().map(|(j,_)|j),"job_digest":job.as_ref().map(|(_,d)|d),"project_context_digest":projects.digest()});
        if snapshot.to_string().len() > 16 * 1024 * 1024 {
            return Err(Failure("outreach_context_inventory_limit"));
        }
        Ok(Self {
            profile,
            contact,
            company,
            job: job.map(|(j, _)| j),
            facts,
            links,
            blockers,
            warnings,
            snapshot,
        })
    }
    /// Deterministic composition from already selected facts. Optional rewriting is a separate intent.
    pub fn preview(&self, input: Value) -> Result<Value> {
        let input = contract::normalize(contract::Kind::Input, input)?;
        if input["contact_id"] != self.contact["id"]
            || input["job_id"]
                != self
                    .job
                    .as_ref()
                    .map(|j| j["id"].clone())
                    .unwrap_or(Value::Null)
        {
            return Err(Failure("outreach_context_changed"));
        }
        let mut result = json!({"status":"needs_input","subject":null,"body":null,"requires_review":true,"evidence_references":[],"missing_information":self.blockers,"unsupported_claim_flags":[],"warnings":self.warnings,"provider_metadata":{"used_llm":false},"outbound_messages_sent":0,"sending_enabled":false});
        if !self.blockers.is_empty() {
            return Ok(result);
        }
        result["context_hash"] = json!(self.digest());
        let fact = self.facts.first().ok_or_else(invalid)?;
        let project = fact["facts"].get("project").unwrap_or(&fact["facts"]);
        let contribution = project["contribution"]
            .as_str()
            .filter(|s| !s.is_empty())
            .ok_or_else(invalid)?;
        let candidate = line(self.profile["full_name"].as_str().ok_or_else(invalid)?);
        let company = line(self.company["name"].as_str().ok_or_else(invalid)?);
        let contact = line(self.contact["full_name"].as_str().ok_or_else(invalid)?);
        if [&candidate, &company, &contact]
            .iter()
            .any(|s| s.is_empty())
        {
            return Err(invalid());
        }
        let style = input["writing_style"].as_str().ok_or_else(invalid)?;
        let greeting = if style == "friendly" { "Hi" } else { "Hello" };
        let title = self
            .job
            .as_ref()
            .and_then(|j| j["title"].as_str())
            .map(line);
        let target = if let Some(title) = &title {
            format!("I'm reaching out about the saved {title} listing at {company}.")
        } else {
            format!("I'm exploring potential engineering opportunities at {company}.")
        };
        let cta = match style {
            "concise" => "Would a brief conversation about fit be useful?",
            "friendly" => "Would you be open to a short chat about a possible fit?",
            "technical" => {
                "Would you be open to discussing where this engineering experience could be useful?"
            }
            "founder-focused" => {
                "Would a brief discussion about contributing to your engineering team be useful?"
            }
            _ => "Would you be open to a brief discussion about a potential fit?",
        };
        let mut project_line = format!(
            "In {}: {contribution}",
            line(project["name"].as_str().unwrap_or("my saved project"))
        );
        let project_text = folded(&project.to_string());
        if let Some(job) = &self.job {
            let description = folded(job["description"].as_str().unwrap_or(""));
            let matched = self.profile["verified_skills"]
                .as_array()
                .ok_or_else(invalid)?
                .iter()
                .filter_map(Value::as_str)
                .filter(|s| description.contains(&folded(s)) && project_text.contains(&folded(s)))
                .take(4)
                .collect::<Vec<_>>();
            if !matched.is_empty() {
                project_line.push_str(&format!(
                    " The saved listing mentions {}.",
                    matched.join(", ")
                ));
            }
        }
        let mut parts = vec![
            format!("{greeting} {contact},"),
            format!("I'm {candidate}. {target}"),
            project_line,
            cta.to_owned(),
            candidate.clone(),
        ];
        parts.extend(self.links.clone());
        let body = parts.join("\n\n");
        if body.chars().count() > input["max_length"].as_u64().ok_or_else(invalid)? as usize {
            result["missing_information"] =
                json!(["Increase max_length or shorten the verified contribution"]);
            return Ok(result);
        }
        let subject = line(&format!(
            "{} — {candidate}",
            title.as_deref().unwrap_or("Engineering opportunities")
        ))
        .chars()
        .take(255)
        .collect::<String>();
        let mut references = vec![
            fact["reference"].clone(),
            json!({"source_type":"candidate_profile","source_id":self.profile["id"]}),
            json!({"source_type":"company","source_id":self.company["id"]}),
            json!({"source_type":"contact","source_id":self.contact["id"]}),
        ];
        for e in self.snapshot["contact_evidence"]
            .as_array()
            .ok_or_else(invalid)?
            .iter()
            .take(100)
        {
            references.push(json!({"source_type":"contact_evidence","source_id":e["id"]}));
        }
        if let Some(job) = &self.job {
            references.push(json!({"source_type":"job","source_id":job["id"]}));
        }
        if input["personal_instructions"]
            .as_str()
            .is_some_and(|s| !s.is_empty())
        {
            result["warnings"].as_array_mut().unwrap().push(json!("Personal instructions are untrusted guidance; apply any additional factual changes through review"));
        }
        result["status"] = json!("draft_ready");
        result["subject"] = json!(subject);
        result["body"] = json!(body);
        result["evidence_references"] = json!(references);
        Ok(result)
    }
}
