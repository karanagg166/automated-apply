// Disposable loopback fixture only. Never loads owner configuration or calls providers.
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { randomBytes, scryptSync } from "node:crypto";

const image = process.argv[2] || "automated-apply-frontend:ci";
const origin = "http://localhost:3200";
const password = "fictional-container-owner"; // pragma: allowlist secret — isolated fixture
const salt = randomBytes(16).toString("hex");
const docker = (...args) =>
  execFileSync("docker", args, { encoding: "utf8" }).trim();
const container = docker(
  "run",
  "-d",
  "--rm",
  "-p",
  "127.0.0.1:3200:3000",
  "-e",
  `FRONTEND_ORIGIN=${origin}`,
  "-e",
  "FRONTEND_LOCAL_HTTP=true",
  "-e",
  `FRONTEND_SESSION_SECRET=${randomBytes(48).toString("hex")}`,
  "-e",
  `FRONTEND_PASSWORD_HASH=${salt}:${scryptSync(password, salt, 64).toString("hex")}`,
  image,
);
try {
  let ready = false;
  for (let attempt = 0; attempt < 50; attempt++) {
    try {
      ready = (
        await fetch(`${origin}/login`, { signal: AbortSignal.timeout(1000) })
      ).ok;
      if (ready) break;
    } catch {
      /* The fixture server may still be starting. */
    }
    await new Promise((resolve) => setTimeout(resolve, 200));
  }
  assert.ok(ready, "Standalone login page must start");
  const path = `${origin}/api/backend/dashboard/overview`;
  assert.equal((await fetch(path)).status, 401);
  const rejected = await fetch(`${origin}/api/auth`, {
    method: "POST",
    headers: {
      Origin: "https://evil.invalid",
      "Content-Type": "application/json",
    },
    body: "{}",
  });
  assert.equal(rejected.status, 403);
  const login = await fetch(`${origin}/api/auth`, {
    method: "POST",
    headers: { Origin: origin, "Content-Type": "application/json" },
    body: JSON.stringify({ password }),
  });
  assert.equal(login.status, 200);
  const cookie = login.headers
    .getSetCookie()
    .find((value) => value.startsWith("aa_owner="));
  assert.ok(cookie?.includes("HttpOnly") && cookie.includes("SameSite=strict"));
  assert.equal(
    (await fetch(path, { headers: { Cookie: cookie.split(";")[0] } })).status,
    503,
  );
  // No backend owner token was supplied; the authenticated proxy fails before network I/O.
  docker(
    "exec",
    container,
    "node",
    "-e",
    "const fs = require('node:fs'); if (process.getuid() === 0 || ['/usr/local/bin/npm', '/usr/local/bin/npx', '/usr/local/lib/node_modules/npm'].some(p => fs.existsSync(p))) process.exit(1)",
  );
  console.log(
    "Standalone container: login, anonymous/origin rejection, HttpOnly cookie, missing-backend fail-closed and non-root runtime without the legacy installer PASS",
  );
} finally {
  docker("rm", "-f", container);
}
