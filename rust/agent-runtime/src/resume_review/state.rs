use super::*;
use crate::{configuration::boolean, packet_record};
use std::collections::BTreeMap;
pub struct Settings {
    pub(crate) source: Option<(String, String)>,
    pub(crate) enabled: bool,
    pub(crate) interval: i32,
}
impl Settings {
    pub fn from_values(values: &BTreeMap<String, String>) -> Result<Self> {
        let source = values
            .get("CANDIDATE_RESUME_DRIVE_URL")
            .filter(|s| !s.is_empty())
            .map(|url| {
                canonical_source(
                    url,
                    values
                        .get("CANDIDATE_RESUME_DRIVE_FILE_ID")
                        .filter(|s| !s.is_empty())
                        .map(String::as_str),
                )
            })
            .transpose()?;
        let interval = values
            .get("RESUME_DRIVE_SYNC_INTERVAL_HOURS")
            .map(String::as_str)
            .unwrap_or("24")
            .parse::<i32>()
            .ok()
            .filter(|n| (1..=168).contains(n))
            .ok_or(Failure("invalid_resume_sync_interval"))?;
        Ok(Self {
            source,
            enabled: boolean(values, "RESUME_DRIVE_SYNC_ENABLED", false)?,
            interval,
        })
    }
}
pub(crate) fn time(raw: &Value) -> Result<Value> {
    if raw.is_null() {
        Ok(Value::Null)
    } else {
        packet_record::timestamp(raw, true).map_err(|_| Failure("invalid_resume_review_record"))
    }
}
pub(crate) async fn source(c: &mut PgConnection, locked: bool) -> Result<Option<Value>> {
    sqlx::query_scalar(if locked {
        "SELECT to_jsonb(s) FROM resume_drive_sources s WHERE key='primary' FOR UPDATE"
    } else {
        "SELECT to_jsonb(s) FROM resume_drive_sources s WHERE key='primary'"
    })
    .fetch_optional(c)
    .await
    .map_err(db)
}
pub(crate) async fn version(c: &mut PgConnection, id: Uuid) -> Result<Value> {
    let row: Option<(Value,Option<Value>)> = sqlx::query_as("SELECT to_jsonb(v),CASE WHEN r.id IS NULL THEN NULL ELSE jsonb_build_object('status',r.status,'review_cycle',r.review_cycle,'base_profile_version',r.base_profile_version,'approved_profile_version',r.approved_profile_version) END FROM drive_resume_versions v LEFT JOIN resume_profile_reviews r ON r.version_id=v.id WHERE v.id=$1").bind(id).fetch_optional(c).await.map_err(db)?;
    let (raw, review) = row.ok_or(Failure("resume_review_not_found"))?;
    version_read(&raw, review.as_ref())
}
fn version_read(raw: &Value, review: Option<&Value>) -> Result<Value> {
    let review = review.ok_or(Failure("resume_review_incomplete"))?;
    let mut value = json!({});
    for key in [
        "id",
        "file_id",
        "canonical_url",
        "file_name",
        "sha256",
        "private_resume_id",
    ] {
        value[key] = raw
            .get(key)
            .filter(|v| v.is_string())
            .cloned()
            .ok_or(Failure("invalid_resume_review_record"))?;
    }
    for key in ["id", "private_resume_id"] {
        value[key] = json!(
            value[key]
                .as_str()
                .ok_or(Failure("invalid_resume_review_record"))?
                .parse::<Uuid>()
                .map_err(|_| Failure("invalid_resume_review_record"))?
        );
    }
    for key in ["source_modified_at", "downloaded_at"] {
        value[key] = time(&raw[key])?;
    }
    for key in ["source_etag", "drive_revision"] {
        value[key] = raw[key].clone();
    }
    if !matches!(review["status"].as_str(), Some("pending" | "approved"))
        || review["review_cycle"].as_i64().is_none_or(|n| n < 1)
    {
        return Err(Failure("invalid_resume_review_record"));
    }
    value["review_status"] = review["status"].clone();
    value["review_cycle"] = review["review_cycle"].clone();
    value["candidate_profile_version"] = review["base_profile_version"].clone();
    value["approved_profile_version"] = review["approved_profile_version"].clone();
    Ok(value)
}
pub(crate) async fn status_in(c: &mut PgConnection, settings: &Settings) -> Result<Value> {
    let source = source(c, false).await?;
    let raw = source.as_ref().cloned().unwrap_or(json!({}));
    let pointer = |key: &str| -> Result<Option<Uuid>> {
        raw.get(key)
            .filter(|v| !v.is_null())
            .map(|v| {
                v.as_str()
                    .ok_or(Failure("invalid_resume_review_record"))?
                    .parse()
                    .map_err(|_| Failure("invalid_resume_review_record"))
            })
            .transpose()
    };
    let latest_id = pointer("latest_version_id")?;
    let active_id = pointer("active_version_id")?;
    // One metadata-only batch includes the50-row page and older active/latest pointers.
    // Never convert review ciphertext to JSON or load it just to project status fields.
    let rows:Vec<(Value,Option<Value>)>=sqlx::query_as("SELECT to_jsonb(v),CASE WHEN r.id IS NULL THEN NULL ELSE jsonb_build_object('status',r.status,'review_cycle',r.review_cycle,'base_profile_version',r.base_profile_version,'approved_profile_version',r.approved_profile_version) END FROM drive_resume_versions v LEFT JOIN resume_profile_reviews r ON r.version_id=v.id WHERE v.id=$1 OR v.id=$2 OR v.id IN(SELECT id FROM drive_resume_versions ORDER BY downloaded_at DESC,id LIMIT 50) ORDER BY v.downloaded_at DESC,v.id").bind(latest_id).bind(active_id).fetch_all(c).await.map_err(db)?;
    let all = rows
        .iter()
        .map(|(raw, review)| version_read(raw, review.as_ref()))
        .collect::<Result<Vec<_>>>()?;
    let find = |id: Option<Uuid>| -> Result<Value> {
        match id {
            None => Ok(Value::Null),
            Some(id) => all
                .iter()
                .find(|row| row["id"] == json!(id))
                .cloned()
                .ok_or(Failure("invalid_resume_review_record")),
        }
    };
    let latest = find(latest_id)?;
    let active = find(active_id)?;
    let versions = all.iter().take(50).cloned().collect::<Vec<_>>();
    let mut output = json!({"source":"Google Drive","canonical_url":settings.source.as_ref().map(|(_,url)|url),"file_id":settings.source.as_ref().map(|(id,_)|id),"generation":1,"sync_enabled":settings.enabled,"interval_hours":settings.interval,"requires_review":true,"connected":false,"status":"not_checked","latest":latest,"active":active,"history":versions,"pending_changes":!latest.is_null() && (active.is_null() || latest["id"]!=active["id"]),"scheduler_active":false,"scheduler_message":"Automatic Drive downloads are unavailable. Upload the PDF manually; saved resume reviews remain available.","metadata_note":"Public downloads expose Last-Modified/ETag only when provided. Drive revision metadata may be unavailable; checks always verify PDF SHA-256.","download_available":false});
    for key in [
        "file_name",
        "last_downloaded_at",
        "source_modified_at",
        "source_etag",
        "drive_revision",
        "last_error",
        "last_checked_at",
        "last_changed_at",
    ] {
        output[key] = raw[key].clone();
    }
    if source.is_some() {
        for key in [
            "canonical_url",
            "file_id",
            "generation",
            "sync_enabled",
            "interval_hours",
            "status",
        ] {
            output[key] = raw[key].clone();
        }
        output["connected"] = json!(
            !latest.is_null() && !matches!(raw["status"].as_str(), Some("not_checked" | "failed"))
        );
    }
    for key in [
        "last_downloaded_at",
        "source_modified_at",
        "last_checked_at",
        "last_changed_at",
    ] {
        output[key] = time(&output[key])?;
    }
    if output["generation"].as_i64().is_none_or(|n| n < 1)
        || output["interval_hours"]
            .as_i64()
            .is_none_or(|n| !(1..=168).contains(&n))
        || !output["sync_enabled"].is_boolean()
    {
        return Err(Failure("invalid_resume_review_record"));
    }
    Ok(output)
}
pub async fn status(c: &mut PgConnection, settings: &Settings) -> Result<Value> {
    let mut tx = c.begin().await.map_err(db)?;
    sqlx::query("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        .execute(&mut *tx)
        .await
        .map_err(db)?;
    let result = status_in(&mut tx, settings).await?;
    tx.commit().await.map_err(db)?;
    Ok(result)
}
pub async fn save_source(
    c: &mut PgConnection,
    input: SourceInput,
    settings: &Settings,
) -> Result<Value> {
    if input.enabled {
        return Err(Failure("drive_oauth_deferred_use_manual_pdf_upload"));
    }
    let mut tx = c.begin().await.map_err(db)?;
    let result = async {
    sqlx::query("INSERT INTO resume_drive_sources(key,file_id,canonical_url,generation,sync_enabled,interval_hours,status,created_at,updated_at) VALUES('primary',$1,$2,1,$3,$4,'not_checked',clock_timestamp(),clock_timestamp()) ON CONFLICT(key) DO NOTHING").bind(&input.file_id).bind(&input.canonical_url).bind(settings.enabled).bind(settings.interval).execute(&mut *tx).await.map_err(db)?;
    let mut current = source(&mut tx, true)
        .await?
        .ok_or(Failure("resume_source_write_ack_failed"))?;
    if current["generation"] != input.expected {
        return Err(Failure("resume_source_generation_conflict"));
    }
    if current["file_id"] != input.file_id {
        for key in [
            "latest_version_id",
            "last_error",
            "last_checked_at",
            "last_changed_at",
            "file_name",
            "last_downloaded_at",
            "source_modified_at",
            "source_etag",
            "drive_revision",
        ] {
            current[key] = Value::Null;
        }
        current["status"] = json!("not_checked");
    }
    current["file_id"] = json!(input.file_id);
    current["canonical_url"] = json!(input.canonical_url);
    current["generation"] = json!(input.expected.checked_add(1).ok_or_else(invalid)?);
    current["sync_enabled"] = json!(false);
    current["interval_hours"] = json!(input.interval);
    let saved:Option<Value>=sqlx::query_scalar("UPDATE resume_drive_sources SET file_id=$1::jsonb->>'file_id',canonical_url=$1::jsonb->>'canonical_url',generation=($1::jsonb->>'generation')::integer,sync_enabled=false,interval_hours=($1::jsonb->>'interval_hours')::integer,status=$1::jsonb->>'status',latest_version_id=($1::jsonb->>'latest_version_id')::uuid,last_error=$1::jsonb->>'last_error',last_checked_at=($1::jsonb->>'last_checked_at')::timestamptz,last_changed_at=($1::jsonb->>'last_changed_at')::timestamptz,file_name=$1::jsonb->>'file_name',last_downloaded_at=($1::jsonb->>'last_downloaded_at')::timestamptz,source_modified_at=($1::jsonb->>'source_modified_at')::timestamptz,source_etag=$1::jsonb->>'source_etag',drive_revision=$1::jsonb->>'drive_revision',updated_at=clock_timestamp() WHERE key='primary' AND generation=$2 RETURNING to_jsonb(resume_drive_sources)").bind(&current).bind(input.expected).fetch_optional(&mut *tx).await.map_err(db)?;
    let mut expected = current;
    let mut saved = saved.ok_or(Failure("resume_source_write_ack_failed"))?;
    for value in [&mut expected, &mut saved] {
        value
            .as_object_mut()
            .ok_or(Failure("invalid_resume_review_record"))?
            .remove("updated_at");
    }
    if saved != expected {
        return Err(Failure("resume_source_write_ack_failed"));
    }
    let result = status_in(&mut tx, settings).await?;
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
