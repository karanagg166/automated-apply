import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { cpSync, mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

function fixture() {
  const root = mkdtempSync(join(tmpdir(), "automated-apply-build-fictional-"));
  cpSync(new URL("../", import.meta.url), root, {
    recursive: true,
    filter: (source) =>
      !/\/(node_modules|dist|dist-edge|tests)(\/|$)/.test(source),
  });
  return root;
}
test("browser builds pin separate native names with the same identity and permissions", () => {
  const root = fixture();
  const original = JSON.parse(readFileSync(join(root, "manifest.json")));
  for (const browser of ["chrome", "brave", "edge"]) {
    execFileSync(process.execPath, [
      join(root, "build.mjs"),
      `--browser=${browser}`,
    ]);
    const host =
      browser === "chrome"
        ? "com.automated_apply.agent"
        : `com.automated_apply.${browser}`;
    const info = JSON.parse(readFileSync(join(root, "dist/build-info.json")));
    assert.equal(info.native_host, host);
    assert.equal(info.extension_id, "gdjbmkffcpicbpiikcohlmokkmcpipgp");
    assert.deepEqual(
      JSON.parse(readFileSync(join(root, "dist/manifest.json"))),
      original,
    );
    for (const name of [
      "chrome-profile.js",
      "preview.js",
      "form-bridge.js",
      "background.js",
      "task-coordinator.js",
      "settings.js",
      "settings.html",
    ]) {
      assert.equal(
        readFileSync(join(root, "dist", name), "utf8"),
        readFileSync(join(root, name), "utf8").replaceAll(
          "com.automated_apply.agent",
          host,
        ),
      );
    }
  }
});
test("unknown targets cannot overwrite an existing valid bundle", () => {
  const root = fixture();
  execFileSync(process.execPath, [join(root, "build.mjs"), "--browser=brave"]);
  const before = readFileSync(join(root, "dist/build-info.json"), "utf8");
  for (const flag of [
    "--browser=safari",
    "--browser=../../untrusted",
    "brave",
  ]) {
    assert.throws(() =>
      execFileSync(process.execPath, [join(root, "build.mjs"), flag], {
        stdio: "pipe",
      }),
    );
    assert.equal(
      readFileSync(join(root, "dist/build-info.json"), "utf8"),
      before,
    );
  }
});

test("ordinary build defaults to the Brave host while preserving extension identity", () => {
  const root = fixture();
  execFileSync(process.execPath, [join(root, "build.mjs")]);
  const info = JSON.parse(readFileSync(join(root, "dist/build-info.json")));
  assert.equal(info.browser, "brave");
  assert.equal(info.native_host, "com.automated_apply.brave");
  assert.equal(info.extension_id, "gdjbmkffcpicbpiikcohlmokkmcpipgp");
});

test("the retained Edge release does not overwrite the Brave build", () => {
  const root = fixture();
  const build = (flags) =>
    execFileSync(process.execPath, [join(root, "build.mjs"), ...flags]);
  build([]);
  const brave = readFileSync(join(root, "dist/build-info.json"), "utf8");
  build(["--browser=edge", "--output=dist-edge"]);
  assert.equal(readFileSync(join(root, "dist/build-info.json"), "utf8"), brave);
  const info = JSON.parse(
    readFileSync(join(root, "dist-edge/build-info.json")),
  );
  assert.equal(info.native_host, "com.automated_apply.edge");
  assert.equal(info.extension_id, JSON.parse(brave).extension_id);
});
