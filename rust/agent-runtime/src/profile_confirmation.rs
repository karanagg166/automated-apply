//! Explicit owner review of one version. Confirmation and safe read-recheck intent commit together.
use crate::{Failure, Result};
use chrono::{DateTime, SecondsFormat, Utc};
use serde::Deserialize;
use serde_json::{Value, json};
use sqlx::{Connection, PgConnection, Row};
use uuid::Uuid;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Confirmation {
    expected_version: Value,
    owner_confirmed: Value,
}
fn invalid() -> Failure {
    Failure("invalid_profile_confirmation")
}
fn db(_: sqlx::Error) -> Failure {
    Failure("profile_database_error")
}
enum Version {
    Number(f64),
    Digits(String),
}
impl Version {
    fn parse(value: &Value) -> Result<Self> {
        match value {
            Value::Bool(true) => Ok(Self::Number(1.0)),
            Value::Number(n) => n
                .as_f64()
                .filter(|n| n.is_finite() && *n >= 1.0 && n.fract() == 0.0)
                .map(Self::Number)
                .ok_or_else(invalid),
            Value::String(raw) => {
                let raw = raw.trim();
                let raw = raw.strip_prefix('+').unwrap_or(raw);
                let (integer, fraction) = raw
                    .split_once('.')
                    .map(|(a, b)| (a, Some(b)))
                    .unwrap_or((raw, None));
                if integer.is_empty()
                    || integer.len() > 4300
                    || fraction.is_some_and(|f| f.is_empty() || f.chars().any(|c| c != '0'))
                {
                    return Err(invalid());
                }
                let bytes = integer.as_bytes();
                if bytes.iter().enumerate().any(|(i, &c)| {
                    !c.is_ascii_digit()
                        && (c != b'_'
                            || i == 0
                            || i + 1 == bytes.len()
                            || !bytes[i - 1].is_ascii_digit()
                            || !bytes[i + 1].is_ascii_digit())
                }) {
                    return Err(invalid());
                }
                let digits = integer.replace('_', "");
                let digits = digits.trim_start_matches('0');
                if digits.is_empty() {
                    return Err(invalid());
                }
                Ok(Self::Digits(digits.into()))
            }
            _ => Err(invalid()),
        }
    }
    fn matches(&self, version: i32) -> bool {
        match self {
            Self::Number(n) => *n == f64::from(version),
            Self::Digits(digits) => *digits == version.to_string(),
        }
    }
}
fn truth(value: &Value) -> bool {
    match value {
        Value::Null => false,
        Value::Bool(v) => *v,
        Value::Number(n) => n.as_f64() != Some(0.0),
        Value::String(s) => !s.is_empty(),
        Value::Array(v) => !v.is_empty(),
        Value::Object(v) => !v.is_empty(),
    }
}
fn current(value: &Value, id: Uuid, version: i32) -> bool {
    value.get("profile_id").and_then(Value::as_str) == Some(id.to_string().as_str())
        && value.get("profile_version").is_some_and(|n| match n {
            Value::Bool(true) => version == 1,
            Value::Number(n) => n.as_f64() == Some(f64::from(version)),
            _ => false,
        })
        && value.get("confirmed_at").is_some_and(truth)
}
pub async fn confirm(connection: &mut PgConnection, input: Confirmation) -> Result<Value> {
    let expected = Version::parse(&input.expected_version)?;
    // Preserve Literal[True] semantics: JSON true or numeric one, never a truthy string.
    if input.owner_confirmed != json!(true) && input.owner_confirmed.as_f64() != Some(1.0) {
        return Err(invalid());
    }
    let mut tx = connection.begin().await.map_err(db)?;
    let row = sqlx::query(
        "SELECT id,version FROM candidate_profiles WHERE singleton_key='primary' FOR UPDATE",
    )
    .fetch_optional(&mut *tx)
    .await
    .map_err(db)?
    .ok_or(Failure("profile_changed_review_current_version"))?;
    let id: Uuid = row.try_get("id").map_err(db)?;
    let version: i32 = row.try_get("version").map_err(db)?;
    if !expected.matches(version) {
        return Err(Failure("profile_changed_review_current_version"));
    }
    let old: Option<Value> = sqlx::query_scalar(
        "SELECT value FROM owner_preferences WHERE key='phase1_profile_confirmation' FOR UPDATE",
    )
    .fetch_optional(&mut *tx)
    .await
    .map_err(db)?;
    let was_current = old.as_ref().is_some_and(|old| current(old, id, version));
    let clock: Value = sqlx::query_scalar("SELECT to_jsonb(clock_timestamp())")
        .fetch_one(&mut *tx)
        .await
        .map_err(db)?;
    let clock = clock
        .as_str()
        .and_then(|s| DateTime::parse_from_rfc3339(s).ok())
        .ok_or(Failure("profile_database_error"))?
        .with_timezone(&Utc);
    let instant = clock.to_rfc3339_opts(
        if clock.timestamp_subsec_micros() == 0 {
            SecondsFormat::Secs
        } else {
            SecondsFormat::Micros
        },
        false,
    );
    let confirmation = json!({"profile_id":id,"profile_version":version,"confirmed_at":instant});
    sqlx::query("INSERT INTO owner_preferences(key,value,created_at,updated_at) VALUES ('phase1_profile_confirmation',$1,clock_timestamp(),clock_timestamp()) ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=clock_timestamp()")
        .bind(&confirmation).execute(&mut *tx).await.map_err(db)?;
    if !was_current {
        let recheck = json!({"id":Uuid::new_v4(),"status":"pending","cursor":null,"reason":"owner_profile_version_confirmed","requested_at":instant,"checked":0,"fresh_reads":0});
        sqlx::query("INSERT INTO owner_preferences(key,value,created_at,updated_at) VALUES ('apply_filter_recheck',$1,clock_timestamp(),clock_timestamp()) ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=clock_timestamp()")
            .bind(recheck).execute(&mut *tx).await.map_err(db)?;
    }
    tx.commit().await.map_err(db)?;
    Ok(confirmation)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn explicit_review_and_positive_version_inputs_retain_the_public_contract() {
        for value in [
            json!(4),
            json!(4.0),
            json!("4"),
            json!(" +004.00 "),
            json!("4_0.0"),
        ] {
            assert!(Version::parse(&value).is_ok());
        }
        for value in [
            json!(0),
            json!(-1),
            json!(4.2),
            json!("4e0"),
            json!("4."),
            json!("4.0_0"),
            json!("4__0"),
            Value::Null,
        ] {
            assert!(Version::parse(&value).is_err());
        }
        assert!(Version::parse(&json!("004.00")).unwrap().matches(4));
        assert!(
            !Version::parse(&json!("99999999999999999999999999999"))
                .unwrap()
                .matches(4)
        );
        assert!(
            serde_json::from_value::<Confirmation>(
                json!({"expected_version":4,"owner_confirmed":true,"submit":true})
            )
            .is_err()
        );
    }
    #[test]
    fn old_confirmation_requires_exact_identity_version_and_nonempty_review_marker() {
        let id = Uuid::from_u128(2);
        assert!(current(
            &json!({"profile_id":id,"profile_version":4,"confirmed_at":"reviewed"}),
            id,
            4
        ));
        for value in [
            json!({"profile_id":Uuid::from_u128(3),"profile_version":4,"confirmed_at":"reviewed"}),
            json!({"profile_id":id,"profile_version":3,"confirmed_at":"reviewed"}),
            json!({"profile_id":id,"profile_version":4,"confirmed_at":""}),
        ] {
            assert!(!current(&value, id, 4));
        }
    }
}
