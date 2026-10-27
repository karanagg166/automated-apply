const CONSENT_LABEL_PATTERN =
  /\b(?:consent|agree|agreement|terms(?:\s+and\s+conditions|\s+of\s+service|\s+of\s+use)?|privacy\s*policy|acknowledge|certif(?:y|ication)|attest(?:ation)?|declare|declaration|hereby|true\s+and\s+(?:correct|accurate)|gdpr|data\s+processing|background\s*check|equal\s*opportunity|\beeo\b|\bnda\b|non.?disclosure|authorize\s+background|accuracy\s+of\s+information)\b/i;

export function formErrorMessage(error) {
  if (error?.message === "unsupported_application_form") {
    if (error.manual_reason === "sensitive_control") {
      return "Sensitive fields (such as password, OTP, payment or national ID controls) were detected on this page. Complete this form manually; no fields were changed.";
    }
    if (error.manual_reason === "security_challenge") {
      return "A CAPTCHA or security challenge is active on this page. Complete the challenge and form manually; no fields were changed.";
    }
    if (error.manual_reason === "cross_origin_frame") {
      return "Open the application form itself. This page uses a cross-origin frame that cannot be inspected safely; no fields were changed.";
    }
    if (
      Array.isArray(error.unsupported_controls) &&
      error.unsupported_controls.length
    ) {
      const reasons = [
        ...new Set(
          error.unsupported_controls
            .map((item) => item?.reason)
            .filter(Boolean),
        ),
      ].slice(0, 3);
      if (reasons.length) {
        return `Open the application form itself. Unsupported controls require manual completion (${reasons.join("; ")}); no fields were changed.`;
      }
    }
  }
  return (
    {
      manual_form_not_authorized:
        "Answer filling is disabled in your local installation. Approve the prepared upgrade and manual extension filling first.",
      profile_review_required:
        "Review and save your real profile at http://127.0.0.1:3000/profile first. Confirm your resume and project contributions there, then retry.",
      unsupported_application_form:
        "Open the application form itself. This page may use unsupported fields, frames or a security challenge; no fields were changed.",
      login_required:
        "Sign in yourself, then reopen the application form and retry.",
      page_changed:
        "The page changed. Keep this application tab active and prepare the answers again.",
      dom_changed:
        "The form changed after answers were prepared. Prepare and review fresh answers before filling; no fields were changed.",
      step_changed:
        "The form step changed. Prepare and review fresh answers for this step before filling; no fields were changed.",
      inspect_and_review_first:
        "Prepare and review answers for the current form step before filling.",
      fill_plan_stale:
        "Your saved facts or application changed, or review authorization expired. Prepare and review fresh answers.",
      platform_fill_policy_denied:
        "Filling is disabled for this platform in your owner settings.",
      application_not_eligible:
        "This saved application is closed, already applied to, or has a different destination. Review it in the dashboard.",
      backend_not_ready:
        "Your installed backend does not support this answer workflow yet. The prepared local upgrade must be approved first.",
    }[error?.message] ||
    "Answers are unavailable. Check the local backend and approved profile, then retry. No application was submitted."
  );
}

export function formPlanText(plan) {
  const actionBlocks = (plan?.actions || []).map((action) => {
    const field = plan?.inspection?.fields?.find(
      (item) => item.field_id === action.field_id,
    );
    const title =
      field?.group_label && field?.label && field.group_label !== field.label
        ? `${field.group_label} (${field.label})`
        : field?.label || field?.group_label || "Unlabelled field";
    const isConsent =
      ["checkbox", "radio"].includes(action.kind) &&
      CONSENT_LABEL_PATTERN.test(
        `${field?.group_label || ""} ${field?.label || ""}`,
      );
    const answer = isConsent
      ? "Manual completion required: Consent and legal declarations are never selected automatically"
      : action.needs_input
        ? `NEEDS_INPUT: ${/^[a-f0-9]{32}$/.test(action.missing_input_id || "") ? "Saved question " + action.missing_input_id + " needs your factual input" : "Needs a reviewed fact in your profile"}`
        : action.kind === "file"
          ? "Upload your confirmed PDF yourself"
          : action.value;
    const sources = [
      ...new Set(
        (action.evidence || []).map((source) =>
          source.startsWith("approved_project:")
            ? "Approved project"
            : source.startsWith("candidate_resource:")
              ? "Reviewed profile link or resume"
              : "Reviewed profile",
        ),
      ),
    ];
    const flags = [
      field?.required ? "required" : null,
      field?.invalid ? "validation error on page" : null,
    ].filter(Boolean);
    const suffix = flags.length ? ` (${flags.join(", ")})` : "";
    return `${title}${suffix}\n${answer}\nSource: ${sources.join(", ") || "No verified source"}`;
  });
  const unsupportedBlocks = (plan?.unsupported_controls || []).map((item) => {
    const flags = [
      item?.required ? "required" : null,
      item?.invalid ? "validation error on page" : null,
    ].filter(Boolean);
    const suffix = flags.length ? ` (${flags.join(", ")})` : "";
    return `${item?.label || "Unlabelled control"}${suffix}\nManual completion required: ${item?.reason || "Unsupported control"}\nSource: Manual only`;
  });
  return [...actionBlocks, ...unsupportedBlocks].join("\n\n");
}

export function missingInputLinks(plan) {
  const unique = new Map();
  for (const action of plan?.actions || []) {
    if (
      !action.needs_input ||
      !/^[a-f0-9]{32}$/.test(action.missing_input_id || "")
    )
      continue;
    const field = plan?.inspection?.fields?.find(
      (item) => item.field_id === action.field_id,
    );
    unique.set(action.missing_input_id, {
      id: action.missing_input_id,
      label: field?.group_label || field?.label || "Saved question",
      url: `http://127.0.0.1:3000/profile?missing_input=${action.missing_input_id}`,
    });
  }
  return [...unique.values()];
}
