import {
  closeSync,
  constants,
  cpSync,
  fstatSync,
  lstatSync,
  openSync,
  readSync,
  readdirSync,
} from "node:fs";
import { isAbsolute, normalize } from "node:path";
import { parseArgs, parseEnv } from "node:util";

const standalone = new URL(".next/standalone/", import.meta.url);
const server = new URL("server.js", standalone);
const staticAssets = new URL(".next/static/", standalone);

function privateConfig(path) {
  if (!path || !isAbsolute(path)) throw new Error();
  const fd = openSync(
    path,
    constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK,
  );
  try {
    const file = fstatSync(fd);
    const limit = 1024 * 1024;
    if (
      !file.isFile() ||
      file.uid !== process.geteuid() ||
      (file.mode & 0o077) !== 0 ||
      file.size > limit
    )
      throw new Error();
    const buffer = Buffer.alloc(limit + 1);
    let offset = 0;
    while (offset < buffer.length) {
      const read = readSync(fd, buffer, offset, buffer.length - offset);
      if (!read) break;
      offset += read;
    }
    if (offset > limit) throw new Error();
    return parseEnv(
      new TextDecoder("utf-8", { fatal: true }).decode(
        buffer.subarray(0, offset),
      ),
    );
  } finally {
    closeSync(fd);
  }
}

function checkBundle() {
  if (
    !lstatSync(server).isFile() ||
    !lstatSync(new URL(".next/BUILD_ID", standalone)).isFile() ||
    readdirSync(standalone).some((name) => name.startsWith(".env"))
  )
    throw new Error("local_frontend_standalone_unavailable");
}

function prepareBuild() {
  checkBundle();
  cpSync(new URL(".next/static/", import.meta.url), staticAssets, {
    recursive: true,
  });
}

function environment(options) {
  const port = Number(options.port);
  const frontend = privateConfig(options["frontend-config"]);
  const runtime = privateConfig(options["runtime-config"]);
  const origin = new URL(frontend.FRONTEND_ORIGIN);
  const listen = runtime.RUST_AGENT_LISTEN ?? "127.0.0.1:8011";
  const rustPort = Number(listen.split(":")[1]);
  const socket = runtime.RUST_AGENT_UNIX_SOCKET;
  const token = runtime.JOB_AGENT_API_TOKEN;
  const approvalKey = runtime.BROWSER_OWNER_APPROVAL_KEY;
  if (
    !/^\d{4,5}$/.test(options.port) ||
    port <= 1024 ||
    port > 65535 ||
    origin.pathname !== "/" ||
    origin.username ||
    origin.password ||
    origin.search ||
    origin.hash ||
    (origin.protocol !== "https:" &&
      (origin.protocol !== "http:" ||
        frontend.FRONTEND_LOCAL_HTTP !== "true" ||
        !["localhost", "127.0.0.1", "[::1]"].includes(origin.hostname) ||
        Number(origin.port) !== port)) ||
    (frontend.FRONTEND_SESSION_SECRET?.length ?? 0) < 32 ||
    !/^[a-f0-9]{32}:[a-f0-9]{128}$/.test(
      frontend.FRONTEND_PASSWORD_HASH ?? "",
    ) ||
    !/^127\.0\.0\.1:\d{4,5}$/.test(listen) ||
    rustPort <= 1024 ||
    rustPort > 65535 ||
    !socket ||
    !isAbsolute(socket) ||
    normalize(socket) !== socket ||
    Buffer.byteLength(socket) > 100 ||
    socket.endsWith("/") ||
    socket.includes("\0") ||
    !/^[\x21-\x7e]{32,512}$/.test(token ?? "") ||
    (approvalKey !== undefined && !/^[\x21-\x7e]{32,512}$/.test(approvalKey)) ||
    (frontend.JOB_AGENT_API_TOKEN !== undefined &&
      frontend.JOB_AGENT_API_TOKEN !== token)
  )
    throw new Error();

  const endpoint = `http://127.0.0.1:${rustPort}`;
  return {
    HOSTNAME: "127.0.0.1",
    PORT: String(port),
    NODE_ENV: "production",
    FRONTEND_ORIGIN: origin.origin,
    FRONTEND_LOCAL_HTTP:
      frontend.FRONTEND_LOCAL_HTTP === "true" ? "true" : "false",
    FRONTEND_SESSION_SECRET: frontend.FRONTEND_SESSION_SECRET,
    FRONTEND_PASSWORD_HASH: frontend.FRONTEND_PASSWORD_HASH,
    JOB_AGENT_API_TOKEN: token,
    ...(approvalKey ? { BROWSER_OWNER_APPROVAL_KEY: approvalKey } : {}),
    BACKEND_ORIGIN: endpoint,
    RUST_AGENT_URL: endpoint,
    BACKEND_UNIX_SOCKET: socket,
    RUST_AGENT_UNIX_SOCKET: socket,
  };
}

async function main() {
  if (process.argv.length === 3 && process.argv[2] === "--prepare-build") {
    prepareBuild();
    return;
  }
  const { values } = parseArgs({
    options: {
      "frontend-config": { type: "string" },
      "runtime-config": { type: "string" },
      "check-config": { type: "boolean" },
      port: { type: "string", default: "3000" },
    },
  });
  const selected = environment(values);
  checkBundle();
  if (!lstatSync(staticAssets).isDirectory())
    throw new Error("local_frontend_static_assets_unavailable");
  if (values["check-config"]) return;
  process.umask(0o077);
  for (const key of Object.keys(process.env)) delete process.env[key];
  Object.assign(process.env, selected);
  await import(server.href);
}

try {
  await main();
} catch {
  process.stderr.write("local_rust_frontend_start_failed\n");
  process.exitCode = 1;
}
