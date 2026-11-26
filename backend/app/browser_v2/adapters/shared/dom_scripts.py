"""In-page JavaScript used by the hosted form filler and the interactive portal adapter."""

from __future__ import annotations

import re

from backend.app.browser_v2.adapters.challenge import CHALLENGE_HELPERS_JS

SCAN_JS = r"""
({root, maxFields}) => {
  const scope = root ? document.querySelector(root) : document;
  if (!scope) return {fields: [], missingRoot: true};
  document.querySelectorAll("[data-aa-field]").forEach(e => e.removeAttribute("data-aa-field"));
  const visible = (el) => !!el && el.getClientRects().length > 0 && getComputedStyle(el).visibility !== "hidden";
  const clip = (s) => (s || "").replace(/\s+/g, " ").trim().slice(0, 300);
  const wrapLabel = (el) => {
    const wrap = el.closest(".field, .application-question, .application-field, .form-group, fieldset, li, [class*='question'], [class*='field']");
    if (!wrap) return "";
    const l = wrap.querySelector("label, legend, .application-label, [class*='label']");
    return l ? clip(l.innerText) : "";
  };
  const labelText = (el) => {
    if (el.labels && el.labels.length) return clip([...el.labels].map(l => l.innerText).join(" "));
    const by = el.getAttribute("aria-labelledby");
    if (by) {
      const t = by.split(/\s+/).map(id => document.getElementById(id)?.innerText || "").join(" ");
      if (t.trim()) return clip(t);
    }
    const aria = el.getAttribute("aria-label");
    if (aria) return clip(aria);
    return wrapLabel(el) || clip(el.getAttribute("placeholder") || el.name || el.id || "");
  };
  const fields = [];
  const seen = new Set();
  let i = 0;
  for (const el of scope.querySelectorAll("input, select, textarea")) {
    if (fields.length >= maxFields) break;
    const type = el.tagName === "SELECT" ? "select" : el.tagName === "TEXTAREA" ? "textarea"
      : (el.getAttribute("role") === "combobox" ? "combobox" : (el.type || "text").toLowerCase());
    if (["hidden", "submit", "button", "image", "reset", "search"].includes(type)) continue;
    if (type !== "file" && !visible(el) && !(["radio", "checkbox"].includes(type) && el.labels && [...el.labels].some(visible))) continue;
    if (el.disabled || el.readOnly) continue;
    if (type === "radio" || type === "checkbox") {
      const key = type + ":" + (el.name || ("#" + i));
      if (seen.has(key)) continue;
      seen.add(key);
      const group = el.name ? [...scope.querySelectorAll(`input[type=${type}][name="${CSS.escape(el.name)}"]`)] : [el];
      const fs = el.closest("fieldset");
      const legend = fs && fs.querySelector("legend");
      const label = clip(legend ? legend.innerText : (group.length > 1 ? (wrapLabel(el) || el.name) : labelText(el)));
      const options = group.map(r => {
        const idx = i++;
        r.setAttribute("data-aa-field", String(idx));
        return {idx, label: clip(r.labels && r.labels.length ? [...r.labels].map(l => l.innerText).join(" ") : r.value),
                checked: r.checked};
      });
      fields.push({kind: type, label, name: el.name || null, required: group.some(r => r.required || r.getAttribute("aria-required") === "true") || /\*\s*$/.test(label),
                   options, value_present: group.some(r => r.checked), single: group.length === 1});
      continue;
    }
    const idx = i++;
    el.setAttribute("data-aa-field", String(idx));
    const label = labelText(el);
    fields.push({idx, kind: type, label, name: el.name || el.id || null,
      required: !!(el.required || el.getAttribute("aria-required") === "true" || /\*\s*$/.test(label)),
      options: el.tagName === "SELECT" ? [...el.options].filter(o => o.value !== "" && !/^\s*(select|choose|--)/i.test(o.text)).map(o => clip(o.text)) : null,
      value_present: el.tagName === "SELECT" ? (el.selectedIndex > 0 && el.value !== "") : !!(el.value && String(el.value).trim()),
      autocomplete: el.getAttribute("autocomplete") || null, accept: el.getAttribute("accept") || null});
  }
  return {fields, missingRoot: false};
}
"""

