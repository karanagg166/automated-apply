// Runs only in the worker's isolated world. No selectors or code come from a model.
export async function submissionDOM(request) {
  const key = "__automatedApplySubmissionV1";
  if (!globalThis[key]) {
    let sealed = null;
    const sha = async (bytes) =>
      [...new Uint8Array(await crypto.subtle.digest("SHA-256", bytes))]
        .map((x) => x.toString(16).padStart(2, "0"))
        .join("");
    const visible = (el) =>
      el.getClientRects().length > 0 &&
      getComputedStyle(el).visibility !== "hidden";
    const contracts = {
      greenhouse: ["application_form", "submit_app", "Submit application"],
      lever: ["lever-application", "lever-submit", "Submit application"],
      google: ["google-form", "google-submit", "Submit"],
    };
    const snapshot = async (req) => {
      const c = contracts[req.adapter];
      if (
        !c ||
        location.href !== req.application_url ||
        !globalThis.__automatedApplyFormV1
      )
        throw Error("unsupported_contract");
      const verified = globalThis.__automatedApplyFormV1({
        operation: "verify_submission",
        document_id: req.document_id,
        actions: req.actions,
      });
      if (verified.state !== "verified")
        throw Error("changed_or_missing_values");
      const forms = [...document.forms];
      const form = document.getElementById(c[0]);
      const button = document.getElementById(c[1]);
      const controls = [...document.querySelectorAll("input,textarea,select")];
      if (
        forms.length !== 1 ||
        form !== forms[0] ||
        !button ||
        button.form !== form ||
        button.tagName !== "BUTTON" ||
        button.type !== "submit" ||
        button.disabled ||
        !visible(button) ||
        button.textContent.trim() !== c[2] ||
        form.action !== req.request_url ||
        form.method !== "post" ||
        form.target ||
        form.noValidate ||
        button.formNoValidate ||
        button.hasAttribute("formaction") ||
        button.hasAttribute("formmethod") ||
        button.hasAttribute("formtarget") ||
        controls.some(
          (el) =>
            el.form !== form ||
            !visible(el) ||
            !el.name ||
            el.disabled ||
            el.readOnly,
        ) ||
        [...form.elements].filter((el) => el.type === "submit").length !== 1 ||
        document.querySelector(
          'iframe,[data-sitekey],input[type=password],input[autocomplete="one-time-code"]',
        ) ||
        /I (?:agree|certify|attest)|consent|criminal|disability|veteran|ethnicity|signature/i.test(
          form.textContent,
        )
      )
        throw Error("changed_or_sensitive_form");
      const entries = [];
      // Construct successful controls directly. Creating FormData here would let
      // a page's formdata listener replace reviewed values before sealing them.
      for (const field of controls) {
        if (["checkbox", "radio"].includes(field.type) && !field.checked)
          continue;
        if (field.type === "file") {
          if (field.files.length !== 1) throw Error("unreviewed_file");
          const value = field.files[0];
          const hash = await sha(await value.arrayBuffer());
          const action = req.actions.find(
            (a) =>
              a.kind === "file" && a.safe_reference === "canonical_pdf:" + hash,
          );
          if (!action) throw Error("unreviewed_file");
          entries.push([
            field.name,
            {
              sha256: hash,
              size: value.size,
              type: value.type,
              name: value.name,
            },
          ]);
        } else
          entries.push([field.name, field.value.replace(/\r?\n/g, "\r\n")]);
      }
      if (button.name) entries.push([button.name, button.value]);
      const metadata = controls.map((el) => [
        el.tagName,
        el.type,
        el.name,
        el.id,
        el.required,
        el.getAttribute("aria-required"),
        el.getAttribute("aria-invalid"),
        el.maxLength,
        el.getAttribute("pattern"),
        el.getAttribute("min"),
        el.getAttribute("max"),
      ]);
      const data = JSON.stringify([
        req.document_id,
        location.href,
        form.action,
        form.method,
        form.enctype,
        button.id,
        button.textContent,
        button.name,
        button.value,
        metadata,
        entries,
      ]);
      return {
        form,
        button,
        data,
        entries,
        document_digest: await sha(new TextEncoder().encode(data)),
      };
    };
    globalThis[key] = async (req) => {
      if (req.operation === "review") {
        const s = await snapshot(req);
        sealed = { ...s, req };
        return {
          state: "reviewable",
          document_id: req.document_id,
          document_digest: s.document_digest,
          entries: s.entries,
        };
      }
      if (req.operation === "validate" && sealed) {
        const fresh = await snapshot(sealed.req);
        if (
          fresh.data !== sealed.data ||
          fresh.form !== sealed.form ||
          fresh.button !== sealed.button ||
          req.document_digest !== sealed.document_digest
        )
          throw Error("stale_document");
        return { state: "verified" };
      }
      if (req.operation === "submit" && sealed) {
        const saved = sealed;
        sealed = null; // Private single use, including failed attempts and double clicks.
        const fresh = await snapshot(saved.req);
        if (
          fresh.data !== saved.data ||
          fresh.form !== saved.form ||
          fresh.button !== saved.button ||
          req.document_digest !== saved.document_digest
        )
          throw Error("stale_document");
        globalThis.__automatedApplyFormV1({
          operation: "arm_submission",
          document_id: saved.req.document_id,
        });
        saved.button.click();
        return { state: "clicked" };
      }
      throw Error("single_use_review_required");
    };
  }
  return await globalThis[key](request);
}
