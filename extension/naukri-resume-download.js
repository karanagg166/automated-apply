// A bounded MAIN-world observation of the PDF produced by the genuine Download
// control. It never invents a provider endpoint, reads cookies or exports bytes.
// Hooks are restored on every exit. Only the generated PDF download is consumed;
// other page actions retain their original behavior.
export async function captureNaukriResumeDownload(work) {
  const fail = (reason) => ({ kind: "needs_input", reason });
  const safe = () =>
    document.visibilityState === "hidden" &&
    location.href === work.target_url &&
    location.origin === "https://www.naukri.com" &&
    location.pathname === "/mnjuser/profile";
  const visible = (e) => e?.getClientRects().length > 0;
  if (!safe()) return fail("provider_context_changed");
  const sections = [...document.querySelectorAll(".section.resume")].filter(
    visible,
  );
  const controls =
    sections.length === 1
      ? [...sections[0].querySelectorAll(".action-container .download")].filter(
          visible,
        )
      : [];
  if (controls.length !== 1)
    return fail("profile_resume_download_control_unsupported");
  const control = controls[0];
  const originalURL = URL.createObjectURL;
  const originalClick = HTMLAnchorElement.prototype.click;
  const clickDescriptor = Object.getOwnPropertyDescriptor(
    HTMLAnchorElement.prototype,
    "click",
  );
  const originalDispatch = HTMLAnchorElement.prototype.dispatchEvent;
  const dispatchDescriptor = Object.getOwnPropertyDescriptor(
    HTMLAnchorElement.prototype,
    "dispatchEvent",
  );
  const captured = new Map();
  const consumed = new Set();
  let downloadEvent;
  let resolvePDF;
  const downloaded = new Promise((resolve) => {
    resolvePDF = resolve;
  });
  const createURL = function (blob) {
    const url = originalURL.call(this, blob);
    // Providers may label a genuine PDF as octet-stream or omit the MIME type.
    // Its bytes are checked after the exact UI-created download anchor is seen.
    if (blob instanceof Blob) {
      captured.set(url, blob);
    }
    return url;
  };
  const click = function (...args) {
    const blob = captured.get(this.href);
    if (safe() && blob && this.hasAttribute("download")) {
      consumed.add(this.href);
      downloadEvent = "anchor_click";
      resolvePDF(blob);
      return; // Consume this exact UI-created PDF instead of saving a private copy.
    }
    return originalClick.apply(this, args);
  };
  const dispatch = function (event) {
    const blob = captured.get(this.href);
    if (
      safe() &&
      blob &&
      this.hasAttribute("download") &&
      event?.type === "click"
    ) {
      consumed.add(this.href);
      downloadEvent = "anchor_dispatch";
      resolvePDF(blob);
      return true;
    }
    return originalDispatch.call(this, event);
  };
  let timer;
  try {
    URL.createObjectURL = createURL;
    HTMLAnchorElement.prototype.click = click;
    HTMLAnchorElement.prototype.dispatchEvent = dispatch;
    if (
      URL.createObjectURL !== createURL ||
      HTMLAnchorElement.prototype.click !== click ||
      HTMLAnchorElement.prototype.dispatchEvent !== dispatch
    )
      return fail("profile_resume_download_capture_unavailable");
    if (!safe() || !control.isConnected)
      return fail("provider_context_changed");
    control.click(); // Ordinary Download UI, exactly once; no upload or Apply.
    const blob = await Promise.race([
      downloaded,
      new Promise((resolve) => {
        timer = setTimeout(() => resolve(null), 8000);
      }),
    ]);
    if (!blob) return fail("profile_resume_download_pdf_not_observed");
    if (blob.size < 5 || blob.size > 2000000)
      return fail("provider_saved_resume_too_large");
    const bytes = new Uint8Array(await blob.arrayBuffer());
    if (new TextDecoder().decode(bytes.slice(0, 5)) !== "%PDF-")
      return fail("provider_saved_resume_not_pdf");
    const sha = [
      ...new Uint8Array(await crypto.subtle.digest("SHA-256", bytes)),
    ]
      .map((x) => x.toString(16).padStart(2, "0"))
      .join("");
    if (!safe()) return fail("provider_context_changed");
    return {
      kind: "provider_pdf_digest",
      sha256: sha,
      byte_count: bytes.length,
      download_event: downloadEvent,
    };
  } catch {
    return fail("profile_resume_download_capture_failed");
  } finally {
    clearTimeout(timer);
    if (URL.createObjectURL === createURL) URL.createObjectURL = originalURL;
    if (HTMLAnchorElement.prototype.click === click) {
      if (clickDescriptor)
        Object.defineProperty(
          HTMLAnchorElement.prototype,
          "click",
          clickDescriptor,
        );
      else delete HTMLAnchorElement.prototype.click;
    }
    if (HTMLAnchorElement.prototype.dispatchEvent === dispatch) {
      if (dispatchDescriptor)
        Object.defineProperty(
          HTMLAnchorElement.prototype,
          "dispatchEvent",
          dispatchDescriptor,
        );
      else delete HTMLAnchorElement.prototype.dispatchEvent;
    }
    for (const url of consumed) URL.revokeObjectURL(url);
    captured.clear();
  }
}
