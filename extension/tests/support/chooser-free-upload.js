// Laboratory-only browser function. Never shipped by extension/build.mjs.
// No native chooser, private endpoint, installed profile or live provider access.
export async function chooserFreeUploadProbe(request) {
  const result = (state, reason, extra = {}) => ({
    state,
    reason,
    application_recorded: false,
    scope: "fictional_browser_probe_only",
    ...extra,
  });
  if (
    location.origin !== "http://127.0.0.1:17351" ||
    document.querySelector('meta[name="fictional-upload-probe"]')?.content !==
      "true"
  )
    return result("BLOCKED_PLATFORM", "fixture_only");
  const binding = globalThis.__fictionalUploadBinding;
  const matches = () =>
    binding &&
    [
      "profile",
      "window",
      "tab",
      "session",
      "document",
      "requisition",
      "employer",
      "resumeRevision",
    ].every((key) => binding[key] === request.binding?.[key]) &&
    location.href === binding.url &&
    document.querySelector("main")?.dataset.requisition ===
      binding.requisition &&
    document.querySelector("main")?.dataset.employer === binding.employer;
  if (!matches()) return result("NEEDS_INPUT", "binding_changed");
  if (binding.consumed)
    return result("SUBMISSION_UNKNOWN", "attempt_already_consumed");
  const resume = request.resume;
  if (resume?.type !== "application/pdf")
    return result("NEEDS_INPUT", "pdf_type_required");
  let bytes;
  try {
    bytes = Uint8Array.from(atob(resume.base64), (c) => c.charCodeAt(0));
  } catch {
    return result("NEEDS_INPUT", "pdf_bytes_invalid");
  }
  if (!bytes.length || bytes.length > 2 * 1024 * 1024)
    return result("NEEDS_INPUT", "pdf_size_invalid");
  if (new TextDecoder().decode(bytes.slice(0, 5)) !== "%PDF-")
    return result("NEEDS_INPUT", "pdf_header_invalid");
  const actualHash = [
    ...new Uint8Array(await crypto.subtle.digest("SHA-256", bytes)),
  ]
    .map((c) => c.toString(16).padStart(2, "0"))
    .join("");
  if (actualHash !== binding.resumeSha256 || actualHash !== resume.sha256)
    return result("NEEDS_INPUT", "canonical_pdf_changed");
  if (!matches()) return result("NEEDS_INPUT", "binding_changed");
  const scopes = document.querySelectorAll(
    '[role="dialog"][aria-label="Application questions"]',
  );
  if (scopes.length !== 1)
    return result("NEEDS_INPUT", "application_scope_ambiguous");
  const scope = scopes[0];
  const buttons = [...scope.querySelectorAll("button")].filter(
    (el) => el.textContent.trim() === "Upload Resume" && !el.disabled,
  );
  if (buttons.length !== 1)
    return result("NEEDS_INPUT", "upload_control_ambiguous");
  const originalInputs = scope.querySelectorAll('input[type="file"]');
  if (originalInputs.length > 1 || originalInputs[0]?.files.length)
    return result("NEEDS_INPUT", "existing_or_ambiguous_attachment");
  if (navigator.userActivation.isActive)
    return result("NEEDS_INPUT", "native_chooser_risk_from_user_activation");
  // Admission is consumed BEFORE ordinary UI initialization. The real worker
  // needs an equivalent durable server fence; this in-world marker is only a probe.
  binding.consumed = true;
  buttons[0].click();
  if (!matches() || !scope.isConnected)
    return result(
      "SUBMISSION_UNKNOWN",
      "navigation_or_binding_changed_after_initialization",
    );
  const inputs = scope.querySelectorAll('input[type="file"]');
  if (
    inputs.length !== 1 ||
    inputs[0].files.length ||
    (originalInputs.length && originalInputs[0] !== inputs[0])
  )
    return result(
      "SUBMISSION_UNKNOWN",
      "upload_control_changed_after_initialization",
    );
  const input = inputs[0];
  const transfer = new DataTransfer();
  transfer.items.add(
    new File([bytes], "resume.pdf", { type: "application/pdf" }),
  );
  input.files = transfer.files;
  input.dispatchEvent(new Event("change", { bubbles: true }));
  for (let check = 0; check < 10; check++) {
    if (!matches() || !scope.isConnected)
      return result(
        "SUBMISSION_UNKNOWN",
        "navigation_or_binding_changed_after_selection",
      );
    const error = scope.querySelector('[role="alert"]')?.textContent || "";
    if (/file upload was unsuccessful/i.test(error))
      return result("NEEDS_INPUT", "upload_failed_no_automatic_retry");
    if (
      scope.querySelector('[role="status"]')?.textContent === "Resume retained"
    )
      return result("VERIFYING", "attachment_retained_in_fixture_ui", {
        bytes: bytes.length,
      });
    await new Promise((resolve) => setTimeout(resolve, 20));
  }
  return result("SUBMISSION_UNKNOWN", "attachment_outcome_unconfirmed");
}
