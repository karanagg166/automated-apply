//! Passive browser capabilities. Inventory never launches a browser or grants account access.
use crate::{Failure, Result};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::{collections::BTreeMap, path::Path};

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Browser {
    Brave,
    Edge,
    Safari,
}
impl Browser {
    pub fn from_values(values: &BTreeMap<String, String>) -> Result<Self> {
        match values
            .get("RUST_BROWSER_ENGINE")
            .map(String::as_str)
            .unwrap_or("brave")
        {
            "brave" => Ok(Self::Brave),
            "edge" => Ok(Self::Edge),
            "safari" => Ok(Self::Safari),
            _ => Err(Failure("unsupported_browser_engine")),
        }
    }
    pub fn application(self) -> &'static str {
        match self {
            Self::Brave => "/Applications/Brave Browser.app",
            Self::Edge => "/Applications/Microsoft Edge.app",
            Self::Safari => "/Applications/Safari.app",
        }
    }
    pub fn native_manifest_directory(self) -> Option<&'static str> {
        match self {
            Self::Brave => {
                Some("Library/Application Support/BraveSoftware/Brave-Browser/NativeMessagingHosts")
            }
            Self::Edge => Some("Library/Application Support/Microsoft Edge/NativeMessagingHosts"),
            Self::Safari => None,
        }
    }
    pub fn inventory(self) -> Value {
        let installed = Path::new(self.application()).is_dir();
        json!({"selected":self,"installed":installed,"application":self.application(),
            "transport":if self==Self::Safari{"safari_web_extension_required"}else{"mv3_native_messaging"},
            "ready":false,"application_dispatch":false,
            "blocker":if !installed{"browser_not_installed"}else if self==Self::Safari{"safari_focus_and_web_extension_validation_required"}else{"fresh_account_binding_extension_and_focus_validation_required"},
            "chrome_fallback":false,"browser_launched":false})
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn explicit_non_chrome_selection_and_native_host_paths() {
        assert_eq!(
            Browser::from_values(&BTreeMap::new()).unwrap(),
            Browser::Brave
        );
        for (name, expected) in [
            ("brave", Browser::Brave),
            ("edge", Browser::Edge),
            ("safari", Browser::Safari),
        ] {
            assert_eq!(
                Browser::from_values(&BTreeMap::from([(
                    "RUST_BROWSER_ENGINE".into(),
                    name.into()
                )]))
                .unwrap(),
                expected
            );
            let status = expected.inventory();
            assert_eq!(status["ready"], false);
            assert_eq!(status["chrome_fallback"], false);
        }
        assert!(Browser::Safari.native_manifest_directory().is_none());
        assert!(
            Browser::Edge
                .native_manifest_directory()
                .unwrap()
                .contains("Microsoft Edge")
        );
        assert!(
            Browser::from_values(&BTreeMap::from([(
                "RUST_BROWSER_ENGINE".into(),
                "chrome".into()
            )]))
            .is_err()
        );
    }
}