FORM_STATE_JS = r"""
({root, submitRe, confirmRe}) => {
""" + CHALLENGE_HELPERS_JS + r"""
  const visible = (el) => !!el && el.isConnected && el.getClientRects().length > 0 && getComputedStyle(el).visibility !== "hidden";
  const text = (el) => (el && el.innerText || "").replace(/\s+/g, " ").trim();
  const body = (document.body && document.body.innerText || "").slice(0, 20000);
  const scope = (root && document.querySelector(root)) || document;
  const errors = [...scope.querySelectorAll("[aria-invalid='true'], .field-error, .error-message, [class*='error']:not(form):not(body)")]
    .filter(visible).map(text).filter(t => t && t.length < 200).slice(0, 5);
  const sub = new RegExp(submitRe, "i");
  const submits = [...scope.querySelectorAll("button, input[type=submit], [role=button]")].filter(visible)
    .filter(b => sub.test((text(b) || b.value || "").trim())).length;
  return {url: location.href, body, errors, submits,
          confirmed: new RegExp(confirmRe, "i").test(body),
          challenge: challengeNodes() || challengeTitle() || /verify (?:that )?you are (?:a )?human|unusual traffic|press and hold/i.test(body)};
}
"""

OPTIONS_JS = r"""
({field, scoped}) => {
  const visible = (el) => !!el && el.isConnected && el.getClientRects().length > 0 && getComputedStyle(el).visibility !== "hidden";
  const text = (el) => (el && el.innerText || "").replace(/\s+/g, " ").trim();
  if (scoped) {
    const box = document.querySelector(field);
    const ids = ((box && (box.getAttribute("aria-controls") || box.getAttribute("aria-owns"))) || "").split(/\s+/).filter(Boolean);
    const lists = ids.map(id => document.getElementById(id)).filter(Boolean);
    if (!lists.length) return null;  // no ARIA link: caller diffs visible options before/after opening
    return lists.flatMap(l => [...l.querySelectorAll("[role=option]")].filter(visible).map(text));
  }
  return [...document.querySelectorAll("[role=option]")].filter(visible).map(text);
}
"""

PROBE_JS = r"""
({loggedIn, loginForm}) => {
""" + CHALLENGE_HELPERS_JS + r"""
  const visible = (el) => !!el && el.getClientRects().length > 0 && getComputedStyle(el).visibility !== "hidden";
  const body = (document.body && document.body.innerText || "").slice(0, 20000);
  const any = (sel) => { try { return [...document.querySelectorAll(sel)].some(visible); } catch (e) { return false; } };
  return {
    url: location.href,
    challenge: challengeText(body) || challengeNodes(),
    otp: any('input[autocomplete="one-time-code"],input[name*="otp" i],input[id*="otp" i]'),
    loginForm: any(loginForm),
    loggedIn: any(loggedIn),
  };
}
"""

