//! Local owner maintenance for an obsolete fixed Chrome pin. No provider IO.
use super::*;
use crate::{browser_inventory::Browser, configuration::Configuration};
use serde::Deserialize;
use std::{
    fs::{File, symlink_metadata},
    io::Read,
    os::unix::fs::{MetadataExt, OpenOptionsExt},
    path::{Path, PathBuf},
};

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Review {
    pub old_binding: Uuid,
    pub new_binding: Uuid,
    pub selection_version: i64,
    pub old_profile_version: i64,
    pub new_profile_version: i64,
    pub browser_session_id: Uuid,
    pub window_id: i64,
    pub account_revision: i64,
    pub candidate_profile_version: i32,
    pub account_sha256: String,
    pub resume_sha256: String,
    pub evidence_sha256: String,
    pub observed_at: DateTime<Utc>,
    pub profile_directory: PathBuf,
    pub owner_confirmed: bool,
}

pub async fn run(config: &Path, review: &Path, apply: bool) -> Result<()> {
    let config = Configuration::load(config)?;
    if config.browser != Browser::Brave || !config.browser_profiles.native_enabled {
        return Err(Failure("brave_native_runtime_required"));
    }
    let review = read_review(review)?;
    let mut connection = config.connect(false).await?;
    let result = replace(&mut connection, &review, apply).await?;
    println!("{result}");
    Ok(())
}

fn read_review(path: &Path) -> Result<Review> {
    let error = Failure("private_brave_pin_review_required");
    if !path.is_absolute() {
        return Err(error);
    }
    let file = File::options()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK | libc::O_CLOEXEC)
        .open(path)
        .map_err(|_| error)?;
    let info = file.metadata().map_err(|_| error)?;
    // SAFETY: geteuid takes no arguments and has no preconditions.
    let user = unsafe { libc::geteuid() };
    if !info.is_file() || info.uid() != user || info.mode() & 0o077 != 0 {
        return Err(error);
    }
    let mut bytes = Vec::new();
    file.take(8193).read_to_end(&mut bytes).map_err(|_| error)?;
    if bytes.len() > 8192 {
        return Err(error);
    }
    let review: Review = serde_json::from_slice(&bytes).map_err(|_| error)?;
    let directory = &review.profile_directory;
    let info = symlink_metadata(directory).map_err(|_| error)?;
    if !directory.is_absolute()
        || !info.is_dir()
        || info.uid() != user
        || info.mode() & 0o077 != 0
        || directory.canonicalize().map_err(|_| error)? != *directory
    {
        return Err(error);
    }
    Ok(review)
}

