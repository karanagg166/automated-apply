//! Local inferred patterns. None is a verified address or permission to send.
use super::*;
use unicode_normalization::UnicodeNormalization;
fn clean(raw: &str) -> String {
    raw.nfkd()
        .filter(char::is_ascii)
        .filter(char::is_ascii_alphanumeric)
        .map(|c| c.to_ascii_lowercase())
        .collect()
}
pub fn generate(first: &str, last: &str, domain: &str, known: Option<&str>) -> Result<Vec<Value>> {
    let domain =
        lookups::domain(domain).ok_or(Failure("contact_company_domain_review_required"))?;
    let first = clean(first);
    let last = clean(last);
    if first.is_empty() && last.is_empty() {
        return Ok(Vec::new());
    }
    let f = first.get(..1).unwrap_or("");
    let l = last.get(..1).unwrap_or("");
    let mut candidates = Vec::new();
    let mut seen = BTreeSet::new();
    let templates = [
        "{first}.{last}@{domain}",
        "{first}@{domain}",
        "{first}{last}@{domain}",
        "{f}{last}@{domain}",
        "{first}{l}@{domain}",
        "{last}.{first}@{domain}",
    ];
    for (template, score, label) in known
        .into_iter()
        .filter(|s| s.len() <= 255)
        .map(|s| (s, 0.75, format!("known_company_pattern:{s}")))
        .chain(templates.into_iter().map(|s| (s, 0.40, s.to_owned())))
    {
        if template.contains("{first}") && first.is_empty()
            || template.contains("{last}") && last.is_empty()
            || template.contains("{f}") && f.is_empty()
            || template.contains("{l}") && l.is_empty()
        {
            continue;
        }
        let mut email = template.to_owned();
        for (key, value) in [
            ("{first}", first.as_str()),
            ("{last}", last.as_str()),
            ("{f}", f),
            ("{l}", l),
            ("{domain}", domain.as_str()),
        ] {
            email = email.replace(key, value);
        }
        if email.contains(['{', '}'])
            || rules::business_email(&email, &domain).is_none()
            || !seen.insert(email.clone())
        {
            continue;
        }
        candidates.push(json!({"email":email,"pattern_used":label,"status":"candidate","confidence_score":score,"disclaimer":"This is an inferred candidate pattern, NOT a verified mailbox."}));
    }
    Ok(candidates)
}
