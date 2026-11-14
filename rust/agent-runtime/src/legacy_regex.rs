//! Fixed English safeguard patterns with frozen Python Unicode semantics and bounded work.
//! Not a general regex API: arbitrary patterns or non-ASCII pattern literals are forbidden.
use crate::{
    Failure, Result,
    profile_contract::{legacy_decimal, legacy_word},
};
use fancy_regex::{Regex as FancyRegex, RegexBuilder};

pub(crate) struct Regex {
    regex: FancyRegex,
    insensitive: bool,
}
pub(crate) struct Match {
    pub start: usize,
    pub end: usize,
    pub text: String,
}
fn whitespace(c: char) -> bool {
    c.is_whitespace() || ('\u{1c}'..='\u{1f}').contains(&c)
}
fn projected(text: &str, insensitive: bool) -> (String, Vec<usize>) {
    let mut output = String::with_capacity(text.len());
    let mut offsets = Vec::with_capacity(text.len() + 1);
    for (at, c) in text.char_indices() {
        let mapped = match c {
            '\u{1c}'..='\u{1f}' => '\t',
            'İ' | 'ı' if insensitive => 'i',
            'ſ' if insensitive => 's',
            'K' if insensitive => 'k',
            c if c.is_ascii() || whitespace(c) => c,
            c if legacy_decimal(c) => '٠',
            c if legacy_word(c) => 'λ',
            _ => '§',
        };
        output.push(mapped);
        offsets.extend(std::iter::repeat_n(at, mapped.len_utf8()));
    }
    offsets.push(text.len());
    (output, offsets)
}
impl Regex {
    pub fn new(pattern: &'static str, insensitive: bool) -> Self {
        assert!(
            pattern.is_ascii(),
            "safeguard patterns must be fixed ASCII literals"
        );
        let regex = RegexBuilder::new(pattern)
            .case_insensitive(insensitive)
            .backtrack_limit(100_000)
            .build()
            .expect("fixed bounded safeguard pattern");
        Self { regex, insensitive }
    }
    pub fn is_match(&self, text: &str) -> Result<bool> {
        let (input, _) = projected(text, self.insensitive);
        self.regex
            .is_match(&input)
            .map_err(|_| Failure("grounding_pattern_limit"))
    }
    pub fn find(&self, text: &str) -> Result<Vec<Match>> {
        let (input, offsets) = projected(text, self.insensitive);
        self.regex
            .find_iter(&input)
            .map(|item| {
                let found = item.map_err(|_| Failure("grounding_pattern_limit"))?;
                let start = offsets[found.start()];
                let end = offsets[found.end()];
                Ok(Match {
                    start,
                    end,
                    text: text[start..end].into(),
                })
            })
            .collect()
    }
    pub fn first_group(&self, text: &str, index: usize) -> Result<Option<String>> {
        let (input, offsets) = projected(text, self.insensitive);
        Ok(self
            .regex
            .captures(&input)
            .map_err(|_| Failure("grounding_pattern_limit"))?
            .and_then(|groups| {
                groups
                    .get(index)
                    .map(|found| text[offsets[found.start()]..offsets[found.end()]].into())
            }))
    }
    pub fn split<'a>(&self, text: &'a str) -> Result<Vec<&'a str>> {
        let mut result = Vec::new();
        let mut start = 0;
        for found in self.find(text)? {
            result.push(&text[start..found.start]);
            start = found.end;
        }
        result.push(&text[start..]);
        Ok(result)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::{Value, json};
    #[test]
    fn fixed_guard_patterns_preserve_python_word_digit_case_and_whitespace_semantics() {
        let cases: Vec<Value> =
            serde_json::from_str(include_str!("../tests/fixtures/guard-regex-corpus.json"))
                .unwrap();
        for (i, case) in cases.iter().enumerate() {
            let pattern = match case["pattern"].as_str().unwrap() {
                "person" => r"\b(?:I|my)\b",
                "number" => r"\b\d[\d,.]*(?:%|[kKmMbB])?\b",
                "name" => r"\b[A-Z][A-Za-z0-9+#]*(?:[.][A-Za-z]+)?\b",
                "sentence" => r"(?<=[.!?])\s+|\n",
                "work" => r"\bI (?:built|implemented|worked|developed|designed)\b",
                "challenge" => r"\b(?:challeng\w*|bugs?|failure)\b",
                _ => panic!("unrecognized fixture pattern"),
            };
            let regex = Regex::new(pattern, case["insensitive"].as_bool().unwrap());
            let text = case["text"].as_str().unwrap();
            let result: Vec<_> = regex
                .find(text)
                .unwrap()
                .into_iter()
                .map(|m| m.text)
                .collect();
            assert_eq!(json!(result), case["output"], "case{i} text{text:?}");
        }
    }
}
