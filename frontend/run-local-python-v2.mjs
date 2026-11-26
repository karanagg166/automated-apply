// Production dashboard launcher for the Python v2 runtime (launchd: com.automated-apply.frontend-v2).
//
//   node frontend/run-local-python-v2.mjs --frontend-config <frontend.private.env> \
//     --runtime-config <phase1.private.env> --port 3000 [--check-config]
//
// Both config files must be regular 0600 files owned by this user. The dashboard owner login
// (FRONTEND_PASSWORD_HASH / FRONTEND_SESSION_SECRET) comes from the frontend config and the
// API bearer token (JOB_AGENT_API_TOKEN) from the runtime config. /api/backend/* is proxied
// only to the Python v2 API on 127.0.0.1:8000; the legacy Rust runtime (:8011) is never used.
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
import { isAbsolute } from "node:path";
import { pathToFileURL } from "node:url";
import { parseArgs, parseEnv } from "node:util";

export const PYTHON_V2_BACKEND = "http://127.0.0.1:8000";
const standalone = new URL(".next/standalone/", import.meta.url);
const server = new URL("server.js", standalone);
const staticAssets = new URL(".next/static/", standalone);

function privateConfig(path) {
  if (!path || !isAbsolute(path))
    throw new Error("config_path_must_be_absolute");
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
      throw new Error("config_must_be_private_0600_file");
    const buffer = Buffer.alloc(limit + 1);
    let offset = 0;
    while (offset < buffer.length) {
      const read = readSync(fd, buffer, offset, buffer.length - offset);
      if (!read) break;
      offset += read;
    }
    if (offset > limit) throw new Error("config_too_large");
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

export function environment(options, frontend, runtime) {
  const port = Number(options.port);
  const origin = new URL(
    frontend.FRONTEND_ORIGIN ?? `http://localhost:${port}`,
  );
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
    !/^[\x21-\x7e]{32,512}$/.test(token ?? "") ||
    (approvalKey !== undefined && !/^[\x21-\x7e]{32,512}$/.test(approvalKey)) ||
    (frontend.JOB_AGENT_API_TOKEN !== undefined &&
      frontend.JOB_AGENT_API_TOKEN !== token)
  )
    throw new Error("frontend_v2_configuration_rejected");
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
    // Fixed: any BACKEND_ORIGIN in the frontend config (e.g. a legacy :8011) is ignored.
    BACKEND_ORIGIN: PYTHON_V2_BACKEND,
    // The legacy /api/workflow route defaults to :8011; pin it to v2 so it can never reach Rust.
    RUST_AGENT_URL: PYTHON_V2_BACKEND,
  };
}

async function main() {
  const { values } = parseArgs({
    options: {
      "frontend-config": { type: "string" },
      "runtime-config": { type: "string" },
      "check-config": { type: "boolean" },
      port: { type: "string", default: "3000" },
    },
  });
  const selected = environment(
    values,
    privateConfig(values["frontend-config"]),
    privateConfig(values["runtime-config"]),
  );
  checkBundle();
  cpSync(new URL(".next/static/", import.meta.url), staticAssets, {
    recursive: true,
  });
  if (values["check-config"]) {
    process.stdout.write(
      `frontend_v2_config_ok backend=${selected.BACKEND_ORIGIN} port=${selected.PORT}\n`,
    );
    return;
  }
  process.umask(0o077);
  for (const key of Object.keys(process.env)) delete process.env[key];
  Object.assign(process.env, selected);
  await import(server.href);
}

if (
  process.argv[1] &&
  import.meta.url === pathToFileURL(process.argv[1]).href
) {
  try {
    await main();
  } catch (error) {
    // Only the error code is printed: never a config value.
    process.stderr.write(
      `local_python_v2_frontend_start_failed: ${error?.message ?? "unknown"}\n`,
    );
    process.exitCode = 1;
  }
}
