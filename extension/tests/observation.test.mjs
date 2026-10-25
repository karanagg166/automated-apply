import test from "node:test";
import assert from "node:assert/strict";
import { observationMessage } from "../observation.js";

const response = (observation, state = "owner_action_required") => ({
  ok: true, data: { observation, state, api_connected: false, identity_verified: false },
});
test("unverifiable portal reports a successful check without claiming a login", () => {
  const message = observationMessage(response("unverifiable"));
  assert.match(message, /reached the local agent/);
  assert.match(message, /open your account menu/);
  assert.match(message, /manual-only/);
  assert.match(message, /identity and applicant API access remain unverified/);
  assert.doesNotMatch(message, /owner_action_required|undefined/);
});
test("visible login form and sign-in indicator have distinct bounded messages", () => {
  assert.match(observationMessage(response("login_required")), /login form is visible/);
  assert.match(observationMessage(response("signed_in_indicator", "browser_session_observed")), /indicator was observed and saved/);
  assert.doesNotMatch(observationMessage(response("signed_in_indicator")), /indicator was observed and saved/);
});
test("malformed or API-connected results cannot become verified browser evidence", () => {
  for (const result of [undefined, { ok: true }, { ok: true, data: { api_connected: true } }]) {
    assert.doesNotMatch(observationMessage(result), /indicator was observed and saved|undefined/);
  }
  const result = response("signed_in_indicator", "browser_session_observed");
  result.data.identity_verified = true;
  assert.match(observationMessage(result), /unexpected response/);
});
test("errors are actionable without rendering arbitrary native or page text", () => {
  assert.match(observationMessage({ ok: false, error_code: "backend_offline" }), /backend is offline/);
  assert.match(observationMessage({ ok: false, error_code: "backend_timeout" }), /timed out/);
  assert.match(observationMessage({ ok: false, error_code: "native_host_timeout" }), /timed out/);
  assert.match(observationMessage({ ok: false, error_code: "native_host_not_found" }), /native host is unavailable/);
  assert.match(observationMessage({ ok: false, error_code: "native_origin_not_authorized" }), /not authorized by the native host/);
  assert.match(observationMessage({ ok: false, error_code: "native_origin_denied" }), /not authorized by the native host/);
  assert.match(observationMessage({ ok: false, error_code: "unsupported_portal_page" }), /supported job portal/);
  const result = { ok: false, error_code: "private account text must not be shown" };
  assert.doesNotMatch(observationMessage(result), /private account/);
});
