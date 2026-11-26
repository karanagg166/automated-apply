"""In-page JavaScript for the Naukri adapter (auth probe, SRP, JD header, chatbot, history, OTP)."""

from __future__ import annotations

from backend.app.browser_v2.adapters.challenge import CHALLENGE_HELPERS_JS

VISIBLE_JS = """const visible = (el) => !!el && el.isConnected && el.getClientRects().length > 0 &&
  getComputedStyle(el).visibility !== "hidden";
const text = (el) => (el && el.innerText || "").replace(/\\s+/g, " ").trim();
const jdHeader = () => document.querySelector("#job_header") ||
  [...document.querySelectorAll('[class*="jd-header"],[class*="jdHeader"]')].find(h => h.querySelector("h1") && visible(h));"""

AUTH_PROBE_JS = "() => {" + VISIBLE_JS + "\n" + CHALLENGE_HELPERS_JS + r"""
  const body = (document.body && document.body.innerText || "").slice(0, 20000);
  const any = (sel) => [...document.querySelectorAll(sel)].some(visible);
  return {
    url: location.href,
    challenge: challengeText(body) || challengeNodes(),
    otp: any('input[autocomplete="one-time-code"],input[name*="otp" i],input[id*="otp" i]'),
    loginForm: any('input[type=password],#usernameField,form[name="login-form"],#loginForm,[class*="loginForm"]'),
    loggedIn: any('.nI-gNb-drawer__icon,.nI-gNb-icon-img,.nI-gNb-info,.nI-gNb-drawer,a[href*="/mnjuser/profile"],.view-profile-wrapper'),
  };
}"""

LISTING_JS = "({limit}) => {" + VISIBLE_JS + r"""
  const out = [], seen = new Set();
  for (const a of document.querySelectorAll('a[href*="/job-listings-"]')) {
    let u; try { u = new URL(a.href, location.origin); } catch { continue; }
    if (u.origin !== "https://www.naukri.com") continue;
    const path = u.pathname.replace(/\/$/, "");
    const m = path.match(/^\/job-listings-[a-zA-Z0-9%_-]+-(\d{10,20})$/);
    if (!m || seen.has(m[1])) continue;
    seen.add(m[1]);
    const card = a.closest('[data-job-id],.srp-jobtuple-wrapper,.cust-job-tuple,article.jobTuple,.jobTuple,article') || a.parentElement;
    const pick = (sel) => text(card && card.querySelector(sel)) || null;
    out.push({id: m[1], url: u.origin + path, title: (a.getAttribute("title") || text(a)) || null,
      company: pick('.comp-name,[class*="comp-name"],[class*="compName"]'),
      posted: pick('.job-post-day,[class*="job-post-day"],[class*="postDay"],[class*="post-day"]'),
      experience: pick('.expwdth,[class*="exp-wrap"],[class*="expwdth"],[class*="experience"]')});
    if (out.length >= limit) break;
  }
  return {jobs: out, empty: /no jobs found|no results found/i.test(document.body && document.body.innerText || "")};
}"""

