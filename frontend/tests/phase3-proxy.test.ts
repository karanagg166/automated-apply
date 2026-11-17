// @vitest-environment node
import { createHash, createHmac } from "node:crypto";
import { NextRequest } from "next/server";
import { beforeEach, afterEach, expect, it, vi } from "vitest";
import { POST, GET, PUT } from "@/app/api/backend/[...path]/route";
import { csrfFor, issueSession } from "@/lib/security";
import { permittedRoute } from "@/lib/gateway";
const ownerKey = "fictional-phase3-owner-approval-only-for-tests";
const origin = "https://workspace.example.org";
let session: string;
function request(path: string, method = "POST", body = "{}") {
  return new NextRequest(`${origin}/api/backend/${path}`, {
    method,
    headers: {
      host: "workspace.example.org",
      origin,
      cookie: `aa_owner=${session}`,
      "x-csrf-token": csrfFor(session),
      "content-type": "application/json",
    },
    ...(method === "GET" ? {} : { body }),
  });
}
function context(path: string) {
  return { params: Promise.resolve({ path: path.split("/") }) };
}
beforeEach(() => {
  vi.stubEnv("FRONTEND_ORIGIN", origin);
  vi.stubEnv(
    "FRONTEND_SESSION_SECRET",
    "fictional-phase3-frontend-session-secret",
  );
  vi.stubEnv("JOB_AGENT_API_TOKEN", "fictional-phase3-backend-token");
  vi.stubEnv("BACKEND_ORIGIN", "http://127.0.0.1:8000");
  vi.stubEnv("BROWSER_OWNER_APPROVAL_KEY", ownerKey);
  session = issueSession();
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});
it("allows only keyed acknowledged-read GET/PUT and local completion POST gateway paths", () => {
  const parent = "10000000-0000-0000-0000-000000000001",
    read = "20000000-0000-0000-0000-000000000002";
  const path = `discovery/runs/${parent}/reads/${read}`;
  expect(permittedRoute(path, "GET")).toBe(true);
  expect(permittedRoute(path, "PUT")).toBe(true);
  expect(permittedRoute(path, "POST")).toBe(false);
  expect(permittedRoute(path, "DELETE")).toBe(false);
  expect(permittedRoute(`${path}/complete`, "POST")).toBe(true);
  expect(permittedRoute(`${path}/complete`, "GET")).toBe(false);
  for (const bad of [
    `${path}/retry`,
    `${path}/complete/extra`,
    `discovery/runs/${parent}/reads/originalRun`,
  ]) {
    expect(permittedRoute(bad, "PUT")).toBe(false);
    expect(permittedRoute(bad, "POST")).toBe(false);
  }
});
it("requires owner CSRF before keyed read PUT and forwards only its empty reviewed body", async () => {
  const path =
    "discovery/runs/10000000-0000-0000-0000-000000000001/reads/20000000-0000-0000-0000-000000000002";
  const fetcher = vi
    .fn()
    .mockResolvedValue(
      new Response("{}", { headers: { "Content-Type": "application/json" } }),
    );
  vi.stubGlobal("fetch", fetcher);
  const denied = request(path, "PUT");
  denied.headers.delete("x-csrf-token");
  expect((await PUT(denied, context(path))).status).toBe(403);
  expect(fetcher).not.toHaveBeenCalled();
  expect((await PUT(request(path, "PUT"), context(path))).status).toBe(200);
  expect(fetcher).toHaveBeenCalledTimes(1);
  const [url, options] = fetcher.mock.calls[0];
  expect(new URL(url).pathname).toBe(`/api/v1/${path}`);
  expect(Buffer.from(options.body).toString()).toBe("{}");
  expect((options.headers as Headers).get("Authorization")).toBe(
    "Bearer fictional-phase3-backend-token",
  );
});
it.each([
  "integrations/gmail/connect/start",
  "integrations/gmail/accounts/connect/start",
  "integrations/gmail/local/accounts/1/connect",
  "integrations/gmail/local/accounts/2/connect",
])("preserves OAuth browser binding from %s", async (path) => {
  const fetcher = vi.fn().mockResolvedValue(
    new Response(
      JSON.stringify({
        authorization_url: "https://accounts.google.com/o/oauth2/v2/auth",
      }),
      {
        headers: {
          "Content-Type": "application/json",
          "Set-Cookie":
            "gmail_oauth_browser=fictional; Path=/api/v1/integrations/gmail/oauth/callback; HttpOnly; SameSite=Lax",
        },
      },
    ),
  );
  vi.stubGlobal("fetch", fetcher);
  const response = await POST(request(path), context(path));
  expect(response.status).toBe(200);
  expect(response.headers.get("set-cookie")).toContain(
    "gmail_oauth_browser=fictional",
  );
  expect(response.headers.get("set-cookie")).toContain("HttpOnly");
});
it("signs exactly the approved missing-answer body and backend path", async () => {
  const path = `application-answers/missing/${"a".repeat(32)}/approve`;
  const body = JSON.stringify({
    expected_version: 2,
    expected_profile_version: 1,
    factual_confirmation: true,
  });
  const fetcher = vi
    .fn()
    .mockResolvedValue(
      new Response("{}", { headers: { "Content-Type": "application/json" } }),
    );
  vi.stubGlobal("fetch", fetcher);
  expect((await POST(request(path, "POST", body), context(path))).status).toBe(
    200,
  );
  const [url, options] = fetcher.mock.calls[0];
  const headers = options.headers as Headers;
  const proof = headers.get("X-Browser-Owner-Approval")!;
  const [version, timestamp, nonce, signature] = proof.split(":");
  expect(version).toBe("v1");
  expect(new URL(url).pathname).toBe(`/api/v1/${path}`);
  expect(Buffer.from(options.body).toString()).toBe(body);
  expect(signature).toBe(
    createHmac("sha256", ownerKey)
      .update(
        [
          "POST",
          `/api/v1/${path}`,
          timestamp,
          nonce,
          createHash("sha256").update(body).digest("hex"),
        ].join("\n"),
      )
      .digest("hex"),
  );
});
it("rejects every Gmail write route before contacting the backend", async () => {
  const fetcher = vi.fn();
  vi.stubGlobal("fetch", fetcher);
  const id = "11111111-1111-4111-8111-111111111111";
  for (const operation of [
    "send",
    "modify",
    "archive",
    "delete",
    "trash",
    "drafts",
    "messages/send",
    "messages/batchModify",
  ]) {
    const path = `integrations/gmail/accounts/${id}/${operation}`;
    expect((await POST(request(path), context(path))).status).toBe(404);
    expect(permittedRoute(path, "DELETE")).toBe(false);
  }
  expect(fetcher).not.toHaveBeenCalled();
});
it("allows exact provider metadata and selected-evidence import paths only", () => {
  const id = "11111111-1111-4111-8111-111111111111",
    evidence = "b".repeat(32);
  expect(permittedRoute("integrations/providers/apify", "GET")).toBe(true);
  expect(
    permittedRoute("integrations/providers/apify/actors/inspect", "POST"),
  ).toBe(true);
  expect(
    permittedRoute("integrations/providers/apify/actors/run", "POST"),
  ).toBe(false);
  expect(permittedRoute(`integrations/gmail/accounts/${id}/leads`, "GET")).toBe(
    true,
  );
  expect(
    permittedRoute(
      `integrations/gmail/accounts/${id}/evidence/${evidence}/import`,
      "POST",
    ),
  ).toBe(true);
  expect(
    permittedRoute(
      `integrations/gmail/accounts/${id}/evidence/${evidence}/import/send`,
      "POST",
    ),
  ).toBe(false);
});
it("returns an honest error without an approval key and never forwards a forged proof", async () => {
  vi.stubEnv("BROWSER_OWNER_APPROVAL_KEY", "");
  const fetcher = vi.fn();
  vi.stubGlobal("fetch", fetcher);
  const path = `application-answers/missing/${"a".repeat(32)}/approve`;
  expect((await POST(request(path), context(path))).status).toBe(503);
  expect(fetcher).not.toHaveBeenCalled();
});