/// Apply only a reviewed identity change. The old account stays bound to
/// its previous profile until the ordinary owner account approval succeeds.
pub async fn replace(c: &mut PgConnection, review: &Review, apply: bool) -> Result<Value> {
    let mut tx = c.begin().await.map_err(db)?;
    if apply {
        lock(&mut tx, None).await?;
    } else {
        sqlx::query("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            .execute(&mut *tx)
            .await
            .map_err(db)?;
    }
    let (at, old_pin) = validate(&mut tx, review, apply).await?;
    let next = review
        .selection_version
        .checked_add(1)
        .ok_or_else(invalid)?;
    if apply {
        let archive_key = format!("chr_pin_backup:{}", review.selection_version);
        let archive = json!({"previous_pin": old_pin, "previous_selection_version": review.selection_version,
            "previous_profile_version": review.old_profile_version, "new_binding": review.new_binding,
            "previous_account_revision": review.account_revision, "evidence_sha256": review.evidence_sha256,
            "recorded_at": at});
        let saved: Option<String> = sqlx::query_scalar(
            "INSERT INTO owner_preferences(key,value) VALUES($1,$2) ON CONFLICT DO NOTHING RETURNING key",
        )
        .bind(&archive_key)
        .bind(archive)
        .fetch_optional(&mut *tx)
        .await
        .map_err(db)?;
        if saved.as_ref() != Some(&archive_key) {
            return Err(Failure("previous_browser_pin_archive_conflict"));
        }
        disable_binding(&mut tx, review.old_binding, review.old_profile_version).await?;
        put(&mut tx, "chr_fixed_profile", &json!({
            "profile_binding_id": review.new_binding, "profile_directory": review.profile_directory,
            "browser": "brave", "verified_via": "owner_reviewed_dedicated_brave_profile",
            "automatic_launch_enabled": false, "evidence_sha256": review.evidence_sha256,
            "verified_at": review.observed_at,
        })).await?;
        select(
            &mut tx,
            review.selection_version,
            Some(review.new_binding),
            at,
        )
        .await?;
    }
    tx.commit()
        .await
        .map_err(|_| Failure("brave_pin_replacement_commit_unconfirmed"))?;
    Ok(json!({"applied": apply, "proposed_selection_version": next,
        "account_reapproval_required": true, "submission_dispatched": false}))
}

async fn validate(
    tx: &mut Transaction<'_, Postgres>,
    review: &Review,
    writing: bool,
) -> Result<(DateTime<Utc>, Value)> {
    let at = now(tx).await?;
    let proof_age = at.signed_duration_since(review.observed_at);
    if !review.owner_confirmed
        || !review.profile_directory.is_absolute()
        || review.old_binding == review.new_binding
        || review.window_id < 0
        || proof_age < chrono::Duration::zero()
        || proof_age > chrono::Duration::minutes(5)
        || [
            &review.account_sha256,
            &review.resume_sha256,
            &review.evidence_sha256,
        ]
        .iter()
        .any(|hash| {
            hash.len() != 64
                || !hash
                    .bytes()
                    .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
        })
    {
        return Err(Failure("fresh_owner_brave_review_required"));
    }
    ensure_stopped(tx, writing).await?;
    let selected = selection(tx).await?;
    let pin = get(tx, "chr_fixed_profile")
        .await?
        .ok_or(Failure("legacy_chrome_pin_required"))?;
    if pin["verified_via"] != "owner_selected_chrome_version_page"
        || pin["profile_binding_id"] != json!(review.old_binding)
        || selected["profile_binding_id"] != pin["profile_binding_id"]
        || selected["version"] != review.selection_version
    {
        return Err(Failure("legacy_chrome_pin_changed"));
    }
    let old = get(tx, &format!("chr_prof:{}", review.old_binding))
        .await?
        .ok_or(invalid())?;
    let target = get(tx, &format!("chr_prof:{}", review.new_binding))
        .await?
        .ok_or(invalid())?;
    if old["id"] != json!(review.old_binding)
        || old["version"] != review.old_profile_version
        || target["id"] != json!(review.new_binding)
        || target["version"] != review.new_profile_version
        || target["browser_session_id"] != json!(review.browser_session_id)
        || target["window_id"] != review.window_id
        || target["commands_enabled"] != false
        || !online(&target, at)?
    {
        return Err(Failure("reviewed_browser_binding_changed"));
    }
    verify_material(tx, review, writing).await?;
    Ok((at, pin))
}

async fn ensure_stopped(tx: &mut Transaction<'_, Postgres>, writing: bool) -> Result<()> {
    // The owner lock covers queues and browser work. The coordinator control
    // has its own row and can also change through the general Agent controls.
    let mode_query = if writing {
        "SELECT mode FROM rust_agent_control WHERE key='primary' FOR SHARE"
    } else {
        "SELECT mode FROM rust_agent_control WHERE key='primary'"
    };
    let mode: Option<String> = sqlx::query_scalar(mode_query)
        .fetch_optional(&mut **tx)
        .await
        .map_err(db)?;
    let queue = get(tx, "application_queue_policy").await?;
    let legacy = get(tx, "naukri_automation").await?;
    if mode.as_deref() != Some("STOPPED")
        || queue.is_none_or(|q| q["state"] != "STOPPED")
        || legacy.is_some_and(|q| q["state"] != "STOPPED")
    {
        return Err(Failure("brave_pin_replacement_requires_stop"));
    }
    let busy: bool = sqlx::query_scalar(include_str!("../../sql/brave_pin_has_active_work.sql"))
        .fetch_one(&mut **tx)
        .await
        .map_err(db)?;
    if busy {
        return Err(Failure("brave_pin_replacement_has_active_work"));
    }
    Ok(())
}

async fn verify_material(
    tx: &mut Transaction<'_, Postgres>,
    review: &Review,
    writing: bool,
) -> Result<()> {
    let account = get(tx, "naukri_account_binding")
        .await?
        .ok_or(Failure("approved_naukri_account_binding_required"))?;
    if account["approved"] != true
        || account["profile_binding_id"] != json!(review.old_binding)
        || account["revision"] != review.account_revision
        || account["account_sha256"] != review.account_sha256
    {
        return Err(Failure("reviewed_naukri_account_changed"));
    }
    let profile = string(&account, "candidate_profile_id")?
        .parse::<Uuid>()
        .map_err(|_| invalid())?;
    let material = if writing {
        concat!(
            include_str!("../../sql/brave_pin_reviewed_resume.sql"),
            " FOR SHARE OF p,r,d"
        )
    } else {
        include_str!("../../sql/brave_pin_reviewed_resume.sql")
    };
    let hashes: Vec<String> = sqlx::query_scalar(material)
        .bind(profile)
        .bind(review.candidate_profile_version)
        .fetch_all(&mut **tx)
        .await
        .map_err(db)?;
    if hashes.len() != 1 || hashes[0] != review.resume_sha256 {
        return Err(Failure("reviewed_canonical_resume_changed"));
    }
    Ok(())
}
