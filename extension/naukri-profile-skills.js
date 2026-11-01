// Observed Naukri keySkillsForm. Only verified additions; no focus, keyboard,
// clipboard, private endpoint, hidden-value assignment or chip removal.
export async function executeNaukriSkills(work) {
  const failure = (reason) => ({ kind: "needs_input", reason });
  const request = work.execution;
  const base = "https://www.naukri.com/mnjuser/profile";
  const visible = (e) =>
    e?.getClientRects().length > 0 &&
    getComputedStyle(e).visibility !== "hidden";
  const text = (e) => e?.textContent?.replace(/\s+/g, " ").trim();
  const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
  const hash = async (value) =>
    [
      ...new Uint8Array(
        await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value)),
      ),
    ]
      .map((x) => x.toString(16).padStart(2, "0"))
      .join("");
  const key = "__automatedApplyNaukriSkillsV1";
  const page = globalThis.__automatedApplyNaukriExecutionV1;
  const pending = () => ({ kind: "profile_skills_prepare_pending" });
  try {
    if (
      work.operation !== "sync_profile" ||
      request?.sync_field !== "skills" ||
      work.target_url !== base
    )
      throw Error("profile_skills_scope_required");
    if (
      !page ||
      page.documentId !== request.document_id ||
      page.adopted ||
      document.visibilityState !== "hidden"
    )
      throw Error("profile_skills_document_or_owner_changed");
    if (
      !Number.isFinite(Date.parse(work.lease_until)) ||
      Date.parse(work.lease_until) <= Date.now()
    )
      throw Error("profile_skills_lease_expired");
    const safe = () => {
      if (page.adopted || document.visibilityState !== "hidden")
        throw Error("owner_tab_active");
      const own = globalThis[key];
      if (
        location.href !== base &&
        !(own?.opened && location.href === base + "?action=modalOpen")
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
      safe();
      const emails = [
        ...new Set(
          [
            ...document.querySelectorAll(
              'header [class*="email"], .chip-summary .email-verify, .detail-list .with-cta span.txt[name="Email"], [class*="user-details"] [class*="email"], [class*="profile-details"] [class*="email"], [class*="personal-details"] [class*="email"]',
            ),
          ]
            .filter(visible)
            .map((e) => (e.value || text(e) || "").trim().toLowerCase())
            .filter((x) => /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(x)),
        ),
      ];
      if (
        emails.length !== 1 ||
        (await hash(emails[0])) !== request.expected_account_sha256
      )
        throw Error("provider_account_identity_unverified");
    };
    const report = async (state, fields = {}) => ({
      kind: "execution_observation",
      observed_url: base,
      requisition: work.requisition,
      execution: {
        state,
        document_id: page.documentId,
        account_sha256: request.expected_account_sha256,
        evidence_sha256: await hash(JSON.stringify([state, fields])),
        profile_fields: fields,
      },
    });
    await account();
    safe();
    let state = globalThis[key];
    if (!state) {
      if (
        request.sync_phase !== "prepare" ||
        !Array.isArray(request.skills_before) ||
        !Array.isArray(request.skills_additions) ||
        !request.skills_additions.length
      )
        throw Error("profile_skills_preparation_required");
      const sections = [
        ...document.querySelectorAll("#lazyKeySkills .card"),
      ].filter(visible);
      if (sections.length !== 1)
        throw Error("profile_skills_section_unsupported");
      const before = [
        ...sections[0].querySelectorAll(".widgetCont > .prefill > span.chip"),
      ]
        .filter(visible)
        .map(text);
      const edits = [
        ...sections[0].querySelectorAll(
          '[role=button][aria-label="Edit key skills"]',
        ),
      ].filter(visible);
      if (
        !same(before, request.skills_before) ||
        edits.length !== 1 ||
        [...document.querySelectorAll(".lightbox.model_open")].some(visible)
      )
        throw Error("profile_skills_preimage_or_editor_changed");
      state = {
        work_id: work.id,
        before,
        additions: request.skills_additions,
        next: 0,
        added: [],
        pending: null,
        opened: true,
        openedAt: Date.now(),
        prepared: false,
        saved: false,
      };
      globalThis[key] = state; // Intent before the ordinary editor-opening click.
      edits[0].click();
      return pending();
    }
    if (
      state.work_id !== work.id ||
      !same(state.before, request.skills_before) ||
      !same(state.additions, request.skills_additions)
    )
      throw Error("profile_skills_work_context_changed");
    const forms = [
      ...document.querySelectorAll(
        '.keySkillsEdit.model_open form[name="keySkillsForm"]',
      ),
    ].filter(visible);
    if (
      !forms.length &&
      request.sync_phase === "prepare" &&
      Date.now() - state.openedAt <= 3000
    )
      return pending();
    if (forms.length !== 1) throw Error("profile_skills_editor_unsupported");
    const form = forms[0];
    const inputs = [...form.querySelectorAll("input,select,textarea")].filter(
      visible,
    );
    const input = form.querySelector("#keySkillSugg");
    if (inputs.length !== 1 || inputs[0] !== input)
      throw Error("profile_skills_input_count_or_identity_changed");
    if (
      input.type !== "text" ||
      input.getAttribute("aria-label") !== "Add skills"
    )
      throw Error("profile_skills_input_type_or_label_changed");
    // React can mount the input before the suggestor assigns its combobox role.
    // Only this recognized, empty control may wait; it cannot fill or Save yet.
    if (input.getAttribute("role") !== "combobox") {
      if (
        input.getAttribute("role") === null &&
        !input.value &&
        request.sync_phase === "prepare" &&
        Date.now() - state.openedAt <= 3000
      )
        return pending();
      throw Error("profile_skills_combobox_not_initialized");
    }
    const chips = () =>
      [
        ...form.querySelectorAll(
          ".keySkillSuggCont .chipsContainer > .chip > .tagTxt",
        ),
      ].map(text);
    const current = chips();
    if (request.sync_phase === "save") {
      if (
        !state.prepared ||
        state.saved ||
        state.pending ||
        input.value ||
        !same(current, request.prepared_skills) ||
        !same(current, [...state.before, ...state.added])
      )
        throw Error("profile_skills_prepared_value_changed");
      const saves = [...form.querySelectorAll("button#saveKeySkills")].filter(
        (e) =>
          visible(e) &&
          !e.disabled &&
          e.type === "button" &&
          text(e) === "Save",
      );
      if (saves.length !== 1 || text(form.querySelector("#chipsVal_err")))
        throw Error("profile_skills_save_unsupported");
      await account();
      safe();
      const expires = Date.parse(request.permit_expires_at);
      if (
        !Number.isFinite(expires) ||
        expires <= Date.now() ||
        expires > Date.now() + 2500
      )
        throw Error("browser_action_permit_expired");
      state.saved = true; // An uncertain click is never repeated, including after reconstruction.
      saves[0].click();
      return await report("PROFILE_SAVE_ATTEMPTED");
    }
    if (request.sync_phase !== "prepare" || state.saved)
      throw Error("profile_skills_phase_changed");
    if (state.pending) {
      const expected = [...state.before, ...state.added, state.pending.value];
      if (same(current, expected) && input.value === "") {
        state.added.push(state.pending.value);
        state.pending = null;
      } else {
        if (!same(current, [...state.before, ...state.added]))
          throw Error("profile_skills_existing_chips_changed");
        if (Date.now() - state.pending.at > 3000)
          throw Error("profile_skills_addition_unconfirmed_no_save");
        return pending();
      }
    }
    if (!same(chips(), [...state.before, ...state.added]) || input.value)
      throw Error("profile_skills_existing_chips_changed");
    if (
      !Number.isInteger(input.maxLength) ||
      input.maxLength < 0 ||
      input.maxLength > 250
    )
      throw Error("profile_skills_input_capacity_unrecognized");
    while (state.next < state.additions.length) {
      const value = state.additions[state.next++];
      if (typeof value !== "string" || !value.trim() || /[,\r\n]/.test(value))
        throw Error("profile_skills_approved_value_invalid");
      if (value.length > input.maxLength) continue;
      safe();
      state.pending = { value, at: Date.now() }; // Before the supported blur conversion.
      Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype,
        "value",
      ).set.call(input, value);
      input.dispatchEvent(new Event("input", { bubbles: true }));
      input.dispatchEvent(new Event("change", { bubbles: true }));
      // Actual provider UI creates a custom chip on blur. Dispatching the DOM
      // event neither focuses another element nor uses the owner's keyboard.
      input.dispatchEvent(new FocusEvent("blur", { bubbles: true }));
      return pending();
    }
    if (!state.added.length)
      throw Error("profile_skills_no_addition_within_provider_capacity");
    state.prepared = true;
    return await report("PROFILE_SKILLS_PREPARED", { skills: chips() });
  } catch (error) {
    return failure(
      /^[a-z][a-z0-9_]{1,80}$/.test(error.message)
        ? error.message
        : "profile_skills_unsupported",
    );
  }
}
