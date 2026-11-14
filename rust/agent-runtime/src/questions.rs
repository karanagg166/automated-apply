//! Owner questions are references to independently saved/confirmed facts, never grants.
use crate::{
    Failure, Result,
    contracts::Run,
    knowledge::{self, ProfilePin},
};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use sqlx::PgConnection;
use uuid::Uuid;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum FactKey {
    ProfileReviewRequired,
    NoticePeriodDays,
    WorkAuthorization,
    ExpectedCompensation,
    AvailabilityDate,
}
impl FactKey {
    pub fn parse(key: &str) -> Result<Self> {
        match key {
            "profile_review_required" => Ok(Self::ProfileReviewRequired),
            "notice_period" | "notice_period_days" => Ok(Self::NoticePeriodDays),
            "work_authorization" => Ok(Self::WorkAuthorization),
            "expected_compensation" => Ok(Self::ExpectedCompensation),
            "availability_date" => Ok(Self::AvailabilityDate),
            _ => Err(Failure("unsupported_owner_question")),
        }
    }
    pub fn key(self) -> &'static str {
        match self {
            Self::ProfileReviewRequired => "profile_review_required",
            Self::NoticePeriodDays => "notice_period_days",
            Self::WorkAuthorization => "work_authorization",
            Self::ExpectedCompensation => "expected_compensation",
            Self::AvailabilityDate => "availability_date",
        }
    }
    pub fn prompt(self) -> &'static str {
        match self {
            Self::ProfileReviewRequired => {
                "Review and confirm the current profile version in Profile."
            }
            Self::NoticePeriodDays => {
                "Save your actual notice period in Profile, then confirm that profile version."
            }
            Self::WorkAuthorization => {
                "Save your actual work authorization in Profile, then confirm that profile version."
            }
            Self::ExpectedCompensation => {
                "Save your expected compensation with currency, period and kind in Profile, then confirm that profile version."
            }
            Self::AvailabilityDate => {
                "Save your actual availability date in Profile, then confirm that profile version."
            }
        }
    }
}
#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Question {
    pub id: Uuid,
    pub key: FactKey,
}
impl Question {
    pub fn new(key: &str) -> Result<Self> {
        Ok(Self {
            id: Uuid::new_v4(),
            key: FactKey::parse(key)?,
        })
    }
}

