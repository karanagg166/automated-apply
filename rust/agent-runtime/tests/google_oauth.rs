use automated_apply_agents::google_oauth::{
    GoogleOAuth, GrantMode, TokenResponse, normalized_scopes, scopes,
};
use serde_json::{Value, json};
use std::{
    collections::BTreeMap,
    io::Write,
    path::PathBuf,
    process::{Command, Stdio},
    sync::{Arc, Mutex},
};
fn values() -> BTreeMap<String, String> {
    BTreeMap::from([
        ("GMAIL_CLIENT_ID".into(), "fictional-client".into()),
        ("GMAIL_CLIENT_SECRET".into(), "fictional-secret".into()),
        (
            "GMAIL_REDIRECT_URI".into(),
            "http://127.0.0.1:8000/api/v1/integrations/gmail/oauth/callback".into(),
        ),
    ])
}
#[test]
fn authorization_pkce_and_scope_parameters_match_actual_legacy_builder_without_send_grants() {
    let sdk = GoogleOAuth::from_values(&values(), false).unwrap().unwrap();
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    let code = r#"
import ast,base64,hashlib,json,sys
from pathlib import Path
from types import SimpleNamespace as S
from urllib.parse import urlencode,parse_qsl,urlsplit
scope=dict(base64=base64,hashlib=hashlib,urlencode=urlencode,ConnectionError=ValueError)
source=ast.parse(Path('backend/app/integrations/google_oauth.py').read_text())
nodes=[n for n in source.body if isinstance(n,ast.Assign) or isinstance(n,ast.ClassDef) and n.name=='GoogleOAuth']
exec(compile(ast.Module(body=nodes,type_ignores=[]),'isolated_google_builder','exec'),scope)
sdk=scope['GoogleOAuth'](S(GMAIL_CLIENT_ID='fictional-client',GMAIL_CLIENT_SECRET='fictional-secret',GMAIL_REDIRECT_URI='http://127.0.0.1:8000/api/v1/integrations/gmail/oauth/callback'))
raw=json.load(sys.stdin)
url=sdk.authorization_url('fictional-state','fictional-verifier','fixture@example.com',**raw)
assert 'backend.app.core.config' not in sys.modules
print(json.dumps(dict(parse_qsl(urlsplit(url).query))))
"#;
    for (mode, flags) in [
        (GrantMode::Metadata, json!({})),
        (GrantMode::Read, json!({"read_body":true})),
        (GrantMode::Compose, json!({"compose":true})),
        (GrantMode::ReadDraft, json!({"read_draft":true})),
    ] {
        let url = reqwest::Url::parse(
            &sdk.authorization_url(
                "fictional-state",
                "fictional-verifier",
                Some("fixture@example.com"),
                mode,
            )
            .unwrap(),
        )
        .unwrap();
        assert_eq!(url.host_str(), Some("accounts.google.com"));
        let actual: BTreeMap<String, String> = url.query_pairs().into_owned().collect();
        let mut child = Command::new(root.join(".venv/bin/python"))
            .args(["-c", code])
            .current_dir(&root)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .spawn()
            .unwrap();
        child
            .stdin
            .take()
            .unwrap()
            .write_all(flags.to_string().as_bytes())
            .unwrap();
        let output = child.wait_with_output().unwrap();
        assert!(output.status.success());
        let expected: BTreeMap<String, String> = serde_json::from_slice(&output.stdout).unwrap();
        assert_eq!(actual, expected);
        assert!(!actual["scope"].contains("gmail.send"));
    }
}
#[test]
fn strict_token_and_configuration_validation_keep_secrets_out_of_errors() {
    let good = json!({"access_token":"fictional","refresh_token":"fictional-refresh","token_type":"Bearer","expires_in":3600,"scope":"openid email"});
    let token = TokenResponse::parse(good.clone()).unwrap();
    assert_eq!(token.access(), "fictional");
    assert_eq!(token.refresh(), Some("fictional-refresh"));
    assert_eq!(token.expires_in(), 3600);
    assert!(token.has_refresh_token());
    assert_eq!(
        token.granted_scopes().unwrap().unwrap(),
        normalized_scopes(&json!(
            "openid https://www.googleapis.com/auth/userinfo.email"
        ))
        .unwrap()
    );
    for (field, value) in [
        ("access_token", json!("")),
        ("refresh_token", json!("")),
        ("token_type", json!("Basic")),
        ("expires_in", json!(true)),
        ("expires_in", json!("3600")),
        ("expires_in", json!(86401)),
    ] {
        let mut bad = good.clone();
        bad[field] = value;
        assert_eq!(
            TokenResponse::parse(bad).err().unwrap().0,
            "invalid_token_response"
        );
    }
    assert!(normalized_scopes(&Value::Null).is_err());
    assert!(
        !scopes(GrantMode::ReadDraft)
            .iter()
            .any(|s| s.ends_with("gmail.send"))
    );
    let mut config = values();
    config.insert(
        "RUST_GOOGLE_FIXTURE_ENDPOINT".into(),
        "http://127.0.0.1:12345/".into(),
    );
    assert!(GoogleOAuth::from_values(&config, false).is_err());
    config.insert(
        "RUST_GOOGLE_FIXTURE_ENDPOINT".into(),
        "http://localhost:12345/".into(),
    );
    assert!(GoogleOAuth::from_values(&config, true).is_err());
    for uri in [
        "http://evil.example/api/v1/integrations/gmail/oauth/callback",
        "https://example.com/other",
        "https://user:secret@example.com/api/v1/integrations/gmail/oauth/callback",
        "http://127.1:8000/api/v1/integrations/gmail/oauth/callback",
    ] {
        let mut config = values();
        config.insert("GMAIL_REDIRECT_URI".into(), uri.into());
        assert!(GoogleOAuth::from_values(&config, false).is_err());
    }
}
async fn fixture(
    status: u16,
    invalid_identity: bool,
) -> (
    String,
    Arc<Mutex<Vec<(String, String)>>>,
    tokio::task::JoinHandle<()>,
) {
    use axum::{Router, body::Body, extract::Request, response::Response};
    let calls = Arc::new(Mutex::new(Vec::new()));
    let captured = calls.clone();
    let app=Router::new().fallback(move|request:Request|{let calls=captured.clone();async move{let path=request.uri().path().to_owned();calls.lock().unwrap().push((request.method().to_string(),path.clone()));let value=match path.as_str(){"/userinfo"=>json!({"sub":"fictional-subject","email_verified":true,"email":"FIXTURE@example.com"}),"/profile"=>json!({"emailAddress":if invalid_identity{"other@example.com"}else{"fixture@example.com"}}),"/token" if status==400=>json!({"error":"invalid_grant","error_description":"private-fictional-canary"}),"/token"=>json!({"access_token":"fictional-access","refresh_token":"fictional-refresh","token_type":"Bearer","expires_in":3600,"scope":"openid"}),_=>json!({})};Response::builder().status(status).body(Body::from(value.to_string())).unwrap()}});
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let task = tokio::spawn(async move { axum::serve(listener, app).await.unwrap() });
    (format!("http://{address}/"), calls, task)
}
#[tokio::test(flavor = "current_thread")]
async fn actual_oauth_fixture_uses_only_fixed_token_identity_profile_and_revoke_endpoints() {
    let (url, calls, server) = fixture(200, false).await;
    let mut config = values();
    config.insert("RUST_GOOGLE_FIXTURE_ENDPOINT".into(), url);
    let sdk = GoogleOAuth::from_values(&config, true).unwrap().unwrap();
    let tokens = sdk
        .exchange("fictional-code", "fictional-verifier")
        .await
        .unwrap();
    assert!(tokens.has_refresh_token());
    sdk.refresh("fictional-refresh").await.unwrap();
    assert_eq!(
        sdk.identity(tokens.access()).await.unwrap(),
        ("fictional-subject".into(), "fixture@example.com".into())
    );
    sdk.revoke("fictional-refresh").await.unwrap();
    assert_eq!(
        *calls.lock().unwrap(),
        vec![
            ("POST".into(), "/token".into()),
            ("POST".into(), "/token".into()),
            ("GET".into(), "/userinfo".into()),
            ("GET".into(), "/profile".into()),
            ("POST".into(), "/revoke".into())
        ]
    );
    server.abort();
}
#[tokio::test(flavor = "current_thread")]
async fn invalid_grant_and_cross_mailbox_identity_fail_with_closed_codes() {
    for (status, mismatch, expected) in [
        (400, false, "credential_revoked_or_code_invalid"),
        (200, true, "gmail_identity_mismatch"),
    ] {
        let (url, _calls, server) = fixture(status, mismatch).await;
        let mut config = values();
        config.insert("RUST_GOOGLE_FIXTURE_ENDPOINT".into(), url);
        let sdk = GoogleOAuth::from_values(&config, true).unwrap().unwrap();
        let error = if mismatch {
            sdk.identity("fictional-access").await.err().unwrap()
        } else {
            sdk.refresh("fictional-refresh").await.err().unwrap()
        };
        assert_eq!(error.0, expected);
        assert!(!error.0.contains("canary"));
        server.abort();
    }
}
#[test]
fn normalized_callback_aliases_cannot_replace_exact_redirect_and_token_dtos_match_python() {
    let mut config = values();
    config.insert(
        "GMAIL_REDIRECT_URI".into(),
        "http://127.0.0.1:8000/x/../api/v1/integrations/gmail/oauth/callback".into(),
    );
    assert!(GoogleOAuth::from_values(&config, false).is_err());
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    let good = json!({"access_token":"fictional","token_type":"bearer","expires_in":1});
    let mut cases = vec![good.clone()];
    for (key, variants) in [
        (
            "expires_in",
            vec![
                json!(true),
                json!(0),
                json!(86400),
                json!(86401),
                json!(1.0),
                json!("1"),
            ],
        ),
        (
            "access_token",
            vec![
                Value::Null,
                json!(""),
                json!(false),
                json!("x".repeat(16385)),
            ],
        ),
        (
            "refresh_token",
            vec![Value::Null, json!(""), json!("fixture-refresh")],
        ),
        (
            "token_type",
            vec![json!("BEARER"), json!("basic"), Value::Null],
        ),
        ("scope", vec![Value::Null, json!(""), json!([])]),
    ] {
        for variant in variants {
            let mut row = good.clone();
            row[key] = variant;
            cases.push(row);
        }
    }
    let code = r#"
import ast,json,sys
from pathlib import Path
from pydantic import BaseModel,ConfigDict,Field,StrictInt,field_validator
scope=dict(BaseModel=BaseModel,ConfigDict=ConfigDict,Field=Field,StrictInt=StrictInt,field_validator=field_validator)
node=next(n for n in ast.parse(Path('backend/app/integrations/google_oauth.py').read_text()).body if isinstance(n,ast.ClassDef) and n.name=='TokenResponse')
exec(compile(ast.Module(body=[node],type_ignores=[]),'isolated_google_token_dto','exec'),scope)
accepted=[]
for row in json.load(sys.stdin):
 try:scope['TokenResponse'].model_validate(row);accepted.append(True)
 except ValueError:accepted.append(False)
assert 'backend.app.core.config' not in sys.modules
print(json.dumps(accepted))
"#;
    let mut child = Command::new(root.join(".venv/bin/python"))
        .args(["-c", code])
        .current_dir(root)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
        .unwrap();
    child
        .stdin
        .take()
        .unwrap()
        .write_all(json!(cases).to_string().as_bytes())
        .unwrap();
    let output = child.wait_with_output().unwrap();
    assert!(output.status.success());
    let expected: Vec<bool> = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(
        cases
            .iter()
            .cloned()
            .map(|v| TokenResponse::parse(v).is_ok())
            .collect::<Vec<_>>(),
        expected
    );
}
