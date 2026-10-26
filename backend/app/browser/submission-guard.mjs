// Fixed fixture contracts and exact body comparison for the one permitted request.
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
export function fixtureContract(url, fixtureOrigin, correlation) {
  const p = new URL(url);
  const match =
    /^\/fixtures\/(greenhouse|lever|google)\/([a-z0-9-]{1,40})\/jobs\/([a-z0-9-]{1,40})\/apply$/.exec(
      p.pathname,
    );
  if (
    !fixtureOrigin ||
    p.origin !== fixtureOrigin ||
    p.protocol !== "http:" ||
    p.hostname !== "127.0.0.1" ||
    p.search ||
    p.hash ||
    p.username ||
    p.password ||
    !match
  )
    throw Error("fixture_submission_only");
  const base = p.origin + p.pathname.slice(0, -6);
  return {
    adapter: match[1],
    origin: p.origin,
    application_url: url,
    request_url: base + "/applications",
    confirmation_url: base + "/confirmation/" + correlation,
    receipt_url: base + "/receipts/" + correlation,
  };
}
const sha = (bytes) => createHash("sha256").update(bytes).digest("hex");
export async function reviewedBody(request, expected, uploads = []) {
  const raw = request.postDataBuffer();
  const type = request.headers()["content-type"] || "";
  if (
    !raw ||
    raw.length > 6 * 1024 * 1024 ||
    !/^(application\/x-www-form-urlencoded|multipart\/form-data)(;|$)/.test(
      type,
    )
  )
    return null;
  try {
    const files = new Map(
      uploads.map((path) => {
        const bytes = readFileSync(path);
        return [sha(bytes), bytes];
      }),
    );
    const form = await new Response(raw, {
      headers: { "content-type": type },
    }).formData();
    const entries = [];
    for (const [name, value] of form) {
      if (typeof value === "string") entries.push([name, value]);
      else {
        const actual = {
          sha256: sha(Buffer.from(await value.arrayBuffer())),
          size: value.size,
          type: value.type,
          name: value.name,
        };
        const wanted = expected[entries.length];
        // CDP omits multipart file bytes. Rebuild from the private canonical PDF;
        // no omitted/page-supplied binary is sent to the fixture employer.
        if (
          actual.size === 0 &&
          wanted?.[0] === name &&
          files.has(wanted[1].sha256) &&
          actual.type === wanted[1].type &&
          actual.name === wanted[1].name
        )
          entries.push([name, wanted[1]]);
        else entries.push([name, actual]);
      }
    }
    if (JSON.stringify(entries) !== JSON.stringify(expected)) return null;
    if (!type.startsWith("multipart/"))
      return { postData: raw, contentType: type };
    const canonical = new FormData();
    for (const [name, value] of expected) {
      if (typeof value === "string") canonical.append(name, value);
      else {
        const bytes = files.get(value.sha256);
        if (!bytes || bytes.length !== value.size) return null;
        canonical.append(
          name,
          new Blob([bytes], { type: value.type }),
          value.name,
        );
      }
    }
    const serialized = new Request("http://127.0.0.1/", {
      method: "POST",
      body: canonical,
    });
    return {
      postData: Buffer.from(await serialized.arrayBuffer()),
      contentType: serialized.headers.get("content-type"),
    };
  } catch {
    return null;
  }
}
export async function matchesBody(request, expected) {
  return !!(await reviewedBody(request, expected));
}
