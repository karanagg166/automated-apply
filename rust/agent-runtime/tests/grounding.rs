use automated_apply_agents::{
    extractive::{self, Instructions},
    grounding::{self, Fact, ModelAnswer},
};
use serde_json::{Value, json};
#[test]
fn extractive_sentences_quotes_and_grounding_differential_corpus() {
    let corpus: Value =
        serde_json::from_str(include_str!("fixtures/grounding-corpus.json")).unwrap();
    let mut errors = Vec::new();
    for (i, case) in corpus["preparations"]
        .as_array()
        .unwrap()
        .iter()
        .enumerate()
    {
        let instructions = Instructions {
            max_characters: case["instructions"]["max_characters"].as_u64().unwrap() as usize,
            max_words: case["instructions"]["max_words"]
                .as_u64()
                .map(|n| n as usize),
        };
        let prepared = extractive::prepare(
            case["question"].as_str().unwrap(),
            &case["context"],
            instructions,
        )
        .unwrap();
        let value = serde_json::to_value(&prepared).unwrap();
        if value != case["output"] {
            errors.push(format!(
                "prepare{i} question{} actual{value} expected{}",
                case["question"], case["output"]
            ));
            continue;
        }
        for (j, matched) in case["matches"].as_array().unwrap().iter().enumerate() {
            let facts: Vec<Fact> =
                serde_json::from_value(case["context"]["evidence"].clone()).unwrap();
            let (content, error) = extractive::match_answer(
                matched["answer"].as_str().unwrap(),
                &prepared,
                &facts,
                instructions,
            )
            .unwrap();
            if json!(content) != matched["content"] || json!(error) != matched["error"] {
                errors.push(format!(
                    "match{i}/{j}: actual{} {} expected{} {}",
                    json!(content),
                    json!(error),
                    matched["content"],
                    matched["error"]
                ));
            }
        }
    }
    for (i, case) in corpus["validations"].as_array().unwrap().iter().enumerate() {
        let content = ModelAnswer::parse(case["content"].clone()).unwrap();
        let facts: Vec<Fact> = serde_json::from_value(case["facts"].clone()).unwrap();
        let opportunity: Vec<Fact> = serde_json::from_value(case["opportunity"].clone()).unwrap();
        let result = grounding::validate(
            &content,
            &facts,
            case["max_characters"].as_u64().unwrap() as usize,
            case["max_words"].as_u64().map(|n| n as usize),
            &opportunity,
        )
        .unwrap();
        if json!(result) != case["error"] {
            errors.push(format!(
                "validation{i}: got{} expected{}",
                json!(result),
                case["error"]
            ));
        }
    }
    for (i, case) in corpus["models"].as_array().unwrap().iter().enumerate() {
        let result = ModelAnswer::parse(case["input"].clone());
        if result.is_ok() != case["accepted"].as_bool().unwrap() {
            errors.push(format!("model{i} acceptance mismatch"));
        }
        if let Ok(value) = result
            && json!(value) != case["output"]
        {
            errors.push(format!("model{i} output mismatch"));
        }
    }
    assert!(
        errors.is_empty(),
        "{} differences:\n{}",
        errors.len(),
        errors
            .iter()
            .take(12)
            .cloned()
            .collect::<Vec<_>>()
            .join("\n")
    );
}
