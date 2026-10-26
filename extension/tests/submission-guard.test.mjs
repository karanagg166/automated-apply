import assert from "node:assert/strict";
import test from "node:test";
import {
  fixtureContract,
  matchesBody,
} from "../../backend/app/browser/submission-guard.mjs";
import { readFileSync } from "node:fs";

test("fixture-only submission contracts reject live employers and redirects", () => {
  const origin = "http://127.0.0.1:18765";
  for (const adapter of ["greenhouse", "lever", "google"]) {
    const c = fixtureContract(
      `${origin}/fixtures/${adapter}/fictional/jobs/1/apply`,
      origin,
      "correlation",
    );
    assert.equal(c.adapter, adapter);
    assert.equal(
      c.confirmation_url,
      `${origin}/fixtures/${adapter}/fictional/jobs/1/confirmation/correlation`,
    );
  }
  for (const url of [
    "https://jobs.lever.co/example/1",
    `${origin}/fixtures/other/a/jobs/1/apply`,
    `${origin}/fixtures/lever/a/jobs/1/apply?redirect=evil`,
    "http://localhost:18765/fixtures/lever/a/jobs/1/apply",
    "http://127.0.0.1:18766/fixtures/lever/a/jobs/1/apply",
  ]) {
    assert.throws(() => fixtureContract(url, origin, "correlation"));
  }
});
test("one-request guard validates the entire form body, including duplicate names", async () => {
  const request = (body) => ({
    postDataBuffer: () => Buffer.from(body),
    headers: () => ({ "content-type": "application/x-www-form-urlencoded" }),
  });
  assert.equal(
    await matchesBody(request("name=Alex+Example&email=alex%40example.com"), [
      ["name", "Alex Example"],
      ["email", "alex@example.com"],
    ]),
    true,
  );
  for (const body of [
    "name=Different&email=alex%40example.com",
    "name=Alex+Example&email=alex%40example.com&email=attacker",
    "name=Alex+Example",
  ]) {
    assert.equal(
      await matchesBody(request(body), [
        ["name", "Alex Example"],
        ["email", "alex@example.com"],
      ]),
      false,
    );
  }
});
test("manual extension/native boundary cannot issue a submission operation", () => {
  const files = ["form-bridge.js", "background.js"];
  for (const file of files) {
    const source = readFileSync(new URL(`../${file}`, import.meta.url), "utf8");
    assert.equal(source.includes('operation: "submit_application"'), false);
    assert.equal(source.includes("submissionDOM"), false);
  }
  const manifest = JSON.parse(
    readFileSync(new URL("../manifest.json", import.meta.url)),
  );
  assert.equal(manifest.host_permissions, undefined);
});

test("multipart gate forwards only the reviewed canonical PDF despite CDP omitted bytes", async () => {
  const { mkdtempSync, writeFileSync, rmSync } = await import("node:fs");
  const { tmpdir } = await import("node:os");
  const { join } = await import("node:path");
  const { createHash } = await import("node:crypto");
  const { reviewedBody } =
    await import("../../backend/app/browser/submission-guard.mjs");
  const dir = mkdtempSync(join(tmpdir(), "fixture-submit-pdf-"));
  try {
    const bytes = Buffer.from("%PDF-1.4\nFictional only\n%%EOF");
    const path = join(dir, "resume.pdf");
    writeFileSync(path, bytes, { mode: 0o600 });
    const expected = [
      ["name", "Alex Example"],
      [
        "resume",
        {
          sha256: createHash("sha256").update(bytes).digest("hex"),
          size: bytes.length,
          type: "application/pdf",
          name: "resume.pdf",
        },
      ],
    ];
    const native = new FormData();
    native.append("name", "Alex Example");
    native.append(
      "resume",
      new Blob([], { type: "application/pdf" }),
      "resume.pdf",
    );
    const serialized = new Request("http://127.0.0.1/", {
      method: "POST",
      body: native,
    });
    const raw = Buffer.from(await serialized.arrayBuffer());
    const request = {
      postDataBuffer: () => raw,
      headers: () => ({
        "content-type": serialized.headers.get("content-type"),
      }),
    };
    assert.equal(await reviewedBody(request, expected), null);
    const allowed = await reviewedBody(request, expected, [path]);
    const sent = await new Response(allowed.postData, {
      headers: { "content-type": allowed.contentType },
    }).formData();
    assert.deepEqual(
      Buffer.from(await sent.get("resume").arrayBuffer()),
      bytes,
    );
    writeFileSync(path, "changed PDF");
    assert.equal(await reviewedBody(request, expected, [path]), null);
  } finally {
    rmSync(dir, { recursive: true });
  }
});
