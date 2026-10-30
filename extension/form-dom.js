// Self-contained for Chrome isolated-world injection and the dedicated worker.
// The website supplies data only. Field references live in a private closure.
export function formDOM(request = { operation: "inspect" }) {
  const key = "__automatedApplyFormV1";
  if (!globalThis[key]) {
    let documentId = crypto.randomUUID();
    const sensitive =
      /password|passcode|passphrase|one.?time|\botp\b|\bmfa\b|\b2fa\b|two.?factor|verification.?code|security.?code|credit.?card|debit.?card|card.?number|\bcvv\b|\bcvc\b|card.?expir|bank.?account|routing.?number|\biban\b|\bifsc\b|\bupi\b|payment|session|token|secret|api.?key|private.?key|social.?security|\bssn\b|\baadhaar\b|\baadhar\b|\bpan\s*(?:card|number|no)\b|tax.?id|national.?id|government.?id|passport|driv(?:er|ing).?licen[sc]e|\bpin\b(?![\s-]*code)|security.?question|\b(?:gender|race|ethnic\w*|religion|disabil\w*|veteran|military|sexual\w*|pronouns?|marital|self.?identif\w*)\b|date.?of.?birth|birth.?date|\bdob\b/i;
    const selfIdentification =
      /\b(?:gender|race|ethnic\w*|religion|disabil\w*|veteran|military|sexual\w*|pronouns?|marital|self.?identif\w*)\b|date.?of.?birth|birth.?date|\bdob\b/i;
    // Keep in sync with CONSENT_LABEL_PATTERN in form-messages.js.
    const consentPattern =
      /\b(?:consent|agree|agreement|terms(?:\s+and\s+conditions|\s+of\s+service|\s+of\s+use)?|privacy\s*policy|acknowledge|certif(?:y|ication)|attest(?:ation)?|declare|declaration|hereby|true\s+and\s+(?:correct|accurate)|gdpr|data\s+processing|background\s*check|equal\s*opportunity|\beeo\b|\bnda\b|non.?disclosure|authorize\s+background|accuracy\s+of\s+information)\b/i;
    const incompleteLabel =
      /^(?:[^a-z0-9]*|enter(?:\s+here|\s+value|\s+text|\s+your\s+answer|\s+details)?|type(?:\s+here|\s+your\s+answer)?|your\s+answer|select(?:\s+an?\s+option|\s+one|\s+value)?|choose(?:\s+an?\s+option|\s+one|\s+value)?|none|--?\s*none\s*--?|--?\s*select\s*--?|n\/a|optional|required|mandatory|input|field|value|text|answer|fill\s+this\s+out|click\s+here|dd[\/.-]mm[\/.-]yyyy|mm[\/.-]dd[\/.-]yyyy|yyyy[\/.-]mm[\/.-]dd)$/i;
    const placeholderOption =
      /^[-–—_\s]*(?:none|select(?:\s+an?\s+option|\s+one|\s+value)?|choose(?:\s+an?\s+option|\s+one|\s+value)?|please\s+select|--+)(?:\s*(?:\.{2,}|…))?[\s-–—_]*$/i;
    const clean = (s) =>
      String(s || "")
        .replace(/[\u0000-\u001f\u007f]+/g, " ")
        .replace(/\s+/g, " ")
        .trim()
        .slice(0, 160);
    const cleanLabelText = (s) =>
      clean(s)
        .replace(/^(?:\*\s*)+/, "")
        .replace(/(?:\s*\*+)+$/, "")
        .replace(/\s*\((?:required|mandatory)\)\s*$/i, "")
        .trim();
    const isCompleteLabel = (s) => {
      const v = cleanLabelText(s);
      return Boolean(v && !incompleteLabel.test(v));
    };
    const visible = (el) => {
      if (!el || !el.isConnected) return false;
      if (
        el.hidden ||
        el.closest?.("[hidden],[inert],template,[aria-hidden='true']")
      )
        return false;
      const rects = el.getClientRects?.();
      if (!rects || rects.length === 0) return false;
      if (typeof el.getBoundingClientRect === "function") {
        const r = el.getBoundingClientRect();
        if (r.width === 0 || r.height === 0) return false;
      }
      for (let cur = el; cur && cur.nodeType === 1; cur = cur.parentElement) {
        const st = getComputedStyle(cur);
        if (
          st.display === "none" ||
          st.visibility === "hidden" ||
          st.visibility === "collapse" ||
          Number.parseFloat(st.opacity) === 0
        )
          return false;
        if (
          cur !== el &&
          (st.overflow === "hidden" ||
            st.overflowY === "hidden" ||
            st.overflowX === "hidden") &&
          typeof cur.getBoundingClientRect === "function"
        ) {
          const cr = cur.getBoundingClientRect();
          if (cr.width === 0 || cr.height === 0) return false;
        }
      }
      return true;
    };
    const textWithoutControls = (node) => {
      if (!node) return "";
      const clone = node.cloneNode(true);
      for (const child of clone.querySelectorAll?.(
        "input,select,textarea,button,option,script,style,[role='alert'],[role='status'],[role='listbox'],.error,.zr-error,.field-error,.error-message,.invalid-feedback,[aria-hidden='true']",
      ) || []) {
        child.remove();
      }
      return clean(clone.textContent);
    };
    const ariaLabelledByText = (el) => {
      const ids = clean(el?.getAttribute?.("aria-labelledby"))
        .split(/\s+/)
        .filter(Boolean);
      if (!ids.length) return "";
      return clean(
        ids
          .map((id) => textWithoutControls(document.getElementById(id)))
          .filter(Boolean)
          .join(" "),
      );
    };
    const primaryControlsIn = (root) =>
      [
        ...(root?.querySelectorAll?.(
          "input:not([type=hidden]):not([type=submit]):not([type=button]):not([type=reset]):not([type=image]),textarea,select",
        ) || []),
      ].filter(visible);
    const containerLabel = (el) => {
      const td = el.closest?.("td");
      if (td && td.parentElement?.tagName === "TR") {
        const tr = td.parentElement;
        if (primaryControlsIn(tr).length === 1) {
          for (const cell of tr.children) {
            if (cell === td) break;
            const t = textWithoutControls(cell);
            if (isCompleteLabel(t)) return t;
          }
        }
      }
      const dd = el.closest?.("dd");
      if (
        dd &&
        dd.previousElementSibling?.tagName === "DT" &&
        primaryControlsIn(dd).length === 1
      ) {
        const t = textWithoutControls(dd.previousElementSibling);
        if (isCompleteLabel(t)) return t;
      }
      let cur = el.parentElement;
      for (let depth = 0; cur && depth < 4; depth += 1) {
        if (["FORM", "FIELDSET", "MAIN", "BODY", "TABLE"].includes(cur.tagName))
          break;
        const inner = primaryControlsIn(cur);
        if (inner.length === 1 && inner[0] === el) {
          for (const cand of cur.querySelectorAll(
            "label,[class*='label'],[class*='question'],.zr-field-label,.cw-label,[data-zcqa*='label']",
          )) {
            const t = textWithoutControls(cand);
            if (isCompleteLabel(t)) return t;
          }
          const direct = textWithoutControls(cur);
          if (isCompleteLabel(direct)) return direct;
        }
        cur = cur.parentElement;
      }
      const fs = el.closest?.("fieldset");
      if (fs && primaryControlsIn(fs).length === 1) {
        const leg = textWithoutControls(fs.querySelector("legend"));
        if (isCompleteLabel(leg)) return leg;
      }
      return "";
    };
    const optionPeerLabel = (el) => {
      const next = el.nextElementSibling;
      if (
        next &&
        // A sibling <label for> that targets another control is not this option's label.
        !(next.tagName === "LABEL" && next.htmlFor && next.htmlFor !== el.id) &&
        !next.querySelector?.("input,select,textarea") &&
        isCompleteLabel(textWithoutControls(next))
      )
        return textWithoutControls(next);
      const p = el.parentElement;
      if (
        p &&
        !["FORM", "FIELDSET", "BODY", "MAIN"].includes(p.tagName) &&
        primaryControlsIn(p).length === 1
      ) {
        const t = textWithoutControls(p);
        if (isCompleteLabel(t)) return t;
      }
      const val = clean(el.getAttribute?.("value") ?? el.value);
      if (val && val.toLowerCase() !== "on" && isCompleteLabel(val)) return val;
      return "";
    };
    const rawLabel = (el) => {
      const directLabels = [...(el.labels || [])]
        .map((l) => textWithoutControls(l))
        .filter(Boolean)
        .join(" ");
      if (isCompleteLabel(directLabels)) return directLabels;
      const ariaBy = ariaLabelledByText(el);
      if (isCompleteLabel(ariaBy)) return ariaBy;
      const aria = clean(el.getAttribute?.("aria-label"));
      if (isCompleteLabel(aria)) return aria;
      if (el.type === "radio" || el.type === "checkbox") {
        const peer = optionPeerLabel(el);
        if (isCompleteLabel(peer)) return peer;
      } else {
        const fromContainer = containerLabel(el);
        if (isCompleteLabel(fromContainer)) return fromContainer;
      }
      const dataLbl = clean(
        el.getAttribute?.("data-label") || el.getAttribute?.("title"),
      );
      if (isCompleteLabel(dataLbl)) return dataLbl;
      const placeholder = clean(el.getAttribute?.("placeholder"));
      if (isCompleteLabel(placeholder)) return placeholder;
      return (
        directLabels ||
        ariaBy ||
        aria ||
        dataLbl ||
        placeholder ||
        clean(el.getAttribute?.("name")) ||
        ""
      );
    };
    const label = (el) => {
      const directLabels = [...(el.labels || [])]
        .map((l) => textWithoutControls(l))
        .filter(Boolean)
        .join(" ");
      if (isCompleteLabel(directLabels)) return cleanLabelText(directLabels);
      const ariaBy = ariaLabelledByText(el);
      if (isCompleteLabel(ariaBy)) return cleanLabelText(ariaBy);
      const aria = clean(el.getAttribute?.("aria-label"));
      if (isCompleteLabel(aria)) return cleanLabelText(aria);
      if (el.type === "radio" || el.type === "checkbox") {
        const peer = optionPeerLabel(el);
        if (isCompleteLabel(peer)) return cleanLabelText(peer);
      } else {
        const fromContainer = containerLabel(el);
        if (isCompleteLabel(fromContainer))
          return cleanLabelText(fromContainer);
      }
      const dataLbl = clean(
        el.getAttribute?.("data-label") || el.getAttribute?.("title"),
      );
      if (isCompleteLabel(dataLbl)) return cleanLabelText(dataLbl);
      const placeholder = clean(el.getAttribute?.("placeholder"));
      if (isCompleteLabel(placeholder)) return cleanLabelText(placeholder);
      return "";
    };
    // The group question is always considered: a declaration legend with a neutral
    // option ("I confirm the above") must still never be selected automatically.
    const isConsentControl = (el, extraGroup = "") =>
      (el.type === "checkbox" || el.type === "radio") &&
      consentPattern.test(
        [rawLabel(el), extraGroup, rawGroupLabel(el), el.name, el.id]
          .filter(Boolean)
          .join(" "),
      );
    const rawGroupLabel = (el) => {
      if (el.type !== "radio" && el.type !== "checkbox") return "";
      const optLbl = label(el).toLowerCase();
      const fs = el.closest?.("fieldset");
      if (fs) {
        const leg =
          textWithoutControls(fs.querySelector("legend")) ||
          ariaLabelledByText(fs) ||
          clean(fs.getAttribute("aria-label"));
        if (
          isCompleteLabel(leg) &&
          cleanLabelText(leg).toLowerCase() !== optLbl
        )
          return leg;
      }
      const rg = el.closest?.('[role="radiogroup"],[role="group"]');
      if (rg) {
        const rgAria =
          ariaLabelledByText(rg) || clean(rg.getAttribute("aria-label"));
        if (
          isCompleteLabel(rgAria) &&
          cleanLabelText(rgAria).toLowerCase() !== optLbl
        )
          return rgAria;
        for (const cand of rg.querySelectorAll(
          "legend,[class*='label'],[class*='question'],.zr-label,.cw-label,p,h3,h4",
        )) {
          if (cand.querySelector("input,select,textarea")) continue;
          if (cand.tagName === "LABEL" && cand.hasAttribute("for")) continue;
          const t = textWithoutControls(cand);
          if (isCompleteLabel(t) && cleanLabelText(t).toLowerCase() !== optLbl)
            return t;
        }
      }
      let cur = el.parentElement;
      for (let depth = 0; cur && depth < 4; depth += 1) {
        if (["FORM", "MAIN", "BODY"].includes(cur.tagName)) break;
        const inner = primaryControlsIn(cur);
        if (inner.length > 1 && inner.every((c) => c.type === el.type)) {
          for (const cand of cur.querySelectorAll(
            "td:first-child,th,dt,legend,[class*='label'],[class*='question'],.zr-label,.cw-label,label:not([for])",
          )) {
            if (cand.querySelector("input,select,textarea")) continue;
            const t = textWithoutControls(cand);
            if (
              isCompleteLabel(t) &&
              cleanLabelText(t).toLowerCase() !== optLbl
            )
              return t;
          }
        }
        cur = cur.parentElement;
      }
      return "";
    };
    const groupLabel = (el) => {
      if (el.type !== "radio" && el.type !== "checkbox") return null;
      const raw = rawGroupLabel(el);
      if (!isCompleteLabel(raw)) return null;
      if (isConsentControl(el, raw)) return null;
      return cleanLabelText(raw) || null;
    };
    const hasMandatoryMarker = (node) =>
      Boolean(
        node &&
        (/(\*\s*$|^[*]\s+|\(\s*(?:required|mandatory)\s*\))/i.test(
          textWithoutControls(node),
        ) ||
          node.querySelector?.(
            ".mandatory,.required,.zr-mandatory,[class*='mandatory'],[aria-label='required']",
          )),
      );
    const isRequired = (el) => {
      if (
        el.required ||
        el.getAttribute("aria-required") === "true" ||
        el.dataset?.required === "true" ||
        el.dataset?.mandatory === "true"
      )
        return true;
      const raw = rawLabel(el);
      if (/(\*\s*$|^[*]\s+|\(\s*(?:required|mandatory)\s*\))/i.test(raw))
        return true;
      if (
        (el.type === "radio" || el.type === "checkbox") &&
        /(\*\s*$|^[*]\s+|\(\s*(?:required|mandatory)\s*\))/i.test(
          rawGroupLabel(el),
        )
      )
        return true;
      for (const lbl of el.labels || []) {
        if (hasMandatoryMarker(lbl)) return true;
      }
      const grp = el.closest?.('[role="radiogroup"],[role="group"],fieldset');
      if (
        grp &&
        (grp.getAttribute("aria-required") === "true" ||
          grp.dataset?.required === "true" ||
          grp.dataset?.mandatory === "true" ||
          hasMandatoryMarker(
            grp.querySelector("legend,[class*='label'],[class*='question']"),
          ))
      )
        return true;
      const row = el.closest?.(
        ".zr-field-row,.cw-form-row,.crc-form-row,.form-group,[data-mandatory='true'],[data-required='true']",
      );
      if (row) {
        if (
          row.dataset?.mandatory === "true" ||
          row.dataset?.required === "true"
        )
          return true;
        if (primaryControlsIn(row).length === 1 && hasMandatoryMarker(row))
          return true;
      }
      return false;
    };
    const isInvalid = (el) => {
      if (el.getAttribute("aria-invalid") === "true") return true;
      if (el.validity?.customError || el.validity?.badInput) return true;
      if (
        el.classList?.contains("is-invalid") ||
        el.classList?.contains("zr-invalid") ||
        el.classList?.contains("field-invalid")
      )
        return true;
      const errIds = clean(
        el.getAttribute("aria-errormessage") ||
          el.getAttribute("aria-describedby"),
      )
        .split(/\s+/)
        .filter(Boolean);
      for (const id of errIds) {
        const errNode = document.getElementById(id);
        if (
          errNode &&
          visible(errNode) &&
          (errNode.getAttribute("role") === "alert" ||
            /error|invalid/i.test(errNode.className || "") ||
            errNode.id === el.getAttribute("aria-errormessage")) &&
          clean(errNode.textContent)
        )
          return true;
      }
      const row = el.closest?.(
        ".zr-field-row,.cw-form-row,.crc-form-row,.form-group,label",
      );
      if (row && primaryControlsIn(row).length === 1) {
        const alertNode = row.querySelector(
          "[role='alert'],.zr-error,.field-error,.error-message,.invalid-feedback",
        );
        if (alertNode && visible(alertNode) && clean(alertNode.textContent))
          return true;
      }
      return false;
    };
    // Only the initial option can be a text placeholder. A later "None" option
    // (or value="none") is a real owner answer and must be preserved.
    const isPlaceholderSelectOption = (opt, index) => {
      if (!opt) return true;
      const text = clean(opt.textContent);
      const val = clean(opt.getAttribute("value") ?? opt.value);
      if (!text) return true;
      if (index !== 0) return false;
      if (placeholderOption.test(text) || placeholderOption.test(val))
        return true;
      if (opt.getAttribute("value") === "" && (opt.disabled || opt.hidden))
        return true;
      return false;
    };
    const radioPeers = (el, controls) => {
      if (el.name) {
        return controls.filter(
          (other) =>
            other.type === "radio" &&
            other.name === el.name &&
            other.form === el.form,
        );
      }
      const grp = el.closest?.('[role="radiogroup"],[role="group"],fieldset');
      return grp
        ? controls.filter(
            (other) =>
              other.type === "radio" &&
              other.closest?.('[role="radiogroup"],[role="group"],fieldset') ===
                grp,
          )
        : [el];
    };
    const checkboxPeers = (el, controls) => {
      if (el.name) {
        const byName = controls.filter(
          (other) =>
            other.type === "checkbox" &&
            other.name === el.name &&
            other.form === el.form,
        );
        if (byName.length > 1) return byName;
      }
      const grp = el.closest?.(
        '[role="group"],fieldset,[data-checkbox-group],.zr-checkbox-group',
      );
      if (grp) {
        const byGrp = controls.filter(
          (other) =>
            other.type === "checkbox" &&
            other.closest?.(
              '[role="group"],fieldset,[data-checkbox-group],.zr-checkbox-group',
            ) === grp,
        );
        if (byGrp.length > 1 && groupLabel(el)) return byGrp;
      }
      return [el];
    };
    const unanswered = (el, controls) => {
      if (el.type === "radio")
        return !radioPeers(el, controls).some((other) => other.checked);
      if (el.type === "checkbox")
        return !checkboxPeers(el, controls).some(
          (other) => other.checked || other.indeterminate,
        );
      if (el.type === "file") return !el.files?.length;
      if (el.tagName === "SELECT") {
        if (el.selectedIndex < 0) return true;
        const selected = el.options[el.selectedIndex];
        if (!selected || selected.disabled) return true;
        if (!String(el.value || "").trim()) return true;
        return isPlaceholderSelectOption(selected, el.selectedIndex);
      }
      if (el.validity?.badInput) return false;
      return !String(el.value || "").trim();
    };
    const isCustomComboboxControl = (el) =>
      el.getAttribute("role") === "combobox" ||
      el.getAttribute("aria-haspopup") === "listbox" ||
      el.getAttribute("aria-autocomplete") === "list" ||
      el.hasAttribute("list") ||
      Boolean(
        el.closest?.(
          '[role="combobox"],lyte-dropdown,lyte-select,lyte-autocomplete,crux-picklist-component,[data-custom-combobox]',
        ),
      );
    const sectionSelector =
      "fieldset,[role='group'],[data-employment-entry],[data-education-entry],[data-work-experience]";
    const sectionTitle = (section) =>
      cleanLabelText(
        [
          ...section.querySelectorAll(
            ":scope > legend,:scope > h2,:scope > h3,:scope > h4",
          ),
        ]
          .map(textWithoutControls)
          .filter(Boolean)
          .join(" / ") ||
          ariaLabelledByText(section) ||
          section.getAttribute("aria-label") ||
          section.getAttribute("data-employment-entry") ||
          section.getAttribute("data-education-entry"),
      );
    const sectionPeers = (section) =>
      [...document.querySelectorAll(sectionSelector)].filter(
        (other) =>
          other.parentElement?.closest(sectionSelector) ===
            section.parentElement?.closest(sectionSelector) &&
          sectionTitle(other) === sectionTitle(section),
      );
    const stableSectionIdentity = (section) => {
      for (const attribute of [
        "id",
        "data-employment-entry",
        "data-education-entry",
      ]) {
        const value = section.getAttribute(attribute);
        if (
          value &&
          [...document.querySelectorAll(`[${attribute}]`)].filter(
            (el) => el.getAttribute(attribute) === value,
          ).length === 1
        )
          return clean(`${attribute}:${value}`);
      }
      return "";
    };
    const ambiguousSection = (el) => {
      for (
        let section = el.closest(sectionSelector);
        section;
        section = section.parentElement?.closest(sectionSelector)
      ) {
        if (sectionPeers(section).length > 1 && !stableSectionIdentity(section))
          return true;
      }
      return false;
    };
    const sectionLabel = (el) => {
      const sections = [];
      for (
        let section = el.closest(sectionSelector);
        section;
        section = section.parentElement?.closest(sectionSelector)
      ) {
        const title = sectionTitle(section);
        const peers = sectionPeers(section);
        const identity = stableSectionIdentity(section);
        const suffix =
          peers.length > 1
            ? identity
              ? ` [${identity}]`
              : ` [entry ${peers.indexOf(section) + 1}]`
            : "";
        if (title || suffix) sections.unshift(`${title || "History"}${suffix}`);
      }
      return clean(sections.join(" / ")) || null;
    };
    // Synchronous SHA-256 keeps inspection usable by the native worker and popup.
    // The key contains metadata only, never entered values or CAPTCHA material.
    const semanticHash = (text) => {
      const bytes = new TextEncoder().encode(text);
      const words = [];
      for (let i = 0; i < bytes.length; i++)
        words[i >> 2] = (words[i >> 2] || 0) | (bytes[i] << (24 - (i % 4) * 8));
      words[bytes.length >> 2] =
        (words[bytes.length >> 2] || 0) |
        (0x80 << (24 - (bytes.length % 4) * 8));
      const total = (((bytes.length + 8) >> 6) + 1) * 16;
      words[total - 1] = bytes.length * 8;
      const primes = [],
        constants = [],
        state = [];
      for (let n = 2; primes.length < 64; n++) {
        if (primes.some((p) => p * p <= n && n % p === 0)) continue;
        primes.push(n);
        if (state.length < 8)
          state.push(((Math.sqrt(n) % 1) * 0x100000000) | 0);
        constants.push(((Math.cbrt(n) % 1) * 0x100000000) | 0);
      }
      const rotate = (x, n) => (x >>> n) | (x << (32 - n));
      for (let start = 0; start < total; start += 16) {
        const schedule = [],
          hash = state.slice();
        for (let i = 0; i < 64; i++) {
          const a = schedule[i - 15],
            b = schedule[i - 2];
          schedule[i] =
            i < 16
              ? words[start + i] | 0
              : ((rotate(a, 7) ^ rotate(a, 18) ^ (a >>> 3)) +
                  schedule[i - 16] +
                  (rotate(b, 17) ^ rotate(b, 19) ^ (b >>> 10)) +
                  schedule[i - 7]) |
                0;
          const t1 =
            (hash[7] +
              (rotate(hash[4], 6) ^ rotate(hash[4], 11) ^ rotate(hash[4], 25)) +
              ((hash[4] & hash[5]) ^ (~hash[4] & hash[6])) +
              constants[i] +
              schedule[i]) |
            0;
          const t2 =
            ((rotate(hash[0], 2) ^ rotate(hash[0], 13) ^ rotate(hash[0], 22)) +
              ((hash[0] & hash[1]) ^
                (hash[0] & hash[2]) ^
                (hash[1] & hash[2]))) |
            0;
          hash.pop();
          hash.unshift((t1 + t2) | 0);
          hash[4] = (hash[4] + t1) | 0;
        }
        for (let i = 0; i < 8; i++) state[i] = (state[i] + hash[i]) | 0;
      }
      return state.map((x) => (x >>> 0).toString(16).padStart(8, "0")).join("");
    };
    const pageStep = () =>
      clean(
        [
          ...document.querySelectorAll(
            '[aria-current="step"],.zr-step-active,.active-step,[data-step-active="true"]',
          ),
        ]
          .filter(visible)
          .map((el) =>
            clean(el.getAttribute("aria-label") || textWithoutControls(el)),
          )
          .join(" / "),
      ) || "Application";
    const controlIdentity = (el) => {
      const scope = el.closest(sectionSelector) || el.form || document;
      const unique = (attribute, value) =>
        value &&
        [...scope.querySelectorAll(`[${attribute}]`)].filter(
          (other) => other.getAttribute(attribute) === value,
        ).length === 1;
      for (const attribute of [
        "id",
        "name",
        "data-testid",
        "data-automation-id",
      ]) {
        const value = el.getAttribute(attribute);
        if (unique(attribute, value)) return clean(`${attribute}:${value}`);
      }
      // An ordinal avoids merging repeated controls while the section signature
      // forces a fresh review when the employer rearranges a repeated history.
      const peers = primaryControlsIn(scope).filter(
        (other) => label(other) === label(el) && other.type === el.type,
      );
      return clean(
        `${el.tagName.toLowerCase()}:${el.type || el.getAttribute("role") || "control"}:${label(el)}:${peers.indexOf(el) + 1}`,
      );
    };
    // Same binding rules as the dedicated browser: exactly one owner and list,
    // bounded, unique choices. Preparation never opens a menu or fires events.
    const choicesFor = (el) => {
      if (el.tagName === "SELECT") return null;
      const id = el.getAttribute("list") || el.getAttribute("aria-controls");
      if (!id) return null;
      const lists = [...document.querySelectorAll("[id]")].filter(
        (n) => n.id === id,
      );
      if (lists.length !== 1) return null;
      const list = lists[0];
      const native = el.tagName === "INPUT" && list.tagName === "DATALIST";
      const owners = [
        ...document.querySelectorAll("[list],[role='combobox']"),
      ].filter(
        (n) =>
          (n.getAttribute("list") || n.getAttribute("aria-controls")) === id,
      );
      if (
        owners.length !== 1 ||
        (!native &&
          (list.getAttribute("role") !== "listbox" ||
            !visible(list) ||
            el.getAttribute("aria-expanded") !== "true")) ||
        list.getAttribute("aria-multiselectable") === "true"
      )
        return null;
      const options = [
        ...list.querySelectorAll(native ? "option" : "[role='option']"),
      ];
      const labels = options.map((o) =>
        clean(
          native
            ? o.label || o.value
            : o.getAttribute("aria-label") || o.textContent,
        ),
      );
      if (
        !options.length ||
        options.length > 300 ||
        labels.some((v) => !v) ||
        new Set(labels.map((v) => v.toLowerCase())).size !== labels.length ||
        options.some(
          (o) => o.disabled || o.getAttribute("aria-disabled") === "true",
        ) ||
        (!native &&
          options.some(
            (o) => !visible(o) || o.closest("[role='listbox']") !== list,
          ))
      )
        return null;
      return { list, options, labels, native };
    };
    let challengeObserved = false;
    const securityState = () => {
      // Widget presence cannot establish whether a human solved a challenge.
      // Never inspect challenge frames, response tokens or CAPTCHA internals.
      const widget = document.querySelector(
        'iframe[src*="recaptcha"],iframe[src*="hcaptcha"],iframe[src*="turnstile"],iframe[src*="challenges.cloudflare"],iframe[src*="funcaptcha"],iframe[src*="arkoselabs"],[data-sitekey],.cf-turnstile,[class*="captcha"],[id*="captcha"]',
      );
      const blocker = [
        ...document.querySelectorAll("[role='dialog'],[role='alert'],h1,h2"),
      ]
        .filter(visible)
        .some((el) =>
          /verify (?:that )?you are human|checking your browser|security (?:check|challenge)|complete (?:the |this )?captcha|access denied/i.test(
            clean(el.textContent),
          ),
        );
      if (blocker || widget) challengeObserved = true;
      return blocker
        ? "blocking"
        : widget
          ? "unverified_widget"
          : challengeObserved
            ? "unknown"
            : "none";
    };
    const isDateControl = (el) => {
      if (["date", "month", "week", "time", "datetime-local"].includes(el.type))
        return true;
      if (el.tagName !== "INPUT") return false;
      const ph = clean(el.getAttribute("placeholder"));
      if (/^(?:dd|mm|yyyy)[\/.-](?:dd|mm)[\/.-](?:yyyy|dd|mm)$/i.test(ph))
        return true;
      const hint = [
        el.className,
        el.getAttribute("data-field-type"),
        el.getAttribute("data-type"),
        el.getAttribute("data-zcqa"),
      ].join(" ");
      if (
        /datepicker|date-picker|lyte-calendar|crux-date|zoho-date|\bdate\b/i.test(
          hint,
        )
      )
        return true;
      const lbl = rawLabel(el);
      return /\b(?:date\s+of\s+birth|birth\s*date|\bdob\b|start\s+date|end\s+date|graduation\s+date|available\s+from\s+date|joining\s+date)\b/i.test(
        lbl,
      );
    };
    const isFrameworkControlled = (el) => {
      if (
        el.hasAttribute("data-framework-controlled") ||
        el.getAttribute("data-controlled") === "true" ||
        el.hasAttribute("ng-model") ||
        el.hasAttribute("formcontrolname") ||
        el.hasAttribute("v-model") ||
        Boolean(
          el.closest?.(
            "lyte-input,lyte-textarea,crux-text-component,[data-reactroot],[data-framework-controlled]",
          ),
        )
      )
        return true;
      if (Object.getOwnPropertyDescriptor(el, "value")?.set) return true;
      return Object.keys(el).some(
        (k) =>
          k === "_valueTracker" ||
          k.startsWith("__reactFiber$") ||
          k.startsWith("__reactProps$") ||
          k.startsWith("__reactInternalInstance$") ||
          k === "__vue__" ||
          k === "__vnode",
      );
    };
    const getStepSignature = () => {
      const steps = [
        ...document.querySelectorAll(
          '[aria-current="step"],.zr-step-active,.active-step,[data-step-active="true"],fieldset,form',
        ),
      ]
        .filter(visible)
        .map((el) =>
          [
            el.tagName,
            el.id,
            el.getAttribute("data-step"),
            clean(
              el.querySelector?.("legend")?.textContent ||
                el.getAttribute("aria-label") ||
                "",
            ),
          ].join(":"),
        );
      return `${location.href}|${steps.join(";")}`;
    };

    let refs = new Map();
    let last = null;
    let touched = false;
    let submitArmed = false;
    let fillConsumed = false;
    let fillCancelled = false;
    let interactiveExecution = false;
    let appliedValues = new Map();
    let controlCount = 0;
    let snapshotControls = [];
    let snapshotForms = [];
    let snapshotStepSignature = "";
    let domMutated = false;
    let userEdited = new WeakSet();

    document.addEventListener(
      "submit",
      (e) => {
        if (submitArmed) {
          submitArmed = false;
        } else if (touched) {
          e.preventDefault();
          e.stopImmediatePropagation();
        }
      },
      true,
    );
    const onUserEdit = (e) => {
      if (e.isTrusted && e.target) userEdited.add(e.target);
    };
    document.addEventListener("input", onUserEdit, true);
    document.addEventListener("change", onUserEdit, true);

    const hasRelevantNode = (nodes) => {
      for (const node of nodes || []) {
        if (node.nodeType !== 1) continue;
        if (
          node.matches?.(
            "input,textarea,select,option,form,iframe,fieldset,legend,label,[role='combobox'],[role='listbox'],[role='radiogroup'],[role='group'],[contenteditable='true']",
          ) ||
          node.querySelector?.(
            "input,textarea,select,option,form,iframe,[role='combobox'],[role='listbox'],[contenteditable='true']",
          )
        )
          return true;
      }
      return false;
    };
    const observedAttributes = [
      "action",
      "method",
      "target",
      "enctype",
      "type",
      "name",
      "id",
      "role",
      "autocomplete",
      "list",
      "src",
      "sandbox",
    ];
    // Observation is active only while a reviewed snapshot is pending. Once the
    // snapshot is invalidated (or consumed), the observer disconnects so large or
    // busy single-page applications do not pay for scanning every later mutation.
    let observer = null;
    const processMutations = (mutations) => {
      if (domMutated) return;
      for (const m of mutations) {
        if (m.type === "childList") {
          if (
            hasRelevantNode(m.addedNodes) ||
            hasRelevantNode(m.removedNodes)
          ) {
            domMutated = true;
            break;
          }
        } else if (m.type === "attributes" && m.target?.nodeType === 1) {
          const t = m.target;
          // Framework renders may assign the same native attributes again.
          // During approved interactions, accept records only when the same node
          // still has the exact reviewed attribute. Actual identity changes and
          // node replacements continue to invalidate the reviewed snapshot.
          if (
            interactiveExecution &&
            ["INPUT", "TEXTAREA", "SELECT"].includes(t.tagName) &&
            snapshotControls.some(
              (saved) =>
                saved.el === t &&
                saved.attributes[m.attributeName] ===
                  t.getAttribute(m.attributeName),
            )
          )
            continue;
          if (
            (t.tagName === "FORM" &&
              ["action", "method", "target", "enctype"].includes(
                m.attributeName,
              )) ||
            (["INPUT", "TEXTAREA", "SELECT"].includes(t.tagName) &&
              ["type", "name", "id", "role", "autocomplete", "list"].includes(
                m.attributeName,
              )) ||
            (t.tagName === "IFRAME" &&
              ["src", "sandbox"].includes(m.attributeName))
          ) {
            domMutated = true;
            break;
          }
        }
      }
      if (domMutated) observer?.disconnect();
    };
    const startObserving = () => {
      if (typeof MutationObserver !== "function" || !document.documentElement)
        return;
      if (!observer) observer = new MutationObserver(processMutations);
      observer.takeRecords(); // Discard records that predate this snapshot.
      observer.observe(document.documentElement, {
        childList: true,
        subtree: true,
        attributes: true,
        attributeFilter: observedAttributes,
      });
    };
    const flushMutations = () => {
      if (observer) processMutations(observer.takeRecords());
    };
    const stopObserving = () => {
      observer?.takeRecords();
      observer?.disconnect();
    };

    const inspect = (onlyEmpty = false, interactionsAllowed = false) => {
      // A second popup/review must invalidate earlier plans in the same document.
      documentId = crypto.randomUUID();
      fillConsumed = false;
      fillCancelled = false;
      appliedValues = new Map();
      const controls = [
        ...document.querySelectorAll("input,textarea,select"),
      ].filter(visible);
      const applicationControl = (el) => {
        if (!["naukri.com", "www.naukri.com"].includes(location.hostname))
          return true;
        // A posting's global search bar is not an application form. Naukri
        // drawers without an explicit form/dialog scope remain manual until
        // a genuine adapter establishes their boundaries.
        return (
          !el.closest("header,nav,[role='search'],[class*='nI-gNb']") &&
          Boolean(el.closest("form,[role='form'],[role='dialog']"))
        );
      };
      controlCount = controls.length;
      snapshotControls = controls.map((el) => ({
        el,
        tagName: el.tagName,
        type: el.type,
        name: el.name,
        id: el.id,
        disabled: el.disabled,
        readOnly: el.readOnly,
        attributes: Object.fromEntries(
          observedAttributes.map((name) => [name, el.getAttribute(name)]),
        ),
      }));
      snapshotForms = [...document.forms].map((f) => ({
        el: f,
        action: f.action,
        method: f.method,
        target: f.target,
        enctype: f.enctype,
      }));
      snapshotStepSignature = getStepSignature();
      domMutated = false;
      startObserving();
      userEdited = new WeakSet();

      const fields = [];
      const unsupportedControls = [];
      const diagnosticIds = new Map();
      const diagnose = (el, item) => {
        const wrapper = el.closest?.(
          "[role='combobox'],lyte-dropdown,lyte-select,lyte-autocomplete,crux-picklist-component",
        );
        const inputs = wrapper
          ? [...wrapper.querySelectorAll("input,select,textarea")].filter(
              visible,
            )
          : [];
        const control = inputs.length === 1 ? inputs[0] : el;
        if (!diagnosticIds.has(control))
          diagnosticIds.set(control, `u${diagnosticIds.size}`);
        const entry = {
          ...item,
          control_id: diagnosticIds.get(control),
          context: sectionLabel(control),
        };
        if (
          !unsupportedControls.some(
            (d) =>
              d.control_id === entry.control_id &&
              d.context === entry.context &&
              d.reason === entry.reason,
          )
        )
          unsupportedControls.push(entry);
      };
      refs = new Map();
      let excludedSensitive = false;
      let crossOriginFormFrame = false;

      const security = securityState();
      let challenge = security !== "none";

      for (const frame of [...document.querySelectorAll("iframe")].filter(
        visible,
      )) {
        const src = clean(frame.getAttribute("src") || "");
        const fHint = [
          src,
          frame.title,
          frame.id,
          frame.name,
          frame.className,
        ].join(" ");
        if (
          /recaptcha|hcaptcha|turnstile|challenges\.cloudflare|funcaptcha|arkoselabs|captcha/i.test(
            fHint,
          )
        ) {
          challenge = true;
          diagnose(frame, {
            kind: "iframe",
            label: clean(frame.title || "Security challenge") || "Challenge",
            required: true,
            reason: "Security challenge or CAPTCHA requires manual completion",
          });
          continue;
        }
        if (/stripe|paypal|checkout|payment|braintree|razorpay/i.test(fHint)) {
          excludedSensitive = true;
          diagnose(frame, {
            kind: "iframe",
            label: clean(frame.title || "Payment frame") || "Payment frame",
            required: true,
            reason: "Sensitive payment frame requires manual completion",
          });
          continue;
        }
        let crossOrigin = false;
        try {
          if (
            src &&
            !src.startsWith("about:") &&
            !src.startsWith("javascript:")
          ) {
            crossOrigin =
              new URL(src, location.href).origin !== location.origin;
          }
          if (
            !crossOrigin &&
            frame.hasAttribute("sandbox") &&
            !/\ballow-same-origin\b/i.test(frame.getAttribute("sandbox") || "")
          ) {
            crossOrigin = true;
          }
          if (!crossOrigin && !frame.contentDocument) {
            crossOrigin = true;
          }
        } catch {
          crossOrigin = true;
        }
        if (crossOrigin || frame.closest("form,[role='form']")) {
          diagnose(frame, {
            kind: "iframe",
            label:
              clean(
                frame.title ||
                  frame.getAttribute("aria-label") ||
                  "Embedded frame",
              ) || "Embedded frame",
            required: false,
            reason:
              "Cross-origin frame cannot be inspected safely — complete manually",
          });
          if (crossOrigin && frame.closest("form,[role='form']")) {
            crossOriginFormFrame = true;
          }
        }
      }

      if (onlyEmpty) {
        for (const widget of [
          ...document.querySelectorAll(
            '[role="combobox"],[role="listbox"]:not(select),lyte-dropdown,lyte-select,lyte-autocomplete,crux-picklist-component,[contenteditable="true"],[role="textbox"]:not(input):not(textarea)',
          ),
        ].filter(visible)) {
          if (widget.querySelector("input,textarea,select")) continue;
          if (widget.matches("input,select,textarea")) continue;
          if (
            widget.getAttribute("role") === "listbox" &&
            [...document.querySelectorAll("[role='combobox']")].some(
              (c) => c.getAttribute("aria-controls") === widget.id,
            )
          )
            continue;
          if (widget.getAttribute("role") === "combobox" && choicesFor(widget))
            continue;
          if (widget.getAttribute("aria-disabled") === "true") continue;
          const isEditor = widget.matches(
            '[contenteditable="true"],[role="textbox"]',
          );
          if (isEditor && clean(widget.textContent)) continue;
          if (
            !isEditor &&
            clean(
              widget.getAttribute("data-value") ||
                widget.getAttribute("aria-valuetext"),
            )
          )
            continue;
          const wLabel =
            cleanLabelText(rawLabel(widget)) ||
            (isEditor ? "Rich text field" : "Custom combobox");
          diagnose(widget, {
            kind: isEditor ? "custom_widget" : "custom_combobox",
            label: wLabel,
            required: isRequired(widget),
            reason: isEditor
              ? "Rich-text or custom widget requires manual entry"
              : "Custom combobox or dropdown requires manual selection",
          });
        }
      }

      const accessible = [
        ...document.querySelectorAll("[role='combobox']"),
      ].filter(
        (el) =>
          visible(el) &&
          !controls.includes(el) &&
          !el.querySelector("input,textarea,select") &&
          choicesFor(el),
      );
      for (const el of [...controls, ...accessible]) {
        if (!applicationControl(el)) continue;
        if (
          ["hidden", "submit", "button", "reset", "image"].includes(el.type) &&
          !(
            el.type === "button" &&
            el.getAttribute("role") === "combobox" &&
            choicesFor(el)
          )
        )
          continue;
        const rawLbl = rawLabel(el);
        const hint = [
          el.type,
          el.name,
          el.id,
          el.autocomplete,
          rawLbl,
          rawGroupLabel(el),
          sectionLabel(el),
        ].join(" ");
        if (/captcha/i.test(hint)) {
          challenge = true;
          continue;
        }
        if (selfIdentification.test(hint.replace(/[_-]/g, " "))) {
          if (onlyEmpty)
            diagnose(el, {
              kind: clean(el.type || "select"),
              label: cleanLabelText(rawLbl) || "Self-identification field",
              required: isRequired(el),
              reason: "Sensitive self-identification requires manual entry",
            });
          continue;
        }
        if (
          sensitive.test(hint) ||
          /^(cc-|current-password|new-password|one-time-code|transaction-)/i.test(
            el.autocomplete || "",
          )
        ) {
          excludedSensitive = true;
          continue;
        }
        const choices = choicesFor(el);
        if (
          el.disabled ||
          el.getAttribute("aria-disabled") === "true" ||
          (el.readOnly && !choices)
        )
          continue;
        if (onlyEmpty && !unanswered(el, controls)) continue;
        if (
          onlyEmpty &&
          choices &&
          !choices.native &&
          (clean(
            el.getAttribute("data-value") || el.getAttribute("aria-valuetext"),
          ) ||
            choices.options.some(
              (o) => o.getAttribute("aria-selected") === "true",
            ))
        )
          continue;

        if (
          onlyEmpty &&
          el.tagName !== "SELECT" &&
          isCustomComboboxControl(el) &&
          !choices
        ) {
          diagnose(el, {
            kind: "custom_combobox",
            label: cleanLabelText(rawLbl) || "Custom combobox",
            required: isRequired(el),
            reason: "Custom combobox or dropdown requires manual selection",
          });
          continue;
        }
        if (
          onlyEmpty &&
          isDateControl(el) &&
          !["date", "month"].includes(el.type)
        ) {
          diagnose(el, {
            kind: "date",
            label: cleanLabelText(rawLbl) || "Date field",
            required: isRequired(el),
            reason: "Date field requires manual entry",
          });
          continue;
        }

        const kind = choices
          ? "select"
          : el.tagName === "TEXTAREA"
            ? "textarea"
            : el.tagName === "SELECT"
              ? "select"
              : el.type;
        if (
          ![
            "text",
            "textarea",
            "email",
            "tel",
            "url",
            "number",
            "date",
            "month",
            "select",
            "radio",
            "checkbox",
            "file",
          ].includes(kind)
        ) {
          if (onlyEmpty) {
            diagnose(el, {
              kind: clean(kind) || "input",
              label: cleanLabelText(rawLbl) || "Unsupported input",
              required: isRequired(el),
              reason: `Unsupported input type (${clean(kind) || "custom"}) requires manual entry`,
            });
          }
          continue;
        }

        const resolvedLabel = label(el);
        const resolvedGroup = groupLabel(el);

        if (onlyEmpty && !resolvedLabel) {
          diagnose(el, {
            kind,
            label: clean(rawLbl) || "Unlabelled field",
            required: isRequired(el),
            reason: "Incomplete or missing field label requires manual entry",
          });
          continue;
        }

        if (
          onlyEmpty &&
          kind === "radio" &&
          !resolvedGroup &&
          !isConsentControl(el)
        ) {
          const grp = radioPeers(el, controls)[0] || el;
          diagnose(grp, {
            kind: "radio",
            label: resolvedLabel || "Radio group",
            required: isRequired(el),
            reason:
              "Radio group is missing a question label — select an option manually",
          });
          continue;
        }

        if (kind === "select" && !choices) {
          const labels = [...el.options]
            .filter(
              (o, i) =>
                !o.disabled && !o.hidden && !isPlaceholderSelectOption(o, i),
            )
            .map((o) => clean(o.textContent).toLowerCase());
          if (!labels.length || new Set(labels).size !== labels.length) {
            diagnose(el, {
              kind,
              label: resolvedLabel,
              required: isRequired(el),
              reason:
                "Missing or ambiguous dropdown choices require manual selection",
            });
            continue;
          }
          if (el.options.length > 300 || el.multiple) {
            if (onlyEmpty) {
              diagnose(el, {
                kind: "select",
                label: resolvedLabel || "Dropdown",
                required: isRequired(el),
                reason: el.multiple
                  ? "Multi-select dropdown requires manual selection"
                  : "Dropdown with more than 300 options requires manual selection",
              });
              continue;
            }
            return {
              version: 1,
              document_id: documentId,
              url: location.href,
              fields: [],
              state: "unsupported",
              has_next: false,
              has_submit: false,
            };
          }
        }

        if (fields.length >= 24) {
          diagnose(el, {
            kind,
            label: resolvedLabel,
            required: isRequired(el),
            reason:
              "Preview is limited to 24 unanswered fields; complete this control manually",
          });
          continue;
        }

        const eventChoiceSupported = Boolean(
          choices &&
          !choices.native &&
          interactionsAllowed &&
          el.tagName === "INPUT" &&
          ["text", "search"].includes(el.type) &&
          choices.options.every(
            (option) =>
              ["DIV", "SPAN", "LI"].includes(option.tagName) &&
              !option.querySelector("a,button,input,select,textarea"),
          ),
        );
        const field = {
          group_label: resolvedGroup,
          section: ["radio", "checkbox"].includes(kind)
            ? null
            : sectionLabel(el),
          preview_only: Boolean(
            ambiguousSection(el) ||
            (choices && !choices.native && !eventChoiceSupported) ||
            (onlyEmpty && isFrameworkControlled(el) && !interactionsAllowed),
          ),
          manual_reason: ambiguousSection(el)
            ? "Repeated history entry has no stable employer or education identity; complete this entry manually"
            : choices && !choices.native && !eventChoiceSupported
              ? "Choose the exact option yourself; event-driven custom dropdown filling is manual"
              : onlyEmpty && isFrameworkControlled(el) && !interactionsAllowed
                ? "Framework-controlled field: authorize website interactions or type the proposed answer yourself"
                : null,
          field_id: `f${fields.length}`,
          control_identity: controlIdentity(el),
          page_step: pageStep(),
          semantic_key: semanticHash(
            JSON.stringify([
              location.origin,
              location.pathname,
              pageStep(),
              sectionLabel(el),
              resolvedGroup,
              resolvedLabel,
              kind,
              controlIdentity(el),
              clean(el.getAttribute("aria-label")),
              clean(el.getAttribute("aria-labelledby")),
              clean(el.autocomplete),
            ]),
          ),
          kind,
          label: resolvedLabel,
          required: isRequired(el),
          options: choices
            ? choices.labels
            : kind === "select"
              ? [...el.options]
                  .filter(
                    (o, i) =>
                      !o.disabled &&
                      !o.hidden &&
                      !isPlaceholderSelectOption(o, i),
                  )
                  .map((o) => clean(o.textContent))
              : ["radio", "checkbox"].includes(kind)
                ? [resolvedLabel]
                : [],
          max_length: Math.min(4000, el.maxLength > 0 ? el.maxLength : 1500),
          invalid: isInvalid(el),
        };
        if (
          field.label.length >= 160 ||
          (field.group_label || "").length >= 160
        ) {
          field.preview_only = true;
          field.manual_reason =
            "Question exceeds the inspection text limit; read and answer the complete question manually";
        }
        refs.set(field.field_id, {
          el,
          field,
          choices,
          choiceValues: choices?.options.map((o) => o.value),
          dateConstraints: [el.min, el.max, el.step],
          name: el.name,
          autocomplete: el.autocomplete,
          options: kind === "select" && !choices ? [...el.options] : [],
          optionSnapshot:
            kind === "select" && !choices
              ? [...el.options].map((o) => ({
                  value: o.value,
                  disabled: o.disabled,
                  hidden: o.hidden,
                }))
              : [],
          initialValue: el.value,
          initialChecked: el.checked,
          initialSelectedIndex: kind === "select" ? el.selectedIndex : -1,
        });
        fields.push(field);
      }

      for (const field of fields) {
        if (
          fields.filter(
            (other) =>
              other.section === field.section &&
              other.group_label === field.group_label &&
              other.label === field.label,
          ).length > 1
        ) {
          field.preview_only = true;
          field.manual_reason =
            "Repeated question needs a distinct employment or form context; answer each control manually";
        }
      }

      const buttons = [
        ...document.querySelectorAll("button,input[type=submit],[role=button]"),
      ].filter((el) => visible(el) && applicationControl(el));
      const next = buttons.filter(
        (el) =>
          el.tagName === "BUTTON" &&
          el.type === "button" &&
          /^(next|continue)$/i.test(clean(el.textContent)),
      );
      const login = controls.some((el) => el.type === "password");
      const backgroundNetwork =
        interactionsAllowed && Boolean(navigator.serviceWorker?.controller);
      const noVerifiedApplicationForm =
        ["naukri.com", "www.naukri.com"].includes(location.hostname) &&
        fields.length === 0 &&
        unsupportedControls.length === 0;
      const state = login
        ? "login_required"
        : challenge ||
            excludedSensitive ||
            crossOriginFormFrame ||
            backgroundNetwork ||
            noVerifiedApplicationForm
          ? "manual_required"
          : fields.length
            ? fields.some((f) => f.invalid)
              ? "validation_errors"
              : "ready"
            : "unsupported";
      last = {
        version: 1,
        document_id: documentId,
        url: location.href,
        fields,
        state,
        challenge_state:
          security === "blocking"
            ? "CHALLENGE_BLOCKING"
            : security === "unverified_widget"
              ? "WIDGET_PRESENT_UNVERIFIED"
              : security === "unknown"
                ? "UNKNOWN"
                : "NONE",
        completed_count: controls.filter(
          (el) =>
            applicationControl(el) &&
            !["hidden", "submit", "button", "reset", "image"].includes(
              el.type,
            ) &&
            !sensitive.test(
              [el.type, el.name, el.id, rawLabel(el)].join(" "),
            ) &&
            !unanswered(el, controls),
        ).length,
        has_next: next.length === 1,
        has_submit: buttons.some(
          (el) =>
            el.type === "submit" ||
            /submit|apply|send/i.test(
              clean(el.textContent || el.getAttribute("value")),
            ),
        ),
      };
      if (onlyEmpty) {
        last.unsupported_controls = unsupportedControls.slice(0, 48);
        last.security_status = security;
        last.manual_reason = login
          ? "login_required"
          : excludedSensitive
            ? "sensitive_control"
            : challenge
              ? security === "blocking"
                ? "security_challenge"
                : "security_widget"
              : backgroundNetwork
                ? "background_network_scope_unverified"
                : crossOriginFormFrame ||
                    (!fields.length &&
                      unsupportedControls.some((u) => u.kind === "iframe"))
                  ? "cross_origin_frame"
                  : !fields.length && unsupportedControls.length
                    ? "unsupported_controls"
                    : noVerifiedApplicationForm
                      ? "verified_application_form_not_present"
                      : null;
      }
      return last;
    };

    const validateSnapshot = (req) => {
      if (req.interaction_authorized && navigator.serviceWorker?.controller)
        return {
          state: "manual_required",
          reason: "background_network_scope_unverified",
          results: [],
          submitted: false,
        };
      if (
        req.expires_at &&
        (!Number.isFinite(Date.parse(req.expires_at)) ||
          Date.parse(req.expires_at) <= Date.now())
      )
        return {
          state: "manual_required",
          reason: "fill_plan_stale",
          results: [],
          submitted: false,
        };
      if (req.document_id !== documentId || location.href !== last?.url)
        return {
          state: "manual_required",
          reason: "step_changed",
          results: [],
          submitted: false,
        };
      if (fillCancelled)
        return {
          state: "manual_required",
          reason: "form_cancelled_reprepare_required",
          results: [],
          submitted: false,
        };
      if (securityState() !== "none")
        return {
          state: "manual_required",
          reason: "security_challenge",
          results: [],
          submitted: false,
        };
      const currentControls = [
        ...document.querySelectorAll("input,textarea,select"),
      ].filter(visible);
      if (currentControls.length !== controlCount)
        return {
          state: "manual_required",
          reason: "dom_changed",
          results: [],
          submitted: false,
        };

      if (req.operation !== "verify_submission") {
        flushMutations();
        if (domMutated) {
          stopObserving();
          return {
            state: "manual_required",
            reason: "dom_changed",
            results: [],
            submitted: false,
          };
        }
        if (getStepSignature() !== snapshotStepSignature) {
          stopObserving();
          return {
            state: "manual_required",
            reason: "step_changed",
            results: [],
            submitted: false,
          };
        }
        const currentForms = [...document.forms];
        if (
          currentForms.length !== snapshotForms.length ||
          currentForms.some(
            (f, i) =>
              f !== snapshotForms[i].el ||
              f.action !== snapshotForms[i].action ||
              f.method !== snapshotForms[i].method ||
              f.target !== snapshotForms[i].target ||
              f.enctype !== snapshotForms[i].enctype,
          )
        ) {
          stopObserving();
          return {
            state: "manual_required",
            reason: "dom_changed",
            results: [],
            submitted: false,
          };
        }
        if (
          currentControls.some(
            (c, i) =>
              c !== snapshotControls[i]?.el ||
              c.tagName !== snapshotControls[i]?.tagName ||
              c.type !== snapshotControls[i]?.type ||
              c.name !== snapshotControls[i]?.name ||
              c.id !== snapshotControls[i]?.id ||
              c.disabled !== snapshotControls[i]?.disabled ||
              c.readOnly !== snapshotControls[i]?.readOnly,
          )
        ) {
          stopObserving();
          return {
            state: "manual_required",
            reason: "dom_changed",
            results: [],
            submitted: false,
          };
        }
      }

      for (const ref of refs.values()) {
        const el = ref.el;
        if (ref.choices) {
          let now = choicesFor(el);
          // A narrowly supported static list may close after its reviewed option
          // was clicked. Do not reopen it or fetch choices: bind the same mounted
          // list/options and require the owning input to retain the exact label.
          if (
            !now &&
            interactiveExecution &&
            ref.choiceClicked &&
            el.getAttribute("aria-expanded") === "false" &&
            document.getElementById(el.getAttribute("aria-controls")) ===
              ref.choices.list &&
            el.value === ref.choiceClicked &&
            ref.choices.list.isConnected
          ) {
            const options = [
              ...ref.choices.list.querySelectorAll("[role='option']"),
            ];
            now = {
              list: ref.choices.list,
              options,
              labels: options.map((o) =>
                clean(o.getAttribute("aria-label") || o.textContent),
              ),
            };
          }
          if (
            !now ||
            now.list !== ref.choices.list ||
            JSON.stringify(now.labels) !== JSON.stringify(ref.choices.labels) ||
            now.options.length !== ref.choices.options.length ||
            now.options.some(
              (o, i) =>
                o !== ref.choices.options[i] || o.value !== ref.choiceValues[i],
            )
          )
            return {
              state: "manual_required",
              reason: "dom_changed",
              results: [],
              submitted: false,
            };
        }
        const group = groupLabel(el);
        const options = ref.choices
          ? ref.choices.labels
          : el.tagName === "SELECT"
            ? [...el.options]
                .filter(
                  (o, i) =>
                    !o.disabled &&
                    !o.hidden &&
                    !isPlaceholderSelectOption(o, i),
                )
                .map((o) => clean(o.textContent))
            : ref.field.options;
        if (
          !el.isConnected ||
          !visible(el) ||
          el.disabled ||
          (el.readOnly && !ref.choices) ||
          el.name !== ref.name ||
          el.autocomplete !== ref.autocomplete ||
          group !== ref.field.group_label ||
          (!["radio", "checkbox"].includes(ref.field.kind) &&
            sectionLabel(el) !== ref.field.section) ||
          JSON.stringify([el.min, el.max, el.step]) !==
            JSON.stringify(ref.dateConstraints) ||
          label(el) !== ref.field.label ||
          (el.tagName === "INPUT" &&
            !ref.choices &&
            el.type !== ref.field.kind) ||
          JSON.stringify(options) !== JSON.stringify(ref.field.options) ||
          (el.tagName === "SELECT" &&
            [...el.options].some(
              (o, i) =>
                o !== ref.options[i] ||
                o.value !== ref.optionSnapshot[i]?.value ||
                o.disabled !== ref.optionSnapshot[i]?.disabled ||
                o.hidden !== ref.optionSnapshot[i]?.hidden,
            )) ||
          isRequired(el) !== ref.field.required ||
          Math.min(4000, el.maxLength > 0 ? el.maxLength : 1500) !==
            ref.field.max_length
        )
          return {
            state: "manual_required",
            reason: "dom_changed",
            results: [],
            submitted: false,
          };
      }
      // Check the entire DOM snapshot before any mutation. Existing values are never returned.
      for (const action of req.actions || []) {
        const ref = refs.get(action.field_id);
        if (
          !ref ||
          !ref.el.isConnected ||
          !visible(ref.el) ||
          ref.el.disabled ||
          (ref.el.readOnly && !ref.choices) ||
          ref.field.kind !== action.kind ||
          label(ref.el) !== ref.field.label ||
          (ref.el.tagName === "INPUT" &&
            !ref.choices &&
            ref.el.type !== action.kind)
        )
          return {
            state: "manual_required",
            reason: "dom_changed",
            results: [],
            submitted: false,
          };
      }
      return null;
    };

    const isCustomWidgetUnanswered = (widget, controls) => {
      const innerInputs = [
        ...widget.querySelectorAll("input,textarea,select"),
      ].filter(visible);
      if (innerInputs.length) {
        return innerInputs.every((input) => unanswered(input, controls));
      }
      const isEditor = widget.matches(
        '[contenteditable="true"],[role="textbox"]',
      );
      if (isEditor) {
        return !clean(widget.textContent);
      }
      const val = clean(
        widget.getAttribute("data-value") ||
          widget.getAttribute("aria-valuetext") ||
          widget.getAttribute("aria-valuenow") ||
          widget.getAttribute("value"),
      );
      if (val) return false;
      if (widget.querySelector?.('[aria-selected="true"]')) return false;
      const controlsId =
        widget.getAttribute("aria-controls") ||
        widget.getAttribute("aria-owns");
      if (controlsId) {
        const listbox = document.getElementById(controlsId);
        if (listbox?.querySelector?.('[aria-selected="true"]')) return false;
      }
      return true;
    };

    const isCustomWidgetIncomplete = (widget, controls) => {
      if (widget.matches("input,textarea,select")) return false;
      if (widget.disabled || widget.getAttribute("aria-disabled") === "true")
        return false;
      if (!isRequired(widget)) return false;
      if (isInvalid(widget)) return true;
      return isCustomWidgetUnanswered(widget, controls);
    };

    const incompleteRequired = () => {
      const controls = [
        ...document.querySelectorAll("input,textarea,select"),
      ].filter(visible);
      const nativeIncomplete = controls.some(
        (el) =>
          !el.disabled &&
          isRequired(el) &&
          (unanswered(el, controls) || !el.validity.valid || isInvalid(el)),
      );
      if (nativeIncomplete) return true;

      const customWidgets = [
        ...document.querySelectorAll(
          '[role="combobox"],[role="listbox"]:not(select),lyte-dropdown,lyte-select,lyte-autocomplete,crux-picklist-component,[contenteditable="true"],[role="textbox"]:not(input):not(textarea),[aria-required="true"]',
        ),
      ].filter(visible);

      return customWidgets.some((widget) =>
        isCustomWidgetIncomplete(widget, controls),
      );
    };

    const actualValue = (el, kind) =>
      kind === "select" && el.tagName === "SELECT"
        ? clean(el.selectedOptions[0]?.textContent)
        : ["radio", "checkbox"].includes(kind)
          ? String(el.checked)
          : el.value;

    globalThis[key] = (req) => {
      if (req.operation === "inspect")
        return inspect(
          req.only_empty === true,
          req.interactions_allowed === true,
        );
      if (req.operation === "cancel_fill" && req.document_id === documentId) {
        fillCancelled = true;
        return {
          state: "manual_required",
          reason: "form_cancelled_reprepare_required",
          results: [],
          submitted: false,
        };
      }
      if (
        !last ||
        req.document_id !== documentId ||
        location.href !== last.url ||
        !["ready", "validation_errors"].includes(last.state)
      )
        return {
          state: "manual_required",
          reason: "step_changed",
          results: [],
          submitted: false,
        };
      if (req.operation === "arm_submission") {
        submitArmed = true;
        return true;
      }
      if (req.operation === "validate_fill")
        return validateSnapshot(req) || { state: "ready", submitted: false };
      if (req.operation === "verify_fill") {
        const changed = validateSnapshot(req);
        const results = [...appliedValues].map(([field_id, value]) => {
          const ref = refs.get(field_id);
          return {
            field_id,
            status: !ref.el.validity.valid
              ? "validation_error"
              : actualValue(ref.el, ref.field.kind) === value
                ? "filled"
                : "failed",
          };
        });
        return (
          changed || {
            state:
              incompleteRequired() || results.some((r) => r.status !== "filled")
                ? "needs_input"
                : "form_filled",
            results,
            submitted: false,
          }
        );
      }
      if (req.operation === "upload_element") {
        if (validateSnapshot(req)) return null;
        const ref = refs.get(req.field_id);
        return ref?.field.kind === "file" &&
          !ref.el.files.length &&
          ref.el.isConnected &&
          visible(ref.el) &&
          ref.el.type === "file" &&
          label(ref.el) === ref.field.label
          ? ref.el
          : null;
      }
      if (req.operation === "next") {
        const changed = validateSnapshot(req);
        if (changed) return changed;
        const controls = [
          ...document.querySelectorAll("input,textarea,select"),
        ].filter(visible);
        if (
          controls.some(
            (el) =>
              !el.disabled &&
              isRequired(el) &&
              (unanswered(el, controls) || !el.validity.valid || isInvalid(el)),
          )
        )
          return { state: "manual_required", results: [], submitted: false };
        const candidates = [...document.querySelectorAll("button")].filter(
          (el) =>
            visible(el) &&
            el.type === "button" &&
            /^(next|continue)$/i.test(clean(el.textContent)),
        );
        if (candidates.length !== 1 || !last.has_next)
          return { state: "manual_required", results: [], submitted: false };
        touched = true;
        candidates[0].click();
        return { state: "progressed", submitted: false };
      }
      if (
        !["fill", "verify_submission"].includes(req.operation) ||
        !Array.isArray(req.actions) ||
        req.actions.length > 24
      )
        return { state: "failed", results: [], submitted: false };

      if (req.operation === "fill") {
        if (
          fillConsumed ||
          new Set(req.actions.map((a) => a.field_id)).size !==
            req.actions.length
        )
          return {
            state: "manual_required",
            reason: "step_changed",
            results: [],
            submitted: false,
          };
        fillConsumed = true;
      }
      const initialError = validateSnapshot(req);
      if (initialError) return initialError;
      const currentControls = [
        ...document.querySelectorAll("input,textarea,select"),
      ].filter(visible);

      if (req.operation === "verify_submission") {
        for (const [id, ref] of refs) {
          const action = req.actions.find((a) => a.field_id === id);
          const el = ref.el;
          if (!el.validity.valid || el.getAttribute("aria-invalid") === "true")
            return { state: "manual_required" };
          if (ref.field.kind === "file") {
            if (el.files.length !== (action ? 1 : 0))
              return { state: "manual_required" };
          } else {
            const value = ["checkbox", "radio"].includes(ref.field.kind)
              ? String(el.checked)
              : ref.field.kind === "select"
                ? clean(el.selectedOptions[0]?.textContent)
                : el.value;
            if (
              action ? value !== action.value : !["", "false"].includes(value)
            )
              return { state: "manual_required" };
          }
        }
        return { state: "verified" };
      }

      // Snapshot unanswered and user-modified status before mutating any control in a group.
      const canFill = new Map();
      for (const [id, ref] of refs) {
        const el = ref.el;
        const isUnansweredNow = unanswered(el, currentControls);
        const modifiedSinceInspect =
          userEdited.has(el) ||
          (ref.field.kind === "select"
            ? el.selectedIndex !== ref.initialSelectedIndex
            : ["checkbox", "radio"].includes(ref.field.kind)
              ? el.checked !== ref.initialChecked
              : el.value !== ref.initialValue);
        canFill.set(id, isUnansweredNow && !modifiedSinceInspect);
      }

      touched = true;
      const pendingResults = [];
      const filledControls = new Set();
      let interrupted = null;
      const applyActions = function* () {
        for (const action of req.actions) {
          // Input/change handlers can navigate, replace controls or change the
          // destination synchronously. Recheck the reviewed page before EACH write.
          interrupted = validateSnapshot(req);
          if (interrupted) break;
          const { el, field, options } = refs.get(action.field_id);
          const peers =
            field.kind === "radio"
              ? radioPeers(el, currentControls)
              : field.kind === "checkbox"
                ? checkboxPeers(el, currentControls)
                : [];
          // A page handler can populate another option after an earlier field's
          // input event. Preserve that selection, including indeterminate values.
          const groupChanged = peers.some(
            (peer) =>
              (peer.checked || peer.indeterminate) && !filledControls.has(peer),
          );
          const valueChanged =
            field.kind === "select"
              ? el.selectedIndex !==
                refs.get(action.field_id).initialSelectedIndex
              : ["radio", "checkbox"].includes(field.kind)
                ? el.checked !== refs.get(action.field_id).initialChecked
                : el.value !== refs.get(action.field_id).initialValue;
          if (
            !canFill.get(action.field_id) ||
            groupChanged ||
            userEdited.has(el) ||
            valueChanged
          ) {
            pendingResults.push({
              field_id: action.field_id,
              status: "untouched",
            });
            continue;
          }
          if (
            field.preview_only ||
            field.kind === "file" ||
            typeof action.value !== "string"
          ) {
            pendingResults.push({
              field_id: action.field_id,
              status: "untouched",
            });
            continue;
          }
          if (isConsentControl(el, field.group_label || "")) {
            pendingResults.push({
              field_id: action.field_id,
              status: "untouched",
            });
            continue;
          }
          if (
            req.only_empty === true &&
            isFrameworkControlled(el) &&
            req.interaction_authorized !== true
          ) {
            pendingResults.push({
              field_id: action.field_id,
              status: "failed",
            });
            continue;
          }
          if (action.value.length > field.max_length) {
            pendingResults.push({
              field_id: action.field_id,
              status: "failed",
            });
            continue;
          }
          // Website events may autosave. They require a separate explicit review.
          if (req.interaction_authorized === true) {
            el.focus();
            interrupted = validateSnapshot(req);
            if (interrupted) break;
          }
          if (["checkbox", "radio"].includes(field.kind)) {
            if (!["true", "false"].includes(action.value)) {
              pendingResults.push({
                field_id: action.field_id,
                status: "failed",
              });
              continue;
            }
            const checked = action.value === "true";
            if (
              (req.emit_events === true ||
                req.interaction_authorized === true) &&
              el.checked !== checked
            ) {
              // React's controlled checkbox/radio change plugin observes click,
              // not a checked assignment followed by synthetic input/change.
              // The worker's network/submission guard stays active for this event.
              el.click();
            } else {
              el.checked = checked;
            }
          } else if (field.kind === "select" && el.tagName !== "SELECT") {
            const choices = refs.get(action.field_id).choices;
            const index = choices?.labels.indexOf(action.value) ?? -1;
            if (
              !choices ||
              index < 0 ||
              (!choices.native && req.interaction_authorized !== true)
            ) {
              pendingResults.push({
                field_id: action.field_id,
                status: "failed",
              });
              continue;
            }
            if (choices.native) {
              if (choices.options[index].value !== action.value) {
                pendingResults.push({
                  field_id: action.field_id,
                  status: "failed",
                });
                continue;
              }
              Object.getOwnPropertyDescriptor(
                HTMLInputElement.prototype,
                "value",
              ).set.call(el, action.value);
            } else {
              // Exact already-visible option only. The site's handler must retain
              // its own selected value; the extension never forges that value.
              refs.get(action.field_id).choiceClicked = action.value;
              choices.options[index].click();
            }
          } else if (field.kind === "select") {
            const matches = options.filter(
              (o) =>
                !o.disabled &&
                !o.hidden &&
                !isPlaceholderSelectOption(o, o.index) &&
                clean(o.textContent) === action.value,
            );
            if (matches.length !== 1) {
              pendingResults.push({
                field_id: action.field_id,
                status: "failed",
              });
              continue;
            }
            el.selectedIndex = matches[0].index;
          } else {
            if (["date", "month"].includes(field.kind)) {
              const probe = document.createElement("input");
              probe.type = field.kind;
              probe.min = el.min;
              probe.max = el.max;
              probe.step = el.step;
              probe.value = action.value;
              if (probe.value !== action.value || !probe.validity.valid) {
                pendingResults.push({
                  field_id: action.field_id,
                  status: "failed",
                });
                continue;
              }
            }
            const proto =
              field.kind === "textarea"
                ? HTMLTextAreaElement.prototype
                : HTMLInputElement.prototype;
            Object.getOwnPropertyDescriptor(proto, "value").set.call(
              el,
              action.value,
            );
          }
          if (
            (req.emit_events === true || req.interaction_authorized === true) &&
            !["checkbox", "radio"].includes(field.kind)
          ) {
            el.dispatchEvent(new Event("input", { bubbles: true }));
            interrupted = validateSnapshot(req);
            if (!interrupted)
              el.dispatchEvent(new Event("change", { bubbles: true }));
          }
          if (req.interaction_authorized === true) el.blur();
          filledControls.add(el);
          appliedValues.set(action.field_id, action.value);
          pendingResults.push({
            field_id: action.field_id,
            el,
            checkValidity: true,
            expectedValue: action.value,
            kind: field.kind,
          });
          if (req.interaction_authorized === true) yield;
        }

        interrupted = interrupted || validateSnapshot(req);
        const results = pendingResults.map((item) =>
          item.checkValidity
            ? {
                field_id: item.field_id,
                status: !item.el.isConnected
                  ? "failed"
                  : !item.el.validity.valid || isInvalid(item.el)
                    ? "validation_error"
                    : actualValue(item.el, item.kind) === item.expectedValue
                      ? "filled"
                      : "failed",
              }
            : item,
        );
        stopObserving();
        return {
          ...(interrupted ? { reason: interrupted.reason } : {}),
          state: interrupted
            ? "manual_required"
            : incompleteRequired() || results.some((r) => r.status !== "filled")
              ? "needs_input"
              : "form_filled",
          results,
          submitted: false,
        };
      };
      const execution = applyActions();
      if (req.interaction_authorized === true) {
        interactiveExecution = true;
        return (async () => {
          let step = execution.next();
          while (!step.done) {
            await new Promise((resolve) => setTimeout(resolve, 200));
            step = execution.next();
          }
          const result = step.value;
          await new Promise((resolve) => setTimeout(resolve, 500));
          const changed = validateSnapshot(req);
          for (const item of result.results) {
            if (item.status !== "filled") continue;
            const ref = refs.get(item.field_id);
            if (
              !ref?.el.isConnected ||
              actualValue(ref.el, ref.field.kind) !==
                appliedValues.get(item.field_id)
            )
              item.status = "failed";
            else if (!ref.el.validity.valid || isInvalid(ref.el))
              item.status = "validation_error";
          }
          interactiveExecution = false;
          if (changed)
            return {
              ...result,
              state: "manual_required",
              reason: changed.reason,
            };
          if (result.results.some((item) => item.status !== "filled"))
            result.state = "needs_input";
          return { ...result, verification: "retained_after_blur" };
        })().finally(() => {
          interactiveExecution = false;
        });
      }
      let step = execution.next();
      while (!step.done) step = execution.next();
      return step.value;
    };
  }
  return globalThis[key](request);
}
