import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { scryptSync } from "node:crypto";
import { once } from "node:events";
import { chmod, mkdtemp, realpath, rm, writeFile } from "node:fs/promises";
import { createServer } from "node:http";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { setTimeout as delay } from "node:timers/promises";
import { fileURLToPath } from "node:url";

const executable = fileURLToPath(
  new URL("../run-local-rust.mjs", import.meta.url),
);
const owner = "fictional-local-cutover-passphrase";
const token = "fictional-local-cutover-runtime-token";

async function listen(server, ...args) {
  server.listen(...args);
  await once(server, "listening");
  return server.address();
}

function close(server) {
  return new Promise((resolve) => server.close(resolve));
}

test(
  "the installed-style frontend serves owner routes through one private Rust socket",
  {
    timeout: 30000,
  },
  async () => {
    const directory = await mkdtemp(join(await realpath(tmpdir()), "aa-bff-"));
    const socket = join(directory, "aa.sock");
    const frontend = join(directory, "frontend.env");
    const runtime = join(directory, "runtime.env");
    const observed = [];
    let tcpRequests = 0;
    let child;
    let exited;
    const trap = createServer((_request, response) => {
      tcpRequests += 1;
      response.writeHead(500).end();
    });
    const upstream = createServer((request, response) => {
      observed.push([
        request.method,
        request.url,
        request.headers.authorization,
      ]);
      response
        .writeHead(200, { "Content-Type": "application/json" })
        .end(JSON.stringify({ path: request.url }));
    });
    try {
      const { port: rustPort } = await listen(trap, 0, "127.0.0.1");
      await listen(upstream, socket);
      await chmod(socket, 0o600);
      const reservation = createServer();
      const { port } = await listen(reservation, 0, "127.0.0.1");
      await close(reservation);
      const origin = `http://127.0.0.1:${port}`;
      const salt = "0123456789abcdef0123456789abcdef";
      const passwordHash = `${salt}:${scryptSync(owner, salt, 64).toString("hex")}`;
      await writeFile(
        frontend,
        `FRONTEND_ORIGIN=${origin}\nFRONTEND_LOCAL_HTTP=true\n` +
          `FRONTEND_SESSION_SECRET=fictional-local-cutover-session-material\n` +
          `FRONTEND_PASSWORD_HASH=${passwordHash}\n`,
        { mode: 0o600 },
      );
      await writeFile(
        runtime,
        `RUST_AGENT_LISTEN=127.0.0.1:${rustPort}\nRUST_AGENT_UNIX_SOCKET='${socket}'\n` +
          `JOB_AGENT_API_TOKEN=${token}\n`,
        { mode: 0o600 },
      );
      child = spawn(
        process.execPath,
        [
          executable,
          "--frontend-config",
          frontend,
          "--runtime-config",
          runtime,
          "--port",
          String(port),
        ],
        {
          env: {
            HOSTNAME: "0.0.0.0",
            JOB_AGENT_API_TOKEN: "fictional-ambient-token",
          },
          stdio: "ignore",
        },
      );
      exited = once(child, "exit");
      // Watch for immediate failure while waiting for the actual Next.js listener.
      let readiness;
      for (
        let attempt = 0;
        attempt < 80 && child.exitCode === null;
        attempt += 1
      ) {
        readiness = await fetch(`${origin}/api/auth`, {
          signal: AbortSignal.timeout(1000),
        }).catch(() => undefined);
        if (readiness) break;
        await delay(100);
      }
      assert.equal(readiness?.status, 401);
      assert.deepEqual(observed, []);

      const login = await fetch(`${origin}/api/auth`, {
        method: "POST",
        headers: { origin, "content-type": "application/json" },
        body: JSON.stringify({ password: owner }),
        signal: AbortSignal.timeout(3000),
      });
      assert.equal(login.status, 200);
      const cookie = login.headers
        .getSetCookie()
        .map((value) => value.split(";")[0])
        .join("; ");
      assert.match(cookie, /aa_owner=/);
      const send = (path) =>
        fetch(`${origin}${path}`, {
          headers: { cookie },
          signal: AbortSignal.timeout(3000),
        });
      for (const [path, forwarded] of [
        ["/api/backend/profile", "/api/v1/profile"],
        ["/api/workflow/control", "/api/v1/rust-agent/control"],
      ]) {
        const response = await send(path);
        assert.equal(response.status, 200);
        assert.deepEqual(await response.json(), { path: forwarded });
        assert.deepEqual(observed.at(-1), [
          "GET",
          forwarded,
          `Bearer ${token}`,
        ]);
      }
      assert.equal(observed.length, 2);
      await close(upstream);
      assert.equal((await send("/api/backend/profile")).status, 504);
      const disconnected = await send("/api/workflow/control");
      assert.equal(disconnected.status, 503);
      assert.deepEqual(await disconnected.json(), {
        error: "workflow_unavailable",
      });
      assert.equal(tcpRequests, 0);
    } finally {
      if (child && child.exitCode === null && child.signalCode === null) {
        child.kill("SIGKILL");
        await exited;
      }
      await close(upstream);
      await close(trap);
      await rm(directory, { recursive: true });
    }
  },
);
