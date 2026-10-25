// Present only the backend's fixed observation contract, never page/account text.
export function observationMessage(result) {
  if (!result?.ok) {
    return {
      unsupported_portal_page: "Open a supported job portal in the active tab, then check again.",
      session_observation_unavailable: "The page changed or its session could not be checked. Keep the portal tab active and retry.",
      backend_offline: "The local backend is offline. Start it, then retry the session check.",
      backend_timeout: "The local backend timed out. Check the local backend and retry.",
      native_host_timeout: "The native host timed out. Check the local backend and retry.",
      native_host_not_found: "The native host is unavailable. Check the extension installation.",
      native_origin_not_authorized: "This extension installation is not authorized by the native host. Check its stable extension ID.",
      native_origin_denied: "This extension installation is not authorized by the native host. Check its stable extension ID.",
    }[result?.error_code] || "Session check unavailable. Check the local backend and extension connection, then retry.";
  }
  const data = result.data;
  if (data?.api_connected !== false || data?.identity_verified !== false) {
    return "The session check returned an unexpected response. No account connection was verified.";
  }
  const limitation = " Account identity and applicant API access remain unverified.";
  if (data.observation === "signed_in_indicator" && data.state === "browser_session_observed") {
    return "A visible sign-in indicator was observed and saved." + limitation;
  }
  if (data.observation === "login_required") {
    return "A login form is visible. Finish signing in on the official portal, open your account menu, then check again." + limitation;
  }
  if (data.observation === "unverifiable") {
    return "The check reached the local agent, but no supported visible sign-in indicator was found. If you are signed in, open your account menu so Log out is visible, keep it open, and check again. You can also choose manual-only support in Connections Center." + limitation;
  }
  return "No browser sign-in indicator was verified. Check the official portal and try again." + limitation;
}
