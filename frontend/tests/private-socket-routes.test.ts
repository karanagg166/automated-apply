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
}));
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
