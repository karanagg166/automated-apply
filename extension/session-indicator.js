// A fixed-enum DOM observation; no text, form values or account identity leave the page.
export function sessionIndicator() {
  const visible = element => !!element?.getClientRects().length &&
    (typeof element.checkVisibility !== "function" || element.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true }));
  const linkedLogout = [...document.querySelectorAll('a[href*="logout"],a[href*="sign_out"],button[data-action="logout"]')].some(visible);
  // Naukri and other portals use ordinary links/buttons whose URLs do not
  // mention logout. Match only the exact visible action label, never page prose.
  const labelledLogout = [...document.querySelectorAll('a,button,[role="button"],[role="menuitem"]')].slice(0, 500).some(element => {
    if (!visible(element)) return false;
    const label = (element.getAttribute?.("aria-label") || element.innerText || "").trim();
    return /^(?:log\s*out|sign\s*out)$/i.test(label);
  });
  const signedIn = linkedLogout || labelledLogout;
  const password = [...document.querySelectorAll('input[type="password"]')].some(visible);
  return signedIn && !password ? "signed_in_indicator" : password && !signedIn ? "login_required" : "unverifiable";
}
