//! Fixed compositional grammar. Neither successful interpretation nor classifier output is authority.
use super::{Intent, normalize};
use crate::{
    Failure, Result,
    legacy_regex::{Match, Regex},
};
use automated_apply_domain::text::folded;
use serde_json::{Value, json};
use std::sync::LazyLock;
macro_rules! rx {
    ($pattern:literal) => {
        rx!($pattern, false)
    };
    ($pattern:literal,$insensitive:literal) => {{
        static VALUE: LazyLock<Regex> = LazyLock::new(|| Regex::new($pattern, $insensitive));
        &*VALUE
    }};
}
fn kind(category: &str) -> Result<Intent> {
    normalize(json!({"category":category}))
}
fn unknown() -> Result<Intent> {
    kind("UNKNOWN")
}
fn make(category: &str, fields: Value) -> Result<Intent> {
    let mut fields = fields;
    fields["category"] = json!(category);
    normalize(fields)
}
fn cut(text: &str, n: usize) -> String {
    text.chars().take(n).collect()
}
fn group(groups: &Option<Vec<Option<Match>>>, n: usize) -> Option<&str> {
    groups.as_ref()?.get(n)?.as_ref().map(|m| m.text.as_str())
}
fn replace(
    text: &str,
    pattern: &Regex,
    mut substitution: impl FnMut(&str) -> String,
) -> Result<String> {
    let mut output = String::new();
    let mut start = 0;
    for found in pattern.find(text)? {
        output.push_str(&text[start..found.start]);
        output.push_str(&substitution(&found.text));
        start = found.end;
    }
    output.push_str(&text[start..]);
    Ok(output)
}
fn remove(text: &str, pattern: &Regex) -> Result<String> {
    replace(text, pattern, |_| " ".into())
}
fn number(text: &str, max: i64) -> Result<u16> {
    let invalid = || Failure("invalid_conversation_intent");
    if text.is_empty() {
        return Err(invalid());
    }
    let mut value = 0u32;
    for c in text.chars() {
        let digit = crate::profile_contract::decimal_digit(c).ok_or_else(invalid)?;
        value = value
            .checked_mul(10)
            .and_then(|n| n.checked_add(digit))
            .filter(|n| *n <= max as u32)
            .ok_or_else(invalid)?;
    }
    if value == 0 {
        return Err(invalid());
    }
    Ok(value as u16)
}
pub(super) fn unsafe_request(text: &str) -> Result<bool> {
    rx!(r"[;`]|ignore .*instructions|system prompt|\bexecute\b|\bshell\b|password|access.?token|api.?key|send (?:an? |the )?email|\bsubmit\b|\bbypass\b|\boverride\b|disable .*approval",true).is_match(text)
}
pub(super) fn parse(text: &str) -> Result<Intent> {
    inner(text, 0)
}
fn inner(text: &str, depth: u8) -> Result<Intent> {
    let trimmed = crate::grounding::trim(text);
    if depth > 64 || !(1..=2048).contains(&trimmed.chars().count()) || unsafe_request(text)? {
        return unknown();
    }
    let original = text
        .replace('’', "'")
        .split(crate::grounding::whitespace)
        .filter(|s| !s.is_empty())
        .collect::<Vec<_>>()
        .join(" ");
    let original = original.trim_end_matches(['.', '?', '!']);
    let original = replace(original, rx!(r"\b\w+\b"), |word| {
        match folded(word).as_str() {
            "applicaton" | "aplication" => "application".into(),
            "aplications" => "applications".into(),
            "conected" | "connnected" => "connected".into(),
            "remtoe" => "remote".into(),
            "pyhton" => "Python".into(),
            "staus" => "status".into(),
            "jbos" => "jobs".into(),
            "develper" => "developer".into(),
            _ => word.into(),
        }
    })?;
    let original = replace(
        &original,
        rx!(
            r"^(?:(?:hi|hello|hey)[,!. ]+)?(?:please |could you |can you )?",
            true
        ),
        |_| String::new(),
    )?;
    let value = folded(&original);
    let limit = rx!(r"\b(?:in|under|within|up to|at most) (\d+) (words?|characters?)\b")
        .first_groups(&value)?;
    if let Some(limit) = limit {
        let words = limit[2].as_ref().expect("unit").text.starts_with("word");
        let count = number(
            &limit[1].as_ref().expect("number").text,
            if words { 500 } else { 3500 },
        )?;
        // Folded offsets can differ from the original; match the original again for slicing.
        let original_limit = rx!(
            r"\b(?:in|under|within|up to|at most) (\d+) (words?|characters?)\b",
            true
        )
        .first_groups(&original)?
        .ok_or(Failure("invalid_conversation_intent"))?;
        let span = original_limit[0].as_ref().expect("full match");
        let reduced = format!("{}{}", &original[..span.start], &original[span.end..]);
        let mut intent = inner(&reduced, depth + 1)?;
        if words {
            intent.max_words = count
        } else {
            intent.max_characters = count
        };
        return Ok(intent);
    }
    let sentences = if original.contains("https://") {
        vec![original.as_str()]
    } else {
        rx!(r"[.!?]+\s+").split(&original)?
    };
    if (2..=3).contains(&sentences.len()) {
        let mut meaningful = vec![];
        for sentence in sentences
            .into_iter()
            .filter(|s| !crate::grounding::trim(s).is_empty())
        {
            let intent = inner(sentence, depth + 1)?;
            if !matches!(intent.category.as_str(), "HELP" | "GENERAL_CHAT") {
                meaningful.push(intent);
            }
        }
        if meaningful.len() == 1 {
            return Ok(meaningful.remove(0));
        }
        if meaningful.len() == 2
            && matches!(meaningful[0].category.as_str(), "FIND_JOBS" | "FILTER_JOBS")
            && meaningful[1].follow_up.as_deref() == Some("filter")
        {
            let follow = meaningful.pop().expect("follow");
            let mut intent = meaningful.pop().expect("search");
            if follow.location.is_some() {
                intent.location = follow.location;
            }
            if follow.days.is_some() {
                intent.days = follow.days;
            }
            if follow.remote {
                intent.remote = true;
            }
            return Ok(intent);
        }
        return make("FOLLOW_UP", json!({"follow_up":"clarify"}));
    }
    if value.is_empty() {
        return kind("HELP");
    }
    if rx!(r"\b(?:forget|reset|clear|start over)\b.*(?:selection|conversation|context|search|again)|^/reset$").is_match(&value)?{return kind("RESET_CONTEXT");}
    if rx!(r"\b(?:approve|approval|confirm)\b").is_match(&value)? {
        return kind("APPROVAL_REQUEST");
    }
    if rx!(r"\bresume\b").is_match(&value)?
        && rx!(r"\b(?:check|status|latest|sync|review|updated)\b").is_match(&value)?
    {
        return kind("RESUME_STATUS");
    }
    if rx!(r"\b(?:profile|skills|experience|locations|notice period|salary preferences)\b")
        .is_match(&value)?
        && rx!(r"^(?:show|check|what|tell|list)").is_match(&value)?
        && !value.contains("project")
        && !value.contains("experience with")
    {
        return make("PROFILE_QUERY", json!({"subject":cut(&value,200)}));
    }
    let project_rank =
        rx!(r"\b(first|second|third|most important|best|top|[1-9]|[12][0-9]|30) project\b")
            .first_group(&value, 1)?;
    if project_rank.is_some()
        || value.contains("project")
        || rx!(r"^(?:explain|describe|tell me about) .+ architecture").is_match(&value)?
    {
        let rank = project_rank
            .as_deref()
            .map(|rank| match rank {
                "first" | "most important" | "best" | "top" => Ok(1),
                "second" => Ok(2),
                "third" => Ok(3),
                rank => number(rank, 30),
            })
            .transpose()?;
        let subject = replace(
            &original,
            rx!(
                r"^(?:tell me about|explain|describe|use|show) (?:my |the )?",
                true
            ),
            |_| String::new(),
        )?;
        return make(
            "PROJECT_QUERY",
            json!({"subject":cut(&subject,200),"project_rank":rank,"follow_up":if rx!(r"^use .*project").is_match(&value)?{Some("answer")}else{None}}),
        );
    }
    if rx!(r"\b(?:connected|connection|connections)\b").is_match(&value)? {
        let connection = [
            "gmail",
            "telegram",
            "supabase",
            "chrome",
            "agy",
            "naukri",
            "wellfound",
            "instahyre",
            "internshala",
            "yc",
        ]
        .into_iter()
        .find(|name| {
            // Fixed application literals, never model-supplied regex.
            Regex::literal_word(name, false)
                .is_match(&value)
                .unwrap_or(false)
        });
        return make("CONNECTION_STATUS", json!({"connection":connection}));
    }
    if rx!(r"\b(?:compare|prioritize|prioritise|best job|which job|rank .*jobs)\b")
        .is_match(&value)?
    {
        return kind("JOB_COMPARISON");
    }
    if value.contains("https://") || value.contains("http://") {
        return legacy(&original);
    }
    if rx!(r"why (?:should .*hire|i want to join)|experience with|challenging engineering problem|scalable system").is_match(&value)?{return make("ANSWER_PREPARATION",json!({"subject":cut(&original,200)}));}
    if rx!(r"^(?:only |just |what about |how about |and |make (?:them|it) )").is_match(&value)? {
        let location = rx!(r"\bin ([\w .-]+)", true).first_group(&original, 1)?;
        return make(
            "FOLLOW_UP",
            json!({"follow_up":"filter","remote":value.contains("remote"),"location":location,"days":if value.contains("today"){Some(1)}else{None}}),
        );
    }
    if rx!(r"\b(?:that|this|it|selected|previous)\b").is_match(&value)?
        && rx!(r"\b(?:job|one|application|prepare|details|show|apply)\b").is_match(&value)?
    {
        return make(
            "FOLLOW_UP",
            json!({"follow_up":if rx!(r"prepare|apply").is_match(&value)?{"prepare"}else{"selected"}}),
        );
    }
    let old = legacy(&original)?;
    if old.category != "UNKNOWN" {
        return Ok(old);
    }
    if rx!(r"\bjobs?\b").is_match(&value)? {
        let normalized = replace(
            &original,
            rx!(
                r"^(?:are there |do (?:you|we) have |any |what are the |look for |search for |find me |show me )",
                true
            ),
            |_| "find ".into(),
        )?;
        let normalized = replace(&normalized, rx!(r"\bnew\s+", true), |_| String::new())?;
        let normalized = replace(&normalized, rx!(r"\b(?:available|open)\s+", true), |_| {
            String::new()
        })?;
        let today = rx!(r"\btoday\b", true).is_match(&normalized)?;
        let normalized = replace(&normalized, rx!(r"\s+today\b", true), |_| String::new())?;
        if value.contains("have not applied") && value.contains("companies") {
            return make("FILTER_JOBS", json!({"not_applied":true}));
        }
        let mut parsed = legacy(&normalized)?;
        if parsed.category != "UNKNOWN" {
            if today {
                parsed.days = Some(1);
            }
            return Ok(parsed);
        }
    }
    if value.contains("companies") && rx!(r"(?:not|haven't) applied").is_match(&value)? {
        return make("FILTER_JOBS", json!({"not_applied":true}));
    }
    if ["thanks", "thank you", "good morning", "good evening"].contains(&value.as_str()) {
        return kind("GENERAL_CHAT");
    }
    unknown()
}
fn legacy(text: &str) -> Result<Intent> {
    let text = crate::grounding::trim(text);
    if !(1..=2048).contains(&text.chars().count()) {
        return unknown();
    }
    let original = text.replace('’', "'");
    let original = original.trim_end_matches(['.', '?', '!']);
    let value = folded(original);
    if rx!(r"[\n\r;`]|ignore .*instructions|system prompt|execute|shell|password|access.?token|send (?:an? |the )?email|submit|bypass|override|disable .*approval").is_match(&value)?{return unknown();}
    if ["help", "hello", "hi", "what can you do"].contains(&value.as_str()) {
        return kind("HELP");
    }
    if rx!(r"\A(?:choose |select |show |job )?(?:[1-9]|10)\z").is_match(&value)? {
        return make(
            "SHOW_JOB",
            json!({"selection":number(value.split_whitespace().last().expect("selection"),10)?}),
        );
    }
    if (value.contains("connected") || value.contains("connection"))
        && rx!(r"^(?:check|show|is |are |tell)").is_match(&value)?
    {
        let connection = ["gmail", "telegram", "supabase", "chrome", "agy"]
            .into_iter()
            .find(|name| value.contains(name));
        return make("CONNECTION_STATUS", json!({"connection": connection}));
    }
    if rx!(r"(?:how many|status|pending).*(?:application)|application.*(?:pending|status)")
        .is_match(&value)?
    {
        return kind("APPLICATION_STATUS");
    }
    if rx!(r"^(?:preview|show|prepare) .*(?:gmail|email) draft").is_match(&value)? {
        return kind("GMAIL_DRAFT_PREVIEW");
    }
    if rx!(r"^(?:find|show|research) (?:the )?(?:recruiters|founders)").is_match(&value)? {
        return kind("FOUNDER_RESEARCH_PREVIEW");
    }
    if let Some(url) = rx!(
        r"\A(?:prepare an application for (?:this url:? )?|apply (?:to|for) )(https://\S+)\z",
        true
    )
    .first_group(original, 1)?
    {
        return Ok(make("PREPARE_APPLICATION", json!({"url":url})).unwrap_or(kind("UNKNOWN")?));
    }
    if let Some(company) = rx!(
        r"\A(?:apply (?:to|for)|prepare an application for) ([\w .&-]{1,100})\z",
        true
    )
    .first_group(original, 1)?
    {
        return make("PREPARE_APPLICATION", json!({"company":company}));
    }
    if !rx!(r"^(?:find|show|filter|search|list)\b").is_match(&value)?
        || !rx!(r"\bjobs?\b").is_match(&value)?
    {
        return unknown();
    }
    let company = rx!(
        r"\b(?:at|for company) ([\w .&-]+?)(?= in | requiring | posted |$)",
        true
    )
    .first_groups(original)?;
    let location = rx!(
        r"\bin (?!the last\b)([\w .-]+?)(?= posted | requiring |$)",
        true
    )
    .first_groups(original)?;
    let role = rx!(
        r"\b(?:find|show|list|search)(?: all)?(?: remote)? ([\w +#/-]+?) jobs?\b",
        true
    )
    .first_groups(original)?;
    let role_value =
        group(&role, 1).filter(|r| !["startup", "all", "the"].contains(&folded(r).as_str()));
    let days = rx!(r"last (\d+|one|two|three|seven|thirty) days?").first_group(&value, 1)?;
    let days = days
        .as_deref()
        .map(|days| match days {
            "one" => Ok(1),
            "two" => Ok(2),
            "three" => Ok(3),
            "seven" => Ok(7),
            "thirty" => Ok(30),
            text => number(text, 365),
        })
        .transpose()?;
    let skills = rx!(r"requiring ([\w +#.,/-]+)", true).first_groups(original)?;
    let mut remainder = original.to_owned();
    for groups in [&skills, &company, &location, &role] {
        if let Some(text) = group(groups, 0) {
            remainder = remainder.replace(text, " ");
        }
    }
    let remainder = remove(
        &remainder,
        rx!(
            r"(?:posted )?in the last (?:\d+|one|two|three|seven|thirty) days?|(?:posted )?the last (?:\d+|one|two|three|seven|thirty) days?|I (?:haven't|have not) applied to|not applied",
            true
        ),
    )?;
    let remainder = remove(
        &remainder,
        rx!(
            r"\b(?:find|show|filter|search|list|all|remote|startup|jobs?)\b",
            true
        ),
    )?;
    if !crate::grounding::trim(&remainder).is_empty() {
        return unknown();
    }
    let skills = if let Some(skills) = group(&skills, 1) {
        rx!(r",\s*| and ")
            .split(skills)?
            .into_iter()
            .take(10)
            .map(str::to_owned)
            .collect::<Vec<_>>()
    } else {
        vec![]
    };
    let not_applied = value.contains("haven't applied") || value.contains("not applied");
    make(
        if not_applied {
            "FILTER_JOBS"
        } else {
            "FIND_JOBS"
        },
        json!({"company":group(&company,1),"location":group(&location,1),"role":role_value,"remote":value.contains("remote"),"startup":value.contains("startup"),"skills":skills,"days":days,"not_applied":not_applied}),
    )
}
