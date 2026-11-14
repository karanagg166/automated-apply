use automated_apply_documents::{Mode, inspect};
use serde_json::Value;
#[test]
fn existing_pdf_worker_acceptance_and_safe_extraction_match_fictional_corpus() {
    let corpus: Value = serde_json::from_str(include_str!("fixtures/pdf-corpus.json")).unwrap();
    for case in corpus["pdfs"].as_array().unwrap() {
        let raw: Vec<u8> = serde_json::from_value(case["bytes"].clone()).unwrap();
        for (name, mode) in [("extract", Mode::Extract), ("validate", Mode::Validate)] {
            let result = inspect(&raw, mode);
            assert_eq!(
                result.is_ok(),
                case[name]["accepted"].as_bool().unwrap(),
                "{} {name}: {:?}",
                case["name"],
                result.as_ref().err()
            );
            if let Ok(value) = result
                && name == "extract"
            {
                assert_eq!(
                    value.pages as u64,
                    case[name]["pages"].as_u64().unwrap(),
                    "{}",
                    case["name"]
                );
                assert_eq!(
                    serde_json::to_value(value.links).unwrap(),
                    case[name]["links"],
                    "{}",
                    case["name"]
                );
                assert_eq!(
                    serde_json::to_value(value.text.split_whitespace().collect::<Vec<_>>())
                        .unwrap(),
                    case[name]["words"],
                    "{}",
                    case["name"]
                );
            }
        }
    }
}
