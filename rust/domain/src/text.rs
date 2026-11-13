use regex::Regex;
use std::{
    collections::{HashMap, HashSet},
    sync::LazyLock,
};

pub fn folded(value: &str) -> String {
    static TABLE: LazyLock<HashMap<char, String>> =
        LazyLock::new(|| serde_json::from_str(include_str!("../data/unicode_fold.json")).unwrap());
    let mut result = String::with_capacity(value.len());
    for c in value.chars() {
        if c.is_ascii() {
            result.push(c.to_ascii_lowercase());
        } else if let Some(replacement) = TABLE.get(&c) {
            result.push_str(replacement);
        } else {
            result.push(c);
        }
    }
    result
}
pub fn lowered(value: &str) -> String {
    static TABLE: LazyLock<HashMap<char, String>> =
        LazyLock::new(|| serde_json::from_str(include_str!("../data/unicode_lower.json")).unwrap());
    static CASED: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"^\p{Cased}$").unwrap());
    static IGNORABLE: LazyLock<Regex> =
        LazyLock::new(|| Regex::new(r"^\p{Case_Ignorable}$").unwrap());
    let characters = value.chars().collect::<Vec<_>>();
    let mut result = String::with_capacity(value.len());
    for (i, &c) in characters.iter().enumerate() {
        if c == 'Σ' {
            let before = characters[..i]
                .iter()
                .rev()
                .find(|c| !IGNORABLE.is_match(&c.to_string()))
                .is_some_and(|c| CASED.is_match(&c.to_string()));
            let after = characters[i + 1..]
                .iter()
                .find(|c| !IGNORABLE.is_match(&c.to_string()))
                .is_some_and(|c| CASED.is_match(&c.to_string()));
            result.push(if before && !after { 'ς' } else { 'σ' });
        } else if c.is_ascii() {
            result.push(c.to_ascii_lowercase());
        } else if let Some(replacement) = TABLE.get(&c) {
            result.push_str(replacement);
        } else {
            result.push(c);
        }
    }
    result
}
pub fn skill_key(value: &str) -> String {
    let value = folded(value)
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(" ");
    match value.as_str() {
        "react.js" | "reactjs" | "react js" => "react",
        "node.js" | "node js" => "nodejs",
        "next.js" | "next js" => "nextjs",
        "express" | "express.js" | "express js" => "expressjs",
        "java script" => "javascript",
        "type script" => "typescript",
        "postgres" => "postgresql",
        "mongo db" => "mongodb",
        "socket.io" | "socket io" => "socketio",
        "fast api" => "fastapi",
        _ => return value,
    }
    .to_owned()
}
pub fn title_key(value: &str) -> String {
    static FAMILY: LazyLock<Vec<(Regex, &str)>> = LazyLock::new(|| {
        vec![
            (
                Regex::new(r"\bfull[-\u{2010}-\u{2015}\s]*stack\b").unwrap(),
                "full stack",
            ),
            (
                Regex::new(r"\bfront[-\u{2010}-\u{2015}\s]*end\b").unwrap(),
                "frontend",
            ),
            (
                Regex::new(r"\bback[-\u{2010}-\u{2015}\s]*end\b").unwrap(),
                "backend",
            ),
        ]
    });
    static WEB: LazyLock<Regex> = LazyLock::new(|| {
        Regex::new(r"\b(backend|frontend|full stack) web (developer|engineer)\b").unwrap()
    });
    let mut value = folded(value)
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(" ");
    for (regex, replacement) in FAMILY.iter() {
        value = regex.replace_all(&value, *replacement).into_owned();
    }
    WEB.replace_all(&value, "$1 $2").into_owned()
}

pub fn description_text(value: &str) -> String {
    static TAGS: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"<[^>]*>").unwrap());
    lowered(&unescape_html(&TAGS.replace_all(value, " ")))
}
pub fn bounded_skill_present(skill: &str, text: &str) -> bool {
    use std::sync::{Arc, Mutex};
    static CACHE: LazyLock<Mutex<HashMap<String, Arc<Regex>>>> =
        LazyLock::new(|| Mutex::new(HashMap::new()));
    let compiled = {
        let mut cache = CACHE.lock().unwrap_or_else(|e| e.into_inner());
        if let Some(regex) = cache.get(skill) {
            regex.clone()
        } else {
            let pattern = format!(
                r"(?:^|[^\p{{L}}\p{{N}}_+#]){}(?:$|[^\p{{L}}\p{{N}}_+#])",
                regex::escape(skill)
            );
            let Ok(regex) = Regex::new(&pattern) else {
                return false;
            };
            let regex = Arc::new(regex);
            if cache.len() >= 256 {
                cache.clear();
            }
            cache.insert(skill.into(), regex.clone());
            regex
        }
    };
    compiled.is_match(text)
}

/// HTML5 character references, including legacy semicolonless prefixes and C1 remaps.
/// Public tables are frozen from the existing Python contract, not fetched at runtime.
pub fn unescape_html(value: &str) -> String {
    static REFERENCES: LazyLock<Regex> = LazyLock::new(|| {
        Regex::new(r"&(#(?:[0-9]+|[xX][0-9a-fA-F]+);?|[^\t\n\x0C <&#;]{1,32};?)").unwrap()
    });
    static NAMED: LazyLock<HashMap<String, String>> =
        LazyLock::new(|| serde_json::from_str(include_str!("../data/html5.json")).unwrap());
    static NUMERIC: LazyLock<HashMap<String, String>> =
        LazyLock::new(|| serde_json::from_str(include_str!("../data/html_numeric.json")).unwrap());
    static INVALID: LazyLock<HashSet<u32>> =
        LazyLock::new(|| serde_json::from_str(include_str!("../data/html_invalid.json")).unwrap());
    REFERENCES
        .replace_all(value, |captures: &regex::Captures<'_>| {
            let name = &captures[1];
            if let Some(number) = name.strip_prefix('#') {
                let number = number.trim_end_matches(';');
                let parsed = if number.starts_with(['x', 'X']) {
                    u32::from_str_radix(&number[1..], 16)
                } else {
                    number.parse::<u32>()
                };
                let Ok(code) = parsed else {
                    return "\u{fffd}".to_owned();
                };
                if let Some(replacement) = NUMERIC.get(&code.to_string()) {
                    return replacement.clone();
                }
                if (0xd800..=0xdfff).contains(&code) || code > 0x10ffff {
                    return "\u{fffd}".to_owned();
                }
                if INVALID.contains(&code) {
                    return String::new();
                }
                return char::from_u32(code).unwrap_or('\u{fffd}').to_string();
            }
            if let Some(replacement) = NAMED.get(name) {
                return replacement.clone();
            }
            for (index, _) in name.char_indices().rev().filter(|(i, _)| *i > 0) {
                if let Some(replacement) = NAMED.get(&name[..index]) {
                    return format!("{}{}", replacement, &name[index..]);
                }
            }
            format!("&{name}")
        })
        .into_owned()
}
