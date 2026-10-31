import test from "node:test";
import assert from "node:assert/strict";
import { spawn, spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import {
  existsSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
  chmodSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import {
  assertDisposableLocalDatabaseUrl,
  buildSanitizedChildEnv,
} from "./chrome-e2e.mjs";

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, "../..");
const EXPECTED_ID = "gdjbmkffcpicbpiikcohlmokkmcpipgp";

function findPython() {
  const candidates = [
    process.env.PYTHON,
    resolve(root, ".venv/bin/python"),
    "python3",
    "python",
  ].filter(Boolean);
  for (const candidate of candidates) {
    if (candidate.startsWith("/") && !existsSync(candidate)) continue;
    const probe = spawnSync(candidate, ["-c", "import pydantic"], {
      cwd: root,
      stdio: "ignore",
    });
    if (probe.status === 0) return candidate;
  }
  throw new Error(
    "Missing Python environment with backend dependencies in this worktree. Run 'python3 -m venv .venv && .venv/bin/pip install -r backend/requirements.txt'.",
  );
}

function runNativeFrame(
  python,
  envPath,
  origin,
  rawInputBuffer,
  closeStdin = true,
) {
  return new Promise((resolvePromise, rejectPromise) => {
    const child = spawn(
      python,
      ["-m", "backend.app.local_agent.native_host", envPath, origin],
      {
        cwd: root,
        env: buildSanitizedChildEnv(),
        stdio: ["pipe", "pipe", "ignore"],
      },
    );
    const timer = setTimeout(() => {
      child.kill();
      rejectPromise(new Error("native frame probe timed out"));
    }, 15000);
    let output = Buffer.alloc(0);
    child.stdout.on("data", (chunk) => {
      output = Buffer.concat([output, chunk]);
      if (output.length >= 4) {
        const len = output.readUInt32LE(0);
        if (output.length >= len + 4) {
          clearTimeout(timer);
          child.stdin.end();
          try {
            resolvePromise(
              JSON.parse(output.subarray(4, len + 4).toString("utf8")),
            );
          } catch (err) {
            rejectPromise(err);
          }
        }
      }
    });
    child.on("error", (err) => {
      clearTimeout(timer);
      rejectPromise(err);
    });
    child.on("exit", (code) => {
      if (output.length < 4) {
        clearTimeout(timer);
        rejectPromise(new Error(`native exited early with code ${code}`));
      }
    });
    child.stdin.write(rawInputBuffer);
    if (closeStdin) child.stdin.end();
  });
}

function encodeFrame(objOrBytes) {
  const payload = Buffer.isBuffer(objOrBytes)
    ? objOrBytes
    : Buffer.from(
        typeof objOrBytes === "string"
          ? objOrBytes
          : JSON.stringify(objOrBytes),
        "utf8",
      );
  const header = Buffer.alloc(4);
  header.writeUInt32LE(payload.length, 0);
  return Buffer.concat([header, payload]);
}

test("manifest version 1.3.4 and public RSA key derive exact stable extension ID", () => {
  const manifest = JSON.parse(
    readFileSync(resolve(here, "../manifest.json"), "utf8"),
  );
  assert.equal(manifest.manifest_version, 3);
  assert.equal(manifest.version, "1.3.4");
  const hash = createHash("sha256")
    .update(Buffer.from(manifest.key, "base64"))
    .digest("hex")
    .slice(0, 32);
  const derivedId = [...hash]
    .map((c) => String.fromCharCode(97 + Number.parseInt(c, 16)))
    .join("");
  assert.equal(derivedId, EXPECTED_ID);

  // Verify disposable DB safety guards fail closed on nonlocal, Supabase, or unexpected targets
  const validLocalUrl = [
    "postgresql://postgres",
    "disposable@127.0.0.1:55449/candidate_profile_test",
  ].join(":");
  assert.equal(
    assertDisposableLocalDatabaseUrl(
      validLocalUrl,
      55449,
      "candidate_profile_test",
      "postgres",
    ),
    validLocalUrl,
  );
  for (const unsafeUrl of [
    "",
    [
      "postgresql://postgres",
      "pw@db.projectref.supabase.co:5432/postgres",
    ].join(":"),
    [
      "postgresql://postgres.ref",
      "pw@aws-0-ap-south-1.pooler.supabase.com:6543/postgres",
    ].join(":"),
    ["postgresql://postgres", "pw@localhost:55449/candidate_profile_test"].join(
      ":",
    ),
    ["postgresql://postgres", "pw@127.0.0.1:5432/candidate_profile_test"].join(
      ":",
    ),
    ["postgresql://postgres", "pw@127.0.0.1:54322/candidate_profile_test"].join(
      ":",
    ),
    ["postgresql://postgres", "pw@127.0.0.1:55449/production"].join(":"),
    [
      "postgresql://postgres",
      "pw@127.0.0.1:55449/candidate_profile_test?sslmode=require",
    ].join(":"),
    [
      "postgresql://wrong_user",
      "pw@127.0.0.1:55449/candidate_profile_test",
    ].join(":"),
  ]) {
    assert.throws(() =>
      assertDisposableLocalDatabaseUrl(
        unsafeUrl,
        55449,
        "candidate_profile_test",
        "postgres",
      ),
    );
  }
  const prevEnv = process.env.PHASE1_DISPOSABLE_DATABASE_URL;
  process.env.PHASE1_DISPOSABLE_DATABASE_URL =
    "postgresql://should-be-stripped";
  try {
    const clean = buildSanitizedChildEnv();
    assert.equal("PHASE1_DISPOSABLE_DATABASE_URL" in clean, false);
    assert.equal("DATABASE_URL" in clean, false);
    assert.equal("SUPABASE_URL" in clean, false);
  } finally {
    if (prevEnv === undefined)
      delete process.env.PHASE1_DISPOSABLE_DATABASE_URL;
    else process.env.PHASE1_DISPOSABLE_DATABASE_URL = prevEnv;
  }
});

test("real Python native host enforces origin, private config, frame size, schema, capability, and offline bounds", async () => {
  const python = findPython();
  const tempDir = mkdtempSync(join(tmpdir(), "automated-apply-native-proto-"));
  try {
    const envPath = join(tempDir, "probe.private.env");
    const dbScheme = [
      "postgresql+asyncpg://job_agent_runtime",
      "fictional@127.0.0.1:55499/candidate_profile_test",
    ].join(":");
    const secretKeyName = ["SECRET", "KEY"].join("_");
    const tokenKeyName = ["JOB_AGENT_API", "TOKEN"].join("_");
    const envLines = [
      'ENVIRONMENT="development"',
      `DATABASE_URL="${dbScheme}"`,
      'DATABASE_SCHEMA="public"',
      'DB_REMOTE_ONLY="false"',
      'DB_REQUIRE_TLS="false"',
      `${tokenKeyName}="fictional-protocol-test-token-0000000000"`,
      `${secretKeyName}="fictional-protocol-secret-key-0000000000"`,
      'LOCAL_AGENT_ENDPOINT="http://127.0.0.1:18099"',
      'CHROME_NATIVE_MESSAGING_ENABLED="true"',
      `CHROME_EXTENSION_ID="${EXPECTED_ID}"`,
      'APPLICATION_SUBMISSION_ENABLED="false"',
      'GMAIL_SENDING_ENABLED="false"',
      'AUTOMATION_EXECUTION_ENABLED="false"',
      'AGY_ENABLED="false"',
    ];
    writeFileSync(envPath, envLines.join("\n") + "\n", { mode: 0o600 });
    const validOrigin = `chrome-extension://${EXPECTED_ID}/`;
    const validFrame = encodeFrame({
      version: 1,
      request_id: crypto.randomUUID(),
      command: "health",
    });

    // 1. Insecure file permissions (0o644) -> native_private_configuration_required
    chmodSync(envPath, 0o644);
    const insecurePerm = await runNativeFrame(
      python,
      envPath,
      validOrigin,
      validFrame,
    );
    assert.equal(insecurePerm.ok, false);
    assert.equal(
      insecurePerm.error_code,
      "native_private_configuration_required",
    );
    chmodSync(envPath, 0o600);

    // 2. Wrong / stale extension origin -> native_origin_denied
    const wrongOrigin = await runNativeFrame(
      python,
      envPath,
      `chrome-extension://${"a".repeat(32)}/`,
      validFrame,
    );
    assert.equal(wrongOrigin.ok, false);
    assert.equal(wrongOrigin.error_code, "native_origin_denied");

    // 3. Zero-length frame -> native_message_size
    const zeroHeader = Buffer.alloc(4);
    zeroHeader.writeUInt32LE(0, 0);
    const zeroFrame = await runNativeFrame(
      python,
      envPath,
      validOrigin,
      zeroHeader,
    );
    assert.equal(zeroFrame.ok, false);
    assert.equal(zeroFrame.error_code, "native_message_size");

    // 4. Oversized frame (> 262144 bytes) -> native_message_size
    const oversizedHeader = Buffer.alloc(4);
    oversizedHeader.writeUInt32LE(262145, 0);
    const oversized = await runNativeFrame(
      python,
      envPath,
      validOrigin,
      oversizedHeader,
    );
    assert.equal(oversized.ok, false);
    assert.equal(oversized.error_code, "native_message_size");

    // 5. Malformed JSON payload -> native_invalid_message
    const malformed = await runNativeFrame(
      python,
      envPath,
      validOrigin,
      encodeFrame("{not-json"),
    );
    assert.equal(malformed.ok, false);
    assert.equal(malformed.error_code, "native_invalid_message");

    // 6. Truncated frame on closed stdin -> native_truncated_message
    const truncatedHeader = Buffer.alloc(4);
    truncatedHeader.writeUInt32LE(50, 0);
    const truncated = await runNativeFrame(
      python,
      envPath,
      validOrigin,
      Buffer.concat([truncatedHeader, Buffer.from("short")]),
      true,
    );
    assert.equal(truncated.ok, false);
    assert.equal(truncated.error_code, "native_truncated_message");

    // 7. Disallowed capability command -> native_capability_denied
    const deniedCap = await runNativeFrame(
      python,
      envPath,
      validOrigin,
      encodeFrame({
        version: 1,
        request_id: crypto.randomUUID(),
        command: "get_application_policy",
      }),
    );
    assert.equal(deniedCap.ok, false);
    assert.equal(deniedCap.error_code, "native_capability_denied");

    // 8. Refused loopback endpoint -> backend_offline (leaving stdin open like Chrome)
    const offline = await runNativeFrame(
      python,
      envPath,
      validOrigin,
      validFrame,
      false,
    );
    assert.equal(offline.ok, false);
    assert.equal(offline.error_code, "backend_offline");
  } finally {
    rmSync(tempDir, { recursive: true, force: true });
  }
});