# Hiring badges rendered inside company-name elements (live internshala: "UV Farms Active").
COMPANY_BADGE = re.compile(r"\s+(?:actively hiring|active|hiring|verified)$", re.IGNORECASE)
CARDS_JS = r"""
({pattern, limit, hosts}) => {
  const text = (el) => (el && el.innerText || "").replace(/\s+/g, " ").trim();
  const re = new RegExp(pattern);
  const out = [], seen = new Set();
  const postingIds = (el) => {
    const ids = new Set();
    for (const x of el.querySelectorAll("a[href]")) {
      try { const v = new URL(x.href, location.href); const mm = hosts.includes(v.hostname) && v.pathname.match(re);
            if (mm) ids.add(mm[1]); } catch (e) { /* ignore */ }
      if (ids.size > 1) break;
    }
    return ids.size;
  };
  for (const a of document.querySelectorAll("a[href]")) {
    let u; try { u = new URL(a.href, location.href); } catch (e) { continue; }
    if (!hosts.includes(u.hostname)) continue;
    const m = u.pathname.match(re);
    if (!m || seen.has(m[1])) continue;
    seen.add(m[1]);
    // Live 2026-11-26: class-name heuristics picked the anchor itself (internshala a.job-title-href) or a
    // bare row (wellfound), losing company/age. The card is the LARGEST ancestor holding only this posting.
    let card = a;
    for (let i = 0; i < 10 && card.parentElement && card.parentElement !== document.body
         && postingIds(card.parentElement) <= 1; i++) card = card.parentElement;
    const ACTION = /^(?:view job|apply(?: now)?|save|share|follow|change status.*|report|see all .*jobs.*)$/i;
    const pick = (sel) => { if (!card) return null; for (const el of card.querySelectorAll(sel)) {
        const t = text(el); if (t && t.length <= 120 && !ACTION.test(t)) return t; } return null; };
    const ctext = text(card).slice(0, 1500);
    // Company blocks listing several roles (wellfound): use the group's single company link.
    const groupCompany = () => {
      let group = card.parentElement;
      for (let i = 0; i < 6 && group && group !== document.body; i++, group = group.parentElement) {
        const names = new Set([...group.querySelectorAll("a[href*='/company/'], a[href*='/companies/']")]
          .map(text).filter(t => t && t.length < 120));
        if (names.size === 1) return [...names][0];
        if (names.size > 1) return null;  // reached a list of several companies: never guess
      }
      return null;
    };
    const posted = (ctext.match(/(?:posted\s*:?\s*)?(?:just now|today|yesterday|few hours ago|\d+\+?\s*(?:minute|hour|day|week|month)s?\s+ago)/i) || [null])[0];
    const applicants = (ctext.match(/(?:less than\s+)?\d[\d,]*\+?\s+applicants?/i) || [null])[0];
    const heading = pick("h2, h3, h4, [class*='title' i]");
    out.push({id: m[1], url: u.origin + u.pathname, title: (a.getAttribute("title") || text(a) || heading || "").slice(0, 200) || null,
              company: pick(".company-name, .company_name, [class*='company-name' i], [class*='company_name' i], "
                            + "a[href*='/company/'], [class*='employer' i], p[class*='company' i], [class*='company' i]:not(div:has(a[href]))")
                       || groupCompany(), posted, applicants});
    const last = out[out.length - 1];
    if (last.company) last.company = last.company.slice(0, 120);  // never a whole card's text
    if (out.length >= limit) break;
  }
  return out;
}
"""

