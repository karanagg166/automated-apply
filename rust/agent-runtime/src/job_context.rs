//! Reviewed listing corrections and employer excerpts. No network or candidate claims.
use crate::{
    Failure, Result, answer_contract::Generate, context_contract::python_space, legacy_regex::Regex,
};
use automated_apply_domain::text::folded;
use chrono::DateTime;
use serde_json::{Value, json};
use sqlx::{Postgres, Transaction};
use std::sync::LazyLock;
use uuid::Uuid;

pub struct Reviewed {
    job: Value,
    company: Option<Value>,
}
fn invalid() -> Failure {
    Failure("invalid_job_context_record")
}
fn collapse(s: &str) -> String {
    folded(s)
        .split(python_space)
        .filter(|s| !s.is_empty())
        .collect::<Vec<_>>()
        .join(" ")
}
fn optional_string(v: &Value) -> Result<Option<&str>> {
    if v.is_null() {
        Ok(None)
    } else {
        v.as_str().map(Some).ok_or_else(invalid)
    }
}
fn metadata(job: &Value) -> Result<&Value> {
    if job["discovery_metadata"].is_null() {
        static EMPTY: LazyLock<Value> = LazyLock::new(|| json!({}));
        return Ok(&EMPTY);
    }
    if !job["discovery_metadata"].is_object() {
        return Err(invalid());
    }
    Ok(&job["discovery_metadata"])
}
fn company_id(job: &Value) -> Result<String> {
    Ok(optional_string(&job["company_id"])?
        .unwrap_or("None")
        .into())
}
fn target_url(job: &Value) -> Result<Value> {
    let application = optional_string(&job["application_url"])?;
    Ok(if application.is_some_and(|s| !s.is_empty()) {
        job["application_url"].clone()
    } else {
        job["job_url"].clone()
    })
}
impl Reviewed {
    pub fn new(mut job: Value, mut company: Option<Value>) -> Result<Self> {
        if !job.is_object()
            || job["id"]
                .as_str()
                .and_then(|s| s.parse::<Uuid>().ok())
                .is_none()
            || job["source_platform"].as_str().is_none()
        {
            return Err(invalid());
        }
        for field in [
            "company_id",
            "title",
            "description",
            "job_url",
            "application_url",
        ] {
            optional_string(&job[field])?;
        }
        if let Some(c) = &company {
            if !c.is_object() || c["name"].as_str().is_none() {
                return Err(invalid());
            }
            if job["company_id"].is_null() || c["id"] != job["company_id"] {
                return Err(invalid());
            }
            optional_string(&c["domain"])?;
        }
        let observed = metadata(&job)?.clone();
        if job["source_platform"] == "naukri" && observed["source_name"] == "naukri" {
            for field in [
                "title",
                "description",
                "location",
                "skills_required",
                "remote_type",
                "employment_type",
                "salary_min",
                "experience_level",
                "salary_max",
                "salary_currency",
                "salary_period",
                "application_url",
            ] {
                job[field] = observed[field].clone();
            }
            for field in ["title", "description", "application_url"] {
                optional_string(&job[field])?;
            }
            let name = optional_string(&observed["company_name"])?;
            let same = company.as_ref().is_some_and(|c| {
                name.is_some_and(|s| {
                    !s.is_empty() && collapse(c["name"].as_str().unwrap()) == collapse(s)
                })
            });
            if !same {
                company = name
                    .filter(|s| !s.is_empty())
                    .map(|name| json!({"id":null,"name":name,"domain":null,"metadata_":{}}));
                job["company_id"] = Value::Null;
            }
        }
        Ok(Self { job, company })
    }
    /// One fixed query on the caller's transaction, using existing owner RLS.
    pub async fn load_in(tx: &mut Transaction<'_, Postgres>, id: Uuid) -> Result<Option<Self>> {
        let row:Option<Value>=sqlx::query_scalar("SELECT jsonb_build_object('job',jsonb_build_object('id',j.id,'company_id',j.company_id,'title',j.title,'description',j.description,'job_url',j.job_url,'application_url',j.application_url,'source_platform',j.source_platform,'discovery_metadata',j.discovery_metadata),'company',CASE WHEN c.id IS NULL THEN NULL ELSE jsonb_build_object('id',c.id,'name',c.name,'domain',c.domain,'metadata_',c.metadata) END) FROM jobs j LEFT JOIN companies c ON c.id=j.company_id WHERE j.id=$1").bind(id).fetch_optional(&mut **tx).await.map_err(|_|Failure("profile_database_error"))?;
        row.map(|row| {
            Self::new(
                row["job"].clone(),
                (!row["company"].is_null()).then(|| row["company"].clone()),
            )
        })
        .transpose()
    }
    pub fn job_view(&self) -> &Value {
        &self.job
    }
    pub fn employer(&self) -> Option<&Value> {
        self.company.as_ref()
    }
    pub fn binding(&self) -> Result<String> {
        binding(&self.job, self.company.as_ref())
    }
    pub fn digest(&self) -> Result<String> {
        let c = self.company.as_ref();
        let mut context = json!({"id":self.job["id"],"title":self.job["title"],"url":target_url(&self.job)?,"description":self.job["description"],"reviewed_opportunity":metadata(&self.job)?["application_opportunity"],"company_id":company_id(&self.job)?,"company":c.map(|v|v["name"].clone()),"domain":c.map(|v|v["domain"].clone()),"metadata":c.map(|v|v["metadata_"].clone())});
        if self.job["source_platform"] == "naukri" {
            context["naukri_listing_review"] = metadata(&self.job)?.clone();
        }
        Ok(crate::python_json::digest(&context))
    }
    /// Caller-supplied company/description can never silently replace the saved listing.
    pub fn bind_request(&self, request: &Generate) -> Result<Generate> {
        if request.job_id.map(|id| id.to_string()).as_deref() != self.job["id"].as_str() {
            return Err(Failure("job_context_mismatch"));
        }
        let company = self.company.as_ref().and_then(|c| c["name"].as_str());
        if request
            .company_name
            .as_ref()
            .zip(company)
            .is_some_and(|(a, b)| {
                folded(a).trim_matches(python_space) != folded(b).trim_matches(python_space)
            })
        {
            return Err(Failure("company_context_mismatch"));
        }
        let description = optional_string(&self.job["description"])?;
        if request
            .job_description
            .as_ref()
            .zip(description.filter(|s| !s.is_empty()))
            .is_some_and(|(a, b)| a.trim_matches(python_space) != b.trim_matches(python_space))
        {
            return Err(Failure("job_context_mismatch"));
        }
        let mut request = request.clone();
        if request.company_name.is_none() {
            request.company_name = company.map(String::from);
        }
        if request.job_description.is_none() {
            request.job_description = description.map(String::from);
        }
        Ok(request)
    }
    pub fn opportunity(&self, now: f64) -> Result<Vec<Value>> {
        reviewed_opportunity(&self.job, self.company.as_ref(), now)
    }
}
pub fn binding(job: &Value, company: Option<&Value>) -> Result<String> {
    Ok(crate::python_json::digest(
        &json!({"job_id":job["id"],"title":job["title"],"url":target_url(job)?,"description":job["description"],"company_id":company_id(job)?,"company":company.map(|v|v["name"].clone()),"company_domain":company.map(|v|v["domain"].clone())}),
    ))
}
pub fn reviewed_opportunity(job: &Value, company: Option<&Value>, now: f64) -> Result<Vec<Value>> {
    if !now.is_finite() {
        return Err(Failure("invalid_context_clock"));
    }
    let saved = &metadata(job)?["application_opportunity"];
    let Some(fields) = saved.as_object() else {
        return Ok(vec![]);
    };
    if saved["binding"] != json!(binding(job, company)?) {
        return Ok(vec![]);
    }
    let mut material = fields.clone();
    material.remove("digest");
    if saved["digest"] != json!(crate::python_json::digest(&Value::Object(material))) {
        return Ok(vec![]);
    }
    let observed = saved["reviewed_at"]
        .as_str()
        .and_then(|s| DateTime::parse_from_rfc3339(s).ok());
    let Some(observed) = observed else {
        return Ok(vec![]);
    };
    let observed =
        observed.timestamp() as f64 + f64::from(observed.timestamp_subsec_micros()) / 1_000_000.0;
    if observed < now - 14.0 * 86400.0 || observed > now {
        return Ok(vec![]);
    }
    static UNSAFE: LazyLock<Regex> = LazyLock::new(|| {
        Regex::new(
            r"ignore\s+(?:all\s+)?(?:previous|prior|system)|(?:system|developer)\s*(?:prompt|message|instruction)|reveal\s+(?:secrets|credentials)|send\s+(?:secrets|cookies)|execute\s+(?:command|script)|disregard\s+instructions",
            true,
        )
    });
    let mut result = vec![];
    for (kind, text_key) in [("job", "job_text"), ("company", "company_text")] {
        if let Some(quote) = saved[text_key]
            .as_str()
            .filter(|s| !s.trim_matches(python_space).is_empty())
        {
            if UNSAFE.is_match(quote)? {
                continue;
            }
            let source_url = saved.get("source_url").ok_or_else(invalid)?;
            let source_url = if kind == "company" {
                saved.get("company_source_url").unwrap_or(source_url)
            } else {
                source_url
            };
            result.push(json!({"reference":{"source_type":format!("opportunity_{kind}"),"source_id":format!("{}:{kind}",saved["digest"].as_str().ok_or_else(invalid)?)},"facts":quote,"source_url":source_url,"reviewed_at":saved["reviewed_at"],"verification":"owner_reviewed_page_excerpt"}));
        }
    }
    Ok(result)
}
/// Only the reviewed quote and opaque source identifier belong in a model prompt.
pub fn prompt_opportunity(facts: &[Value]) -> Vec<Value> {
    facts
        .iter()
        .map(|f| json!({"reference":f["reference"],"facts":f["facts"]}))
        .collect()
}
