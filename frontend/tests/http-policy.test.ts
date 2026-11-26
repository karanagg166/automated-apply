import { describe, expect, it } from "vitest";
import {
  maximumBodyBytes,
  requiresOwnerApproval,
} from "../src/lib/http-policy";
import { permittedRoute } from "../src/lib/gateway";

describe("shared request security policy", () => {
  const id = "00000000-0000-0000-0000-000000000001";
  it("bounds bodies consistently before forwarding", () => {
    expect(maximumBodyBytes("dashboard/resumes")).toBe(5 * 1024 * 1024);
    expect(maximumBodyBytes("local-agent/chrome")).toBe(256 * 1024);
    expect(maximumBodyBytes(`jobs/${id}/application-preview`)).toBe(65536);
    expect(maximumBodyBytes("application-answers/generate")).toBe(65536);
    expect(maximumBodyBytes("discovery/runs")).toBe(1048576);
  });
  it("signs only exact sensitive owner operations", () => {
    // The legacy browser-assistant routes were retired in Phase 9E.
    expect(
      requiresOwnerApproval(
        `browser-applications/${id}/authorize-submission`,
        "POST",
      ),
    ).toBe(false);
    expect(
      requiresOwnerApproval(
        `application-answers/missing/${id}/approve`,
        "POST",
      ),
    ).toBe(true);
    expect(
      requiresOwnerApproval(`application-answers/missing/${id}/approve`, "GET"),
    ).toBe(false);
    expect(
      requiresOwnerApproval(
        `application-answers/missing/${id}/approve/extra`,
        "POST",
      ),
    ).toBe(false);
  });
  it("retains the closed gateway allowlist", () => {
    // Retired v1 execution routes are no longer proxied (Phase 9E).
    expect(
      permittedRoute(
        `execution/questions/${id}/delivery-reconciliation`,
        "POST",
      ),
    ).toBe(false);
    expect(
      permittedRoute(
        `execution/questions/${id}/delivery-reconciliation`,
        "GET",
      ),
    ).toBe(false);
    expect(
      permittedRoute(
        `execution/questions/${id}/delivery-reconciliation/resend`,
        "POST",
      ),
    ).toBe(false);
    expect(permittedRoute(`application-packets/${id}/tracking`, "PATCH")).toBe(
      true,
    );
    expect(permittedRoute(`application-packets/${id}/tracking`, "POST")).toBe(
      false,
    );
    expect(permittedRoute("../operations/status", "GET")).toBe(false);
    expect(permittedRoute("unlisted", "POST")).toBe(false);
  });
});
