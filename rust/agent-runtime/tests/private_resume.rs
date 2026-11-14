use automated_apply_agents::{Failure, private_resume::Settings, resume_suggestions};
use serde_json::Value;
use std::collections::BTreeMap;
fn corpus() -> Value {
    serde_json::from_str(include_str!(
        "../../document-worker/tests/fixtures/pdf-corpus.json"
    ))
    .unwrap()
}
#[test]
fn existing_fernet_resume_bytes_decrypt_without_key_or_ciphertext_migration() {
    let corpus = corpus();
    let key = corpus["fernet"]["key"].as_str().unwrap();
    let settings = Settings::from_values(&BTreeMap::from([(
        "RESUME_ENCRYPTION_KEY".into(),
        key.into(),
    )]))
    .unwrap();
    for case in corpus["fernet"]["cases"].as_array().unwrap() {
        let expected: Vec<u8> = serde_json::from_value(case["raw"].clone()).unwrap();
        let token = case["token"].as_str().unwrap();
        let digest = case["sha256"].as_str().unwrap();
        assert_eq!(
            settings.verified(token.as_bytes(), digest).unwrap(),
            expected
        );
        let mut corrupt = token.as_bytes().to_vec();
        corrupt[30] ^= 1;
        assert_eq!(
            settings.verified(&corrupt, digest),
            Err(Failure("private_pdf_integrity_failed"))
        );
        assert_eq!(
            settings.verified(token.as_bytes(), &"0".repeat(64)),
            Err(Failure("private_pdf_checksum_failed"))
        );
    }
    let unavailable = Settings::from_values(&BTreeMap::new()).unwrap();
    assert_eq!(
        unavailable.verified(b"token", "digest"),
        Err(Failure("resume_encryption_unavailable"))
    );
}
#[test]
fn resume_import_suggestions_match_existing_untrusted_python_extraction() {
    for case in corpus()["suggestions"].as_array().unwrap() {
        assert_eq!(
            resume_suggestions::suggestions(case["text"].as_str().unwrap()).unwrap(),
            case["output"],
            "{}",
            case["text"]
        );
    }
}
