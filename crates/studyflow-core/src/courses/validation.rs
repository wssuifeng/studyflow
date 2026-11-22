use std::fmt;

use serde_json::{Map, Value};

#[derive(Debug, PartialEq, Eq)]
pub struct PackageError {
    pub field: String,
    pub reason: String,
}

impl PackageError {
    pub const CODE: &'static str = "INVALID_COURSE_PACKAGE";

    pub(crate) fn at(field: impl Into<String>, reason: impl Into<String>) -> Self {
        Self {
            field: field.into(),
            reason: reason.into(),
        }
    }
}

impl fmt::Display for PackageError {
    fn fmt(&self, output: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(output, "{}: {}", self.field, self.reason)
    }
}
impl std::error::Error for PackageError {}

pub(super) type Checked<T> = Result<T, PackageError>;

pub(super) fn invalid<T>(field: &str, reason: impl Into<String>) -> Checked<T> {
    Err(PackageError::at(field, reason))
}

pub(super) fn object<'a>(
    value: &'a Value,
    field: &str,
    allowed: &[&str],
    required: &[&str],
) -> Checked<&'a Map<String, Value>> {
    let items = value
        .as_object()
        .ok_or_else(|| PackageError::at(field, "需要对象"))?;
    let mut unknown: Vec<_> = items
        .keys()
        .filter(|key| !allowed.contains(&key.as_str()))
        .map(String::as_str)
        .collect();
    if !unknown.is_empty() {
        unknown.sort_unstable();
        return invalid(field, format!("未知字段 {}", unknown.join(", ")));
    }
    let mut missing: Vec<_> = required
        .iter()
        .copied()
        .filter(|key| !items.contains_key(*key))
        .collect();
    if !missing.is_empty() {
        missing.sort_unstable();
        return invalid(field, format!("缺少字段 {}", missing.join(", ")));
    }
    Ok(items)
}

pub(super) fn text<'a>(
    value: &'a Value,
    field: &str,
    limit: usize,
    empty: bool,
) -> Checked<&'a str> {
    value
        .as_str()
        .filter(|data| data.chars().count() <= limit && (empty || !data.trim().is_empty()))
        .ok_or_else(|| PackageError::at(field, format!("需要非空字符串，最多{limit}字符")))
}

pub(super) fn default_text<'a>(
    value: Option<&'a Value>,
    field: &str,
    limit: usize,
) -> Checked<&'a str> {
    match value {
        Some(value) => text(value, field, limit, true),
        None => Ok(""),
    }
}

pub(crate) fn identifier<'a>(value: &'a Value, field: &str) -> Checked<&'a str> {
    value
        .as_str()
        .filter(|data| {
            let mut bytes = data.bytes();
            data.len() <= 64
                && bytes.next().is_some_and(|b| b.is_ascii_lowercase())
                && bytes.all(|b| {
                    b.is_ascii_lowercase() || b.is_ascii_digit() || matches!(b, b'_' | b'-')
                })
        })
        .ok_or_else(|| {
            PackageError::at(
                field,
                "id需小写字母开头，仅字母、数字、下划线、短横线，最多64字符",
            )
        })
}

pub(super) fn list<'a>(
    value: &'a Value,
    field: &str,
    min: usize,
    max: usize,
) -> Checked<&'a [Value]> {
    value
        .as_array()
        .filter(|items| (min..=max).contains(&items.len()))
        .map(Vec::as_slice)
        .ok_or_else(|| PackageError::at(field, format!("需要{min}—{max}项列表")))
}

pub(super) fn default_list<'a>(
    value: Option<&'a Value>,
    field: &str,
    max: usize,
) -> Checked<&'a [Value]> {
    value.map_or(Ok(&[]), |value| list(value, field, 0, max))
}

pub(super) fn choice<'a>(
    value: Option<&'a Value>,
    default: &'a str,
    allowed: &[&str],
    field: &str,
    reason: &str,
) -> Checked<&'a str> {
    let data = value.map_or(Some(default), Value::as_str);
    data.filter(|data| allowed.contains(data))
        .ok_or_else(|| PackageError::at(field, reason))
}