fn valid_compensation_amount(value: &Value) -> bool {
    let text = match value {
        Value::String(s) => s.clone(),
        Value::Number(n) => n.to_string(),
        _ => return false,
    };
    if text.len() > 65536 {
        return false;
    }
    let text = text.trim();
    let negative = text.starts_with('-');
    let text = text.strip_prefix(['+', '-']).unwrap_or(text);
    let mut parts = text.split(['e', 'E']);
    let mantissa = parts.next().unwrap_or("");
    let exponent = match parts.next() {
        Some(s) => match s.parse::<i64>() {
            Ok(n) => n,
            Err(_) => return false,
        },
        None => 0,
    };
    if parts.next().is_some() {
        return false;
    }
    let mut digits = String::with_capacity(mantissa.len());
    let mut fraction = 0i64;
    let mut dot = false;
    for c in mantissa.chars() {
        if c == '.' && !dot {
            dot = true;
            continue;
        }
        if !c.is_ascii_digit() {
            return false;
        }
        digits.push(c);
        if dot {
            fraction += 1;
        }
    }
    if digits.is_empty() {
        return false;
    }
    let trimmed = digits.trim_start_matches('0');
    if trimmed.is_empty() {
        return true;
    }
    if negative {
        return false;
    }
    let coefficient = trimmed.trim_end_matches('0');
    let trailing = (trimmed.len() - coefficient.len()) as i64;
    let Some(shift) = exponent
        .checked_sub(fraction)
        .and_then(|n| n.checked_add(trailing))
        .and_then(|n| n.checked_add(2))
    else {
        return false;
    };
    if !(0..=14).contains(&shift) || coefficient.len() > 15 {
        return false;
    }
    coefficient
        .parse::<u64>()
        .ok()
        .and_then(|n| n.checked_mul(10u64.pow(shift as u32)))
        .is_some_and(|cents| cents <= 100_000_000_000_000)
}
fn valid_fact(key: FactKey, value: &Value) -> bool {
    match key {
        FactKey::ProfileReviewRequired => true,
        FactKey::NoticePeriodDays => value.as_u64().is_some_and(|n| n <= 3650),
        FactKey::WorkAuthorization => value
            .as_str()
            .is_some_and(|s| !s.trim().is_empty() && s.chars().count() <= 200),
        FactKey::AvailabilityDate => value.as_str().is_some_and(|s| {
            s.len() == 10 && chrono::NaiveDate::parse_from_str(s, "%Y-%m-%d").is_ok()
        }),
        FactKey::ExpectedCompensation => {
            let Some(amount) = value.get("amount") else {
                return false;
            };
            valid_compensation_amount(amount)
                && value
                    .get("currency")
                    .and_then(Value::as_str)
                    .is_some_and(|s| s.len() == 3 && s.bytes().all(|b| b.is_ascii_uppercase()))
                && matches!(
                    value.get("period").and_then(Value::as_str),
                    Some("hour" | "month" | "year")
                )
                && matches!(
                    value.get("kind").and_then(Value::as_str),
                    Some("ctc" | "base_salary" | "total_compensation")
                )
        }
    }
}
/// No answer is accepted from the model or resolution request. The existing confirmed
/// profile is the only source; no provider save or profile mutation occurs here.
pub async fn known(
    connection: &mut PgConnection,
    question: &Question,
) -> Result<Option<ProfilePin>> {
    let Some(profile) = knowledge::reviewed_profile(connection).await? else {
        return Ok(None);
    };
    if question.key == FactKey::ProfileReviewRequired {
        return Ok(Some(profile.pin));
    }
    let value: Option<Value> = sqlx::query_scalar(
        "SELECT preferences->$1 FROM candidate_profiles WHERE id=$2 AND version=$3",
    )
    .bind(question.key.key())
    .bind(profile.pin.id)
    .bind(profile.pin.version)
    .fetch_optional(connection)
    .await
    .map_err(|_| Failure("owner_fact_database_error"))?
    .flatten();
    Ok(value
        .filter(|v| valid_fact(question.key, v))
        .map(|_| profile.pin))
}
pub fn public_question(run: &Run, revision: i64) -> Option<Value> {
    run.question.as_ref().map(|q|json!({"id":q.id,"run_id":run.id,"revision":revision,"key":q.key,"prompt":q.key.prompt(),"resolution":"confirmed_profile_reference_only"}))
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn compensation_requires_units_and_does_not_guess_from_salary_preferences() {
        for value in ["100.000", "1E+2", "-0.000", "100.0100", "1000000000000.000"] {
            assert!(valid_compensation_amount(&json!(value)));
        }
        for value in ["100.0010", "1E+100000", "-1.00", "NaN", "1E-3"] {
            assert!(!valid_compensation_amount(&json!(value)));
        }
        assert!(!valid_fact(FactKey::ExpectedCompensation, &json!(100)));
        assert!(!valid_fact(
            FactKey::ExpectedCompensation,
            &json!({"amount":"100","currency":"INR"})
        ));
        assert!(valid_fact(
            FactKey::ExpectedCompensation,
            &json!({"amount":"100.50","currency":"INR","period":"year","kind":"ctc"})
        ));
        assert!(!valid_fact(
            FactKey::ExpectedCompensation,
            &json!({"amount":"1000000000000.01","currency":"INR","period":"year","kind":"ctc"})
        ));
    }
    #[test]
    fn dates_and_notice_periods_require_real_typed_facts() {
        assert!(!valid_fact(FactKey::NoticePeriodDays, &json!(false)));
        assert!(valid_fact(FactKey::NoticePeriodDays, &json!(0)));
        assert!(!valid_fact(FactKey::AvailabilityDate, &json!("2026-02-30")));
        assert!(valid_fact(FactKey::AvailabilityDate, &json!("2026-11-14")));
        assert!(FactKey::parse("approve_submission").is_err());
    }
}