DETAIL_JS = "() => {" + VISIBLE_JS + r"""
  const header = jdHeader();
  const spans = header ? [...header.querySelectorAll("span,p,div")].map(text).filter(t => t && t.length < 80) : [];
  const applicantRe = [/^(?:applicants?\s*:?\s*)?[\d,]+\+?(?:\s*(?:-|–|to)\s*[\d,]+)?(?:\s*applicants?)?$/i,
                       /^(?:applicants?\s*:?\s*)?(?:less than|fewer than)\s+[\d,]+(?:\s*applicants?)?$/i];
  const applicants = [...new Set(spans.filter(t => /applicants?/i.test(t) && applicantRe.some(r => r.test(t))))];
  const posted = spans.find(t => /^posted\s*:?/i.test(t)) || null;
  let datePosted = null;
  for (const s of document.querySelectorAll('script[type="application/ld+json"]')) {
    try {
      const d = JSON.parse(s.textContent);
      const items = Array.isArray(d) ? d : (d["@graph"] || [d]);
      for (const it of items) {
        if ([].concat(it["@type"] || []).some(t => String(t).includes("JobPosting")) && it.datePosted) datePosted = String(it.datePosted);
      }
    } catch (e) {}
  }
  let ldDescription = null;
  for (const s of document.querySelectorAll('script[type="application/ld+json"]')) {
    try {
      const d = JSON.parse(s.textContent);
      for (const it of (Array.isArray(d) ? d : (d["@graph"] || [d]))) {
        if ([].concat(it["@type"] || []).some(t => String(t).includes("JobPosting")) && it.description) {
          const box = document.createElement("div"); box.innerHTML = String(it.description);
          ldDescription = box.textContent;
        }
      }
    } catch (e) {}
  }
  const jd = document.querySelector('[class*="job-desc"],[class*="JDC"],[class*="dang-inner-html"]');
  const description = (text(jd) || ldDescription || "").replace(/\s+/g, " ").trim().slice(0, 8000) || null;
  const salary = spans.find(t => /(lacs?|lakhs?|lpa|₹|not disclosed|crore)/i.test(t) && t.length < 60) || null;
  // Phase 8: was `const location`, which shadowed window.location (url was always undefined and a
  // header without a location element threw "Cannot read properties of null (reading 'href')").
  const jobLocation = text(header && header.querySelector('[class*="location"],[class*="loc"]')) || null;
  const workMode = spans.find(t => /^(remote|hybrid|work from (home|office)|on-?site)/i.test(t)) || null;
  const experience = spans.find(t => /^(?:\d{1,2}\s*(?:-|–|to)\s*\d{1,2}|\d{1,2}\+?)\s*(?:yrs?|years?)$|^fresher/i.test(t)) || null;
  const buttons = header ? [...header.querySelectorAll("button,[role=button],a")].filter(visible) : [];
  return {
    description, salary, location: jobLocation, workMode, experience,
    url: window.location.href,
    title: text(header && header.querySelector("h1")) || null,
    company: text(header && header.querySelector('[class*="comp-name"] > a,[class*="compName"] > a'))
      || text(header && header.querySelector('[class*="comp-name"],[class*="compName"]')) || null,
    applicants, posted, datePosted,
    applied: buttons.some(b => /^(already applied|applied)$/i.test(text(b))),
    external: buttons.some(b => /company site/i.test(text(b))) || !!document.querySelector("#company-site-button"),
    // Phase 8: the employer URL when Naukri exposes it in the DOM (ATS handoff); usually null
    // because "Apply on company site" opens the URL from JS.
    externalUrl: (() => {
      for (const b of [...buttons, document.querySelector("#company-site-button")].filter(Boolean)) {
        if (!/company site/i.test(text(b)) && b.id !== "company-site-button") continue;
        const a = b.closest("a[href]") || b.querySelector("a[href]");
        const v = (a && a.href) || b.getAttribute("data-href") || b.getAttribute("data-url");
        if (v && /^https:\/\//.test(v) && !/naukri\.com/.test(new URL(v).hostname)) return v;
      }
      return null;
    })(),
    applyButtons: buttons.filter(b => b.tagName === "BUTTON" && /^apply$/i.test(text(b)) && !b.disabled).length,
    closed: /this job is no longer (?:available|active)|job (?:has )?expired|no longer accepting applications|hiring for this (?:job|role) is closed/i
      .test((document.body && document.body.innerText || "").slice(0, 20000)),
  };
}"""

# Phase 8: the click path resolves the Apply control exactly like DETAIL_JS (same header root,
# visible + enabled only) and marks the single match so the locator can never see a hidden copy.
MARK_APPLY_JS = "() => {" + VISIBLE_JS + r"""
  for (const old of document.querySelectorAll("[data-aa-apply]")) old.removeAttribute("data-aa-apply");
  const header = jdHeader();
  const buttons = header ? [...header.querySelectorAll("button,[role=button],a")].filter(visible) : [];
  const apply = buttons.filter(b => b.tagName === "BUTTON" && /^apply$/i.test(text(b)) && !b.disabled);
  if (apply.length === 1) apply[0].setAttribute("data-aa-apply", "1");
  const drawer = [...document.querySelectorAll(".chatbot_DrawerContentWrapper")].some(visible);
  return {
    header: !!header, count: apply.length, drawer,
    applied: buttons.some(b => /^(already applied|applied)$/i.test(text(b))),
    external: buttons.some(b => /company site/i.test(text(b))) || !!document.querySelector("#company-site-button"),
  };
}"""