DETAIL_JS = r"""
({applyRe, appliedRe, externalRe, applySel, companySel, hintRe}) => {
  const visible = (el) => !!el && el.isConnected && el.getClientRects().length > 0 && getComputedStyle(el).visibility !== "hidden";
  const text = (el) => (el && el.innerText || "").replace(/\s+/g, " ").trim();
  const body = (document.body && document.body.innerText || "").slice(0, 30000);
  // Phase 8: the portal's primary selector only counts elements that also read as Apply.
  const primary = applySel ? [...document.querySelectorAll(applySel)].filter(el => visible(el) && !el.disabled &&
    new RegExp(applyRe, "i").test(((el.innerText || "").replace(/\s+/g, " ").trim() || el.value || "").trim())) : [];
  const pick = (sel) => { const el = [...document.querySelectorAll(sel)].find(visible); return el ? text(el) : null; };
  const desc = [...document.querySelectorAll("[class*='description' i], [class*='job-desc' i], [class*='jobDescription' i], [class*='about' i], [class*='details' i], article, main")]
    .filter(visible).map(text).sort((a, b) => b.length - a.length)[0] || "";
  // Live 2026-11-26 (wellfound): the logged-in NAV has an "Applied" link - navigation/header/menu
  // controls are never apply/applied evidence for the job on the page.
  const chrome = "nav, header, [role=navigation], [role=menu], [role=menubar], [role=banner], aside";
  const controls = [...document.querySelectorAll("button, a, [role=button], input[type=submit]")]
    .filter(b => visible(b) && !b.closest(chrome));
  const label = (b) => (text(b) || b.value || "").trim();
  const ACTION = /^(?:view job|apply(?: now)?|save|share|follow|change status.*|report|interested|not interested|see all .*jobs.*)$/i;
  const shortText = (sel) => { if (!sel) return null; for (const el of document.querySelectorAll(sel)) {
      if (!visible(el) || el.closest(chrome)) continue; const t = text(el);
      if (t && t.length >= 2 && t.length <= 80 && !ACTION.test(t)) return t; } return null; };
  const apply = new RegExp(applyRe, "i"), applied = new RegExp(appliedRe, "i"), external = new RegExp(externalRe, "i");
  // Phase 8: duplicate CTAs that trigger the SAME action (same ng-click/onclick/href/form) are one
  // control (live instahyre: header + sticky footer "Apply"); different actions stay ambiguous.
  const actionKey = (b) => [label(b).toLowerCase(), b.getAttribute("ng-click") || b.getAttribute("onclick") ||
    b.getAttribute("data-action") || (b.href ? new URL(b.href, location.href).href : "") ||
    (b.form ? (b.form.getAttribute("action") || b.form.id || "form") : "")].join("|");
  // Live 2026-11-26 (instahyre): <a>Apply now</a> wraps <button ng-click=submitChoice(..)>Apply now</button>:
  // one click target, so nested matches collapse to the innermost control.
  const innermost = (list) => list.filter(b => !list.some(o => o !== b && b.contains(o)));
  const applyControls = innermost(primary.length ? primary : controls.filter(b => apply.test(label(b)) && !b.disabled));
  const applyActions = new Set(applyControls.map(actionKey)).size;
  const sameAction = applyControls.length > 1 && applyActions === 1 && !actionKey(applyControls[0]).endsWith("|");
  // Phase 8: posting date from the job page when the card had none (JSON-LD JobPosting.datePosted,
  // <time datetime>, article:published_time).
  let datePosted = null;
  for (const s of document.querySelectorAll('script[type="application/ld+json"]')) {
    try {
      const d = JSON.parse(s.textContent);
      for (const it of (Array.isArray(d) ? d : (d["@graph"] || [d]))) {
        if ([].concat(it["@type"] || []).some(t => String(t).includes("JobPosting")) && it.datePosted) datePosted = String(it.datePosted);
      }
    } catch (e) { /* ignore */ }
  }
  if (!datePosted) {
    const meta = document.querySelector('meta[property="article:published_time"],meta[itemprop="datePosted"]');
    const t = [...document.querySelectorAll("main time[datetime], article time[datetime], [class*='posted' i] time[datetime]")]
      .find(el => !el.closest(chrome));
    datePosted = (meta && meta.getAttribute("content")) || (t && t.getAttribute("datetime")) || null;
  }
  return {
    url: location.href,
    title: pick("h1") || pick("h2"),
    company: shortText(companySel) || shortText("[class*='company' i] a, [class*='company-name' i], [class*='companyName' i], [class*='company' i], [class*='employer' i], [class*='startup' i] a"),
    description: desc.slice(0, 8000) || null,
    posted: (body.match(/(?:posted\s*(?:on)?\s*:?\s*)?(?:just now|today|yesterday|few hours ago|\d+\+?\s*(?:minute|hour|day|week|month)s?\s+ago|\d{4}-\d{2}-\d{2})/i) || [null])[0],
    applicants: (body.match(/(?:less than\s+)?\d[\d,]*\+?\s+applicants?/i) || [null])[0],
    salary: (body.match(/(?:₹|rs\.?|inr|\$|usd)\s?[\d,.]+\s*(?:k|l|lpa|lakhs?|lacs?)?(?:\s*(?:-|–|to)\s*(?:₹|rs\.?|inr|\$|usd)?\s?[\d,.]+\s*(?:k|l|lpa|lakhs?|lacs?)?)?(?:\s*(?:\/|per)\s*(?:year|annum|month|yr|mo))?/i) || [null])[0],
    location: pick("[class*='location' i]"),
    workMode: (body.match(/\b(remote|hybrid|work from home|on-?site|in office)\b/i) || [null])[0],
    // Live 2026-11-26 (internshala): "150+ candidates have already applied" is NOT our application.
    // Body text counts only in the first person, and never while an enabled Apply control is shown.
    applied: controls.some(b => applied.test(label(b))) || (!applyControls.length &&
      /\byou(?:'ve| have)(?: already)? applied\b|\byou already applied\b|\balready applied to this\b/i.test(body)),
    // A portal-declared primary Apply control wins over duplicate CTAs of the same flow (live internshala: 4).
    applyButtons: sameAction ? 1 : applyControls.length,
    externalLinks: controls.filter(b => external.test(label(b))).map(b => b.href || null).filter(Boolean).slice(0, 3),
    datePosted,
    closed: /no longer (?:accepting applications|available|active|open)|this (?:job|role|position|opening) (?:has been|is|was) (?:closed|filled|removed)|(?:job|position|role) (?:is )?(?:closed|expired|filled)|applications? (?:are |is )?(?:now )?closed|not accepting applications/i.test(body),
    loginToApply: /(?:log ?in|sign ?in|sign up|create an account|register) (?:to|before you) apply/i.test(body),
    unsupportedApply: !!hintRe && controls.some(b => new RegExp(hintRe, "i").test(label(b))),
  };
}
"""

