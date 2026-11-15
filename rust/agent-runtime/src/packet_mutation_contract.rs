//! Closed owner edit contracts. A supplied answer or revision never conveys review/approval.
use crate::{
    Failure, Result,
    packet_contract::{self, Question},
};
use serde::Serialize;
use serde_json::{Map, Value};
use uuid::Uuid;

#[derive(Clone, Copy)]
pub enum Kind {
    Refresh,
    Questions,
    Answer,
}
#[derive(Serialize)]
#[serde(untagged)]
pub enum Input {
    Refresh {
        expected_revision: i32,
        resume_resource_id: Option<Uuid>,
        refresh_saved_data: bool,
        #[serde(skip)]
        explicit_resume: bool,
    },
    Questions {
        expected_revision: i32,
        questions: Vec<Question>,
    },
    Answer {
        expected_revision: i32,
        answer: String,
    },
}
impl Input {
    pub fn revision(&self) -> i32 {
        match self {
            Self::Refresh {
                expected_revision, ..
            }
            | Self::Questions {
                expected_revision, ..
            }
            | Self::Answer {
                expected_revision, ..
            } => *expected_revision,
        }
    }
    pub fn explicit_resume(&self) -> bool {
        matches!(
            self,
            Self::Refresh {
                explicit_resume: true,
                ..
            }
        )
    }
}
fn invalid() -> Failure {
    Failure("invalid_packet_edit_request")
}
fn object(input: &Value, allowed: &[&str]) -> Result<Map<String, Value>> {
    let body = input.as_object().ok_or_else(invalid)?;
    if body.keys().any(|k| !allowed.contains(&k.as_str())) {
        return Err(invalid());
    }
    Ok(body.clone())
}
pub fn normalize(kind: Kind, input: Value) -> Result<Input> {
    let body = object(
        &input,
        match kind {
            Kind::Refresh => &[
                "expected_revision",
                "resume_resource_id",
                "refresh_saved_data",
            ],
            Kind::Questions => &["expected_revision", "questions"],
            Kind::Answer => &["expected_revision", "answer"],
        },
    )?;
    let expected_revision = crate::profile_contract::pagination_integer(
        body.get("expected_revision").cloned().ok_or_else(invalid)?,
        1,
        2147483646,
    )
    .map_err(|_| invalid())? as i32;
    match kind {
        Kind::Refresh => Ok(Input::Refresh {
            expected_revision,
            resume_resource_id: body
                .get("resume_resource_id")
                .filter(|v| !v.is_null())
                .map(|v| v.as_str().and_then(|s| s.parse().ok()).ok_or_else(invalid))
                .transpose()?,
            refresh_saved_data: body
                .get("refresh_saved_data")
                .map(crate::resource_contract::boolean)
                .transpose()
                .map_err(|_| invalid())?
                .and_then(|v| v.as_bool())
                .unwrap_or(false),
            explicit_resume: body.contains_key("resume_resource_id"),
        }),
        Kind::Questions => {
            let rows = body
                .get("questions")
                .and_then(Value::as_array)
                .filter(|a| !a.is_empty() && a.len() <= 50)
                .ok_or_else(invalid)?;
            let questions = rows
                .iter()
                .map(|v| packet_contract::question(v.clone()).map_err(|_| invalid()))
                .collect::<Result<Vec<_>>>()?;
            Ok(Input::Questions {
                expected_revision,
                questions,
            })
        }
        Kind::Answer => {
            let answer = body
                .get("answer")
                .and_then(Value::as_str)
                .ok_or_else(invalid)?
                .trim();
            if !(1..=10000).contains(&answer.chars().count()) {
                return Err(invalid());
            }
            Ok(Input::Answer {
                expected_revision,
                answer: answer.into(),
            })
        }
    }
}
