//! Disposable PDF inspection only. No filesystem, network, OCR or model access.
use lopdf::{
    Dictionary, Document, LoadOptions, Object, Stream,
    content::{Content, Operation},
};
use serde::Serialize;
use std::collections::BTreeSet;

pub const MAX_BYTES: usize = 5 * 1024 * 1024;
const STREAM_LIMIT: usize = 4 * 1024 * 1024;
#[derive(Clone, Copy)]
pub enum Mode {
    Extract,
    Validate,
}
#[derive(Serialize)]
pub struct Extracted {
    pub text: String,
    pub pages: usize,
    pub links: Vec<String>,
}
type Result<T> = std::result::Result<T, &'static str>;
fn resolve<'a>(doc: &'a Document, value: &'a Object) -> Result<&'a Object> {
    doc.dereference(value)
        .map(|(_, v)| v)
        .map_err(|_| "invalid_pdf_reference")
}
fn optional<'a>(doc: &'a Document, row: &'a Dictionary, key: &[u8]) -> Result<Option<&'a Object>> {
    if !row.has(key) {
        return Ok(None);
    }
    resolve(doc, row.get(key).map_err(|_| "invalid_pdf_dictionary")?).map(Some)
}
fn dictionary(value: &Object) -> Result<&Dictionary> {
    value.as_dict().map_err(|_| "invalid_pdf_dictionary")
}
fn action<'a>(
    doc: &'a Document,
    value: &'a Object,
    opening: bool,
    mode: Mode,
) -> Result<Option<&'a Dictionary>> {
    let value = resolve(doc, value)?;
    if matches!(mode, Mode::Validate) {
        // The source-only validation contract disallows all opening actions.
        if opening {
            return Err("active_content_not_supported");
        }
    } else if opening && matches!(value, Object::Array(_)) {
        return Ok(None);
    }
    let row = dictionary(value)?;
    if matches!(mode, Mode::Extract) && row.has(b"Next") {
        return Err("active_content_not_supported");
    }
    let kind = optional(doc, row, b"S")?
        .and_then(|s| s.as_name().ok())
        .ok_or("active_content_not_supported")?;
    if kind != b"GoTo" && (opening || kind != b"URI") {
        return Err("active_content_not_supported");
    }
    Ok(Some(row))
}
pub fn inspect(raw: &[u8], mode: Mode) -> Result<Extracted> {
    if raw.len() > MAX_BYTES {
        return Err("pdf_too_large");
    }
    if !raw.starts_with(b"%PDF-")
        || !raw[raw.len().saturating_sub(1024)..]
            .windows(5)
            .any(|w| w == b"%%EOF")
    {
        return Err("invalid_pdf");
    }
    let mut doc = Document::load_mem_with_options(
        raw,
        LoadOptions {
            strict: true,
            max_decompressed_size: Some(STREAM_LIMIT),
            ..Default::default()
        },
    )
    .map_err(|_| "invalid_or_unsafe_pdf")?;
    if doc.is_encrypted() || doc.trailer.has(b"Encrypt") || doc.encryption_state.is_some() {
        return Err("encrypted_pdf_not_supported");
    }
    if doc.objects.len() > 50000 {
        return Err("pdf_too_complex");
    }
    let pages = doc.get_pages();
    let max = if matches!(mode, Mode::Extract) {
        20
    } else {
        100
    };
    if pages.is_empty() || pages.len() > max {
        return Err("pdf_page_limit");
    }
    let root = doc.catalog().map_err(|_| "invalid_pdf_catalog")?;
    if root.has(b"AA") {
        return Err("active_content_not_supported");
    }
    if let Some(open) = optional(&doc, root, b"OpenAction")? {
        action(&doc, open, true, mode)?;
    }
    if let Some(names) = optional(&doc, root, b"Names")? {
        let names = dictionary(names)?;
        let attachments = optional(&doc, names, b"EmbeddedFiles")?
            .map(dictionary)
            .transpose()?;
        // An empty EmbeddedFiles dictionary contains no attachments. Extraction
        // permits that common producer artifact; source validation is stricter.
        if names.has(b"JavaScript")
            || attachments.is_some_and(|row| matches!(mode, Mode::Validate) || !row.is_empty())
        {
            return Err("active_content_not_supported");
        }
    }
    if let Some(form) = optional(&doc, root, b"AcroForm")?
        && (matches!(mode, Mode::Extract) || dictionary(form)?.has(b"XFA"))
    {
        return Err("active_content_not_supported");
    }
    let mut links = BTreeSet::new();
    let mut parts = Vec::new();
    for (number, id) in &pages {
        let page = doc.get_dictionary(*id).map_err(|_| "invalid_pdf_page")?;
        if page.has(b"AA") {
            return Err("active_content_not_supported");
        }
        if let Some(annotations) = optional(&doc, page, b"Annots")? {
            let annotations = annotations
                .as_array()
                .map_err(|_| "invalid_pdf_annotations")?;
            if annotations.len() > 10000 {
                return Err("pdf_too_complex");
            }
            for item in annotations {
                let item = dictionary(resolve(&doc, item)?)?;
                let subtype = optional(&doc, item, b"Subtype")?.and_then(|v| v.as_name().ok());
                if item.has(b"AA")
                    || (matches!(mode, Mode::Extract)
                        && subtype.is_some_and(|s| {
                            [
                                b"FileAttachment".as_slice(),
                                b"RichMedia",
                                b"Movie",
                                b"Sound",
                                b"Screen",
                                b"3D",
                                b"Widget",
                            ]
                            .contains(&s)
                        }))
                {
                    return Err("active_content_not_supported");
                }
                if let Some(raw) = optional(&doc, item, b"A")?
                    && let Some(action) = action(&doc, raw, false, mode)?
                    && matches!(mode, Mode::Extract)
                    && let Some(uri) = optional(&doc, action, b"URI")?
                {
                    let bytes = uri.as_str().map_err(|_| "invalid_pdf_link")?;
                    let uri = String::from_utf8_lossy(bytes);
                    if !["https://", "http://", "mailto:", "tel:"]
                        .iter()
                        .any(|s| uri.to_ascii_lowercase().starts_with(s))
                    {
                        return Err("active_content_not_supported");
                    }
                    if uri.starts_with("https://")
                        && uri.chars().count() <= 2048
                        && links.len() < 100
                    {
                        links.insert(uri.into_owned());
                    }
                }
            }
        }
        if matches!(mode, Mode::Extract) {
            // lopdf ignores Td/TD/Tm line movement when collecting text. Preserve
            // vertical boundaries in the in-memory extraction copy so adjacent
            // names, emails and skills do not become a single invented token.
            let raw = doc
                .get_page_content_with_limit(*id, STREAM_LIMIT)
                .map_err(|_| "pdf_text_extraction_failed")?;
            let mut content = Content::decode(&raw).map_err(|_| "pdf_text_extraction_failed")?;
            let mut operations = Vec::with_capacity(content.operations.len());
            let mut last_y = None;
            for operation in content.operations {
                let number = |index: usize| {
                    operation.operands.get(index).and_then(|v| match v {
                        Object::Integer(n) => Some(*n as f64),
                        Object::Real(n) => Some(f64::from(*n)),
                        _ => None,
                    })
                };
                let boundary = match operation.operator.as_str() {
                    "BT" => {
                        last_y = None;
                        false
                    }
                    "Td" | "TD" => number(1).is_some_and(|v| v.abs() > 0.01),
                    "Tm" => {
                        let y = number(5);
                        let moved = last_y
                            .zip(y)
                            .is_some_and(|(a, b): (f64, f64)| (a - b).abs() > 0.01);
                        last_y = y;
                        moved
                    }
                    _ => false,
                };
                if boundary {
                    operations.push(Operation::new("T*", vec![]));
                }
                operations.push(operation);
            }
            content.operations = operations;
            let encoded = content.encode().map_err(|_| "pdf_text_extraction_failed")?;
            let stream = doc.add_object(Stream::new(Dictionary::new(), encoded));
            doc.get_dictionary_mut(*id)
                .map_err(|_| "invalid_pdf_page")?
                .set("Contents", stream);
            // Limits cover page streams and font/CMap decoding before text allocation.
            let page = doc
                .extract_text_with_limit(&[*number], STREAM_LIMIT)
                .map_err(|_| "pdf_text_extraction_failed")?;
            parts.push(page.chars().take(16000).collect::<String>());
        }
    }
    Ok(Extracted {
        text: parts.join("\n").chars().take(32000).collect(),
        pages: pages.len(),
        links: links.into_iter().collect(),
    })
}
