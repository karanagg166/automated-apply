// @vitest-environment node
import { beforeEach, describe, expect, it } from "vitest";
import { scryptSync } from "node:crypto";
import {
  allowedRequest,
  allowLogin,
  csrfFor,
  issueSession,
  validCsrf,
  validSession,
  verifyPassword,
} from "@/lib/security";
import { permittedRoute } from "@/lib/gateway";
it("limits answer reuse routes to saved drafts and explicit approval operations", () => {
  const id = "11111111-1111-4111-8111-111111111111";
  expect(permittedRoute("application-answers/drafts", "GET")).toBe(true);
  expect(
    permittedRoute(`application-answers/drafts/${id}/approve-reuse`, "POST"),
  ).toBe(true);
  expect(
    permittedRoute(`application-answers/drafts/${id}/approve-reuse`, "GET"),
  ).toBe(false);
  expect(
    permittedRoute(`application-answers/drafts/${id}/execute`, "POST"),
  ).toBe(false);
  expect(permittedRoute("application-answers/generate", "POST")).toBe(false);
});
it("limits resume sync proxy routes to exact owner operations", () => {
  const id = "11111111-1111-4111-8111-111111111111";
  expect(permittedRoute("dashboard/resume-sync", "GET")).toBe(true);
  expect(permittedRoute("dashboard/resume-sync/source", "PUT")).toBe(true);
  expect(permittedRoute("dashboard/resume-sync/sync", "POST")).toBe(true);
  expect(
    permittedRoute(`dashboard/resume-sync/versions/${id}/review`, "GET"),
  ).toBe(true);
  expect(
    permittedRoute(`dashboard/resume-sync/versions/${id}/approve`, "POST"),
  ).toBe(true);
  expect(permittedRoute("dashboard/resume-sync/sync", "GET")).toBe(false);
  expect(
    permittedRoute(`dashboard/resume-sync/versions/${id}/approve`, "GET"),
  ).toBe(false);
  expect(permittedRoute("dashboard/resume-sync/../../operations", "POST")).toBe(
    false,
  );
});
beforeEach(() => {
  process.env.FRONTEND_ORIGIN = "https://workspace.example.org";
  process.env.FRONTEND_SESSION_SECRET =
    "fictional-test-session-secret-not-for-real-use";
  delete process.env.FRONTEND_LOCAL_HTTP;
});
describe("single-owner boundary", () => {
  it("rejects tampering, expired cookies and unauthenticated requests", () => {
    const token = issueSession(100000);
    expect(validSession(token, 100001)).toBe(true);
    expect(validSession(token + "x", 100001)).toBe(false);
    expect(validSession(token, 100000 + 9 * 3600000)).toBe(false);
    expect(validSession(undefined)).toBe(false);
  });
  it("binds CSRF proof to this session", () => {
    const a = issueSession(),
      b = issueSession();
    expect(validCsrf(a, csrfFor(a))).toBe(true);
    expect(validCsrf(b, csrfFor(a))).toBe(false);
    expect(validCsrf(a, null)).toBe(false);
  });
  it.each([
    "https://evil.example",
    "null",
    "https://workspace.example.org.evil.com",
  ])("rejects cross-origin mutation %s", (origin) => {
    const request = new Request("https://workspace.example.org/api/auth", {
      method: "POST",
      headers: { host: "workspace.example.org", origin },
    });
    expect(allowedRequest(request, true)).toBe(false);
  });
  it("requires exact host and origin for mutations", () => {
    expect(
      allowedRequest(
        new Request("https://workspace.example.org/api/auth", {
          method: "POST",
          headers: {
            host: "workspace.example.org",
            origin: "https://workspace.example.org",
          },
        }),
        true,
      ),
    ).toBe(true);
    expect(
      allowedRequest(
        new Request("https://workspace.example.org/api/auth", {
          headers: { host: "evil.example" },
        }),
      ),
    ).toBe(false);
  });
  it("verifies a salted passphrase without a client secret", () => {
    const salt = "abcdef0123456789abcdef0123456789"; // pragma: allowlist secret — fixed test salt
    process.env.FRONTEND_PASSWORD_HASH = `${salt}:${scryptSync("fictional password", salt, 64).toString("hex")}`;
    expect(verifyPassword("fictional password")).toBe(true);
    expect(verifyPassword("incorrect")).toBe(false);
  });
  it("accepts a standalone bind address only with the configured external host and origin", () => {
    const request = (url: string, host = "workspace.example.org") =>
      new Request(url, {
        method: "POST",
        headers: {
          host,
          origin: "https://workspace.example.org",
          "x-forwarded-host": "workspace.example.org",
        },
      });
    expect(allowedRequest(request("https://0.0.0.0:3000/api/auth"), true)).toBe(
      true,
    );
    expect(
      allowedRequest(
        request("https://0.0.0.0:3000/api/auth", "evil.example"),
        true,
      ),
    ).toBe(false);
    expect(allowedRequest(request("http://0.0.0.0:3000/api/auth"), true)).toBe(
      false,
    );
    expect(allowedRequest(request("https://evil.example/api/auth"), true)).toBe(
      false,
    );
  });
  it("globally limits single-owner login attempts", () => {
    for (let i = 0; i < 10; i++) expect(allowLogin(1000)).toBe(true);
    expect(allowLogin(1000)).toBe(false);
    expect(allowLogin(1000000)).toBe(true);
  });
  it.each([
    "../../health",
    "https://evil.example",
    "integrations/gmail/oauth/callback",
    "credits/status",
    "startups/%2e%2e",
    "admin",
    "mcp",
  ])("rejects unlisted privileged proxy paths %s", (path) =>
    expect(permittedRoute(path, "POST")).toBe(false),
  );
  it("allows exact owner workflows", () => {
    expect(permittedRoute("startups/search", "POST")).toBe(true);
    expect(permittedRoute("dashboard/resumes", "POST")).toBe(true);
    expect(permittedRoute("profile", "DELETE")).toBe(false);
  });
});

import { readBoundedBody } from "@/lib/http-boundary";
it("bounds unauthenticated login input before buffering it", async () => {
  const request = new Request("https://workspace.example.org/api/auth", {
    method: "POST",
    body: "x".repeat(4096),
  });
  await expect(readBoundedBody(request, 2048)).rejects.toMatchObject({
    status: 413,
  });
});
it("bounds slow request bodies", async () => {
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(new Uint8Array([1]));
    },
  });
  const request = new Request("https://workspace.example.org/api/auth", {
    method: "POST",
    body: stream,
    duplex: "half",
  } as RequestInit);
  await expect(readBoundedBody(request, 2048, 10)).rejects.toMatchObject({
    status: 408,
  });
});

it("browser gateway exposes only authenticated application operations", () => {
  const id = "11111111-1111-4111-8111-111111111111";
  expect(permittedRoute("browser-applications", "POST")).toBe(true);
  expect(permittedRoute(`browser-applications/${id}/open`, "POST")).toBe(true);
  expect(permittedRoute(`browser-applications/${id}/actions`, "POST")).toBe(
    true,
  );
  expect(permittedRoute(`browser-applications/${id}`, "GET")).toBe(true);
  for (const path of ["cookies", "tabs", "evaluate", "filesystem"]) {
    expect(permittedRoute(`browser-applications/${id}/${path}`, "POST")).toBe(
      false,
    );
  }
  expect(permittedRoute(`browser-applications/${id}/open`, "GET")).toBe(false);
});
