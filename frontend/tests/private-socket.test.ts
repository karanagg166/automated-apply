// @vitest-environment node
import { afterEach, expect, it } from "vitest";
import {
  chmod,
  lstat,
  mkdtemp,
  realpath,
  rm,
  symlink,
  unlink,
  writeFile,
} from "node:fs/promises";
import { createServer, type RequestListener } from "node:http";
import { tmpdir } from "node:os";
import { join } from "node:path";
import {
  privateSocketFetch,
  privateSocketPath,
} from "../src/lib/private-socket";
const retire: (() => Promise<void>)[] = [];
afterEach(async () => {
  for (const action of retire.splice(0).reverse()) await action();
});
async function fixture(listener: RequestListener) {
  const directory = await mkdtemp(join(await realpath(tmpdir()), "aa-ipc-"));
  await chmod(directory, 0o700);
  const socket = join(directory, "s.sock");
  const server = createServer(listener);
  await new Promise<void>((resolve, reject) => {
    server.once("error", reject);
    server.listen(socket, resolve);
  });
  await chmod(socket, 0o600);
  retire.push(async () => {
    await new Promise<void>((resolve) => server.close(() => resolve()));
    await rm(directory, { recursive: true, force: true });
  });
  return { socket, directory, server };
}
const endpoint = new URL("http://127.0.0.1:18011/api/v1/jobs?limit=1");
const options = {
  method: "GET",
  headers: new Headers({ Authorization: "Bearer fictional-token" }),
  timeoutMs: 1000,
};
it("forwards one authenticated Unix request and preserves independent browser cookies", async () => {
  let count = 0;
  const { socket } = await fixture((request, response) => {
    count++;
    expect(request.url).toBe("/api/v1/jobs?limit=1");
    expect(request.headers.host).toBe("127.0.0.1:18011");
    expect(request.headers.authorization).toBe("Bearer fictional-token");
    expect(request.headers["x-forwarded-proto"]).toBeUndefined();
    const chunks: Buffer[] = [];
    request.on("data", (chunk: Buffer) => chunks.push(chunk));
    request.on("end", () => {
      expect(Buffer.concat(chunks).toString()).toBe('{"fictional":true}');
      response.setHeader("Set-Cookie", [
        "first=1; HttpOnly",
        "second=2; HttpOnly",
      ]);
      response.setHeader("ETag", '"fixture"');
      response.end('{"ok":true}');
    });
  });
  expect(await privateSocketPath(socket)).toBe(socket);
  const result = await privateSocketFetch(socket, endpoint, {
    ...options,
    method: "POST",
    body: Buffer.from('{"fictional":true}'),
  });
  expect(await result.json()).toEqual({ ok: true });
  expect(result.headers.getSetCookie()).toEqual([
    "first=1; HttpOnly",
    "second=2; HttpOnly",
  ]);
  expect(count).toBe(1);
});
it("refuses non-private paths, file aliases and replaced socket identities", async () => {
  const { socket, directory } = await fixture((_q, r) => r.end());
  expect(await privateSocketPath(undefined)).toBeUndefined();
  for (const raw of [
    "",
    "relative.sock",
    `${directory}/./s.sock`,
    `${directory}/../s.sock`,
    "/" + "x".repeat(101),
  ])
    await expect(privateSocketPath(raw)).rejects.toThrow();
  await chmod(socket, 0o660);
  await expect(privateSocketPath(socket)).rejects.toThrow(
    "private_socket_identity_required",
  );
  await chmod(socket, 0o600);
  await chmod(directory, 0o750);
  await expect(privateSocketPath(socket)).rejects.toThrow(
    "private_socket_directory_required",
  );
  await chmod(directory, 0o700);
  const alias = join(directory, "alias");
  await symlink(socket, alias);
  await expect(privateSocketPath(alias)).rejects.toThrow();
  await unlink(socket);
  await writeFile(socket, "preserve", { mode: 0o600 });
  await expect(privateSocketPath(socket)).rejects.toThrow();
  expect((await lstat(socket)).isFile()).toBe(true);
});
it("rejects a redirect after one call", async () => {
  let count = 0;
  const { socket } = await fixture((_q, r) => {
    count++;
    r.writeHead(302, { Location: "http://example.com/private" });
    r.end();
  });
  await expect(privateSocketFetch(socket, endpoint, options)).rejects.toThrow(
    "private_socket_redirect_denied",
  );
  expect(count).toBe(1);
});
it("bounds incomplete response headers and never retries a timed-out mutation", async () => {
  let count = 0;
  const { socket } = await fixture((_q, _r) => {
    count++;
  });
  await expect(
    privateSocketFetch(socket, endpoint, {
      ...options,
      method: "POST",
      timeoutMs: 30,
    }),
  ).rejects.toMatchObject({ name: "TimeoutError" });
  expect(count).toBe(1);
});
it("keeps the deadline while reading a stalled response body", async () => {
  const { socket } = await fixture((_q, r) => {
    r.writeHead(200);
    r.write("partial");
  });
  const response = await privateSocketFetch(socket, endpoint, {
    ...options,
    timeoutMs: 50,
  });
  await expect(response.text()).rejects.toThrow();
});
it("supports empty responses and rejects remote or ambiguous endpoint authorities", async () => {
  let count = 0;
  const { socket } = await fixture((_q, r) => {
    count++;
    r.writeHead(204);
    r.end();
  });
  const response = await privateSocketFetch(socket, endpoint, options);
  expect(response.status).toBe(204);
  expect(await response.text()).toBe("");
  for (const url of [
    "http://localhost:18011/x",
    "https://127.0.0.1:18011/x",
    "http://u:p@127.0.0.1:18011/x",
    "http://127.0.0.1/x",
    "http://127.0.0.1:18011/x#fragment",
  ])
    await expect(
      privateSocketFetch(socket, new URL(url), options),
    ).rejects.toThrow("private_socket_endpoint_required");
  expect(count).toBe(1);
  await unlink(socket);
  await expect(privateSocketFetch(socket, endpoint, options)).rejects.toThrow();
  expect(count).toBe(1);
});
