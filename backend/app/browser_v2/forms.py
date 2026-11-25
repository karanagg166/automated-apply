"""Compact interactive-form extraction: labels, types, options, required flags.

Returns small JSON for LLM/HITL use. Never returns raw HTML.
"""

from __future__ import annotations

from typing import Any

MAX_FIELDS = 60
MAX_TEXT = 300

EXTRACT_FORM_JS = r"""
({root, maxFields, maxText}) => {
  const scope = root ? document.querySelector(root) : document;
  if (!scope) return {fields: [], chatbot: null, truncated: false};
  const visible = (el) => !!el && el.getClientRects().length > 0 &&
    getComputedStyle(el).visibility !== "hidden";
  const clip = (s) => (s || "").replace(/\s+/g, " ").trim().slice(0, maxText);
  const labelFor = (el) => {
    if (el.labels && el.labels.length) return clip([...el.labels].map(l => l.innerText).join(" "));
    const aria = el.getAttribute("aria-label") || "";
    const by = el.getAttribute("aria-labelledby");
    if (by) return clip(by.split(/\s+/).map(id => document.getElementById(id)?.innerText || "").join(" "));
    return clip(aria || el.getAttribute("placeholder") || el.name || "");
  };
  const fields = [];
  const seenRadio = new Set();
  for (const el of scope.querySelectorAll(
      "input,select,textarea,[contenteditable='true'],[role=combobox],[role=radiogroup]")) {
    if (fields.length >= maxFields) break;
    if (!visible(el)) continue;
    const type = el.tagName === "SELECT" ? "select" : el.tagName === "TEXTAREA" ? "textarea"
      : el.isContentEditable ? "contenteditable" : (el.getAttribute("role") || el.type || "text");
    if (["hidden", "submit", "button", "image", "reset"].includes(type)) continue;
    if (type === "radio") {
      if (seenRadio.has(el.name)) continue;
      seenRadio.add(el.name);
      const group = [...scope.querySelectorAll(`input[type=radio][name="${CSS.escape(el.name)}"]`)];
      fields.push({kind: "radio", name: el.name || null, label: labelFor(el),
        required: group.some(r => r.required),
        options: group.map(r => clip(r.value || labelFor(r))).slice(0, 50)});
      continue;
    }
    fields.push({
      kind: type, name: el.name || el.id || null, label: labelFor(el),
      required: !!(el.required || el.getAttribute("aria-required") === "true"),
      options: el.tagName === "SELECT" ? [...el.options].map(o => clip(o.text)).slice(0, 50) : undefined,
      value_present: !!(el.value || (el.isContentEditable && el.textContent.trim())),
    });
  }
  const drawer = document.querySelector(".chatbot_DrawerContentWrapper");
  let chatbot = null;
  if (visible(drawer)) {
    const msgs = [...drawer.querySelectorAll(".chatbot_MessageContainer .botItem .botMsg")].filter(visible);
    chatbot = {
      question: clip(msgs.length ? msgs[msgs.length - 1].innerText : ""),
      chips: [...drawer.querySelectorAll(".chipsContainer .chatbot_Chip")].filter(visible).map(c => clip(c.innerText)),
      radios: [...drawer.querySelectorAll("input.ssrc__radio[type=radio]")].map(r => clip(r.value)),
      text_input: !!drawer.querySelector('.textArea[contenteditable="true"]'),
      file_input: !!drawer.querySelector("input.chatbot_Uploader[type=file]"),
    };
  }
  return {fields, chatbot, truncated: fields.length >= maxFields};
}
"""


async def extract_form(page: Any, root: str | None = None) -> dict[str, Any]:
    """Compact snapshot of the visible form or Naukri chatbot on `page`."""
    return await page.evaluate(
        EXTRACT_FORM_JS, {"root": root, "maxFields": MAX_FIELDS, "maxText": MAX_TEXT})
