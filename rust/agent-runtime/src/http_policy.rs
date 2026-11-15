//! Frozen build-time policy shared with the Next.js BFF and legacy API boundary.
use regex::Regex;
use serde_json::Value;
use std::sync::LazyLock;

static APPROVALS: LazyLock<Vec<Regex>> = LazyLock::new(|| {
    let policy: Value = serde_json::from_str(include_str!("../../../contracts/http-security.json"))
        .expect("checked HTTP policy");
    assert_eq!(policy["schema_version"], 1);
    policy["owner_approval"]
        .as_array()
        .expect("checked approval list")
        .iter()
        .map(|v| {
            Regex::new(v.as_str().expect("checked approval pattern")).expect("checked shared regex")
        })
        .collect()
});
pub fn requires_owner_approval(path: &str, method: &str) -> bool {
    method == "POST"
        && path
            .strip_prefix("/api/v1/")
            .is_some_and(|path| APPROVALS.iter().any(|p| p.is_match(path)))
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn owner_proof_patterns_bind_exact_sensitive_paths_and_methods() {
        let id = "00000000-0000-0000-0000-000000000001";
        for path in [
            format!("/api/v1/application-answers/missing/{id}/approve"),
            format!("/api/v1/application-answers/drafts/{id}/approve-reuse"),
            format!("/api/v1/browser-applications/{id}/authorize-submission"),
        ] {
            assert!(requires_owner_approval(&path, "POST"));
            assert!(!requires_owner_approval(&path, "GET"));
            assert!(!requires_owner_approval(&(path + "/extra"), "POST"));
        }
        assert!(!requires_owner_approval(
            "/api/v1/application-answers/generate",
            "POST"
        ));
    }
}
