// Self-contained for Chrome isolated-world injection and the dedicated worker.
// The website supplies data only. Field references live in a private closure.
export function formDOM(request = { operation: "inspect" }) {
  const key = "__automatedApplyFormV1";
  if (!globalThis[key]) {
    const documentId = crypto.randomUUID();
    const sensitive =
      /password|passcode|one.?time|\botp\b|\bmfa\b|credit.?card|card.?number|\bcvv\b|\bcvc\b|session|token|secret|social.?security|\bssn\b/i;
    const clean = (s) =>
      String(s || "")
        .replace(/[\u0000-\u001f\u007f]/g, " ")
        .trim()
        .slice(0, 160);
    const visible = (el) =>
      el.getClientRects().length > 0 &&
      getComputedStyle(el).visibility !== "hidden";
    const label = (el) =>
      clean(
        el.labels?.[0]?.textContent ||
          el.getAttribute("aria-label") ||
          el.getAttribute("placeholder") ||
          "",
      );
    let refs = new Map();
    let last = null;
    let touched = false;
    let controlCount = 0;
    document.addEventListener(
      "submit",
      (e) => {
        if (touched) {
          e.preventDefault();
          e.stopImmediatePropagation();
        }
      },
      true,
    );
    const inspect = () => {
      const controls = [
        ...document.querySelectorAll("input,textarea,select"),
      ].filter(visible);
      controlCount = controls.length;
      const fields = [];
      refs = new Map();
      let excludedSensitive = false;
      for (const el of controls) {
        if (["hidden", "submit", "button", "reset", "image"].includes(el.type))
          continue;
        const hint = [el.type, el.name, el.id, el.autocomplete, label(el)].join(
          " ",
        );
        if (
          sensitive.test(hint) ||
          /^(cc-|current-password|new-password)/.test(el.autocomplete || "")
        ) {
          excludedSensitive = true;
          continue;
        }
        if (el.disabled || el.readOnly) continue;
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
        )
          continue;
        if (fields.length >= 24)
          return {
            version: 1,
            document_id: documentId,
            url: location.href,
            fields: [],
            state: "unsupported",
            has_next: false,
            has_submit: false,
          };
        const field = {
          group_label:
            clean(
              el.closest("fieldset")?.querySelector("legend")?.textContent,
            ) || null,
          field_id: `f${fields.length}`,
          kind,
          label: label(el),
          required: el.required || el.getAttribute("aria-required") === "true",
          options: [],
          max_length: Math.min(4000, el.maxLength > 0 ? el.maxLength : 1500),
          invalid: el.getAttribute("aria-invalid") === "true",
        };
        if (kind === "select") {
          if (el.options.length > 20 || el.multiple)
            return {
              version: 1,
              document_id: documentId,
              url: location.href,
              fields: [],
              state: "unsupported",
              has_next: false,
              has_submit: false,
            };
          field.options = [...el.options].map((o) => clean(o.textContent));
        }
        if (["radio", "checkbox"].includes(kind)) field.options = [label(el)];
        refs.set(field.field_id, {
          el,
          field,
          name: el.name,
          autocomplete: el.autocomplete,
          options: kind === "select" ? [...el.options] : [],
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
      const challenge = !!document.querySelector(
        'iframe[src*="recaptcha"],iframe[src*="hcaptcha"],[data-sitekey],input[autocomplete="one-time-code"]',
      );
      const login = controls.some((el) => el.type === "password");
      last = {
        version: 1,
        document_id: documentId,
        url: location.href,
        fields,
        state: login
          ? "login_required"
          : challenge || excludedSensitive
            ? "manual_required"
            : fields.length
              ? fields.some((f) => f.invalid)
                ? "validation_errors"
                : "ready"
              : "unsupported",
        has_next: next.length === 1,
        has_submit: buttons.some(
          (el) =>
            el.type === "submit" ||
            /submit|apply|send/i.test(
              clean(el.textContent || el.getAttribute("value")),
            ),
        ),
      };
      return last;
    };
    globalThis[key] = (req) => {
      if (req.operation === "inspect") return inspect();
      if (
        !last ||
        req.document_id !== documentId ||
        location.href !== last.url ||
        !["ready", "validation_errors"].includes(last.state)
      )
        return { state: "manual_required", results: [], submitted: false };
      if (req.operation === "upload_element") {
        const ref = refs.get(req.field_id);
        return ref?.field.kind === "file" &&
          ref.el.isConnected &&
          visible(ref.el) &&
          ref.el.type === "file" &&
          label(ref.el) === ref.field.label
          ? ref.el
          : null;
      }
      if (req.operation === "next") {
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
        req.operation !== "fill" ||
        !Array.isArray(req.actions) ||
        req.actions.length > 24
      )
        return { state: "failed", results: [], submitted: false };
      const results = [];
      if (
        [...document.querySelectorAll("input,textarea,select")].filter(visible)
          .length !== controlCount
      )
        return { state: "manual_required", results: [], submitted: false };
      for (const ref of refs.values()) {
        const el = ref.el;
        const group =
          clean(el.closest("fieldset")?.querySelector("legend")?.textContent) ||
          null;
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
          (el.required || el.getAttribute("aria-required") === "true") !==
            ref.field.required ||
          Math.min(4000, el.maxLength > 0 ? el.maxLength : 1500) !==
            ref.field.max_length
        )
          return { state: "manual_required", results: [], submitted: false };
      }
      // Check the entire DOM snapshot before any mutation. Existing values are never returned.
      for (const action of req.actions) {
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
          return { state: "manual_required", results: [], submitted: false };
      }
      touched = true;
      for (const action of req.actions) {
        const { el, field, options } = refs.get(action.field_id);
        if (field.kind === "file" || typeof action.value !== "string") {
          results.push({ field_id: action.field_id, status: "untouched" });
          continue;
        }
        if (action.value.length > field.max_length) {
          results.push({ field_id: action.field_id, status: "failed" });
          continue;
        }
        // No change/input events in manual mode: those may trigger external writes.
        if (["checkbox", "radio"].includes(field.kind)) {
          if (!["true", "false"].includes(action.value)) {
            results.push({ field_id: action.field_id, status: "failed" });
            continue;
          }
          el.checked = action.value === "true";
        } else if (field.kind === "select") {
          const matches = options.filter(
            (o) => clean(o.textContent) === action.value,
          );
          if (matches.length !== 1) {
            results.push({ field_id: action.field_id, status: "failed" });
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
        if (req.emit_events === true) {
          el.dispatchEvent(new Event("input", { bubbles: true }));
          el.dispatchEvent(new Event("change", { bubbles: true }));
        }
        results.push({
          field_id: action.field_id,
          status: el.validity.valid ? "filled" : "validation_error",
        });
      }
      return {
        state: results.some((r) => r.status !== "filled")
          ? "needs_input"
          : "form_filled",
        results,
        submitted: false,
      };
    };
  }
  return globalThis[key](request);
}
