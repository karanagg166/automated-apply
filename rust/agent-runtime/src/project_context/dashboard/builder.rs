//! Prepare pending project candidates from explicitly configured local sources.
mod repository;
mod template;

use super::{
    CONFIGURATION_KEY, approval::contexts, configuration_record, db, key, lock_record,
    next_revision, save, stored_error, timestamp,
};
use crate::{
    Failure, Result,
    configuration::Configuration,
    context_contract::{Kind, normalize},
    execution,
    python_json::digest,
    recovery, server,
};
use serde::Deserialize;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use sqlx::{Connection, PgConnection};
use std::{
    collections::BTreeMap,
    path::{Component, Path, PathBuf},
    time::Duration,
};

const FILE_LIMIT: usize = 128 * 1024;
const STALE: Failure = Failure("configuration_changed_reload");
const PENDING: &str = "pending_review";

pub(crate) struct Settings {
    template_root: Option<PathBuf>,
    checkouts: BTreeMap<String, PathBuf>,
}

impl Settings {
    pub(crate) fn from_values(values: &BTreeMap<String, String>) -> Result<Self> {
        let invalid = Failure("invalid_project_source_configuration");
        let absolute = |path: &Path| {
            path.is_absolute()
                && path.as_os_str().len() <= 4096
                && !path.as_os_str().as_encoded_bytes().contains(&0)
                && path
                    .components()
                    .any(|part| matches!(part, Component::Normal(_)))
                && path
                    .components()
                    .all(|part| !matches!(part, Component::ParentDir))
        };
        let template_root = values
            .get("CANDIDATE_CONTEXT_ROOT")
            .filter(|root| !root.is_empty())
            .map(PathBuf::from);
        let checkouts: BTreeMap<String, PathBuf> = match values.get("CANDIDATE_PROJECT_CHECKOUTS") {
            Some(encoded) if !encoded.trim().is_empty() && encoded.len() <= 131_072 => {
                serde_json::from_str(encoded).map_err(|_| invalid)?
            }
            None => BTreeMap::new(),
            Some(encoded) if encoded.trim().is_empty() => BTreeMap::new(),
            Some(_) => return Err(invalid),
        };
        if template_root.as_ref().is_some_and(|root| !absolute(root))
            || checkouts.len() > 30
            || checkouts
                .iter()
                .any(|(url, root)| !repository::valid_url(url) || !absolute(root))
        {
            return Err(invalid);
        }
        Ok(Self {
            template_root,
            checkouts,
        })
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct Input {
    expected_configuration_revision: u64,
}

impl Input {
    pub(crate) fn parse(body: &[u8], query: Option<&str>) -> Result<Self> {
        let invalid = Failure("invalid_project_context_request");
        if query.is_some() {
            return Err(invalid);
        }
        serde_json::from_slice(body).map_err(|_| invalid)
    }
}

struct Intent {
    configuration: Value,
    project: Value,
    key: String,
    previous: Option<Value>,
}

async fn intent(connection: &mut PgConnection, id: &str, input: Input) -> Result<Intent> {
    let mut tx = connection.begin().await.map_err(db)?;
    sqlx::query("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        .execute(&mut *tx)
        .await
        .map_err(db)?;
    let stored = sqlx::query_scalar("SELECT value FROM owner_preferences WHERE key=$1")
        .bind(CONFIGURATION_KEY)
        .fetch_optional(&mut *tx)
        .await
        .map_err(db)?;
    let configuration = configuration_record(stored)?;
    if configuration["revision"].as_u64() != Some(input.expected_configuration_revision) {
        return Err(STALE);
    }
    let project = configuration["configuration"]["projects"]
        .as_array()
        .ok_or_else(super::invalid)?
        .iter()
        .find(|project| project["id"] == id)
        .cloned()
        .ok_or(Failure("project_not_found"))?;
    let key = key(&project)?;
    let previous = sqlx::query_scalar("SELECT value FROM owner_preferences WHERE key=$1")
        .bind(&key)
        .fetch_optional(&mut *tx)
        .await
        .map_err(db)?;
    tx.commit().await.map_err(db)?;
    Ok(Intent {
        configuration,
        project,
        key,
        previous,
    })
}

fn owner_facts(candidate: &Value) -> impl Iterator<Item = &Value> {
    candidate["facts"]
        .as_array()
        .into_iter()
        .flatten()
        .filter(|fact| fact["verification"] == "owner_supplied")
}

async fn persist(connection: &mut PgConnection, intent: Intent, candidate: Value) -> Result<Value> {
    let mut tx = connection.begin().await.map_err(db)?;
    let result = async {
        execution::lock_owner_in(&mut tx).await?;
        let config = lock_record(&mut tx, CONFIGURATION_KEY).await?;
        if configuration_record(config)? != intent.configuration {
            return Err(STALE);
        }
        let stored = lock_record(&mut tx, &intent.key).await?;
        if stored != intent.previous {
            return Err(Failure("project_changed_rebuild_and_review"));
        }
        let mut knowledge = normalize(
            Kind::Knowledge,
            stored
                .clone()
                .filter(super::super::truth)
                .unwrap_or(json!({})),
        )?;
        let current = &knowledge["candidate"];
        let unchanged = !current.is_null()
            && current["source_hash"] == candidate["source_hash"]
            && current["configuration"] == candidate["configuration"]
            && owner_facts(current).eq(owner_facts(&candidate));
        if unchanged && knowledge["last_checked_commit"] == candidate["commit_sha"] {
            return Ok(json!({"status":"unchanged","project":knowledge}));
        }
        if !unchanged {
            let now = timestamp(&mut tx).await?;
            let event = json!({"kind":"project_context_built","before_hash":digest(current),
                "after_hash":digest(&candidate),"actor_ref":"static_extractor","created_at":now});
            let audits = knowledge["audits"]
                .as_array_mut()
                .ok_or_else(super::invalid)?;
            if audits.len() >= 100 {
                return Err(Failure("project_audit_archive_required"));
            }
            audits.push(event);
            knowledge["built_at"] = json!(now);
        }
        knowledge["revision"] = json!(next_revision(&knowledge)?);
        knowledge["last_checked_commit"] = candidate["commit_sha"].clone();
        if !unchanged {
            knowledge["candidate"] = candidate;
        }
        save(&mut tx, &intent.key, stored.as_ref(), &knowledge).await?;
        Ok(json!({"status":if unchanged { "unchanged" } else { PENDING },"project":knowledge}))
    }
    .await;
    match result {
        Ok(value) => {
            tx.commit()
                .await
                .map_err(|_| Failure("dashboard_commit_outcome_unknown"))?;
            Ok(value)
        }
        Err(error) => {
            tx.rollback().await.map_err(db)?;
            Err(error)
        }
    }
}

pub(crate) async fn execute(config: &Configuration, id: &str, input: Input) -> Result<Value> {
    let mut reader = config.connect(false).await?;
    let selection = recovery::bounded(Duration::from_secs(12), async {
        server::readiness(&mut reader, config).await?;
        intent(&mut reader, id, input).await
    })
    .await;
    recovery::close(reader).await;
    let selection = selection.map_err(stored_error)?;
    if selection.project["name"].as_str().is_none_or(str::is_empty) {
        return Err(Failure("project_name_and_repository_required"));
    }
    let candidate = tokio::time::timeout(
        Duration::from_secs(30),
        candidate(&config.project_sources, &selection.project),
    )
    .await
    .map_err(|_| Failure("repository_read_timeout"))??;
    let mut writer = config.connect(false).await?;
    let result = tokio::time::timeout(Duration::from_secs(12), async {
        server::readiness(&mut writer, config).await?;
        persist(&mut writer, selection, candidate).await
    })
    .await
    .unwrap_or(Err(Failure("dashboard_commit_outcome_unknown")));
    recovery::close(writer).await;
    result.map_err(stored_error)
}

fn sha256(text: &str) -> String {
    format!("{:x}", Sha256::digest(text.as_bytes()))
}

fn evidence(
    path: &str,
    commit: Option<&str>,
    hash: &str,
    start: usize,
    end: usize,
    url: Option<&str>,
) -> Value {
    json!({"file":path,"commit_sha":commit,"content_sha256":hash,
        "line_start":start,"line_end":end,"url":url})
}

fn fact(
    topic: &str,
    text: &str,
    verification: &str,
    evidence: &[Value],
    technology: Option<&str>,
    personal: bool,
) -> Value {
    let mut value = json!({"topic":topic,"text":text,"verification":verification,"evidence":evidence,
        "technology":technology,"personal_claim":personal});
    value["id"] = json!(digest(&value));
    value
}

struct Evidence {
    commit: Option<String>,
    source_hash: String,
    facts: Vec<Value>,
    unsupported: Vec<String>,
    revision: String,
}

async fn candidate(settings: &Settings, project: &Value) -> Result<Value> {
    let owner = project["context_file"]
        .as_str()
        .filter(|path| !path.is_empty());
    let owner = match owner {
        Some(path) => {
            let root = settings
                .template_root
                .clone()
                .ok_or(Failure("project_template_root_required"))?;
            let path = path.to_owned();
            let name = project["name"]
                .as_str()
                .ok_or_else(super::invalid)?
                .to_owned();
            tokio::task::spawn_blocking(move || template::facts(&root, &path, &name))
                .await
                .map_err(|_| Failure("context_file_unreadable"))??
        }
        None => vec![],
    };
    let Evidence {
        commit,
        source_hash,
        facts,
        unsupported,
        revision,
    } = match project["repository_url"].as_str() {
        Some(url) => repository::build(settings, project, url, owner).await?,
        None if !owner.is_empty() => {
            let source_hash = digest(&json!(owner));
            let revision = digest(&json!({"configuration":project,"source_hash":source_hash}));
            Evidence {
                commit: None,
                source_hash,
                facts: owner,
                unsupported: vec![],
                revision,
            }
        }
        None => return Err(Failure("project_name_and_repository_required")),
    };
    let summaries = contexts(&facts.iter().collect::<Vec<_>>());
    let value = json!({"configuration":project,"commit_sha":commit,"source_hash":source_hash,
        "revision":revision,"facts":facts,"unsupported_stack_claims":unsupported,
        "candidate_contexts":summaries,"last_verified_version":commit,"status":PENDING});
    let normalized = normalize(Kind::Knowledge, json!({"candidate":value}))
        .map_err(|_| Failure("invalid_project_source_evidence"))?;
    Ok(normalized["candidate"].clone())
}
