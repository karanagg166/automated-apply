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

    const inspect = (onlyEmpty = false) => {
      // A second popup/review must invalidate earlier plans in the same document.
      documentId = crypto.randomUUID();
      fillConsumed = false;
      appliedValues = new Map();
      const controls = [
        ...document.querySelectorAll("input,textarea,select"),
      ].filter(visible);
      controlCount = controls.length;
      snapshotControls = controls.map((el) => ({
        el,
        tagName: el.tagName,
        type: el.type,
        name: el.name,
        id: el.id,
        disabled: el.disabled,
        readOnly: el.readOnly,
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
      const seenUnsupportedGroups = new Set();
      refs = new Map();
      let excludedSensitive = false;
      let crossOriginFormFrame = false;

      let challenge = Boolean(
        document.querySelector(
          'iframe[src*="recaptcha"],iframe[src*="hcaptcha"],iframe[src*="turnstile"],iframe[src*="challenges.cloudflare"],iframe[src*="funcaptcha"],iframe[src*="arkoselabs"],[data-sitekey],.cf-turnstile,input[autocomplete="one-time-code"]',
        ),
      );

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
          unsupportedControls.push({
            kind: "iframe",
            label: clean(frame.title || "Security challenge") || "Challenge",
            required: true,
            reason: "Security challenge or CAPTCHA requires manual completion",
          });
          continue;
        }
        if (/stripe|paypal|checkout|payment|braintree|razorpay/i.test(fHint)) {
          excludedSensitive = true;
          unsupportedControls.push({
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
          unsupportedControls.push({
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
          unsupportedControls.push({
            kind: isEditor ? "custom_widget" : "custom_combobox",
            label: wLabel,
            required: isRequired(widget),
            reason: isEditor
              ? "Rich-text or custom widget requires manual entry"
              : "Custom combobox or dropdown requires manual selection",
          });
        }
      }

      for (const el of controls) {
        if (["hidden", "submit", "button", "reset", "image"].includes(el.type))
          continue;
        const rawLbl = rawLabel(el);
        const hint = [
          el.type,
          el.name,
          el.id,
          el.autocomplete,
          rawLbl,
          rawGroupLabel(el),
        ].join(" ");
        if (/captcha/i.test(hint)) {
          challenge = true;
          continue;
        }
        if (selfIdentification.test(hint.replace(/[_-]/g, " "))) {
          if (onlyEmpty)
            unsupportedControls.push({
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
        if (el.disabled || el.readOnly) continue;
        if (onlyEmpty && !unanswered(el, controls)) continue;

        if (onlyEmpty && isCustomComboboxControl(el)) {
          unsupportedControls.push({
            kind: "custom_combobox",
            label: cleanLabelText(rawLbl) || "Custom combobox",
            required: isRequired(el),
            reason: "Custom combobox or dropdown requires manual selection",
          });
          continue;
        }
        if (onlyEmpty && isDateControl(el)) {
          unsupportedControls.push({
            kind: "date",
            label: cleanLabelText(rawLbl) || "Date field",
            required: isRequired(el),
            reason: "Date field requires manual entry",
          });
          continue;
        }
        if (onlyEmpty && isFrameworkControlled(el)) {
          unsupportedControls.push({
            kind: "framework_input",
            label: cleanLabelText(rawLbl) || "Framework-controlled input",
            required: isRequired(el),
            reason: "Framework-controlled input requires manual typing",
          });
          continue;
        }

        const kind =
          el.tagName === "TEXTAREA"
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
            "select",
            "radio",
            "checkbox",
            "file",
          ].includes(kind)
        ) {
          if (onlyEmpty) {
            unsupportedControls.push({
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
          unsupportedControls.push({
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
          const grpKey = el.name || resolvedLabel;
          if (!seenUnsupportedGroups.has(grpKey)) {
            seenUnsupportedGroups.add(grpKey);
            unsupportedControls.push({
              kind: "radio",
              label: resolvedLabel || "Radio group",
              required: isRequired(el),
              reason:
                "Radio group is missing a question label — select an option manually",
            });
          }
          continue;
        }

        if (kind === "select") {
          if (el.options.length > 20 || el.multiple) {
            if (onlyEmpty) {
              unsupportedControls.push({
                kind: "select",
                label: resolvedLabel || "Dropdown",
                required: isRequired(el),
                reason: el.multiple
                  ? "Multi-select dropdown requires manual selection"
                  : "Dropdown with more than 20 options requires manual selection",
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
          const overLimit = {
            version: 1,
            document_id: documentId,
            url: location.href,
            fields: [],
            state: "unsupported",
            has_next: false,
            has_submit: false,
          };
          if (onlyEmpty) {
            overLimit.manual_reason = "too_many_fields";
            overLimit.unsupported_controls = [
              {
                kind: "form",
                label: "Application form",
                required: false,
                reason:
                  "Form step has more than 24 unanswered fields — answer some fields manually first",
              },
            ];
          }
          return overLimit;
        }

        const field = {
          group_label: resolvedGroup,
          field_id: `f${fields.length}`,
          kind,
          label: resolvedLabel,
          required: isRequired(el),
          options:
            kind === "select"
              ? [...el.options].map((o) => clean(o.textContent))
              : ["radio", "checkbox"].includes(kind)
                ? [resolvedLabel]
                : [],
          max_length: Math.min(4000, el.maxLength > 0 ? el.maxLength : 1500),
          invalid: isInvalid(el),
        };
        refs.set(field.field_id, {
          el,
          field,
          name: el.name,
          autocomplete: el.autocomplete,
          options: kind === "select" ? [...el.options] : [],
          optionSnapshot:
            kind === "select"
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

      const buttons = [
        ...document.querySelectorAll("button,input[type=submit],[role=button]"),
      ].filter(visible);
      const next = buttons.filter(
        (el) =>
          el.tagName === "BUTTON" &&
          el.type === "button" &&
          /^(next|continue)$/i.test(clean(el.textContent)),
      );
      const login = controls.some((el) => el.type === "password");
      const state = login
        ? "login_required"
        : challenge || excludedSensitive || crossOriginFormFrame
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
        last.unsupported_controls = unsupportedControls.slice(0, 24);
        last.manual_reason = login
          ? "login_required"
          : excludedSensitive
            ? "sensitive_control"
            : challenge
              ? "security_challenge"
              : crossOriginFormFrame ||
                  (!fields.length &&
                    unsupportedControls.some((u) => u.kind === "iframe"))
                ? "cross_origin_frame"
                : !fields.length && unsupportedControls.length
                  ? "unsupported_controls"
                  : null;
      }
      return last;
    };

    const validateSnapshot = (req) => {
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
        const group = groupLabel(el);
        const options =
          el.tagName === "SELECT"
            ? [...el.options].map((o) => clean(o.textContent))
            : ref.field.options;
        if (
          !el.isConnected ||
          !visible(el) ||
          el.disabled ||
          el.readOnly ||
          el.name !== ref.name ||
          el.autocomplete !== ref.autocomplete ||
          group !== ref.field.group_label ||
          label(el) !== ref.field.label ||
          (el.tagName === "INPUT" && el.type !== ref.field.kind) ||
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
          ref.el.readOnly ||
          ref.field.kind !== action.kind ||
          label(ref.el) !== ref.field.label ||
          (ref.el.tagName === "INPUT" && ref.el.type !== action.kind)
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

    const incompleteRequired = () => {
      const controls = [
        ...document.querySelectorAll("input,textarea,select"),
      ].filter(visible);
      return controls.some(
        (el) =>
          !el.disabled &&
          isRequired(el) &&
          (unanswered(el, controls) || !el.validity.valid || isInvalid(el)),
      );
    };

    const actualValue = (el, kind) =>
      kind === "select"
        ? clean(el.selectedOptions[0]?.textContent)
        : ["radio", "checkbox"].includes(kind)
          ? String(el.checked)
          : el.value;

    globalThis[key] = (req) => {
      if (req.operation === "inspect") return inspect(req.only_empty === true);
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
        if (field.kind === "file" || typeof action.value !== "string") {
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
        if (req.only_empty === true && isFrameworkControlled(el)) {
          pendingResults.push({ field_id: action.field_id, status: "failed" });
          continue;
        }
        if (action.value.length > field.max_length) {
          pendingResults.push({ field_id: action.field_id, status: "failed" });
          continue;
        }
        // No change/input events in manual mode: those may trigger external writes.
        if (["checkbox", "radio"].includes(field.kind)) {
          if (!["true", "false"].includes(action.value)) {
            pendingResults.push({
              field_id: action.field_id,
              status: "failed",
            });
            continue;
          }
          const checked = action.value === "true";
          if (req.emit_events === true && el.checked !== checked) {
            // React's controlled checkbox/radio change plugin observes click,
            // not a checked assignment followed by synthetic input/change.
            // The worker's network/submission guard stays active for this event.
            el.click();
          } else {
            el.checked = checked;
          }
        } else if (field.kind === "select") {
          const matches = options.filter(
            (o) => !o.disabled && clean(o.textContent) === action.value,
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
          req.emit_events === true &&
          !["checkbox", "radio"].includes(field.kind)
        ) {
          el.dispatchEvent(new Event("input", { bubbles: true }));
          interrupted = validateSnapshot(req);
          if (!interrupted)
            el.dispatchEvent(new Event("change", { bubbles: true }));
        }
        filledControls.add(el);
        appliedValues.set(action.field_id, action.value);
        pendingResults.push({
          field_id: action.field_id,
          el,
          checkValidity: true,
          expectedValue: action.value,
          kind: field.kind,
        });
      }

      interrupted = interrupted || validateSnapshot(req);
      const results = pendingResults.map((item) =>
        item.checkValidity
          ? {
              field_id: item.field_id,
              status: !item.el.validity.valid
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
  }
  return globalThis[key](request);
}
