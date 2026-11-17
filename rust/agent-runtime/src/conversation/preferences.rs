//! Existing search preference DTO only; matching never grants application eligibility.
use crate::{Failure, Result};
use serde_json::{Value, json};
use std::sync::LazyLock;
struct Contract {
    schema: Value,
    validator: jsonschema::Validator,
}
fn contract() -> &'static Contract {
    static VALUE: LazyLock<Contract> = LazyLock::new(|| {
        let schema: Value =
            serde_json::from_str(include_str!("../../schemas/conversation-preferences.json"))
                .expect("frozen search preferences");
        let validator = jsonschema::draft202012::options()
            .should_validate_formats(false)
            .build(&schema)
            .expect("search preference validator");
        Contract { schema, validator }
    });
    &VALUE
}
fn invalid() -> Failure {
    Failure("invalid_conversation_preferences")
}
pub fn normalize(mut input: Value) -> Result<Value> {
    if input.to_string().len() > 65536 {
        return Err(invalid());
    }
    let fields = input.as_object_mut().ok_or_else(invalid)?;
    for key in ["saved_jobs_only"] {
        if let Some(value) = fields.get_mut(key) {
            *value = crate::resource_contract::boolean(value).map_err(|_| invalid())?;
        }
    }
    for key in ["require_known_properties", "duplicate_prevention"] {
        if let Some(value) = fields.get(key) {
            if value != true && value.as_f64() != Some(1.0) {
                return Err(invalid());
            }
        }
        if fields.contains_key(key) {
            fields.insert(key.into(), json!(true));
        }
    }
    let c = contract();
    let value =
        crate::profile_contract::normalize_shape(&c.schema, input).map_err(|_| invalid())?;
    if !c.validator.is_valid(&value) {
        return Err(invalid());
    }
    for (low, high) in [
        ("minimum_experience", "maximum_experience"),
        ("minimum_salary", "maximum_salary"),
        ("minimum_employees", "maximum_employees"),
    ] {
        if let (Some(a), Some(b)) = (value[low].as_f64(), value[high].as_f64()) {
            if a > b {
                return Err(invalid());
            }
        }
    }
    if value["source_platforms"].as_array().is_none_or(|a| {
        a.iter().any(|s| {
            s.as_str()
                .is_none_or(|s| !(1..=100).contains(&s.chars().count()))
        })
    }) {
        return Err(invalid());
    }
    Ok(value)
}

pub(crate) const PATH: &str = "/api/v1/local-agent/search-preferences";

async fn saved(connection: &mut sqlx::PgConnection) -> Result<Option<Value>> {
    let row: Option<Option<Value>> = sqlx::query_scalar(
        "SELECT CASE WHEN octet_length(value::text) <= 65536 THEN value END
         FROM owner_preferences WHERE key = 'agent_search_preferences'",
    )
    .fetch_optional(connection)
    .await
    .map_err(|_| Failure("profile_database_error"))?;
    row.map(|value| value.ok_or(Failure("invalid_saved_conversation_preferences")))
        .transpose()
}

pub(crate) async fn effective(connection: &mut sqlx::PgConnection) -> Result<Value> {
    let profile: Option<Value> = sqlx::query_scalar(
        "SELECT preferences FROM candidate_profiles WHERE singleton_key = 'primary'",
    )
    .fetch_optional(&mut *connection)
    .await
    .map_err(|_| Failure("profile_database_error"))?;
    let mut fields = serde_json::Map::new();
    for values in [profile, saved(connection).await?].into_iter().flatten() {
        fields.extend(
            values
                .as_object()
                .ok_or(Failure("invalid_saved_conversation_preferences"))?
                .clone(),
        );
    }
    normalize(Value::Object(fields)).map_err(|_| Failure("invalid_saved_conversation_preferences"))
}

pub(crate) async fn read(connection: &mut sqlx::PgConnection) -> Result<Value> {
    normalize(saved(connection).await?.unwrap_or_else(|| json!({})))
        .map_err(|_| Failure("invalid_saved_conversation_preferences"))
}

pub(crate) async fn dispatch(
    connection: &mut sqlx::PgConnection,
    method: &str,
    query: Option<&str>,
    body: &[u8],
) -> Result<Value> {
    use sqlx::Connection;
    if query.is_some() {
        return Err(invalid());
    }
    match method {
        "GET" if body.is_empty() => read(connection).await,
        "PUT" => {
            let value = normalize(serde_json::from_slice(body).map_err(|_| invalid())?)?;
            let mut tx = connection
                .begin()
                .await
                .map_err(|_| Failure("profile_database_error"))?;
            crate::execution::lock_owner_in(&mut tx).await?;
            let stored: Option<Value> = sqlx::query_scalar(
                "INSERT INTO owner_preferences(key, value) VALUES ('agent_search_preferences', $1)
                 ON CONFLICT(key) DO UPDATE SET value = EXCLUDED.value, updated_at = clock_timestamp()
                 RETURNING value",
            ).bind(&value).fetch_optional(&mut *tx).await.map_err(|_| Failure("profile_database_error"))?;
            if stored.as_ref() != Some(&value) || saved(&mut tx).await?.as_ref() != Some(&value) {
                tx.rollback()
                    .await
                    .map_err(|_| Failure("profile_database_error"))?;
                return Err(Failure("conversation_preferences_write_ack_failed"));
            }
            tx.commit()
                .await
                .map_err(|_| Failure("conversation_preferences_outcome_unknown"))?;
            Ok(value)
        }
        "GET" => Err(invalid()),
        _ => Err(Failure("conversation_preferences_method_not_allowed")),
    }
}
