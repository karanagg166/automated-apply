//! Canonical legacy JSON bindings for owner approvals/context hashes, without Python at runtime.
use crate::resources::ascii_string;
use serde_json::{Number, Value};
use sha2::{Digest, Sha256};

fn number(value: &Number) -> String {
    if !value.is_f64() {
        return value.to_string();
    }
    let raw = value.to_string();
    let negative = raw.starts_with('-');
    let raw = raw.trim_start_matches('-');
    let (mantissa, exponent) = raw.split_once(['e', 'E']).unwrap_or((raw, "0"));
    let exponent = exponent.parse::<i32>().expect("finite JSON float exponent");
    let fractional = mantissa.split_once('.').map(|(_, s)| s.len()).unwrap_or(0);
    let digits = mantissa.replace('.', "");
    let leading = digits.len() - digits.trim_start_matches('0').len();
    if leading == digits.len() {
        return if negative { "-0.0" } else { "0.0" }.into();
    }
    let power = digits.len() as i32 - fractional as i32 + exponent - leading as i32 - 1;
    let digits = digits[leading..].trim_end_matches('0');
    let value = if !(-4..16).contains(&power) {
        let coefficient = if digits.len() == 1 {
            digits.into()
        } else {
            format!("{}.{}", &digits[..1], &digits[1..])
        };
        format!(
            "{coefficient}e{}{:02}",
            if power < 0 { "-" } else { "+" },
            power.unsigned_abs()
        )
    } else {
        let point = power + 1;
        if point <= 0 {
            format!("0.{}{}", "0".repeat((-point) as usize), digits)
        } else if point as usize >= digits.len() {
            format!("{}{}.0", digits, "0".repeat(point as usize - digits.len()))
        } else {
            format!(
                "{}.{}",
                &digits[..point as usize],
                &digits[point as usize..]
            )
        }
    };
    if negative { format!("-{value}") } else { value }
}
pub fn serialize(value: &Value, compact: bool, ascii: bool) -> String {
    fn write(value: &Value, compact: bool, ascii: bool, out: &mut String) {
        let separator = if compact { "," } else { ", " };
        match value {
            Value::Null => out.push_str("null"),
            Value::Bool(b) => out.push_str(if *b { "true" } else { "false" }),
            Value::Number(n) => out.push_str(&number(n)),
            Value::String(s) => out.push_str(&if ascii {
                ascii_string(s)
            } else {
                serde_json::to_string(s).expect("JSON string")
            }),
            Value::Array(values) => {
                out.push('[');
                for (index, item) in values.iter().enumerate() {
                    if index > 0 {
                        out.push_str(separator);
                    }
                    write(item, compact, ascii, out);
                }
                out.push(']');
            }
            Value::Object(values) => {
                out.push('{');
                let mut keys: Vec<_> = values.keys().collect();
                keys.sort();
                for (index, key) in keys.into_iter().enumerate() {
                    if index > 0 {
                        out.push_str(separator);
                    }
                    write(&Value::String(key.clone()), compact, ascii, out);
                    out.push_str(if compact { ":" } else { ": " });
                    write(&values[key], compact, ascii, out);
                }
                out.push('}');
            }
        }
    }
    let mut output = String::new();
    write(value, compact, ascii, &mut output);
    output
}
pub fn digest(value: &Value) -> String {
    format!(
        "{:x}",
        Sha256::digest(serialize(value, true, true).as_bytes())
    )
}