# Phase 8: the click path marks the control DETAIL_JS counted (same chrome exclusion, same
# primary selector, same "same action" dedup), so a nav/sticky copy can never make it "changed".
MARK_APPLY_JS = r"""
({applyRe, appliedRe, applySel}) => {
  const visible = (el) => !!el && el.isConnected && el.getClientRects().length > 0 && getComputedStyle(el).visibility !== "hidden";
  const text = (el) => (el && el.innerText || "").replace(/\s+/g, " ").trim();
  for (const old of document.querySelectorAll("[data-aa-apply]")) old.removeAttribute("data-aa-apply");
  const chrome = "nav, header, [role=navigation], [role=menu], [role=menubar], [role=banner], aside";
  const label = (b) => (text(b) || b.value || "").trim();
  const apply = new RegExp(applyRe, "i"), applied = new RegExp(appliedRe, "i");
  const primary = applySel ? [...document.querySelectorAll(applySel)]
    .filter(el => visible(el) && !el.disabled && apply.test(label(el))) : [];
  const controls = [...document.querySelectorAll("button, a, [role=button], input[type=submit]")]
    .filter(b => visible(b) && !b.closest(chrome));
  const actionKey = (b) => [label(b).toLowerCase(), b.getAttribute("ng-click") || b.getAttribute("onclick") ||
    b.getAttribute("data-action") || (b.href ? new URL(b.href, location.href).href : "") ||
    (b.form ? (b.form.getAttribute("action") || b.form.id || "form") : "")].join("|");
  const matches = primary.length ? primary : controls.filter(b => apply.test(label(b)) && !b.disabled);
  const found = matches.filter(b => !matches.some(o => o !== b && b.contains(o)));
  const actions = new Set(found.map(actionKey)).size;
  const same = found.length > 1 && actions === 1 && !actionKey(found[0]).endsWith("|");
  if (found.length === 1 || same) found[0].setAttribute("data-aa-apply", "1");
  return {count: same ? 1 : found.length, applied: controls.some(b => applied.test(label(b)))};
}
"""

DIALOG_JS = r"""
(selectors) => {
  const visible = (el) => !!el && el.isConnected && el.getClientRects().length > 0 && getComputedStyle(el).visibility !== "hidden";
  for (const sel of selectors) {
    const el = [...document.querySelectorAll(sel)].filter(visible).pop();
    if (el && el.querySelector("input, textarea, select, button")) {
      if (!el.id) el.id = "aa-dialog-" + Math.random().toString(36).slice(2, 8);
      return "#" + CSS.escape(el.id);
    }
  }
  return null;
}
"""
