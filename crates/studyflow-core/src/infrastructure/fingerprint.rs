use std::fmt::Write;

use serde_json::{Number, Value};
use sha2::{Digest, Sha256};

/// Byte layouts used by existing Python JSON fingerprints. All three sort keys.
#[derive(Clone, Copy)]
pub enum JsonFingerprint {
    Ascii,
    Utf8,
    CompactUtf8,
}

impl JsonFingerprint {
    pub fn hash(self, value: &Value) -> String {
        format!("{:x}", Sha256::digest(self.serialize(value).as_bytes()))
    }

    pub fn serialize(self, value: &Value) -> String {
        let mut output = String::new();
        self.write_value(&mut output, value);
        output
    }

    fn write_value(self, output: &mut String, value: &Value) {
        let (item_separator, field_separator) = match self {
            Self::CompactUtf8 => (",", ":"),
            _ => (", ", ": "),
        };
        match value {
            Value::Array(items) => {
                output.push('[');
                for (index, item) in items.iter().enumerate() {
                    if index > 0 {
                        output.push_str(item_separator);
                    }
                    self.write_value(output, item);
                }
                output.push(']');
            }
            Value::Object(fields) => {
                let mut keys: Vec<_> = fields.keys().collect();
                keys.sort_unstable();
                output.push('{');
                for (index, key) in keys.into_iter().enumerate() {
                    if index > 0 {
                        output.push_str(item_separator);
                    }
                    self.write_string(output, key);
                    output.push_str(field_separator);
                    self.write_value(output, &fields[key]);
                }
                output.push('}');
            }
            Value::String(text) => self.write_string(output, text),
            Value::Null => output.push_str("null"),
            Value::Bool(value) => output.push_str(if *value { "true" } else { "false" }),
            Value::Number(number) => write_number(output, number),
        }
    }

    fn write_string(self, output: &mut String, text: &str) {
        output.push('"');
        for ch in text.chars() {
            match ch {
                '"' => output.push_str("\\\""),
                '\\' => output.push_str("\\\\"),
                '\u{08}' => output.push_str("\\b"),
                '\u{0c}' => output.push_str("\\f"),
                '\n' => output.push_str("\\n"),
                '\r' => output.push_str("\\r"),
                '\t' => output.push_str("\\t"),
                '\u{00}'..='\u{1f}' => write!(output, "\\u{:04x}", u32::from(ch)).unwrap(),
                _ if matches!(self, Self::Ascii) && ch >= '\u{7f}' => {
                    for code in ch.encode_utf16(&mut [0; 2]) {
                        write!(output, "\\u{code:04x}").unwrap();
                    }
                }
                _ => output.push(ch),
            }
        }
        output.push('"');
    }
}

fn write_number(output: &mut String, number: &Number) {
    if !number.is_f64() {
        write!(output, "{number}").unwrap();
        return;
    }
    let value = number.as_f64().expect("finite JSON number");
    // serde_json emits a shortest round-trip mantissa. Preserve it while
    // applying Python repr's exponent threshold, plus sign, and zero padding.
    let shortest = number.to_string();
    if let Some((mantissa, exponent)) = shortest.split_once(['e', 'E']) {
        let exponent: i32 = exponent.parse().expect("JSON number exponent");
        if !(-4..16).contains(&exponent) {
            write!(output, "{mantissa}e{exponent:+03}").unwrap();
            return;
        }
    }
    if value.abs() >= 1e16 || (value != 0.0 && value.abs() < 1e-4) {
        let scientific = format!("{value:e}");
        let (mantissa, exponent) = scientific.split_once('e').expect("scientific exponent");
        let exponent: i32 = exponent.parse().expect("scientific exponent value");
        write!(output, "{mantissa}e{exponent:+03}").unwrap();
    } else {
        let decimal = value.to_string();
        output.push_str(&decimal);
        if !decimal.contains('.') {
            output.push_str(".0");
        }
    }
}
