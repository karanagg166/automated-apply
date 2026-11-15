//! Existing primary-profile CRUD with normalization, atomic CAS and commit before ACK.
//! Keeps resume associations, confirmation/history and unrelated columns outside writes.
use crate::{
    Failure, Result,
    profile_contract::{self, Operation},
};
use chrono::{DateTime, SecondsFormat, Utc};
use serde_json::Value;
use sqlx::{Connection, PgConnection};
use uuid::Uuid;

const LOAD: &str = r#"SELECT to_jsonb(p) FROM (SELECT full_name,email,phone,linkedin_url,github_url,portfolio_url,personal_website,verified_experience_years,verified_skills,verified_roles,education,projects,certifications,summary,preferences,id,singleton_key,version,created_at,updated_at FROM candidate_profiles WHERE singleton_key='primary') p"#;
const UPDATE: &str = r#"UPDATE candidate_profiles SET
full_name=($1::jsonb->>'full_name'),
email=($1::jsonb->>'email'),
phone=($1::jsonb->>'phone'),
linkedin_url=($1::jsonb->>'linkedin_url'),
github_url=($1::jsonb->>'github_url'),
portfolio_url=($1::jsonb->>'portfolio_url'),
personal_website=($1::jsonb->>'personal_website'),
verified_experience_years=($1::jsonb->>'verified_experience_years')::double precision,
verified_skills=$1::jsonb->'verified_skills',
verified_roles=$1::jsonb->'verified_roles',
education=$1::jsonb->'education',
projects=$1::jsonb->'projects',
certifications=$1::jsonb->'certifications',
summary=($1::jsonb->>'summary'),
preferences=$1::jsonb->'preferences',version=version+1,updated_at=clock_timestamp() WHERE id=$2 AND singleton_key='primary' AND version=$3"#;
const INSERT: &str = r#"WITH stamp AS (SELECT clock_timestamp() AS at) INSERT INTO candidate_profiles (full_name,email,phone,linkedin_url,github_url,portfolio_url,personal_website,verified_experience_years,verified_skills,verified_roles,education,projects,certifications,summary,preferences,id,singleton_key,version,created_at,updated_at) SELECT ($1::jsonb->>'full_name'),($1::jsonb->>'email'),($1::jsonb->>'phone'),($1::jsonb->>'linkedin_url'),($1::jsonb->>'github_url'),($1::jsonb->>'portfolio_url'),($1::jsonb->>'personal_website'),($1::jsonb->>'verified_experience_years')::double precision,$1::jsonb->'verified_skills',$1::jsonb->'verified_roles',$1::jsonb->'education',$1::jsonb->'projects',$1::jsonb->'certifications',($1::jsonb->>'summary'),$1::jsonb->'preferences',$2,'primary',1,at,at FROM stamp ON CONFLICT (singleton_key) DO NOTHING"#;
const META: &[&str] = &["id", "singleton_key", "version", "created_at", "updated_at"];
pub struct Saved {
    pub value: Value,
    pub version: i32,
    pub created: bool,
    raw: Value,
}
fn db(_: sqlx::Error) -> Failure {
    Failure("profile_database_error")
}
async fn load(connection: &mut PgConnection) -> Result<Option<Saved>> {
    let Some(raw) = sqlx::query_scalar::<_, Value>(LOAD)
        .fetch_optional(connection)
        .await
        .map_err(db)?
    else {
        return Ok(None);
    };
    let mut body = raw
        .as_object()
        .ok_or(Failure("invalid_profile_record"))?
        .clone();
    for key in META {
        body.remove(*key);
    }
    let source = Value::Object(body.clone());
    let mut value = profile_contract::normalize_record(Value::Object(body))?;
    let metadata = value.as_object_mut().unwrap();
    for key in META {
        metadata.insert(
            (*key).into(),
            raw.get(*key)
                .cloned()
                .ok_or(Failure("invalid_profile_record"))?,
        );
    }
    let id = metadata["id"]
        .as_str()
        .and_then(|s| s.parse::<Uuid>().ok())
        .ok_or(Failure("invalid_profile_record"))?;
    metadata.insert("id".into(), Value::String(id.to_string()));
    let version = metadata["version"]
        .as_i64()
        .and_then(|n| i32::try_from(n).ok())
        .filter(|n| *n > 0)
        .ok_or(Failure("invalid_profile_record"))?;
    if metadata["singleton_key"] != "primary" {
        return Err(Failure("invalid_profile_record"));
    }
    for key in ["created_at", "updated_at"] {
        let time = metadata[key]
            .as_str()
            .and_then(|s| DateTime::parse_from_rfc3339(s).ok())
            .ok_or(Failure("invalid_profile_record"))?;
        metadata.insert(
            key.into(),
            Value::String(time.with_timezone(&Utc).to_rfc3339_opts(
                if time.timestamp_subsec_micros() == 0 {
                    SecondsFormat::Secs
                } else {
                    SecondsFormat::Micros
                },
                true,
            )),
        );
    }
    Ok(Some(Saved {
        value,
        version,
        created: false,
        raw: source,
    }))
}
pub async fn get(connection: &mut PgConnection) -> Result<Saved> {
    load(connection).await?.ok_or(Failure("profile_not_found"))
}
fn career(value: &Value) -> Value {
    let mut body = value.as_object().unwrap().clone();
    for key in META {
        body.remove(*key);
    }
    Value::Object(body)
}
fn legacy_equal(a: &Value, b: &Value) -> bool {
    match (a, b) {
        (Value::Number(a), Value::Number(b)) => a.as_f64() == b.as_f64(),
        (Value::Bool(a), Value::Number(b)) | (Value::Number(b), Value::Bool(a)) => {
            b.as_f64() == Some(if *a { 1.0 } else { 0.0 })
        }
        (Value::Array(a), Value::Array(b)) => {
            a.len() == b.len() && a.iter().zip(b).all(|(a, b)| legacy_equal(a, b))
        }
        (Value::Object(a), Value::Object(b)) => {
            a.len() == b.len()
                && a.iter()
                    .all(|(key, a)| b.get(key).is_some_and(|b| legacy_equal(a, b)))
        }
        _ => a == b,
    }
}
/// Input and existing records are normalized independently; no model-supplied authority.
/// PostgreSQL transaction commit completes before this function acknowledges a save.
pub async fn save(
    connection: &mut PgConnection,
    input: Value,
    expected: Option<i32>,
    patch: bool,
    live: bool,
) -> Result<Saved> {
    let supplied = profile_contract::normalize(
        if patch {
            Operation::Update
        } else {
            Operation::Create
        },
        input,
    )?;
    save_normalized(connection, supplied, expected, patch, live).await
}
/// Caller must use the public contract normalizer before entering this persistence boundary.
pub(crate) async fn save_normalized(
    connection: &mut PgConnection,
    supplied: Value,
    expected: Option<i32>,
    patch: bool,
    live: bool,
) -> Result<Saved> {
    if patch && expected.is_none() {
        return Err(Failure("profile_version_required"));
    }
    if expected.is_some_and(|n| !(1..=2147483646).contains(&n)) {
        return Err(Failure("invalid_profile_version"));
    }
    if live {
        profile_contract::reject_placeholders(&supplied)?;
    }
    let mut transaction = connection.begin().await.map_err(db)?;
    let current = load(&mut transaction).await?;
    let created = current.is_none();
    if let Some(current) = current {
        let previous = career(&current.value);
        let next = if patch {
            profile_contract::merge_update(previous.clone(), supplied)?
        } else {
            supplied
        };
        let unchanged = legacy_equal(&current.raw, &next);
        let Some(version) = expected else {
            if unchanged {
                transaction.commit().await.map_err(db)?;
                return Ok(current);
            }
            return Err(Failure("profile_version_required"));
        };
        if version != current.version {
            return Err(Failure("profile_version_conflict"));
        }
        let id = current.value["id"]
            .as_str()
            .unwrap()
            .parse::<Uuid>()
            .unwrap();
        // Even a no-op with If-Match checks the version atomically.
        let query = if unchanged {
            "UPDATE candidate_profiles SET version=version WHERE id=$2 AND singleton_key='primary' AND version=$3 AND $1::jsonb IS NOT NULL"
        } else {
            UPDATE
        };
        let changed = sqlx::query(query)
            .bind(next)
            .bind(id)
            .bind(version)
            .execute(&mut *transaction)
            .await
            .map_err(db)?
            .rows_affected();
        if changed != 1 {
            return Err(Failure("profile_version_conflict"));
        }
    } else {
        if patch {
            return Err(Failure("profile_not_found"));
        }
        if expected.is_some() {
            return Err(Failure("profile_version_conflict"));
        }
        let count = sqlx::query(INSERT)
            .bind(supplied)
            .bind(Uuid::new_v4())
            .execute(&mut *transaction)
            .await
            .map_err(db)?
            .rows_affected();
        if count != 1 {
            return Err(Failure("profile_version_conflict"));
        }
    }
    // Result validation is inside the transaction, preserving rollback on invalid output.
    let mut saved = get(&mut transaction).await?;
    transaction.commit().await.map_err(db)?;
    saved.created = created;
    Ok(saved)
}

