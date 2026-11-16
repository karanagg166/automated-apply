//! Approved project evidence loaded from one read snapshot; no scanning or approval side effects.
use crate::{
    Failure, Result,
    context_contract::{self, Kind, python_space},
    legacy_regex::Regex,
};
use automated_apply_domain::text::folded;
use serde_json::{Map, Value, json};
use sqlx::{Connection, PgConnection, Postgres, Transaction};
use std::{collections::HashSet, sync::LazyLock};

pub struct Snapshot {
    configuration: Value,
    knowledge: Vec<(Value, Value)>,
}
fn invalid() -> Failure {
    Failure("invalid_project_context_record")
}
fn named(s: &str) -> String {
    folded(s)
        .chars()
        .filter(|c| c.is_ascii_lowercase() || c.is_ascii_digit())
        .collect()
}
fn truth(v: &Value) -> bool {
    match v {
        Value::Null => false,
        Value::Bool(b) => *b,
        Value::Number(n) => n.as_f64() != Some(0.0),
        Value::String(s) => !s.is_empty(),
        Value::Array(a) => !a.is_empty(),
        Value::Object(o) => !o.is_empty(),
    }
}
fn key(project: &Value) -> Result<String> {
    let id = project["id"].as_str().ok_or_else(invalid)?;
    Ok(format!(
        "{}{}",
        if project["name"].as_str().is_some_and(|s| !s.is_empty())
            && project["repository_url"].is_null()
        {
            "document_"
        } else {
            "candidate_"
        },
        id
    ))
}
fn config(records: &Map<String, Value>) -> Result<Value> {
    context_contract::normalize(
        Kind::Configuration,
        records
            .get("candidate_configuration_v1")
            .filter(|v| truth(v))
            .cloned()
            .unwrap_or(json!({})),
    )
}
impl Snapshot {
    pub fn from_records(records: &Map<String, Value>) -> Result<Self> {
        let configuration = config(records)?;
        let mut knowledge = Vec::new();
        for project in configuration["configuration"]["projects"]
            .as_array()
            .ok_or_else(invalid)?
        {
            let value = records
                .get(&key(project)?)
                .filter(|v| truth(v))
                .cloned()
                .unwrap_or(json!({}));
            knowledge.push((
                project.clone(),
                context_contract::normalize(Kind::Knowledge, value)?,
            ));
        }
        Ok(Self {
            configuration,
            knowledge,
        })
    }
    /// Uses existing caller credentials and forced RLS; opens no additional connection or schema.
    pub async fn load(connection: &mut PgConnection) -> Result<Self> {
        let db = |_| Failure("profile_database_error");
        let mut tx = connection.begin().await.map_err(db)?;
        sqlx::query("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            .execute(&mut *tx)
            .await
            .map_err(db)?;
        let snapshot = Self::load_in(&mut tx).await?;
        tx.commit().await.map_err(db)?;
        Ok(snapshot)
    }
    /// Generation can bind profile/job/evidence in its own repeatable-read transaction.
    pub async fn load_in(tx: &mut Transaction<'_, Postgres>) -> Result<Self> {
        let db = |_| Failure("profile_database_error");
        let isolation: String =
            sqlx::query_scalar("SELECT current_setting('transaction_isolation')")
                .fetch_one(&mut **tx)
                .await
                .map_err(db)?;
        if !matches!(isolation.as_str(), "repeatable read" | "serializable") {
            return Err(Failure("project_context_snapshot_required"));
        }
        let value: Option<Value> = sqlx::query_scalar(
            "SELECT value FROM owner_preferences WHERE key='candidate_configuration_v1'",
        )
        .fetch_optional(&mut **tx)
        .await
        .map_err(db)?;
        let mut records = Map::new();
        if let Some(value) = value {
            records.insert("candidate_configuration_v1".into(), value);
        }
        let configuration = config(&records)?;
        let keys = configuration["configuration"]["projects"]
            .as_array()
            .ok_or_else(invalid)?
            .iter()
            .map(key)
            .collect::<Result<Vec<_>>>()?;
        let rows: Vec<(String, Value)> =
            sqlx::query_as("SELECT key,value FROM owner_preferences WHERE key=ANY($1)")
                .bind(keys)
                .fetch_all(&mut **tx)
                .await
                .map_err(db)?;
        records.extend(rows);
        Self::from_records(&records)
    }
    /// Bind the complete local evidence state, including URL/hash metadata kept out of prompts.
    pub fn digest(&self) -> String {
        crate::python_json::digest(
            &json!({"configuration":self.configuration,"knowledge":self.knowledge}),
        )
    }
    /// Legacy browser plans bind the metadata of all current approved projects.
    pub(crate) fn browser_digest(&self) -> Result<String> {
        let mut projects = Vec::new();
        for (project, knowledge) in &self.knowledge {
            let candidate = &knowledge["candidate"];
            let approved = &knowledge["approved"];
            if candidate.is_null()
                || approved.is_null()
                || candidate["revision"] != approved["revision"]
                || project != &candidate["configuration"]
            {
                continue;
            }
            if approved["project_id"] != project["id"] {
                return Err(invalid());
            }
            projects.push(json!({"project_id":approved["project_id"],"name":project["name"],"revision":approved["revision"],"priority":project["priority"],"commit_sha":approved["commit_sha"],"fact_ids":approved["fact_ids"]}));
        }
        Ok(crate::python_json::digest(&json!(projects)))
    }
    /// Provider projection carries only approved narrative text and opaque citations.
    /// Full provenance remains in the local snapshot digest and saved draft evidence.
    pub fn prompt_evidence(&self, question: &str, category: &str) -> Result<Vec<Value>> {
        Ok(self
            .answer_evidence(question, category)?
            .into_iter()
            .map(|e| {
                json!({
                    "reference":e["reference"],
                    "facts":{"name":e["facts"]["name"],"contribution":e["facts"]["contribution"]}
                })
            })
            .collect())
    }
    pub fn answer_evidence(&self, question: &str, category: &str) -> Result<Vec<Value>> {
        if question.chars().count() > 2000 {
            return Err(Failure("project_context_limit"));
        }
        if !matches!(category, "project_explanation" | "technical_experience") {
            return Ok(vec![]);
        }
        let normalized = named(question);
        let names: HashSet<_> = self
            .knowledge
            .iter()
            .filter(|(p, _)| {
                p["name"]
                    .as_str()
                    .is_some_and(|s| !s.is_empty() && normalized.contains(&named(s)))
            })
            .map(|(p, _)| p["id"].clone())
            .collect();
        let mut result = Vec::new();
        for (project, knowledge) in &self.knowledge {
            let candidate = &knowledge["candidate"];
            let approval = &knowledge["approved"];
            if candidate.is_null()
                || approval.is_null()
                || candidate["revision"] != approval["revision"]
                || project != &candidate["configuration"]
            {
                continue;
            }
            // A stored record may never redirect another project's approval into this context.
            if approval["project_id"] != project["id"] {
                return Err(invalid());
            }
            if !names.is_empty() && !names.contains(&approval["project_id"]) {
                continue;
            }
            let personal = approval["facts"]
                .as_array()
                .ok_or_else(invalid)?
                .iter()
                .filter(|f| f["personal_claim"] == true)
                .filter_map(|f| match approvable(f) {
                    Ok(true) => Some(Ok(f)),
                    Ok(false) => None,
                    Err(e) => Some(Err(e)),
                })
                .collect::<Result<Vec<_>>>()?;
            let topic = |topic: &str| personal.iter().any(|f| f["topic"] == topic);
            if !topic("contribution") {
                continue;
            }
            let text = personal
                .iter()
                .map(|f| f["text"].as_str().ok_or_else(invalid))
                .collect::<Result<Vec<_>>>()?
                .join(" ");
            static CHALLENGE: LazyLock<Regex> =
                LazyLock::new(|| Regex::new(r"\b(?:challeng\w*|bug|failure)\b", true));
            static DECISION: LazyLock<Regex> =
                LazyLock::new(|| Regex::new(r"\b(?:decision|tradeoff|trade-off)\b", true));
            static API: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"\bAPIs?\b", true));
            if CHALLENGE.is_match(question)? && !topic("challenge")
                || DECISION.is_match(question)? && !topic("design_decision")
                || API.is_match(question)? && !topic("api")
            {
                continue;
            }
            static SKILLS: LazyLock<Vec<(&str, Regex)>> = LazyLock::new(|| {
                vec![
                    ("PostgreSQL", Regex::new(r"\bPostgreSQL\b", true)),
                    ("Redis", Regex::new(r"\bRedis\b", true)),
                    ("MongoDB", Regex::new(r"\bMongoDB\b", true)),
                    ("FastAPI", Regex::new(r"\bFastAPI\b", true)),
                    ("Python", Regex::new(r"\bPython\b", true)),
                    ("React", Regex::new(r"\bReact\b", true)),
                ]
            });
            let mut unsupported = false;
            for (skill, pattern) in SKILLS.iter() {
                if pattern.is_match(question)? && !folded(&text).contains(&folded(skill)) {
                    unsupported = true;
                    break;
                }
            }
            if unsupported {
                continue;
            }
            let score = question
                .split(python_space)
                .filter(|s| !s.is_empty())
                .filter(|s| folded(&text).contains(&folded(s)))
                .count()
                + 2;
            result.push(json!({"reference":{"source_type":"project_context","source_id":format!("{}:{}",approval["project_id"].as_str().ok_or_else(invalid)?,approval["revision"].as_str().ok_or_else(invalid)?)},"facts":{"name":project["name"],"contribution":text,"fact_ids":personal.iter().map(|f|f["id"].clone()).collect::<Vec<_>>(),"commit_sha":approval["commit_sha"],"revision":approval["revision"],"evidence":personal.iter().flat_map(|f|f["evidence"].as_array().unwrap().iter().cloned()).collect::<Vec<_>>()},"score":score,"priority":project["priority"]}));
        }
        result.sort_by(|a, b| {
            b["score"]
                .as_u64()
                .cmp(&a["score"].as_u64())
                .then_with(|| a["priority"].as_u64().cmp(&b["priority"].as_u64()))
        });
        result.truncate(6);
        Ok(result)
    }
}
pub fn approvable(fact: &Value) -> Result<bool> {
    static SUSPICIOUS: LazyLock<Regex> = LazyLock::new(|| {
        Regex::new(
            r"(?s)ignore.{0,60}(?:instruction|prompt)|system\s+(?:prompt|message)|(?:run|execute)\s+(?:shell|command|sql)|(?:reveal|print|export).{0,30}(?:token|password|secret)|(?:sk-[A-Za-z0-9_-]{12,}|sbp_[A-Za-z0-9_-]{12,}|\d{6,}:[A-Za-z0-9_-]{20,})",
            true,
        )
    });
    Ok(!fact["evidence"].as_array().ok_or_else(invalid)?.is_empty()
        && fact["verification"] != "inferred"
        && (fact["personal_claim"] != true || fact["verification"] == "owner_supplied")
        && !SUSPICIOUS.is_match(fact["text"].as_str().ok_or_else(invalid)?)?)
}
