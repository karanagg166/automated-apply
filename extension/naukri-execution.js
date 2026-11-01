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
    if (state.adopted || document.visibilityState !== "hidden")
      throw Error("owner_tab_active");
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
            'header [class*="email"], .chip-summary .email-verify, .detail-list .with-cta span.txt[name="Email"], [class*="user-details"] [class*="email"], [class*="profile-details"] [class*="email"], [class*="personal-details"] [class*="email"]',
          ),
        ]
          .filter(visible)
          .map((e) => (e.value || clean(e) || "").trim().toLowerCase())
          .filter((x) => /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(x)),
      ),
    ];
    if (
      emails.length === 0 &&
      ["inspect_application", "apply", "reconcile_application"].includes(
        work.operation,
      )
    ) {
      const proof = request?.account_observation;
      const binding = work.binding;
      const age = Date.now() - Date.parse(proof?.observed_at);
      const keys = [
        "profile_binding_id",
        "profile_version",
        "selection_version",
        "browser_session_id",
        "window_id",
        "tab_id",
      ];
      if (
        proof?.source === "profile_ui" &&
        proof.work_id === work.id &&
        proof.account_sha256 === request.expected_account_sha256 &&
        /^[A-Za-z0-9_-]{16,100}$/.test(proof.profile_document_id || "") &&
        proof.profile_document_id !== state.documentId &&
        binding &&
        typeof binding.profile_binding_id === "string" &&
        typeof binding.browser_session_id === "string" &&
        Number.isInteger(binding.tab_id) &&
        Number.isInteger(binding.window_id) &&
        binding.profile_version >= 1 &&
        binding.selection_version >= 1 &&
        keys.every((key) => proof.binding?.[key] === binding[key]) &&
        Number.isFinite(age) &&
        age >= 0 &&
        age <= 120000
      )
        return proof.account_sha256;
    }
    if (
      emails.length !== 1 ||
      (await hash(emails[0])) !== request?.expected_account_sha256
    )
      throw Error("provider_account_identity_unverified");
    return hash(emails[0]);
  };
  const key = "__automatedApplyNaukriExecutionV1";
  if (!globalThis[key]) {
    globalThis[key] = {
      documentId: crypto.randomUUID(),
      used: false,
      seal: null,
      adopted: false,
    };
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState !== "hidden") globalThis[key].adopted = true;
    });
  }
  const state = globalThis[key];
  const summarySection = () => {
    const headings = [
      ...document.querySelectorAll(
        'h1.section-heading,h2,h3,h4,[class*="widgetTitle"]',
      ),
    ].filter(
      (e) => visible(e) && clean(e)?.toLowerCase() === "profile summary",
    );
    if (headings.length !== 1) return null;
    if (headings[0].matches(".widgetTitle"))
      return headings[0].closest(".card");
    return headings[0].closest(
      '.profileSummary.section,section,[class*="widget"],[class*="card"]',
    );
  };
  const summaryValue = () => {
    const section = summarySection();
    if (section?.querySelector(".widgetHead > .widgetTitle")) {
      const values = [
        ...section.querySelectorAll(".widgetCont > .prefill"),
      ].filter(visible);
      if (
        values.length !== 1 ||
        values[0].querySelector(
          'a.morelink[aria-label="Read more of profile summary"]',
        )
      )
        return undefined;
      const clone = values[0].cloneNode(true);
      for (const link of clone.querySelectorAll("a.morelink")) link.remove();
      return clean(clone);
    }
    if (section?.matches(".profileSummary.section")) {
      const cards = [...section.querySelectorAll(".card-container")].filter(
        visible,
      );
      const values = [
        ...section.querySelectorAll(
          ".card-container .card-details > p.card-sub-heading",
        ),
      ].filter(visible);
      if (cards.length === 1 && values.length === 1) return clean(values[0]);
      if (
        !cards.length &&
        [
          ...section.querySelectorAll(".heading-container.cursor .add-more"),
        ].filter((e) => visible(e) && clean(e) === "Add").length === 1 &&
        section.querySelector(".section-sub-heading")
      )
        return "";
      return undefined;
    }
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
    if (
      work.operation === "inspect_profile_sync" ||
      work.operation === "verify_account"
    ) {
      await account();
      const fields = {};
      const section = summarySection();
      const more =
        section &&
        [
          ...section.querySelectorAll(
            '.widgetCont .prefill a.morelink[aria-label="Read more of profile summary"]',
          ),
        ].filter(visible);
      if (more?.length === 1) {
        safe();
        more[0].click();
        await new Promise((resolve) => {
          const observer = new MutationObserver(() => {
            if (
              !section.contains(more[0]) ||
              more[0].getAttribute("aria-label") !==
                "Read more of profile summary"
            )
              done();
          });
          const timer = setTimeout(done, 1000);
          function done() {
            clearTimeout(timer);
            observer.disconnect();
            resolve();
          }
          observer.observe(section, {
            subtree: true,
            childList: true,
            attributes: true,
          });
          if (
            !section.contains(more[0]) ||
            more[0].getAttribute("aria-label") !==
              "Read more of profile summary"
          )
            done();
        });
        safe();
      }
      const summary = summaryValue();
      if (summary !== undefined) fields.summary = summary;
      const names = [
        ...document.querySelectorAll(
          '[class*="profile-details"] [class*="fullname"],.dashboard-component .hdn > .fullname',
        ),
      ].filter(visible);
      if (names.length === 1) fields.full_name = clean(names[0]);
      if (work.operation === "inspect_profile_sync") {
        const detail = (name) => {
          const values = [
            ...document.querySelectorAll(
              `.dashboard-component .detail-list span.txt[name="${name}"]`,
            ),
          ].filter(visible);
          return values.length === 1 ? clean(values[0]) : undefined;
        };
        const phone = detail("Mobile");
        // A masked phone is unknown, not a conflicting personal fact.
        if (phone && /^\+?[\d\s()-]{7,24}$/.test(phone)) fields.phone = phone;
        const location = detail("Location");
        if (location) fields.location = location;
        const widget = (label) => {
          const titles = [
            ...document.querySelectorAll(".widgetHead > .widgetTitle"),
          ].filter((e) => visible(e) && clean(e)?.toLowerCase() === label);
          return titles.length === 1 ? titles[0].closest(".card") : null;
        };
        const skillsWidget = widget("key skills");
        if (skillsWidget) {
          const chips = [
            ...skillsWidget.querySelectorAll(
              ".widgetCont > .prefill > span.chip",
            ),
          ]
            .filter(visible)
            .map(clean);
          if (
            chips.length &&
            chips.length <= 100 &&
            chips.every((v) => v && v.length <= 200)
          )
            fields.skills = [...new Set(chips)];
          else if (
            !chips.length &&
            [...skillsWidget.querySelectorAll(".widgetCont > .empty")].filter(
              visible,
            ).length === 1
          )
            fields.skills = [];
        }
        for (const [field, title, row] of [
          ["experience", "employment", ".widgetCont .emp-list"],
          ["education", "education", ".widgetCont .edu-list"],
          ["projects", "projects", null],
        ]) {
          const card = widget(title);
          if (!card) continue;
          if (row && [...card.querySelectorAll(row)].some(visible))
            fields[field] = { presence_only: true };
          else if (
            [...card.querySelectorAll(".widgetCont > .empty")].filter(visible)
              .length === 1
          )
            fields[field] = [];
        }
      }
      const extra = { profile_fields: fields };
      if (
        work.operation === "inspect_profile_sync" &&
        request.verify_saved_resume
      ) {
        if (!/^[a-f0-9]{64}$/.test(request.expected_resume_sha256 || ""))
          throw Error("canonical_private_pdf_unavailable_or_invalid");
        const pdf = request.provider_pdf_observation;
        if (!pdf) return failure("profile_resume_download_capture_required");
        if (
          pdf.kind !== "provider_pdf_digest" ||
          pdf.sha256 !== request.expected_resume_sha256 ||
          !Number.isInteger(pdf.byte_count) ||
          pdf.byte_count < 5 ||
          pdf.byte_count > 2000000
        )
          throw Error("provider_saved_resume_differs_from_canonical_pdf");
        extra.resume_sha256 = pdf.sha256;
        extra.resume_bytes = pdf.byte_count;
      }
      return await result("PROFILE_OBSERVED", extra);
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
          (request.previous_summary_reference ?? null) ||
        !request.approved_summary
      )
        throw Error("profile_sync_preimage_changed");
      const edits = [
        ...section.querySelectorAll(
          "button,a,h1.section-heading .new-pencil,.heading-container.cursor .add-more,[role=button][aria-label='Edit profile summary']",
        ),
      ].filter(
        (e) =>
          visible(e) &&
          (/^(Edit|Edit profile summary)$/.test(
            e.getAttribute("aria-label") || clean(e),
          ) ||
            (section.matches(".profileSummary.section") &&
              (e.matches("h1.section-heading .new-pencil") ||
                (e.matches(".add-more") && clean(e) === "Add")))),
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
      // React mutations wake this immediately in an inactive/locked tab. Fixed
      // timer polls can consume the entire permit under Chrome timer throttling.
      const until = async (check) => {
        if (check()) return;
        await new Promise((resolve) => {
          const observer = new MutationObserver(() => {
            if (check()) done();
          });
          const timer = setTimeout(
            done,
            Math.max(0, Date.parse(request.permit_expires_at) - Date.now()),
          );
          function done() {
            clearTimeout(timer);
            observer.disconnect();
            resolve();
          }
          observer.observe(document.body, {
            subtree: true,
            childList: true,
            attributes: true,
          });
          if (check()) done();
        });
        safe();
        checkPermit();
      };
      await until(() =>
        [...document.querySelectorAll("textarea")].some(visible),
      );
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
        (label !== "Profile summary" &&
          !(
            section.matches(".profileSummary.section") &&
            textarea.id === "summary" &&
            textarea.name === "summary" &&
            clean(
              textarea.closest("[role=dialog]")?.querySelector("h1"),
            )?.toLowerCase() === "profile summary"
          )) ||
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
      await until(() =>
        [...scope.querySelectorAll("button")].some(
          (e) => visible(e) && clean(e) === "Save" && !e.disabled,
        ),
      );
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
          '.section.resume .action-container .download, #lazyAttachCV.card .attachCV .cvPreview [role="button"][aria-label="Download resume"][data-title="download-resume"]',
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
      // A click can asynchronously reveal a questionnaire. It must stay in its
      // original owned tab; do not close it and mistake the click for a receipt.
      for (let attempt = 0; attempt < 24; attempt++) {
        safe();
        if (
          [...document.querySelectorAll(".chatbot_DrawerContentWrapper")].some(
            visible,
          )
        )
          return await result("QUESTIONNAIRE", {
            title: fresh.title,
            company: fresh.company,
          });
        if (
          [
            ...document.querySelectorAll(
              '#job_header button,[class*="jd-header"] button',
            ),
          ].some(
            (e) => visible(e) && /^(applied|already applied)$/i.test(clean(e)),
          )
        )
          break;
        await new Promise((resolve) => setTimeout(resolve, 100));
      }
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
