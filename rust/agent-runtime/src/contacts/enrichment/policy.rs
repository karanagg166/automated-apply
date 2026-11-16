//! Actual local-first decisions. Provider capability does not establish entitlement.
use super::*;
pub fn role_matches(role: Option<&str>, filters: &[Value]) -> bool {
    let value = automated_apply_domain::text::folded(role.unwrap_or("")).replace('-', " ");
    filters.is_empty()
        || filters.iter().any(|f| {
            let Some(f) = f.as_str() else {
                return false;
            };
            let f = automated_apply_domain::text::folded(f);
            let terms = match f.as_str() {
                "cto" => vec!["cto".to_owned(), "chief technology".to_owned()],
                "ceo" => vec!["ceo".to_owned(), "chief executive".to_owned()],
                "hr" => vec!["hr".to_owned(), "human resources".to_owned()],
                "recruiter" => vec!["recruit".to_owned(), "talent acquisition".to_owned()],
                _ => vec![f.replace('_', " ")],
            };
            terms.iter().any(|s| value.contains(s))
        })
}
pub fn needs_lookup(contact: &Value, ttl: i64, now: DateTime<Utc>) -> bool {
    if rules::truthy(&contact["do_not_contact"])
        || rules::truthy(&contact["human_corrected"])
        || rules::truthy(&contact["metadata_"]["identity_review_required"])
    {
        return false;
    }
    if rules::fresh(&contact["last_checked_at"], ttl, now) {
        if rules::truthy(&contact["email"])
            && matches!(
                contact["email_status"].as_str(),
                Some("verified" | "provider_reported")
            )
            && rules::fresh(&rules::email_observed_at(contact), ttl, now)
        {
            return false;
        }
        if contact["metadata_"]["evidence_strength"] == "strong"
            && rules::truthy(&contact["linkedin_url"])
        {
            return false;
        }
    }
    true
}
pub fn fallback_justified(previous: &Value, allow: bool, identifier: bool) -> bool {
    allow
        && identifier
        && previous["status"] == "completed"
        && previous["contacts"]
            .as_array()
            .is_some_and(|c| !c.is_empty() && !c.iter().any(|p| rules::truthy(&p["email"])))
}
pub fn saved_run(mut value: Value) -> Result<Value> {
    if !value.is_object() {
        return Err(invalid());
    }
    value.as_object_mut().unwrap().retain(|key, _| {
        matches!(
            key.as_str(),
            "id" | "company_id"
                | "state"
                | "target_roles"
                | "provider_plan"
                | "contact_ids"
                | "counts"
                | "usage"
                | "errors"
                | "started_at"
                | "completed_at"
        )
    });
    let states = [
        "not_configured",
        "authorization_required",
        "queued",
        "running",
        "completed",
        "not_found",
        "rate_limited",
        "budget_exhausted",
        "failed",
        "unsupported_operation",
        "billing_uncertain",
    ];
    if !value["state"].as_str().is_some_and(|s| states.contains(&s)) {
        return Err(invalid());
    }
    for (key, max) in [
        ("target_roles", 20),
        ("provider_plan", 2),
        ("contact_ids", 25),
        ("usage", 100),
        ("errors", 100),
    ] {
        if value[key].as_array().is_none_or(|a| a.len() > max) {
            return Err(invalid());
        }
    }
    if value["target_roles"]
        .as_array()
        .unwrap()
        .iter()
        .any(|v| v.as_str().is_none_or(|s| s.chars().count() > 255))
        || value["contact_ids"]
            .as_array()
            .unwrap()
            .iter()
            .any(|v| v.as_str().and_then(|s| s.parse::<Uuid>().ok()).is_none())
    {
        return Err(invalid());
    }
    // Provider plan in original runs is a list of selected provider names.
    if value["provider_plan"]
        .as_array()
        .unwrap()
        .iter()
        .any(|p| !matches!(p.as_str(), Some("apollo" | "signalhire")))
    {
        return Err(invalid());
    }
    let counts = value["counts"].as_object().ok_or_else(invalid)?;
    let mut safe_counts = serde_json::Map::new();
    if let Some(n) = counts.get("contacts") {
        if n.as_u64().is_none_or(|n| n > 25) {
            return Err(invalid());
        }
        safe_counts.insert("contacts".into(), n.clone());
    }
    if let Some(n) = counts.get("outbound_messages_sent") {
        if n != &json!(0) {
            return Err(invalid());
        }
        safe_counts.insert("outbound_messages_sent".into(), n.clone());
    }
    if let Some(research) = counts.get("candidate_research") {
        let rows = research
            .as_array()
            .filter(|rows| rows.len() <= 25)
            .ok_or_else(invalid)?;
        let mut retained = Vec::new();
        for row in rows {
            let id = row["contact_id"]
                .as_str()
                .and_then(|s| s.parse::<Uuid>().ok())
                .ok_or_else(invalid)?;
            let candidates = row["candidates"]
                .as_array()
                .filter(|c| c.len() <= 6)
                .ok_or_else(invalid)?;
            let mut safe = Vec::new();
            for candidate in candidates {
                let email = candidate["email"]
                    .as_str()
                    .filter(|s| s.len() <= 255)
                    .ok_or_else(invalid)?;
                crate::profile_contract::email(email).map_err(|_| invalid())?;
                let pattern = candidate["pattern_used"]
                    .as_str()
                    .filter(|s| s.len() <= 255)
                    .ok_or_else(invalid)?;
                let score = candidate["confidence_score"]
                    .as_f64()
                    .filter(|n| n.is_finite() && (0.0..=1.0).contains(n))
                    .ok_or_else(invalid)?;
                if candidate["status"] != "candidate" {
                    return Err(invalid());
                }
                safe.push(json!({"email":email,"pattern_used":pattern,"status":"candidate","confidence_score":score,"disclaimer":"This is an inferred candidate pattern, NOT a verified mailbox."}));
            }
            retained.push(json!({"contact_id":id,"candidates":safe}));
        }
        safe_counts.insert("candidate_research".into(), json!(retained));
    }
    let usage = value["usage"]
        .as_array()
        .unwrap()
        .iter()
        .map(|u| {
            if !matches!(u["provider"].as_str(), Some("apollo" | "signalhire"))
                || !u["state"].as_str().is_some_and(|s| states.contains(&s))
                || !matches!(
                    u["operation"].as_str(),
                    Some("search_people" | "enrich_person")
                )
            {
                return Err(invalid());
            }
            let mut selected = serde_json::Map::new();
            for key in [
                "provider",
                "state",
                "operation",
                "reserved_estimate",
                "confirmed_provider_credits",
            ] {
                if let Some(v) = u.get(key) {
                    if matches!(key, "reserved_estimate" | "confirmed_provider_credits")
                        && !v.is_null()
                        && v.as_f64().is_none_or(|n| !n.is_finite() || n < 0.0)
                    {
                        return Err(invalid());
                    }
                    selected.insert(key.into(), v.clone());
                }
            }
            Ok(Value::Object(selected))
        })
        .collect::<Result<Vec<_>>>()?;
    value["counts"] = json!(safe_counts);
    let error_count = value["errors"].as_array().unwrap().len();
    value["errors"] = json!(if error_count > 0 {
        vec!["historical_provider_error_requires_review"]
    } else {
        vec![]
    });
    value["retained_error_count"] = json!(error_count);
    value["usage"] = json!(usage);
    value["record_basis"] = json!("retained_enrichment_run");
    value["live_verified"] = json!(false);
    Ok(value)
}
