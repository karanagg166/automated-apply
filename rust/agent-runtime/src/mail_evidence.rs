//! Bounded selected-message evidence. Raw message bodies never leave this computation.
use crate::{Failure, Result, context_contract::python_space, resources::public_https};
use automated_apply_domain::text::folded;
use base64::{
    Engine,
    engine::{DecodePaddingMode, GeneralPurpose, GeneralPurposeConfig, general_purpose::STANDARD},
};
use html5gum::{State, Token, Tokenizer};
use regex::Regex;
use serde_json::{Value, json};
use std::{collections::BTreeMap, sync::LazyLock};

pub fn headers(message: &Value) -> BTreeMap<String, String> {
    let mut result = BTreeMap::new();
    for header in message["payload"]["headers"]
        .as_array()
        .into_iter()
        .flatten()
        .take(100)
    {
        let (Some(name), Some(value)) = (header["name"].as_str(), header["value"].as_str()) else {
            continue;
        };
        let name = folded(name);
        if [
            "from",
            "to",
            "cc",
            "bcc",
            "subject",
            "date",
            "message-id",
            "authentication-results",
        ]
        .contains(&name.as_str())
        {
            result.entry(name).or_insert_with(|| {
                value
                    .split(python_space)
                    .filter(|s| !s.is_empty())
                    .collect::<Vec<_>>()
                    .join(" ")
                    .chars()
                    .take(1000)
                    .collect()
            });
        }
    }
    result
}
pub fn decoded_body(encoded: &str, limit: usize) -> Result<Vec<u8>> {
    if encoded.len() > 350000 {
        return Err(Failure("gmail_mime_limits"));
    }
    let mut encoded = encoded.replace('-', "+").replace('_', "/");
    while !encoded.len().is_multiple_of(4) {
        encoded.push('=');
    }
    let engine = GeneralPurpose::new(
        &base64::alphabet::STANDARD,
        GeneralPurposeConfig::new()
            .with_decode_padding_mode(DecodePaddingMode::Indifferent)
            .with_decode_allow_trailing_bits(true),
    );
    let raw = engine
        .decode(encoded)
        .map_err(|_| Failure("gmail_mime_invalid"))?;
    if raw.len() > limit {
        return Err(Failure("gmail_mime_limits"));
    }
    Ok(raw)
}
fn add_link(links: &mut Vec<String>, value: String) {
    if links.len() < 200 {
        links.push(value);
    }
}
fn html(input: &str, links: &mut Vec<String>) -> Result<String> {
    let mut tokenizer = Tokenizer::new(input);
    let mut hidden: Vec<Vec<u8>> = vec![];
    let mut text = String::new();
    let mut count = 0usize;
    while let Some(token) = tokenizer.next() {
        count += 1;
        if count > 100000 {
            return Err(Failure("gmail_mime_limits"));
        }
        match token.map_err(|_| Failure("gmail_mime_invalid"))? {
            Token::StartTag(tag) => {
                let name = tag.name.as_slice();
                if [b"script".as_slice(), b"style", b"head", b"template"].contains(&name) {
                    if hidden.len() >= 100 {
                        return Err(Failure("gmail_mime_limits"));
                    }
                    // HTML self-closing syntax does not make script/style content safe.
                    // The default emitter already records the emitted start tag.
                    hidden.push(name.to_vec());
                    if name == b"script" {
                        tokenizer.set_state(State::ScriptData);
                    } else if name == b"style" {
                        tokenizer.set_state(State::RawText);
                    }
                } else if name == b"a"
                    && hidden.is_empty()
                    && let Some(value) = tag.attributes.get(b"href".as_slice())
                {
                    add_link(links, String::from_utf8_lossy(&value.value).into_owned());
                }
            }
            Token::EndTag(tag) => {
                if hidden
                    .last()
                    .is_some_and(|name| name.as_slice() == tag.name.as_slice())
                {
                    hidden.pop();
                }
            }
            Token::String(value) if hidden.is_empty() => {
                if !text.is_empty() {
                    text.push(' ');
                }
                text.push_str(&String::from_utf8_lossy(&value.value));
            }
            _ => {}
        }
    }
    Ok(text)
}
static URLS: LazyLock<Regex> = LazyLock::new(|| Regex::new(r#"https://[^\s<>"']+"#).unwrap());
static SIGNALS: LazyLock<Vec<(&'static str, Regex)>> = LazyLock::new(|| {
    [
    ("possible_interview",r"\binterview\b"),
    ("possible_rejection",r"\b(?:unfortunately|not moving forward)\b"),
    ("possible_acknowledgment",r"\b(?:application received|received your application)\b"),
    ("possible_job_lead",r"\b(?:job alert|vacanc|hiring|open position|job opening)\b"),
    ("possible_recruiter_response",r"\b(?:recruit(?:er|ing|ment)|talent acquisition)\b.{0,100}\b(?:response|reply|opportunity|reach(?:ing)? out|discuss)\b"),
    ("possible_follow_up_request",r"\b(?:please|kindly)\b.{0,100}\b(?:provide|share|reply|respond|confirm|complete|send)\b|\bfollow[ -]?up\b"),
    ("possible_status_update",r"\b(?:application status|status of your application|application update|under review|next stage|next steps)\b"),
].into_iter().map(|(name,pattern)|(name,Regex::new(pattern).unwrap())).collect()
});
struct Evidence {
    bytes: usize,
    parts: usize,
    texts: Vec<String>,
    links: Vec<String>,
}
impl Evidence {
    fn walk(&mut self, part: &Value, depth: usize) -> Result<()> {
        self.parts += 1;
        if depth > 12 || self.parts > 100 || !part.is_object() {
            return Err(Failure("gmail_mime_limits"));
        }
        if part
            .get("filename")
            .is_some_and(|v| v.as_str().is_none_or(|s| !s.is_empty()))
            || part["body"]
                .get("attachmentId")
                .is_some_and(|v| !v.is_null() && v != false && v != "")
        {
            return Ok(());
        }
        if matches!(part["mimeType"].as_str(), Some("text/plain" | "text/html")) {
            let encoded = part["body"]
                .get("data")
                .and_then(Value::as_str)
                .or_else(|| part["body"].get("data").is_none().then_some(""))
                .ok_or(Failure("gmail_mime_limits"))?;
            let raw = decoded_body(encoded, 262144 - self.bytes)?;
            self.bytes += raw.len();
            let mut text = String::from_utf8_lossy(&raw).into_owned();
            if part["mimeType"] == "text/html" {
                text = html(&text, &mut self.links)?;
            }
            for found in URLS.find_iter(&text) {
                add_link(&mut self.links, found.as_str().to_owned());
            }
            self.texts.push(text);
        }
        if let Some(parts) = part.get("parts") {
            for child in parts.as_array().ok_or(Failure("gmail_mime_limits"))? {
                self.walk(child, depth + 1)?;
            }
        }
        Ok(())
    }
}
pub fn content_evidence(payload: &Value) -> Result<Value> {
    let mut evidence = Evidence {
        bytes: 0,
        parts: 0,
        texts: vec![],
        links: vec![],
    };
    evidence.walk(payload, 0)?;
    let mut safe = vec![];
    for link in evidence.links {
        if let Some(valid) = public_https(&link)
            && let Ok(mut parsed) = reqwest::Url::parse(&valid)
        {
            parsed.set_query(None);
            parsed.set_fragment(None);
            let clean = parsed.to_string();
            if !safe.contains(&clean) {
                safe.push(clean);
                if safe.len() == 25 {
                    break;
                }
            }
        }
    }
    let text = folded(&evidence.texts.join(" "));
    let signals = SIGNALS
        .iter()
        .filter(|(_, pattern)| pattern.is_match(&text))
        .map(|(name, _)| *name)
        .collect::<Vec<_>>();
    Ok(
        json!({"links":safe,"signals":signals,"verification_status":"requires_review","submission_confirmed":false,"signal_basis":"selected_message_body_keywords","status_confirmed":false}),
    )
}
/// RFC5322 parsing is used only after bounded, unfolded header selection.
pub fn single_address(raw: &str) -> Option<String> {
    if raw.len() > 1000 || raw.chars().any(|c| c == '\r' || c == '\n') {
        return None;
    }
    let header = format!("{raw}\r\n");
    let parsed = mail_parser::parsers::MessageStream::new(header.as_bytes()).parse_address();
    let addresses = parsed.as_address()?;
    let list = addresses.as_list()?;
    (list.len() == 1)
        .then(|| list[0].address().map(folded))
        .flatten()
}
// Keep the dependency's standard encoding explicit for MIME output helpers.
pub fn encoded(raw: &[u8]) -> String {
    STANDARD.encode(raw).replace('+', "-").replace('/', "_")
}
