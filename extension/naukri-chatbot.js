// Ordinary UI adapter for the genuine retained Naukri chatbot structure.
// No endpoints, keyboard, clipboard, focus, chooser or fabricated user activation.
export async function naukriChatbot(request) {
  const fail = (reason) => ({ kind: "needs_input", reason });
  const key = "__automatedApplyNaukriChatbotV1";
  if (!globalThis[key]) {
    const state = {
      documentId: crypto.randomUUID(),
      used: new Set(),
      adopted: false,
    };
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState !== "hidden") state.adopted = true;
    });
    globalThis[key] = state;
  }
  const state = globalThis[key];
  const visible = (e) =>
    e?.isConnected &&
    e.getClientRects().length > 0 &&
    getComputedStyle(e).visibility !== "hidden";
  const clean = (e) => e?.textContent?.replace(/\s+/g, " ").trim();
  const hash = async (value) =>
    [
      ...new Uint8Array(
        await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value)),
      ),
    ]
      .map((x) => x.toString(16).padStart(2, "0"))
      .join("");
  const safe = () => {
    if (state.adopted || document.visibilityState !== "hidden")
      throw Error("owner_tab_active");
    if (
      location.href !== request.url ||
      location.origin !== "https://www.naukri.com" ||
      !location.pathname.endsWith("-" + request.requisition)
    )
      throw Error("provider_context_changed");
    if (
      /captcha|verify (?:that )?you are human|unusual traffic|access denied|too many requests/i.test(
        document.body?.innerText || "",
      ) ||
      [
        ...document.querySelectorAll(
          'iframe[src*="captcha"],input[type=password],input[autocomplete="one-time-code"]',
        ),
      ].some(visible)
    )
      throw Error("provider_challenge_requires_owner");
  };
  const snapshot = async () => {
    safe();
    const drawers = [
      ...document.querySelectorAll(".chatbot_DrawerContentWrapper"),
    ].filter(visible);
    if (drawers.length !== 1) throw Error("questionnaire_drawer_unrecognized");
    const drawer = drawers[0];
    if (
      drawer.closest(
        '#job_header,#job_description,[class*="job-desc"],[class*="jobDesc"]',
      )
    )
      throw Error("questionnaire_scope_unrecognized");
    const messages = [
      ...drawer.querySelectorAll(".chatbot_MessageContainer .botItem .botMsg"),
    ].filter(visible);
    const question = clean(messages.at(-1));
    if (!question || question.length > 2000)
      throw Error("questionnaire_question_unrecognized");
    const visibleChips = [
      ...drawer.querySelectorAll(".chipsContainer .chatbot_Chip"),
    ].filter(visible);
    const editors = [
      ...drawer.querySelectorAll('.textArea[contenteditable="true"]'),
    ].filter(visible);
    // The real text form has a separate optional Skip chip beside its editor.
    // That navigation control is not the set of permitted factual answers.
    // Only this exact observed combination is supported; real choice chips keep
    // their existing exact-choice handling and step seal.
    const textWithSkip =
      editors.length === 1 &&
      visibleChips.length === 1 &&
      /^skip this question$/i.test(clean(visibleChips[0]));
    const chips = textWithSkip ? [] : visibleChips;
    // Genuine single-select radio groups are siblings after the current bot
    // message. Older groups before that message are not current controls.
    const lastMessage = messages.at(-1);
    const panels = [
      ...drawer.querySelectorAll(".singleselect-radiobutton"),
    ].filter(
      (e) =>
        visible(e) &&
        e.parentElement === lastMessage?.closest(".chatbot_MessageContainer") &&
        lastMessage.compareDocumentPosition(e) &
          Node.DOCUMENT_POSITION_FOLLOWING,
    );
    const radios =
      panels.length === 1
        ? [...panels[0].querySelectorAll('input.ssrc__radio[type="radio"]')]
        : [];
    const radioLabels = radios.map((e) =>
      [...(e.labels || [])].filter(
        (label) =>
          panels[0].contains(label) &&
          label.classList.contains("ssrc__label") &&
          visible(label),
      ),
    );
    if (
      panels.length > 1 ||
      (panels.length &&
        (!radios.length ||
          chips.length ||
          editors.length ||
          radios.some(
            (e, i) =>
              e.name !== "radio-button" ||
              e.getAttribute("data-val") !== "pb" ||
              e.getAttribute("data-index") !== String(i) ||
              !e.id ||
              radioLabels[i].length !== 1 ||
              radioLabels[i][0].control !== e ||
              clean(radioLabels[i][0]) !== e.value,
          )))
    )
      throw Error("questionnaire_radio_controls_unrecognized");
    const options = radios.length
      ? radios.map((e) => e.value)
      : chips.map(clean);
    const upload = [
      ...drawer.querySelectorAll('input.chatbot_Uploader[type="file"]'),
    ];
    const kind =
      upload.length && options.some((s) => /^upload (?:resume|cv)$/i.test(s))
        ? "file"
        : chips.length || radios.length
          ? "choice"
          : editors.length === 1
            ? "text"
            : null;
    if (
      !kind ||
      options.length > 50 ||
      options.some((s) => !s || s.length > 160) ||
      new Set(options).size !== options.length
    )
      throw Error("questionnaire_controls_unrecognized");
    const signature = await hash(
      JSON.stringify([location.href, question, kind, options]),
    );
    return {
      drawer,
      question,
      chips,
      radios,
      radioLabels: radioLabels.map((labels) => labels[0]),
      options,
      editor: editors[0],
      kind,
      signature,
    };
  };
  try {
    const current = await snapshot();
    const observation = {
      kind: "questionnaire",
      document_id: state.documentId,
      step_sha256: current.signature,
      question: current.question,
      answer_kind: current.kind,
      options: current.options,
      max_characters: 4000,
    };
    if (request.operation === "inspect") return observation;
    if (request.operation !== "answer")
      return fail("questionnaire_operation_unsupported");
    if (
      request.document_id !== state.documentId ||
      request.step_sha256 !== current.signature ||
      state.used.has(current.signature)
    )
      return fail("questionnaire_step_changed_or_consumed");
    const expires = Date.parse(request.permit_expires_at);
    if (
      !Number.isFinite(expires) ||
      expires <= Date.now() ||
      expires > Date.now() + 2500 ||
      navigator.userActivation.isActive
    )
      return fail("questionnaire_action_permit_expired");
    if (current.kind === "file")
      return fail("questionnaire_resume_attachment_requires_supported_upload");
    if (
      typeof request.answer !== "string" ||
      !request.answer.trim() ||
      request.answer.length > 4000
    )
      return fail("questionnaire_answer_invalid");
    if (
      /\b(?:email|e-mail|login|password|otp|consent|terms and conditions)\b/i.test(
        current.question,
      )
    )
      return fail("questionnaire_identity_or_consent_requires_owner");
    if (current.kind === "choice") {
      if (!current.options.includes(request.answer))
        return fail("questionnaire_exact_choice_required");
      if (current.radios.length) {
        const index = current.options.indexOf(request.answer);
        const radio = current.radios[index];
        if (current.radios.some((e) => e.checked))
          return fail("questionnaire_existing_value_preserved");
        if (radio.disabled || radio.getAttribute("aria-disabled") === "true")
          return fail("questionnaire_control_disabled");
        safe();
        state.used.add(current.signature); // Radio handlers may submit immediately.
        current.radioLabels[index].click();
        for (let i = 0; i < 8; i++) {
          safe();
          // A radio can advance immediately, or require the current scoped Save.
          // Never click a Save belonging to a later question or the job header.
          if (
            !current.drawer.isConnected ||
            clean(
              [...current.drawer.querySelectorAll(".botItem .botMsg")]
                .filter(visible)
                .at(-1),
            ) !== current.question
          )
            break;
          const fresh = await snapshot();
          if (fresh.signature !== current.signature) break;
          if (
            fresh.radios[index] !== radio ||
            !radio.checked ||
            current.radios.filter((e) => e.checked).length !== 1
          )
            return fail("questionnaire_radio_selection_not_confirmed");
          const sends = [...fresh.drawer.querySelectorAll(".send")].filter(
            (e) =>
              visible(e) &&
              !e.classList.contains("disabled") &&
              !e.hasAttribute("disabled") &&
              e.getAttribute("aria-disabled") !== "true" &&
              /^(save|send|next|continue)$/i.test(clean(e)),
          );
          if (sends.length === 1) {
            safe();
            sends[0].click();
            break;
          }
          if (sends.length > 1)
            return fail("questionnaire_send_control_not_confirmed");
          if (i === 7) return fail("questionnaire_send_control_not_confirmed");
          await new Promise((resolve) => setTimeout(resolve, 100));
        }
        return {
          kind: "questionnaire_answer_attempted",
          document_id: state.documentId,
          step_sha256: current.signature,
          submitted: false,
        };
      }
      const chip = current.chips[current.options.indexOf(request.answer)];
      if (
        chip.hasAttribute("disabled") ||
        chip.getAttribute("aria-disabled") === "true" ||
        chip.classList.contains("disabled")
      )
        return fail("questionnaire_control_disabled");
      safe();
      state.used.add(current.signature); // Before a choice handler can submit.
      chip.click();
    } else {
      if (
        current.editor.textContent.trim() &&
        current.editor.textContent !== request.answer
      )
        return fail("questionnaire_existing_value_preserved");
      safe();
      state.used.add(current.signature); // Input handlers can save/submit too.
      current.editor.textContent = request.answer;
      current.editor.dispatchEvent(
        new InputEvent("input", {
          bubbles: true,
          inputType: "insertText",
          data: request.answer,
        }),
      );
      for (let i = 0; i < 8; i++) {
        safe();
        const fresh = await snapshot();
        if (
          fresh.signature !== current.signature ||
          fresh.editor !== current.editor ||
          current.editor.textContent !== request.answer
        )
          return fail("questionnaire_changed_after_input");
        const sends = [...fresh.drawer.querySelectorAll(".send")].filter(
          (e) =>
            visible(e) &&
            !e.classList.contains("disabled") &&
            !e.hasAttribute("disabled") &&
            e.getAttribute("aria-disabled") !== "true" &&
            /^(save|send|next|continue)$/i.test(clean(e)),
        );
        if (sends.length === 1) {
          safe();
          sends[0].click();
          return {
            kind: "questionnaire_answer_attempted",
            document_id: state.documentId,
            step_sha256: current.signature,
            submitted: false,
          };
        }
        await new Promise((resolve) => setTimeout(resolve, 100));
      }
      return fail("questionnaire_send_control_not_confirmed");
    }
    return {
      kind: "questionnaire_answer_attempted",
      document_id: state.documentId,
      step_sha256: current.signature,
      submitted: false,
    };
  } catch (error) {
    return fail(
      /^[A-Za-z][A-Za-z0-9_]{1,63}$/.test(error.message)
        ? error.message
        : "questionnaire_observation_failed",
    );
  }
}
