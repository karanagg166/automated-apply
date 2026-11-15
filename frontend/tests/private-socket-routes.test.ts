// @vitest-environment node
import { afterEach, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { chmod, mkdtemp, realpath, rm } from "node:fs/promises";
import { createServer, type RequestListener } from "node:http";
import { tmpdir } from "node:os";
import { join } from "node:path";
vi.mock("../src/lib/security", () => ({
  SESSION_COOKIE: "fixture-session",
  allowedRequest: () => true,
  validSession: () => true,
  validCsrf: (_s: string, csrf: string) => csrf === "fictional-csrf",
  configuration: () => ({ secure: true }),
}));
import {
  GET as workflowGet,
  PUT as workflowPut,
} from "../src/app/api/workflow/[...path]/route";
import { GET as backendGet } from "../src/app/api/backend/[...path]/route";
const retire: (() => Promise<void>)[] = [];
afterEach(async () => {
  vi.unstubAllEnvs();
  for (const action of retire.splice(0).reverse()) await action();
});
async function fixture(listener: RequestListener) {
  const directory = await mkdtemp(join(await realpath(tmpdir()), "aa-bff-"));
  await chmod(directory, 0o700);
  const socket = join(directory, "s.sock"),
    server = createServer(listener);
  await new Promise<void>((resolve, reject) => {
    server.once("error", reject);
    server.listen(socket, resolve);
  });
  await chmod(socket, 0o600);
  retire.push(async () => {
    await new Promise<void>((resolve) => server.close(() => resolve()));
    await rm(directory, { recursive: true, force: true });
  });
  vi.stubEnv(
    "JOB_AGENT_API_TOKEN",
    "0123456789abcdefghijklmnopqrstuvwxyzABCDEF",
  );
  return socket;
}
it("routes guarded workflow mutations over private IPC without claiming forwarded TLS", async () => {
  let calls = 0;
  const socket = await fixture((req, res) => {
    calls++;
    expect(req.url).toBe("/api/v1/rust-agent/discovery/schedule");
    expect(req.headers["x-forwarded-proto"]).toBeUndefined();
    expect(req.headers.host).toBe("127.0.0.1:18011");
    expect(req.headers.authorization).toBe(
      "Bearer 0123456789abcdefghijklmnopqrstuvwxyzABCDEF",
    );
    res.setHeader("Content-Type", "application/json");
    res.end('{"revision":2}');
  });
  vi.stubEnv("RUST_AGENT_URL", "http://127.0.0.1:18011");
  vi.stubEnv("RUST_AGENT_UNIX_SOCKET", socket);
  vi.stubEnv("RUST_AGENT_TRUST_LOOPBACK_PROXY", "true");
  const context = {
    params: Promise.resolve({ path: ["discovery", "schedule"] }),
  };
  const makeRequest = (csrf: string) =>
    new NextRequest(
      "https://workspace.example/api/workflow/discovery/schedule",
      {
        method: "PUT",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
        body: '{"expected_revision":1}',
      },
    );
  expect((await workflowPut(makeRequest("wrong"), context)).status).toBe(403);
  expect(calls).toBe(0);
  const result = await workflowPut(makeRequest("fictional-csrf"), context);
  expect(result.status).toBe(200);
  expect(await result.json()).toEqual({ revision: 2 });
  expect(calls).toBe(1);
  const denied = await workflowGet(
    new NextRequest(
      "https://workspace.example/api/workflow/discovery/schedule?extra=1",
    ),
    context,
  );
  expect(denied.status).toBe(404);
  expect(calls).toBe(1);
});
it("routes ordinary API reads over IPC preserving response status and ETag", async () => {
  let calls = 0;
  const socket = await fixture((req, res) => {
    calls++;
    expect(req.url).toBe("/api/v1/profile");
    res.setHeader("Content-Type", "application/json");
    res.setHeader("ETag", '"fixture-2"');
    res.end('{"fixture":true}');
  });
  vi.stubEnv("BACKEND_ORIGIN", "http://127.0.0.1:18011");
  vi.stubEnv("BACKEND_UNIX_SOCKET", socket);
  const result = await backendGet(
    new NextRequest("https://workspace.example/api/backend/profile"),
    { params: Promise.resolve({ path: ["profile"] }) },
  );
  expect(result.status).toBe(200);
  expect(result.headers.get("ETag")).toBe('"fixture-2"');
  expect(await result.json()).toEqual({ fixture: true });
  expect(calls).toBe(1);
});
