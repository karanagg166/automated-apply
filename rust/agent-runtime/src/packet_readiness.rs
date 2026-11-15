//! Pure legacy readiness computation over validated saved-packet projections.
//! This result is never application/admission authority; current context/approval gates remain separate.
use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};

pub struct Snapshot<'a> {
    pub warnings: &'a [String],
    pub destination_warnings: &'a [String],
    pub candidate_present: bool,
    pub preparation_supported: bool,
    pub destination_valid: bool,
    pub source_consistent: bool,
    pub resume_selected: bool,
    pub resume_reason: &'a str,
}
#[derive(Clone, Copy)]
pub enum Validation {
    DraftReady,
    NeedsInput,
    FileUploadRequired,
    ProviderUnavailable,
    ValidationFailed,
}
pub struct Field<'a> {
    pub question: &'a str,
    pub required: bool,
    pub effective_answer: Option<&'a str>,
    pub validation: Validation,
    pub requires_review: bool,
    pub reviewed: bool,
    pub answer_expires_at: Option<DateTime<Utc>>,
}
#[derive(Clone, Copy, Default)]
pub struct Flags {
    pub stale: bool,
    pub approved: bool,
    pub submitted: bool,
}
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum State {
    NeedsProfile,
    NeedsInput,
    NeedsResume,
    NeedsReview,
    ReadyForManualHandoff,
    ManualActionRequired,
    CompletedByUser,
    CompletedVerified,
    Unsupported,
}
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Readiness {
    pub state: State,
    pub blockers: Vec<String>,
    pub manual_steps: Vec<String>,
    pub warnings: Vec<String>,
    pub stale: bool,
}
pub fn calculate(
    snapshot: Snapshot<'_>,
    fields: &[Field<'_>],
    flags: Flags,
    now: DateTime<Utc>,
) -> Readiness {
    let mut warnings = snapshot.warnings.to_vec();
    warnings.extend_from_slice(snapshot.destination_warnings);
    let make = |state, blockers, manual_steps, warnings, stale| Readiness {
        state,
        blockers,
        manual_steps,
        warnings,
        stale,
    };
    let mut manual = vec![
        "Open the official application website yourself".into(),
        "Complete the form and submit it on that website".into(),
    ];
    if snapshot.resume_selected {
        manual.insert(1,"manual_resume_upload_required: open the selected resource and upload the actual file if requested".into());
    }
    if flags.submitted {
        warnings.push("Submission is self-reported; no provider confirmation exists".into());
        return make(
            State::CompletedByUser,
            vec![],
            vec![],
            warnings,
            flags.stale,
        );
    }
    if !snapshot.candidate_present {
        return make(
            State::NeedsProfile,
            vec!["Save a candidate profile".into()],
            vec![],
            warnings,
            flags.stale,
        );
    }
    if !snapshot.preparation_supported {
        return make(
            State::Unsupported,
            vec!["No preparation adapter is implemented for this saved source".into()],
            vec![],
            warnings,
            false,
        );
    }
    let mut blockers = vec![];
    if !snapshot.destination_valid {
        blockers.push(
            "Correct the saved application URL or expired listing before refreshing this packet"
                .into(),
        );
    }
    if !snapshot.source_consistent {
        blockers
            .push("Correct the saved posting source so its platform label and host agree".into());
    }
    if flags.stale {
        return make(State::NeedsReview,vec!["Saved profile, resume, evidence or job changed; refresh the packet and review its new revision".into()],manual,warnings,true);
    }
    if !snapshot.resume_selected {
        blockers.insert(0, snapshot.resume_reason.into());
        return make(State::NeedsResume, blockers, vec![], warnings, false);
    }
    for field in fields {
        if field
            .answer_expires_at
            .is_some_and(|deadline| deadline <= now)
        {
            blockers.push(format!("Reconfirm expired answer: {}", field.question));
        }
        if field.required
            && !matches!(field.validation, Validation::FileUploadRequired)
            && (field.effective_answer.is_none_or(str::is_empty)
                || !matches!(field.validation, Validation::DraftReady))
        {
            blockers.push(format!("Answer required: {}", field.question));
        }
    }
    if !blockers.is_empty() {
        return make(State::NeedsInput, blockers, manual, warnings, false);
    }
    for field in fields {
        if field.effective_answer.is_some_and(|v| !v.is_empty())
            && field.requires_review
            && !field.reviewed
        {
            blockers.push(format!("Review answer: {}", field.question));
        }
    }
    if !blockers.is_empty() || !flags.approved {
        blockers.push(
            "Review the exact packet revision, selected resume and application destination".into(),
        );
        return make(State::NeedsReview, blockers, manual, warnings, false);
    }
    make(
        State::ReadyForManualHandoff,
        vec![],
        manual,
        warnings,
        false,
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::{Value, json};
    #[test]
    fn legacy_readiness_oracle_preserves_all_state_precedence_and_expiry_boundaries() {
        let corpus: Value = serde_json::from_str(include_str!(
            "../tests/fixtures/packet-readiness-corpus.json"
        ))
        .unwrap();
        let now = DateTime::parse_from_rfc3339(corpus["now"].as_str().unwrap())
            .unwrap()
            .with_timezone(&Utc);
        let warnings = vec!["Snapshot warning".to_string()];
        let destination_warnings = vec!["Destination warning".to_string()];
        for case in corpus["cases"].as_array().unwrap() {
            let bits = case[0].as_u64().unwrap();
            let variant = case[1].as_u64().unwrap() as usize;
            let result = case[2].as_u64().unwrap() as usize;
            let data = &corpus["fields"][variant];
            let fields = data
                .as_array()
                .unwrap()
                .iter()
                .map(|v| Field {
                    question: v["question"].as_str().unwrap(),
                    required: v["required"].as_bool().unwrap(),
                    effective_answer: v["effective_answer"].as_str(),
                    validation: match v["validation_status"].as_str().unwrap() {
                        "draft_ready" => Validation::DraftReady,
                        "needs_input" => Validation::NeedsInput,
                        "file_upload_required" => Validation::FileUploadRequired,
                        "provider_unavailable" => Validation::ProviderUnavailable,
                        "validation_failed" => Validation::ValidationFailed,
                        _ => panic!("invalid oracle variant"),
                    },
                    requires_review: v["requires_review"].as_bool().unwrap(),
                    reviewed: v["review_status"] == "reviewed",
                    answer_expires_at: v["answer_expires_at"]
                        .as_str()
                        .map(|s| DateTime::parse_from_rfc3339(s).unwrap().with_timezone(&Utc)),
                })
                .collect::<Vec<_>>();
            let value = calculate(
                Snapshot {
                    warnings: &warnings,
                    destination_warnings: &destination_warnings,
                    candidate_present: bits & 1 != 0,
                    preparation_supported: bits & 2 != 0,
                    destination_valid: bits & 4 != 0,
                    source_consistent: bits & 8 != 0,
                    resume_selected: bits & 16 != 0,
                    resume_reason: "Choose a confirmed resume",
                },
                &fields,
                Flags {
                    stale: bits & 32 != 0,
                    approved: bits & 64 != 0,
                    submitted: bits & 128 != 0,
                },
                now,
            );
            assert_eq!(
                json!(value),
                corpus["results"][result],
                "bits={bits} variant={variant}"
            );
        }
        assert_eq!(corpus["cases"].as_array().unwrap().len(), 3584);
    }
}
