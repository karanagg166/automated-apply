// Site-specific ordinary UI adapter in the isolated world. No private endpoints,
// cookies export, arbitrary selectors, keyboard, clipboard, popup or file chooser.
export async function executeNaukri(work) {
  const failure = (reason) => ({ kind: "needs_input", reason });
  const digest = async (value) =>
    [...new Uint8Array(await crypto.subtle.digest("SHA-256", value))]
      .map((x) => x.toString(16).padStart(2, "0"))
      .join("");
  const hash = (value) => digest(new TextEncoder().encode(value));
  const visible = (el) =>
    el?.getClientRects().length > 0 &&
    getComputedStyle(el).visibility !== "hidden";
  const clean = (el) => el?.textContent?.replace(/\s+/g, " ").trim();
  const request = work.execution;
  const expectedUrl = work.target_url || work.url;
  const safe = () => {
    if (document.visibilityState !== "hidden") throw Error("owner_tab_active");
    if (
      location.href !== expectedUrl ||
      location.origin !== "https://www.naukri.com"
    )
      throw Error("provider_navigation_changed");
    if (
      /captcha|verify (?:that )?you are human|unusual traffic|access denied|too many requests/i.test(
        document.body?.innerText || "",
      ) ||
      [
        ...document.querySelectorAll(
          'iframe[src*="captcha"],[data-sitekey],input[type=password],input[autocomplete="one-time-code"]',
        ),
      ].some(visible)
    )
      throw Error("provider_challenge_requires_owner");
  };
  const account = async () => {
    const emails = [
      ...new Set(
        [
          ...document.querySelectorAll(
            'header [class*="email"], .chip-summary .email-verify, [class*="user-details"] [class*="email"], [class*="profile-details"] [class*="email"], [class*="personal-details"] [class*="email"], input[type=email]',
          ),
        ]
          .filter(visible)
          .map((e) => (e.value || clean(e) || "").trim().toLowerCase())
          .filter((x) => /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(x)),
      ),
    ];
    if (
      emails.length !== 1 ||
      (await hash(emails[0])) !== request?.expected_account_sha256
    )
      throw Error("provider_account_identity_unverified");
    return hash(emails[0]);
  };
  const key = "__automatedApplyNaukriExecutionV1";
  if (!globalThis[key])
    globalThis[key] = {
      documentId: crypto.randomUUID(),
      used: false,
      seal: null,
    };
  const state = globalThis[key];
  const summarySection = () => {
    const headings = [
      ...document.querySelectorAll('h2,h3,h4,[class*="widgetTitle"]'),
    ].filter((e) => visible(e) && clean(e) === "Profile summary");
    if (headings.length !== 1) return null;
    return headings[0].closest('section,[class*="widget"],[class*="card"]');
  };
  const summaryValue = () => {
    const section = summarySection();
    const paragraphs =
      section && [...section.querySelectorAll("p")].filter(visible);
    if (!paragraphs || paragraphs.length !== 1) return undefined;
    return clean(paragraphs[0]);
  };
  const result = async (name, extra = {}) => ({
    kind: "execution_observation",
    observed_url: expectedUrl,
    requisition: work.requisition,
    execution: {
      state: name,
      document_id: state.documentId,
      account_sha256: await account(),
      evidence_sha256: await hash(
        JSON.stringify([work.requisition, name, extra]),
      ),
      ...extra,
    },
  });
  const snapshot = async () => {
    safe();
    await account();
    const modern = [...document.querySelectorAll("#job_header")].filter(
      visible,
    );
    const legacy = [
      ...document.querySelectorAll('[class*="jd-header"], [class*="jdHeader"]'),
    ].filter(
      (e) =>
        visible(e) &&
        e.querySelectorAll("h1").length === 1 &&
        e.querySelector('[class*="comp-name"], [class*="compName"]'),
    );
    const headers = modern.length ? modern : legacy;
    if (headers.length !== 1) throw Error("job_header_unrecognized");
    const header = headers[0];
    const title = clean(header.querySelector("h1"));
    const company = clean(
      header.querySelector(
        '[class*="comp-name"] > a, [class*="compName"] > a',
      ) || header.querySelector('[class*="comp-name"], [class*="compName"]'),
    );
    if (
      title !== request.expected_title ||
      company !== request.expected_company ||
      !location.pathname.endsWith("-" + work.requisition)
    )
      throw Error("provider_job_or_company_changed");
    const applied = [...header.querySelectorAll("button,[role=button]")]
      .filter(visible)
      .some((e) => /^(already applied|applied)$/i.test(clean(e)));
    if (applied) return { applied, title, company };
    if (
      [
        ...document.querySelectorAll(
          "form, [role=dialog], input[type=checkbox]",
        ),
      ]
        .filter(visible)
        .some((e) => e.tagName !== "INPUT" || e.checked)
    )
      throw Error("direct_apply_has_additional_side_effects_or_form");
    const controls = [...header.querySelectorAll("button")].filter(
      (e) =>
        visible(e) &&
        clean(e) === "Apply" &&
        !e.disabled &&
        !e.form &&
        !e.hasAttribute("formaction"),
    );
    if (controls.length !== 1)
      throw Error("supported_direct_apply_control_required");
    const button = controls[0];
    if (
      button.getAttribute("aria-haspopup") ||
      button.getAttribute("onclick")?.match(/window\.open|location/)
    )
      throw Error("external_application_requires_review");
    return {
      title,
      company,
      button,
      control: await hash(
        JSON.stringify([
          state.documentId,
          location.href,
          title,
          company,
          clean(header),
          clean(
            document.querySelector(
              '[class*="job-desc"], [class*="jobDesc"], [itemprop="description"]',
            ),
          ),
          [
            ...document.querySelectorAll(
              '[class*="key-skill"], [class*="keySkill"]',
            ),
          ].map(clean),
          [
            ...document.querySelectorAll('script[type="application/ld+json"]'),
          ].map((e) => e.textContent),
          button.outerHTML,
        ]),
      ),
    };
  };
  try {
    safe();
    if (work.operation === "inspect_profile_sync") {
      await account();
      const fields = {};
      const summary = summaryValue();
      if (summary !== undefined) fields.summary = summary;
      const names = [
        ...document.querySelectorAll(
          '[class*="profile-details"] [class*="fullname"]',
        ),
      ].filter(visible);
      if (names.length === 1) fields.full_name = clean(names[0]);
      return await result("PROFILE_OBSERVED", { profile_fields: fields });
    }
    if (work.operation === "sync_profile") {
      const section = summarySection();
      const summary = summaryValue();
      if (
        state.used ||
        !section ||
        state.documentId !== request.document_id ||
        typeof summary !== "string"
      )
        throw Error("profile_summary_control_unsupported");
      if (
        (summary ? await hash(JSON.stringify(summary)) : null) !==
          request.previous_summary_reference ||
        !request.approved_summary
      )
        throw Error("profile_sync_preimage_changed");
      const edits = [...section.querySelectorAll("button,a")].filter(
        (e) =>
          visible(e) &&
          /^(Edit|Edit profile summary)$/.test(
            e.getAttribute("aria-label") || clean(e),
          ),
      );
      if (edits.length !== 1)
        throw Error("profile_summary_control_unsupported");
      const checkPermit = () => {
        safe();
        const expires = Date.parse(request.permit_expires_at);
        if (
          !Number.isFinite(expires) ||
          expires <= Date.now() ||
          expires > Date.now() + 2500
        )
          throw Error("browser_action_permit_expired");
      };
      await account();
      checkPermit();
      state.used = true;
      edits[0].click();
      for (
        let i = 0;
        i < 20 && ![...document.querySelectorAll("textarea")].some(visible);
        i++
      )
        await new Promise((r) => setTimeout(r, 50));
      const textareas = [...document.querySelectorAll("textarea")].filter(
        visible,
      );
      if (textareas.length !== 1)
        throw Error("profile_summary_editor_unsupported");
      const textarea = textareas[0];
      const label =
        textarea.getAttribute("aria-label") ||
        [...(textarea.labels || [])].map(clean).join(" ");
      const scope = textarea.closest("form,[role=dialog],section");
      if (
        label !== "Profile summary" ||
        !scope ||
        [...scope.querySelectorAll("input,select,textarea")].filter(visible)
          .length !== 1
      )
        throw Error("profile_summary_editor_unsupported");
      if (
        textarea.maxLength > 0 &&
        request.approved_summary.length > textarea.maxLength
      )
        throw Error("profile_summary_exceeds_platform_limit");
      Object.getOwnPropertyDescriptor(
        HTMLTextAreaElement.prototype,
        "value",
      ).set.call(textarea, request.approved_summary);
      for (const event of ["input", "change", "blur"])
        textarea.dispatchEvent(new Event(event, { bubbles: true }));
      await new Promise((r) => setTimeout(r, 50));
      if (!textarea.isConnected || textarea.value !== request.approved_summary)
        throw Error("profile_summary_value_not_retained");
      const saves = [...scope.querySelectorAll("button")].filter(
        (e) => visible(e) && clean(e) === "Save" && !e.disabled,
      );
      if (saves.length !== 1) throw Error("profile_summary_save_unsupported");
      await account();
      checkPermit();
      saves[0].click();
      return await result("PROFILE_SAVE_ATTEMPTED");
    }
    if (work.operation === "inspect_profile") {
      await account();
      if (request.provider_pdf_observation) {
        const pdf = request.provider_pdf_observation;
        if (
          pdf.kind !== "provider_pdf_digest" ||
          !/^[a-f0-9]{64}$/.test(pdf.sha256) ||
          !Number.isInteger(pdf.byte_count) ||
          pdf.byte_count < 5 ||
          pdf.byte_count > 2000000
        )
          throw Error("provider_saved_resume_download_unverified");
        if (pdf.sha256 !== request.expected_resume_sha256)
          throw Error("provider_saved_resume_differs_from_canonical_pdf");
        safe();
        return await result("PROFILE_VERIFIED", {
          resume_sha256: pdf.sha256,
          resume_bytes: pdf.byte_count,
        });
      }
      const buttons = [
        ...document.querySelectorAll(
          ".section.resume .action-container .download",
        ),
      ].filter(visible);
      if (buttons.length === 1)
        return failure("profile_resume_download_capture_required");
      const links = [...document.querySelectorAll("a[href]")].filter(
        (e) =>
          visible(e) &&
          /^(download(?: resume| cv)?|download your resume)$/i.test(
            clean(e) || e.getAttribute("aria-label") || "",
          ),
      );
      if (links.length !== 1)
        throw Error("profile_resume_download_control_unsupported");
      const url = new URL(links[0].href);
      if (
        url.origin !== location.origin ||
        url.username ||
        url.password ||
        url.hash ||
        !["", "_self"].includes(links[0].target)
      )
        throw Error("profile_resume_download_origin_unsupported");
      // Read only the ordinary UI's explicit same-origin download. Never guess
      // an endpoint, follow redirects or send bytes to the backend/provider.
      const response = await fetch(url.href, {
        method: "GET",
        credentials: "same-origin",
        redirect: "error",
        cache: "no-store",
        signal: AbortSignal.timeout(8000),
      });
      if (
        !response.ok ||
        response.headers.get("content-type")?.split(";")[0] !==
          "application/pdf" ||
        Number(response.headers.get("content-length")) > 2000000
      )
        throw Error("provider_saved_resume_download_unverified");
      const reader = response.body.getReader();
      const chunks = [];
      let size = 0;
      try {
        while (true) {
          const item = await reader.read();
          if (item.done) break;
          size += item.value.length;
          if (size > 2000000) throw Error("provider_saved_resume_too_large");
          chunks.push(item.value);
        }
      } finally {
        await reader.cancel();
      }
      const bytes = new Uint8Array(size);
      let offset = 0;
      for (const chunk of chunks) {
        bytes.set(chunk, offset);
        offset += chunk.length;
      }
      if (new TextDecoder().decode(bytes.slice(0, 5)) !== "%PDF-")
        throw Error("provider_saved_resume_not_pdf");
      const sha = await digest(bytes);
      if (sha !== request.expected_resume_sha256)
        throw Error("provider_saved_resume_differs_from_canonical_pdf");
      safe();
      return await result("PROFILE_VERIFIED", {
        resume_sha256: sha,
        resume_bytes: size,
      });
    }
    if (work.operation === "inspect_application") {
      const s = await snapshot();
      if (s.applied)
        return await result("APPLIED", { title: s.title, company: s.company });
      state.seal = s;
      return await result("NOT_APPLIED", {
        title: s.title,
        company: s.company,
        control_sha256: s.control,
      });
    }
    if (work.operation === "apply") {
      if (state.used || !state.seal || state.documentId !== request.document_id)
        throw Error("single_use_document_admission_required");
      const fresh = await snapshot();
      if (
        fresh.button !== state.seal.button ||
        fresh.control !== state.seal.control ||
        fresh.control !== request.control_sha256
      )
        throw Error("provider_apply_control_changed");
      const expires = Date.parse(request.permit_expires_at);
      if (
        !Number.isFinite(expires) ||
        expires <= Date.now() ||
        expires > Date.now() + 2500
      )
        throw Error("browser_action_permit_expired");
      if (navigator.userActivation.isActive)
        throw Error("unexpected_browser_user_activation");
      safe();
      state.used = true; // Consume BEFORE any handler, including throw/navigation.
      fresh.button.click();
      // Click is reported as an attempt only. Persistent provider history is
      // checked in new documents and transactions; no generic success text.
      return await result("CLICKED", {
        title: fresh.title,
        company: fresh.company,
      });
    }
    if (work.operation === "reconcile_application") {
      await account();
      const links = [
        ...document.querySelectorAll('a[href*="/job-listings-"]'),
      ].filter((e) => {
        try {
          const u = new URL(e.href);
          return (
            visible(e) &&
            u.origin === location.origin &&
            u.pathname.endsWith("-" + work.requisition)
          );
        } catch {
          return false;
        }
      });
      if (links.length !== 1 || clean(links[0]) !== request.expected_title)
        throw Error("exact_application_history_row_required");
      const row = links[0].closest(
        'article,li,tr,[class*="apply-card"],[class*="jobTuple"],[class*="application-card"]',
      );
      const company = clean(
        row?.querySelector(
          '[class*="comp-name"],[class*="compName"],[class*="company"]',
        ),
      );
      if (
        !row ||
        company !== request.expected_company ||
        ![...row.querySelectorAll("span,p,[role=status]")].some(
          (e) => visible(e) && clean(e) === "Application Sent",
        )
      )
        throw Error("provider_application_sent_receipt_missing");
      safe();
      return await result("APPLICATION_SENT", {
        title: request.expected_title,
        company,
      });
    }
    return failure("background_operation_not_supported");
  } catch (error) {
    return failure(
      /^[a-zA-Z][a-zA-Z0-9_]{1,63}$/.test(error.message)
        ? error.message
        : "provider_execution_unconfirmed",
    );
  }
}
