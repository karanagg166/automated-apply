//! Exact local USD micros; provider billing remains independently preliminary.
use crate::{Failure, Result};
use serde_json::Value;
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord)]
pub struct Usd(u64);
fn invalid() -> Failure {
    Failure("invalid_apify_usd_amount")
}
impl Usd {
    /// Environment caps accept plain nonnegative decimals with at most six fractional places.
    pub fn parse(raw: &str) -> Result<Self> {
        if raw.is_empty() || raw.len() > 24 || raw.trim() != raw {
            return Err(invalid());
        }
        let (whole, fraction) = raw.split_once('.').unwrap_or((raw, ""));
        if whole.is_empty()
            || whole.len() > 10
            || !whole.bytes().all(|b| b.is_ascii_digit())
            || whole.len() > 1 && whole.starts_with('0')
            || fraction.len() > 6
            || !fraction.bytes().all(|b| b.is_ascii_digit())
            || raw.contains('.') && fraction.is_empty()
        {
            return Err(invalid());
        }
        let whole = whole.parse::<u64>().map_err(|_| invalid())?;
        let fraction = if fraction.is_empty() {
            0
        } else {
            fraction.parse::<u64>().map_err(|_| invalid())? * 10_u64.pow(6 - fraction.len() as u32)
        };
        Ok(Self(whole * 1_000_000 + fraction))
    }
    pub fn micros(self) -> u64 {
        self.0
    }
    pub fn decimal(self) -> String {
        format!("{}.{:06}", self.0 / 1_000_000, self.0 % 1_000_000)
    }
    /// Conservative exact ceiling of a finite JSON estimate, including scientific notation.
    pub fn estimate(value: &Value) -> Result<Self> {
        let n = value.as_number().ok_or_else(invalid)?;
        if n.as_f64()
            .is_none_or(|v| !v.is_finite() || !(0.0..=1e12).contains(&v))
        {
            return Err(invalid());
        }
        let raw = n.to_string();
        let raw = raw
            .strip_prefix('-')
            .filter(|_| n.as_f64() == Some(0.0))
            .unwrap_or(&raw);
        let (mantissa, exp) = raw.split_once(['e', 'E']).unwrap_or((raw, "0"));
        let exponent = exp.parse::<i32>().map_err(|_| invalid())?;
        let (whole, fraction) = mantissa.split_once('.').unwrap_or((mantissa, ""));
        let digits = format!("{whole}{fraction}")
            .parse::<u128>()
            .map_err(|_| invalid())?;
        let power = exponent - fraction.len() as i32 + 6;
        let micros = if digits == 0 {
            0
        } else if power >= 0 {
            digits
                .checked_mul(10_u128.checked_pow(power as u32).ok_or_else(invalid)?)
                .ok_or_else(invalid)?
        } else if power <= -39 {
            1
        } else {
            let divisor = 10_u128.pow((-power) as u32);
            digits / divisor + u128::from(digits % divisor != 0)
        };
        Ok(Self(u64::try_from(micros).map_err(|_| invalid())?))
    }
    pub fn estimated_total(start: &Value, per_item: &Value, limit: u64) -> Result<Self> {
        if !(1..=100).contains(&limit) {
            return Err(invalid());
        }
        let start = Self::estimate(start)?;
        let per_item = Self::estimate(per_item)?;
        Ok(Self(
            per_item
                .0
                .checked_mul(limit)
                .and_then(|n| n.checked_add(start.0))
                .ok_or_else(invalid)?,
        ))
    }
}
