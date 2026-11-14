// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createServer, type Server } from "node:http";
import { NextRequest } from "next/server";
import { GET, POST } from "@/app/api/workflow/[...path]/route";
import { csrfFor, issueSession } from "@/lib/security";
let server: Server | undefined;
let session: string;
const TOKEN = "fictional-loopback-owner-token-0123456789";
beforeEach(() => {
  vi.stubEnv("FRONTEND_ORIGIN", "http://localhost:3000");
  vi.stubEnv("FRONTEND_LOCAL_HTTP", "true");
  vi.stubEnv(
    "FRONTEND_SESSION_SECRET",
    "fictional-session-secret-at-least-32-characters",
  );
  vi.stubEnv("JOB_AGENT_API_TOKEN", TOKEN);
  session = issueSession();
});
afterEach(async () => {
  if (server) {
    server.closeAllConnections();
    await new Promise<void>((resolve) => server!.close(() => resolve()));
    server = undefined;
  }
  vi.unstubAllEnvs();
});
function request(
  path: string,
  method = "GET",
  body?: string,
  extra: Record<string, string> = {},
) {
  return new NextRequest(`http://localhost:3000/api/workflow/${path}`, {
    method,
    headers: {
      host: "localhost:3000",
      origin: "http://localhost:3000",
      cookie: `aa_owner=${session}`,
      "x-csrf-token": csrfFor(session),
      "content-type": "application/json",
      ...extra,
    },
    ...(body === undefined ? {} : { body }),
  });
}
function params(path: string) {
  return { params: Promise.resolve({ path: path.split("/") }) };
}
async function fixture(handler: Parameters<typeof createServer>[0]) {
  server = createServer(handler);
  await new Promise<void>((resolve) => server!.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  if (!address || typeof address === "string") throw new Error("fixture bind");
  vi.stubEnv("RUST_AGENT_URL", `http://127.0.0.1:${address.port}`);
}
describe("private workflow proxy", () => {
  it("forwards exactly one approved mutation with server-only credentials and its exact revision", async () => {
    let calls = 0;
    await fixture(async (incoming, outgoing) => {
      calls++;
      expect(incoming.url).toBe(
        "/api/v1/rust-agent/runs/11111111-1111-4111-8111-111111111111/approvals/22222222-2222-4222-8222-222222222222",
      );
      expect(incoming.headers.authorization).toBe(`Bearer ${TOKEN}`);
      expect(incoming.headers.cookie).toBeUndefined();
      expect(incoming.headers["x-forwarded-proto"]).toBeUndefined();
      let body = "";
      for await (const chunk of incoming) body += chunk;
      expect(JSON.parse(body)).toEqual({
        expected_revision: 12,
        decision: "approve",
      });
      outgoing.end('{"state":"ready"}');
    });
    const path =
      "runs/11111111-1111-4111-8111-111111111111/approvals/22222222-2222-4222-8222-222222222222";
    const response = await POST(
      request(
        path,
        "POST",
        JSON.stringify({ expected_revision: 12, decision: "approve" }),
      ),
      params(path),
    );
    expect(response.status).toBe(200);
    expect(calls).toBe(1);
    expect(await response.text()).not.toContain(TOKEN);
    expect(response.headers.get("cache-control")).toBe("no-store");
  });
  it("requires owner session, exact origin and CSRF before forwarding", async () => {
    await fixture((_request, response) => {
      throw new Error("must not forward");
    });
    expect(
      (
        await GET(
          request("runs", "GET", undefined, { cookie: "" }),
          params("runs"),
        )
      ).status,
    ).toBe(401);
    expect(
      (
        await POST(
          request("runs", "POST", "{}", { origin: "https://evil.invalid" }),
          params("runs"),
        )
      ).status,
    ).toBe(401);
    expect(
      (
        await POST(
          request("runs", "POST", "{}", { "x-csrf-token": "wrong" }),
          params("runs"),
        )
      ).status,
    ).toBe(403);
  });
  it("denies arbitrary methods/routes, queries, unsafe targets and oversized bodies", async () => {
    expect((await GET(request("runs?x=y"), params("runs"))).status).toBe(404);
    expect(
      (await POST(request("send", "POST", "{}"), params("send"))).status,
    ).toBe(404);
    vi.stubEnv("RUST_AGENT_URL", "https://evil.invalid:8011");
    expect((await GET(request("runs"), params("runs"))).status).toBe(503);
    vi.stubEnv("RUST_AGENT_URL", "http://127.0.0.1:8011");
    expect(
      (await POST(request("runs", "POST", "x".repeat(65537)), params("runs")))
        .status,
    ).toBe(413);
  });
  it("does not follow redirects, expose upstream errors, or retry failed writes", async () => {
    let calls = 0;
    await fixture((_request, response) => {
      calls++;
      response.writeHead(302, { location: "https://evil.invalid" });
      response.end(JSON.stringify({ error: TOKEN }));
    });
    const response = await POST(request("runs", "POST", "{}"), params("runs"));
    expect(response.status).toBe(502);
    expect(calls).toBe(1);
    expect(await response.text()).not.toContain(TOKEN);
  });
  it("rejects oversized upstream data without exposing private fragments", async () => {
    await fixture((_request, response) =>
      response.end(JSON.stringify({ private: "x".repeat(524289) })),
    );
    const response = await GET(request("runs"), params("runs"));
    expect(response.status).toBe(502);
    expect((await response.text()).length).toBeLessThan(150);
  });
});