PAGE_STATE_JS = "() => {" + VISIBLE_JS + r"""
  const drawer = [...document.querySelectorAll(".chatbot_DrawerContentWrapper")].find(visible);
  const header = document.querySelector('#job_header,[class*="jd-header"],[class*="jdHeader"]');
  const msgs = drawer ? [...drawer.querySelectorAll(".chatbot_MessageContainer .botItem .botMsg")].filter(visible) : [];
  return {
    url: location.href,
    body: (document.body && document.body.innerText || "").slice(0, 20000),
    drawer: !!drawer,
    question: msgs.length ? text(msgs[msgs.length - 1]).slice(0, 2000) : null,
    chips: drawer ? [...drawer.querySelectorAll(".chipsContainer .chatbot_Chip")].filter(visible).map(text)
      .filter(t => !/^skip this question$/i.test(t)) : [],
    skippable: !!drawer && [...drawer.querySelectorAll(".chatbot_Chip, button, [role=button], span, div")]
      .some(el => visible(el) && el.children.length === 0 && /^skip this question$/i.test(text(el))),
    radios: drawer ? [...drawer.querySelectorAll('input.ssrc__radio[type="radio"]')].map(r => String(r.value || "").trim()) : [],
    textInput: !!(drawer && [...drawer.querySelectorAll('.textArea[contenteditable="true"],textarea,input[type=text]')].find(visible)),
    // Phase 8: multi-select checkboxes and dropdowns inside the chatbot drawer.
    checkboxes: drawer ? [...drawer.querySelectorAll('input[type="checkbox"]')].map(c => {
      const label = (c.id && drawer.querySelector('label[for="' + CSS.escape(c.id) + '"]')) || c.closest("label");
      return text(label) || String(c.value || "").trim();
    }).filter(Boolean) : [],
    selectOptions: (() => { const s = drawer && [...drawer.querySelectorAll("select")].find(visible);
      return s ? [...s.options].filter(o => o.value !== "" && !/^(select|choose)\b/i.test(o.text.trim()))
        .map(o => o.text.trim()) : []; })(),
    fileInput: !!(drawer && drawer.querySelector('input.chatbot_Uploader[type="file"]')),  // often hidden: lowest priority
    headerApplied: !!header && [...header.querySelectorAll("button,[role=button]")].some(b => /^(applied|already applied)$/i.test(text(b))),
  };
}"""

HISTORY_JS = "({title, company}) => {" + VISIBLE_JS + r"""
  const norm = (s) => (s || "").toLowerCase().replace(/\s+/g, " ").trim();
  const rows = [...document.querySelectorAll(".jdTuplesContainer .jdTupleContainer")].map(card => ({
    title: text(card.querySelector(".jdTitle")), company: text(card.querySelector(".subheading .company")),
    status: text(card.querySelector("section.apply-status .title")),
  }));
  return rows.filter(r => norm(r.title) === norm(title) && norm(r.company) === norm(company));
}"""


HISTORY_ALL_JS = "() => {" + VISIBLE_JS + r"""
  return [...document.querySelectorAll(".jdTuplesContainer .jdTupleContainer")].slice(0, 100).map(card => ({
    title: text(card.querySelector(".jdTitle")), company: text(card.querySelector(".subheading .company")),
    status: text(card.querySelector("section.apply-status .title")),
  }));
}"""


OTP_STATE_JS = "() => {" + VISIBLE_JS + r"""
  const boxes = [...document.querySelectorAll('input[autocomplete="one-time-code"],input[name*="otp" i],input[id*="otp" i],input[class*="otp" i]')].filter(visible);
  const verify = [...document.querySelectorAll("button,[role=button],input[type=submit]")].filter(visible)
    .filter(b => /^(verify|submit|continue|login|proceed|confirm)$/i.test((text(b) || b.value || "").trim()));
  const body = (document.body && document.body.innerText || "").slice(0, 8000);
  return {boxes: boxes.length, maxLength: boxes.length === 1 ? (boxes[0].maxLength || 0) : 1,
          verify: verify.length, invalid: /invalid otp|incorrect otp|otp (?:has )?expired|wrong otp/i.test(body),
          url: location.href};
}"""
