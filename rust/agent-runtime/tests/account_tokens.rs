use automated_apply_agents::account_tokens::TokenStore;
use serde_json::{Value, json};
use std::{
    collections::BTreeMap,
    io::Write,
    path::PathBuf,
    process::{Command, Stdio},
};
// Public zero-byte fixture keys only; no real account credential or environment is loaded.
const KEY: &str = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=";
fn store() -> TokenStore {
    TokenStore::new("fixture", BTreeMap::from([("fixture".into(), KEY.into())])).unwrap()
}
fn python(input: Value) -> Value {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    let code = r#"
import ast,json,sys,hashlib,re
from cryptography.fernet import Fernet,InvalidToken
from types import SimpleNamespace as S
from pathlib import Path
raw=json.load(sys.stdin)
scope=dict(hashlib=hashlib,json=json,re=re,Fernet=Fernet,InvalidToken=InvalidToken)
source=Path('backend/app/integrations/token_store.py').read_text()
nodes=[n for n in ast.parse(source).body if isinstance(n,ast.ClassDef) and n.name in {'ConnectionError','TokenStore'}]
exec(compile(ast.Module(body=nodes,type_ignores=[]),'isolated_token_store','exec'),scope)
class Secret:
 def get_secret_value(self):return raw['key']
store=scope['TokenStore'](S(OAUTH_ACTIVE_KEY_ID='fixture',OAUTH_ENCRYPTION_KEYS={'fixture':Secret()}))
if raw['operation']=='encrypt':result=store.encrypt(raw['value'],raw['purpose'])
else:result=store.decrypt(raw['envelope'],raw['purpose'])
assert 'backend.app.core.config' not in sys.modules
print(json.dumps(result))
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
        .write_all(input.to_string().as_bytes())
        .unwrap();
    let output = child.wait_with_output().unwrap();
    assert!(output.status.success());
    serde_json::from_slice(&output.stdout).unwrap()
}
#[test]
fn actual_python_tokens_decrypt_in_rust_and_rust_tokens_decrypt_in_python() {
    let store = store();
    for value in [
        Value::Null,
        json!({"access_token":"fictional-value","refresh_token":"fictional-refresh","expires_in":3600}),
        json!({"unicode":"工作","list":[true,3,null]}),
    ] {
        let original = python(
            json!({"operation":"encrypt","key":KEY,"purpose":"read-account:fixture","value":value}),
        );
        assert_eq!(
            store
                .decrypt(original.as_str().unwrap(), "read-account:fixture")
                .unwrap(),
            value
        );
        let envelope = store.encrypt(&value, "read-account:fixture").unwrap();
        assert_eq!(
            python(
                json!({"operation":"decrypt","key":KEY,"purpose":"read-account:fixture","envelope":envelope})
            ),
            value
        );
    }
}
#[test]
fn token_envelopes_refuse_wrong_account_purpose_key_identity_tampering_and_malformed_input() {
    let store = store();
    let token = store
        .encrypt(&json!({"secret":"fictional-canary"}), "account:first")
        .unwrap();
    assert_eq!(
        store.decrypt(&token, "account:second").unwrap_err().0,
        "token_decryption_failed"
    );
    for envelope in [
        "".into(),
        "fixture:invalid:notciphertext".into(),
        token.replacen("fixture:", "missing:", 1),
        format!("{token}tampered"),
    ] {
        assert_eq!(
            store.decrypt(&envelope, "account:first").unwrap_err().0,
            "token_decryption_failed"
        );
    }
    assert!(TokenStore::new("missing", BTreeMap::new()).is_err());
    assert!(TokenStore::new("bad/key", BTreeMap::from([("bad/key".into(), KEY.into())])).is_err());
    assert!(
        TokenStore::new(
            "fixture",
            BTreeMap::from([("fixture".into(), "invalid-key".into())])
        )
        .is_err()
    );
}
#[test]
fn key_rotation_retains_old_tokens_and_partial_configuration_never_silently_disables_encryption() {
    let original = store()
        .encrypt(&json!({"token":"fictional"}), "account:fixture")
        .unwrap();
    let next = fernet::Fernet::generate_key();
    let rotated = TokenStore::new(
        "next",
        BTreeMap::from([
            ("fixture".into(), KEY.into()),
            ("next".into(), next.clone()),
        ]),
    )
    .unwrap();
    assert_eq!(
        rotated.decrypt(&original, "account:fixture").unwrap(),
        json!({"token":"fictional"})
    );
    assert!(
        rotated
            .encrypt(&Value::Null, "account:fixture")
            .unwrap()
            .starts_with("next:")
    );
    let changed = TokenStore::new("fixture", BTreeMap::from([("fixture".into(), next)])).unwrap();
    assert_eq!(
        changed.decrypt(&original, "account:fixture").unwrap_err().0,
        "token_decryption_failed"
    );
    assert!(TokenStore::from_values(&BTreeMap::new()).unwrap().is_none());
    assert!(
        TokenStore::from_values(&BTreeMap::from([(
            "OAUTH_ACTIVE_KEY_ID".into(),
            "fixture".into()
        )]))
        .is_err()
    );
}