/// An outer resume-review transaction atomically changes facts and the material resume binding.
pub(crate) async fn activate_resume_in(
    c: &mut PgConnection,
    supplied: Value,
    expected: Option<i32>,
    resume: Uuid,
    live: bool,
) -> Result<Saved> {
    let supplied = profile_contract::normalize(Operation::Create, supplied)?;
    if live {
        profile_contract::reject_placeholders(&supplied)?;
    }
    sqlx::query("SELECT id FROM candidate_profiles WHERE singleton_key='primary' FOR UPDATE")
        .execute(&mut *c)
        .await
        .map_err(db)?;
    let current = load(c).await?;
    if current.as_ref().map(|profile| profile.version) != expected {
        return Err(Failure("profile_version_conflict"));
    }
    let created = current.is_none();
    let id = if let Some(current) = current {
        let id = current.value["id"]
            .as_str()
            .and_then(|s| s.parse::<Uuid>().ok())
            .ok_or(Failure("invalid_profile_record"))?;
        let affected = sqlx::query(include_str!("../sql/update_profile_resume.sql"))
            .bind(&supplied)
            .bind(id)
            .bind(current.version)
            .bind(resume)
            .execute(&mut *c)
            .await
            .map_err(db)?
            .rows_affected();
        if affected != 1 {
            return Err(Failure("profile_version_conflict"));
        }
        id
    } else {
        let id = Uuid::new_v4();
        // The separate insert keeps ordinary profile CRUD compatible with pre-resume schemas.
        let affected = sqlx::query(include_str!("../sql/insert_profile_resume.sql"))
            .bind(&supplied)
            .bind(id)
            .bind(resume)
            .execute(&mut *c)
            .await
            .map_err(db)?
            .rows_affected();
        if affected != 1 {
            return Err(Failure("profile_version_conflict"));
        }
        id
    };
    let active: Option<Uuid> =
        sqlx::query_scalar("SELECT active_resume_version_id FROM candidate_profiles WHERE id=$1")
            .bind(id)
            .fetch_one(&mut *c)
            .await
            .map_err(db)?;
    let mut saved = get(c).await?;
    if active != Some(resume) || !legacy_equal(&career(&saved.value), &supplied) {
        return Err(Failure("profile_write_ack_failed"));
    }
    saved.created = created;
    Ok(saved)
}
