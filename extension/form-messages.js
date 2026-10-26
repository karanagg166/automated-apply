export function formErrorMessage(error) {
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
      fill_plan_stale:
        "Your saved facts or application changed. Prepare and review fresh answers.",
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
  return plan.actions
    .map((action) => {
      const field = plan.inspection.fields.find(
        (item) => item.field_id === action.field_id,
      );
      const answer = action.needs_input
        ? "Needs a reviewed fact in your profile"
        : action.kind === "file"
          ? "Upload your confirmed PDF yourself"
          : action.value;
      const sources = [
        ...new Set(
          action.evidence.map((source) =>
            source.startsWith("approved_project:")
              ? "Approved project"
              : source.startsWith("candidate_resource:")
                ? "Reviewed profile link or resume"
                : "Reviewed profile",
          ),
        ),
      ];
      return `${field?.label || "Unlabelled field"}${field?.required ? " (required)" : ""}\n${answer}\nSource: ${sources.join(", ") || "No verified source"}`;
    })
    .join("\n\n");
}
