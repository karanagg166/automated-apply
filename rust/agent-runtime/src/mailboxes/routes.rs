//! Closed owner account paths and bounded browser callback decoding.
use super::*;
pub const ACCOUNTS: &str = "/api/v1/integrations/gmail/local/accounts";
pub const CALLBACK: &str = "/api/v1/integrations/gmail/oauth/callback";
#[derive(Clone, Copy)]
pub enum Route<'a> {
    Accounts,
    Connect(Slot),
    Verify(Slot),
    Disconnect(Slot),
    Callback,
    Search(Slot),
    Read(Slot, &'a str),
    Drafts(Slot),
    TestDraft(Slot),
    AlertPolicy(Slot),
    AlertSync(Slot),
}
pub fn route(path: &str) -> Option<Route<'_>> {
    if path == ACCOUNTS {
        return Some(Route::Accounts);
    }
    if path == CALLBACK {
        return Some(Route::Callback);
    }
    let tail = path.strip_prefix(ACCOUNTS)?.strip_prefix('/')?;
    let (slot, action) = tail.split_once('/')?;
    let slot = Slot::parse(slot).ok()?;
    if let Some(id) = action
        .strip_prefix("messages/")
        .and_then(|tail| tail.strip_suffix("/read"))
    {
        return message_id(id).ok().map(|_| Route::Read(slot, id));
    }
    match action {
        "search" => Some(Route::Search(slot)),
        "drafts" => Some(Route::Drafts(slot)),
        "test-draft" => Some(Route::TestDraft(slot)),
        "job-alerts" => Some(Route::AlertPolicy(slot)),
        "job-alerts/sync" => Some(Route::AlertSync(slot)),
        "connect" => Some(Route::Connect(slot)),
        "verify" => Some(Route::Verify(slot)),
        "disconnect" => Some(Route::Disconnect(slot)),
        _ => None,
    }
}
pub struct Callback {
    pub state: String,
    pub slot: Slot,
    pub code: Option<String>,
    pub error: Option<String>,
}
pub fn callback(query: Option<&str>) -> Result<Callback> {
    let invalid = Failure("invalid_oauth_callback");
    let raw = query.filter(|s| s.len() <= 16000).ok_or(invalid)?;
    let url = reqwest::Url::parse(&format!("http://127.0.0.1/?{raw}")).map_err(|_| invalid)?;
    let mut values = BTreeMap::new();
    for (key, value) in url.query_pairs() {
        if ![
            "state",
            "code",
            "error",
            "scope",
            "authuser",
            "prompt",
            "error_description",
            "error_uri",
        ]
        .contains(&key.as_ref())
            || values.insert(key.to_string(), value.to_string()).is_some()
        {
            return Err(Failure("ambiguous_oauth_callback"));
        }
    }
    let state = values
        .remove("state")
        .filter(|s| (32..=128).contains(&s.len()))
        .ok_or(invalid)?;
    let parts: Vec<&str> = state.split('.').collect();
    if parts.len() != 3
        || parts[0] != "mailbox"
        || parts[2].is_empty()
        || !parts[2]
            .bytes()
            .all(|c| c.is_ascii_alphanumeric() || c == b'_' || c == b'-')
    {
        return Err(invalid);
    }
    let slot = Slot::parse(parts[1]).map_err(|_| invalid)?;
    let code = values.remove("code");
    let error = values.remove("error");
    if code
        .as_ref()
        .is_some_and(|s| s.len() > 4096 || s.chars().any(char::is_control))
        || error
            .as_ref()
            .is_some_and(|s| s.len() > 100 || s.chars().any(char::is_control))
    {
        return Err(invalid);
    }
    Ok(Callback {
        state,
        slot,
        code,
        error,
    })
}
pub fn browser_cookie(headers: &axum::http::HeaderMap, slot: Slot) -> Result<String> {
    let name = format!("gmail54_oauth_{}", slot.name());
    let mut found = None;
    for value in headers.get_all("cookie") {
        let raw = value
            .to_str()
            .map_err(|_| Failure("invalid_oauth_browser_binding"))?;
        for part in raw.split(';') {
            if let Some((key, value)) = part.trim().split_once('=')
                && key == name
            {
                if found.is_some()
                    || !(32..=128).contains(&value.len())
                    || !value
                        .bytes()
                        .all(|c| c.is_ascii_alphanumeric() || c == b'_' || c == b'-')
                {
                    return Err(Failure("invalid_oauth_browser_binding"));
                }
                found = Some(value.to_string());
            }
        }
    }
    found.ok_or(Failure("invalid_oauth_browser_binding"))
}
