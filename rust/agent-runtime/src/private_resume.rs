//! Existing private PDF bytes and primary-resource binding; no candidate facts are inferred.
use crate::{Failure, Result, context_contract, profile_store, resource_contract};
use fernet::Fernet;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use sqlx::{Connection, PgConnection, Postgres, Transaction};
use std::{
    collections::BTreeMap, os::unix::fs::MetadataExt, path::PathBuf, process::Stdio, time::Duration,
};
use subtle::ConstantTimeEq;
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use uuid::Uuid;
pub const MAX_PDF: usize = 5 * 1024 * 1024;
type StoredResume = (String, Vec<u8>, String, bool, Option<Uuid>);
pub struct Settings {
    cipher: Option<Fernet>,
    worker: PathBuf,
}
impl Settings {
    pub fn from_values(values: &BTreeMap<String, String>) -> Result<Self> {
        let cipher = values
            .get("RESUME_ENCRYPTION_KEY")
            .filter(|s| !s.trim().is_empty())
            .map(|s| Fernet::new(s).ok_or(Failure("invalid_resume_encryption_key")))
            .transpose()?;
        let worker = match values.get("RUST_DOCUMENT_WORKER") {
            Some(path) => PathBuf::from(path),
            None => std::env::current_exe()
                .map_err(|_| Failure("document_worker_unavailable"))?
                .with_file_name("automated-apply-documents"),
        };
        if !worker.is_absolute() {
            return Err(Failure("document_worker_unavailable"));
        }
        Ok(Self { cipher, worker })
    }
    fn cipher(&self) -> Result<&Fernet> {
        self.cipher
            .as_ref()
            .ok_or(Failure("resume_encryption_unavailable"))
    }
    fn encrypt(&self, raw: &[u8]) -> Result<(Vec<u8>, String)> {
        Ok((
            self.cipher()?.encrypt(raw).into_bytes(),
            format!("{:x}", Sha256::digest(raw)),
        ))
    }
    pub fn verified(&self, ciphertext: &[u8], digest: &str) -> Result<Vec<u8>> {
        if ciphertext.len() > 7 * 1024 * 1024 {
            return Err(Failure("private_pdf_integrity_failed"));
        }
        let token =
            std::str::from_utf8(ciphertext).map_err(|_| Failure("private_pdf_integrity_failed"))?;
        let raw = self
            .cipher()?
            .decrypt(token)
            .map_err(|_| Failure("private_pdf_integrity_failed"))?;
        let actual = format!("{:x}", Sha256::digest(&raw));
        if raw.len() > MAX_PDF
            || !raw.starts_with(b"%PDF-")
            || !bool::from(actual.as_bytes().ct_eq(digest.as_bytes()))
        {
            return Err(Failure("private_pdf_checksum_failed"));
        }
        Ok(raw)
    }
    pub async fn inspect(&self, raw: &[u8], extract: bool) -> Result<Value> {
        if raw.len() > MAX_PDF || !raw.starts_with(b"%PDF-") {
            return Err(Failure("invalid_pdf_upload"));
        }
        let meta = std::fs::symlink_metadata(&self.worker)
            .map_err(|_| Failure("document_worker_unavailable"))?;
        if !meta.is_file()
            || meta.uid() != unsafe { libc::geteuid() }
            || meta.mode() & 0o6022 != 0
            || meta.mode() & 0o100 == 0
        {
            return Err(Failure("document_worker_unavailable"));
        }
        let mut process = tokio::process::Command::new(&self.worker)
            .arg(if extract { "extract" } else { "validate" })
            .env_clear()
            .env("PATH", "/usr/bin:/bin")
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .kill_on_drop(true)
            .spawn()
            .map_err(|_| Failure("document_worker_unavailable"))?;
        let pid = process.id().ok_or(Failure("document_worker_unavailable"))?;
        let mut stdin = process
            .stdin
            .take()
            .ok_or(Failure("document_worker_unavailable"))?;
        let mut stdout = process
            .stdout
            .take()
            .ok_or(Failure("document_worker_unavailable"))?
            .take(200001);
        let result = {
            let work = async {
                let send = async {
                    stdin
                        .write_all(raw)
                        .await
                        .map_err(|_| Failure("invalid_or_unsafe_pdf"))?;
                    drop(stdin);
                    Ok::<_, Failure>(())
                };
                let receive = async {
                    let mut bytes = Vec::new();
                    stdout
                        .read_to_end(&mut bytes)
                        .await
                        .map_err(|_| Failure("invalid_or_unsafe_pdf"))?;
                    if bytes.len() > 200000 {
                        return Err(Failure("pdf_output_limit"));
                    }
                    Ok(bytes)
                };
                let wait = async {
                    let status = process
                        .wait()
                        .await
                        .map_err(|_| Failure("invalid_or_unsafe_pdf"))?;
                    if !status.success() {
                        return Err(Failure("invalid_or_unsafe_pdf"));
                    }
                    Ok(())
                };
                let (_, bytes, _) = tokio::try_join!(send, receive, wait)?;
                if extract {
                    let out: Value = serde_json::from_slice(&bytes)
                        .map_err(|_| Failure("invalid_pdf_extraction"))?;
                    validate_extracted(out)
                } else if bytes == b"valid" {
                    Ok(json!({"valid":true}))
                } else {
                    Err(Failure("invalid_or_unsafe_pdf"))
                }
            };
            tokio::pin!(work);
            tokio::select! {
                result=tokio::time::timeout(Duration::from_secs(10),&mut work)=>result.unwrap_or(Err(Failure("pdf_validation_timeout"))),
                error=memory_watch(pid)=>Err(error),
            }
        };
        // kill_on_drop also covers HTTP cancellation; reap explicitly after ordinary failure.
        if process.try_wait().ok().flatten().is_none() {
            let _ = process.start_kill();
            let _ = process.wait().await;
        }
        result
    }
}
async fn memory_watch(pid: u32) -> Failure {
    #[cfg(target_os = "macos")]
    loop {
        tokio::time::sleep(Duration::from_millis(100)).await;
        let output = tokio::process::Command::new("/bin/ps")
            .args(["-o", "rss=", "-p", &pid.to_string()])
            .env_clear()
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .kill_on_drop(true)
            .output()
            .await;
        match output {
            Ok(out) if out.stdout.len() < 100 => {
                if std::str::from_utf8(&out.stdout)
                    .ok()
                    .and_then(|s| s.trim().parse::<usize>().ok())
                    .is_some_and(|rss| rss > 768 * 1024)
                {
                    return Failure("pdf_memory_limit");
                }
            }
            _ => return Failure("pdf_memory_supervision_failed"),
        }
    }
    #[cfg(not(target_os = "macos"))]
    {
        let _ = pid;
        std::future::pending().await
    }
}
fn validate_extracted(value: Value) -> Result<Value> {
    let invalid = || Failure("invalid_pdf_extraction");
    let object = value
        .as_object()
        .filter(|v| v.len() == 3)
        .ok_or_else(invalid)?;
    if object
        .get("text")
        .and_then(Value::as_str)
        .is_none_or(|s| s.chars().count() > 32000)
        || object
            .get("pages")
            .and_then(Value::as_u64)
            .is_none_or(|n| !(1..=20).contains(&n))
        || object
            .get("links")
            .and_then(Value::as_array)
            .is_none_or(|v| {
                v.len() > 100
                    || v.iter().any(|s| {
                        s.as_str()
                            .is_none_or(|s| s.chars().count() > 2048 || !s.starts_with("https://"))
                    })
            })
    {
        return Err(invalid());
    }
    Ok(value)
}
fn db(_: sqlx::Error) -> Failure {
    Failure("profile_database_error")
}
pub async fn upload(
    connection: &mut PgConnection,
    label: &str,
    raw: &[u8],
    settings: &Settings,
) -> Result<Value> {
    if label.is_empty() || label.chars().count() > 200 {
        return Err(Failure("invalid_resume_label"));
    }
    settings.cipher()?;
    let extracted = settings.inspect(raw, true).await?;
    let (ciphertext, digest) = settings.encrypt(raw)?;
    let id = Uuid::new_v4();
    let mut tx = connection.begin().await.map_err(db)?;
    let actual:(Uuid,String)=sqlx::query_as("INSERT INTO private_resumes(id,label,ciphertext,sha256,confirmed,created_at,updated_at) VALUES($1,$2,$3,$4,false,clock_timestamp(),clock_timestamp()) RETURNING id,sha256").bind(id).bind(label).bind(ciphertext).bind(&digest).fetch_one(&mut *tx).await.map_err(db)?;
    if actual != (id, digest) {
        return Err(Failure("private_resume_insert_mismatch"));
    }
    let suggestions = crate::resume_suggestions::suggestions(extracted["text"].as_str().unwrap())?;
    let out = json!({"id":id,"label":label,"pages":extracted["pages"],"text":extracted["text"],"suggestions":suggestions,"origin":"extracted_from_resume","confirmed":false,"warnings":["Extracted text is untrusted evidence. Review every imported field before saving.","No external AI provider received this PDF.","Scanned PDFs may require manual entry; no OCR is performed."]});
    tx.commit().await.map_err(db)?;
    Ok(out)
}
pub async fn listing(connection: &mut PgConnection) -> Result<Value> {
    let rows:Vec<Value>=sqlx::query_scalar("SELECT to_jsonb(r) FROM (SELECT id,label,confirmed,resource_id,created_at,sha256 FROM private_resumes ORDER BY created_at DESC LIMIT 100) r").fetch_all(connection).await.map_err(db)?;
    Ok(json!({"resumes":rows}))
}
pub async fn download(
    connection: &mut PgConnection,
    id: Uuid,
    settings: &Settings,
) -> Result<Vec<u8>> {
    let row: Option<(Vec<u8>, String)> =
        sqlx::query_as("SELECT ciphertext,sha256 FROM private_resumes WHERE id=$1")
            .bind(id)
            .fetch_optional(connection)
            .await
            .map_err(db)?;
    let (ciphertext, digest) = row.ok_or(Failure("private_resume_not_found"))?;
    settings.verified(&ciphertext, &digest)
}
pub struct Confirm {
    pub primary: bool,
    pub primary_resource: Option<Uuid>,
    pub sha256: Option<String>,
    pub profile_version: Option<i32>,
}
pub fn confirmation(input: Value) -> Result<Confirm> {
    let invalid = || Failure("invalid_resume_confirmation");
    let body = input.as_object().ok_or_else(invalid)?;
    if body.keys().any(|s| {
        ![
            "owner_confirmed",
            "primary",
            "expected_primary_resource_id",
            "expected_sha256",
            "expected_profile_version",
        ]
        .contains(&s.as_str())
    }) || body.get("owner_confirmed") != Some(&json!(true))
    {
        return Err(invalid());
    }
    let primary = body
        .get("primary")
        .map(resource_contract::boolean)
        .transpose()
        .map_err(|_| invalid())?
        .unwrap_or(json!(false))
        .as_bool()
        .ok_or_else(invalid)?;
    let primary_resource = body
        .get("expected_primary_resource_id")
        .filter(|v| !v.is_null())
        .map(|v| v.as_str().and_then(|s| s.parse().ok()).ok_or_else(invalid))
        .transpose()?;
    let sha256 = body
        .get("expected_sha256")
        .filter(|v| !v.is_null())
        .map(|v| {
            v.as_str()
                .filter(|s| {
                    s.len() == 64
                        && s.bytes()
                            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
                })
                .map(String::from)
                .ok_or_else(invalid)
        })
        .transpose()?;
    let profile_version = body
        .get("expected_profile_version")
        .filter(|v| !v.is_null())
        .map(|v| {
            context_contract::integer(v.clone())
                .ok()
                .and_then(|v| v.as_i64())
                .filter(|n| *n > 0)
                .and_then(|n| i32::try_from(n).ok())
                .ok_or_else(invalid)
        })
        .transpose()?;
    Ok(Confirm {
        primary,
        primary_resource,
        sha256,
        profile_version,
    })
}
pub async fn confirm(
    connection: &mut PgConnection,
    id: Uuid,
    input: Confirm,
    settings: &Settings,
) -> Result<Value> {
    let mut tx = connection.begin().await.map_err(db)?;
    match confirm_in(&mut tx, id, input, settings).await {
        Ok(value) => {
            tx.commit().await.map_err(db)?;
            Ok(value)
        }
        Err(error) => {
            tx.rollback().await.map_err(db)?;
            Err(error)
        }
    }
}
async fn confirm_in(
    tx: &mut Transaction<'_, Postgres>,
    id: Uuid,
    input: Confirm,
    settings: &Settings,
) -> Result<Value> {
    if sqlx::query_scalar::<_, bool>(
        "SELECT EXISTS (SELECT 1 FROM drive_resume_versions WHERE private_resume_id=$1)",
    )
    .bind(id)
    .fetch_one(&mut **tx)
    .await
    .map_err(db)?
    {
        return Err(Failure("drive_resume_review_required"));
    }
    sqlx::query("SELECT id FROM candidate_profiles WHERE singleton_key='primary' FOR UPDATE")
        .execute(&mut **tx)
        .await
        .map_err(db)?;
    let profile = profile_store::get(tx).await?;
    let owner: Uuid = profile.value["id"].as_str().unwrap().parse().unwrap();
    if input.profile_version.is_some_and(|n| n != profile.version) {
        return Err(Failure("profile_version_conflict"));
    }
    let row:Option<StoredResume>=sqlx::query_as("SELECT label,ciphertext,sha256,confirmed,resource_id FROM private_resumes WHERE id=$1 FOR UPDATE").bind(id).fetch_optional(&mut **tx).await.map_err(db)?;
    let (label, ciphertext, digest, confirmed, resource) =
        row.ok_or(Failure("private_resume_not_found"))?;
    if input.sha256.is_some_and(|s| s != digest) {
        return Err(Failure("private_resume_changed"));
    }
    settings.verified(&ciphertext, &digest)?;
    let current:Vec<Uuid>=sqlx::query_scalar("SELECT id FROM candidate_resources WHERE candidate_profile_id=$1 AND resource_type='resume' AND is_primary FOR UPDATE").bind(owner).fetch_all(&mut **tx).await.map_err(db)?;
    if current.len() > 1 {
        return Err(Failure("private_resume_binding_invalid"));
    }
    let primary = current.first().copied();
    if input.primary && (primary.is_none() || primary != resource) {
        if primary != input.primary_resource {
            return Err(Failure("canonical_resume_changed"));
        }
        if let Some(primary) = primary {
            sqlx::query("UPDATE candidate_resources SET is_primary=false,updated_at=clock_timestamp() WHERE id=$1").bind(primary).execute(&mut **tx).await.map_err(db)?;
        }
        sqlx::query("UPDATE owner_preferences SET value=jsonb_build_object('invalidated_at',to_jsonb(clock_timestamp()),'reason','canonical_resume_changed'),updated_at=clock_timestamp() WHERE key='phase1_profile_confirmation'").execute(&mut **tx).await.map_err(db)?;
    }
    let resource = if confirmed {
        let resource = resource.ok_or(Failure("private_resume_binding_invalid"))?;
        let correct:bool=sqlx::query_scalar("SELECT EXISTS (SELECT 1 FROM candidate_resources WHERE id=$1 AND candidate_profile_id=$2 AND resource_type='resume' AND source_type='private_upload' AND url=$3 AND user_confirmed)").bind(resource).bind(owner).bind(format!("private-resume:{id}")).fetch_one(&mut **tx).await.map_err(db)?;
        if !correct {
            return Err(Failure("private_resume_binding_invalid"));
        }
        if input.primary {
            sqlx::query("UPDATE candidate_resources SET is_primary=true,updated_at=clock_timestamp() WHERE id=$1").bind(resource).execute(&mut **tx).await.map_err(db)?;
        }
        resource
    } else {
        if resource.is_some() {
            return Err(Failure("private_resume_binding_invalid"));
        }
        let resource = Uuid::new_v4();
        sqlx::query("INSERT INTO candidate_resources(id,candidate_profile_id,resource_type,label,url,source_type,user_confirmed,is_primary,created_at,updated_at) VALUES($1,$2,'resume',$3,$4,'private_upload',true,$5,clock_timestamp(),clock_timestamp())").bind(resource).bind(owner).bind(label).bind(format!("private-resume:{id}")).bind(input.primary).execute(&mut **tx).await.map_err(db)?;
        sqlx::query("UPDATE private_resumes SET confirmed=true,resource_id=$2,updated_at=clock_timestamp() WHERE id=$1").bind(id).bind(resource).execute(&mut **tx).await.map_err(db)?;
        resource
    };
    Ok(json!({"resource_id":resource,"confirmed":true}))
}
