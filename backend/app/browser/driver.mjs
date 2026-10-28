// Private JSON-lines transport. Each inspected document keeps its own tab and guard.
import { chromium } from "../../../frontend/node_modules/@playwright/test/index.mjs";
import { formDOM } from "../../../extension/form-dom.js";
import { submissionDOM } from "../../../extension/submission-dom.js";
import { fixtureContract, reviewedBody } from "./submission-guard.mjs";
import { createHash } from "node:crypto";
import { createInterface } from "node:readline";
import {
  mkdirSync,
  lstatSync,
  realpathSync,
  existsSync,
  readdirSync,
  writeFileSync,
  readFileSync,
  unlinkSync,
} from "node:fs";
import { resolve } from "node:path";
let context,
  page,
  current,
  intentionalPage = false,
  manualLogin = false;
const states = new Map(),
  documents = new Map();
const send = (x) => process.stdout.write(JSON.stringify(x) + "\n");
const allowedHost = (url) =>
  [
    "boards.greenhouse.io",
    "job-boards.greenhouse.io",
    "jobs.lever.co",
  ].includes(url.hostname) ||
  (url.hostname === "docs.google.com" && url.pathname.startsWith("/forms/"));
async function evaluateForm(
  state,
  request = { operation: "inspect" },
  byValue = true,
) {
  const result = await state.cdp.send("Runtime.callFunctionOn", {
    functionDeclaration: formDOM.toString(),
    executionContextId: state.world,
    arguments: [{ value: request }],
    returnByValue: byValue,
    awaitPromise: true,
  });
  if (result.exceptionDetails) throw Error("isolated_inspector_failed");
  return byValue ? result.result.value : result.result.objectId;
}
async function evaluateSubmission(state, request) {
  const r = await state.cdp.send("Runtime.callFunctionOn", {
    functionDeclaration: submissionDOM.toString(),
    executionContextId: state.world,
    arguments: [{ value: request }],
    returnByValue: true,
    awaitPromise: true,
  });
  if (r.exceptionDetails) throw Error("submission_document_changed");
  return r.result.value;
}
async function launch(req) {
  const profile = resolve(req.profile);
  if (
    !profile.endsWith("/automated-apply-automation") ||
    profile.includes("Google/Chrome")
  )
    throw Error("dedicated_profile_required");
  mkdirSync(profile, { recursive: true, mode: 0o700 });
  if (
    lstatSync(profile).isSymbolicLink() ||
    realpathSync(profile) !== profile ||
    lstatSync(profile).mode & 0o077
  )
    throw Error("private_profile_required");
  const marker = resolve(profile, "automated-apply-profile");
  if (!existsSync(marker)) {
    if (readdirSync(profile).length)
      throw Error("existing_profile_not_authorized");
    writeFileSync(marker, "automated-apply-dedicated-v1", {
      mode: 0o600,
      flag: "wx",
    });
  }
  if (
    lstatSync(marker).isSymbolicLink() ||
    readFileSync(marker, "utf8") !== "automated-apply-dedicated-v1"
  )
    throw Error("dedicated_profile_required");
  // Remove only task-named orphan uploads after an interrupted browser process.
  for (const name of readdirSync(profile)) {
    if (/^upload-[a-f0-9-]{36}\.pdf$/.test(name))
      unlinkSync(resolve(profile, name));
  }
  context = await chromium.launchPersistentContext(profile, {
    channel: "chromium",
    headless: req.headless === true,
    serviceWorkers: "block",
    acceptDownloads: false,
    args: ["--disable-background-networking", "--disable-sync"],
  });
  if (!manualLogin) {
    await context.routeWebSocket("**/*", (ws) => {
      for (const state of states.values()) state.violations++;
      ws.close();
    });
    await context.route("**/*", async (route) => {
      const request = route.request();
      let state;
      try {
        state = states.get(request.frame().page());
      } catch {}
      const dest = new URL(request.url());
      const grant = state?.submission;
      if (grant && Date.now() < grant.deadline && !state.violations) {
        if (
          request.method() === "POST" &&
          request.url() === grant.request_url &&
          request.frame() === state.page.mainFrame() &&
          request.isNavigationRequest() &&
          !grant.dispatched
        ) {
          const body = await reviewedBody(
            request,
            grant.entries,
            state.uploads,
          );
          if (!body) {
            state.violations++;
            await route.abort();
            return;
          }
          grant.dispatched = true; // Before handing the only request to the network.
          try {
            // Chromium transparently retries a continued POST on an empty response.
            // Fetch the intercepted native request once and fulfill its navigation;
            // transport retries and automatic redirects are explicitly disabled.
            const response = await route.fetch({
              postData: body.postData,
              headers: {
                ...request.headers(),
                "content-type": body.contentType,
                "x-automated-apply-correlation": grant.correlation,
              },
              maxRetries: 0,
              maxRedirects: 0,
              timeout: Math.max(1, grant.deadline - Date.now()),
            });
            if (Date.now() >= grant.deadline) await route.abort("failed");
            else await route.fulfill({ response });
          } catch {
            // Never expose an empty socket to Chromium's automatic POST retry path.
            await route.abort("failed").catch(() => {});
          }
          return;
        }
        const from = request.redirectedFrom();
        if (
          request.method() === "GET" &&
          request.url() === grant.confirmation_url &&
          grant.dispatched &&
          !grant.confirmationRead &&
          from?.url() === grant.request_url &&
          from.method() === "POST" &&
          request.frame() === state.page.mainFrame() &&
          request.isNavigationRequest()
        ) {
          grant.confirmationRead = true;
          await route.continue();
          return;
        }
      }
      if (
        !state ||
        state.guarded ||
        !["GET", "HEAD"].includes(request.method()) ||
        dest.origin !== state.origin ||
        (request.isNavigationRequest() && request.url() !== state.url)
      ) {
        if (state) state.violations++;
        await route.abort();
        return;
      }
      await route.continue();
    });
    context.on("page", (p) => {
      if (!intentionalPage) {
        for (const state of states.values()) state.violations++;
        void p.close();
      }
    });
  }
}
for await (const line of createInterface({ input: process.stdin })) {
  try {
    if (line.length > 8 * 1024 * 1024) throw Error("message_size");
    const req = JSON.parse(line);
    if (req.operation === "open" || req.operation === "sign_in") {
      const url = new URL(req.url);
      const fixture =
        req.fixture_origin &&
        url.origin === req.fixture_origin &&
        url.hostname === "127.0.0.1" &&
        url.protocol === "http:";
      if (
        !fixture &&
        (url.protocol !== "https:" ||
          !allowedHost(url) ||
          url.search ||
          url.hash)
      )
        throw Error("unsupported_url");
      if (url.username || url.password || documents.size >= 10)
        throw Error("unsupported_url_or_tab_limit");
      if (!context) {
        manualLogin = req.operation === "sign_in";
        await launch(req);
      }
      if (manualLogin !== (req.operation === "sign_in"))
        throw Error("separate_sign_in_session_required");
      intentionalPage = true;
      try {
        page =
          documents.size === 0 && context.pages().length
            ? context.pages()[0]
            : await context.newPage();
      } finally {
        intentionalPage = false;
      }
      current = {
        page,
        origin: url.origin,
        url: url.href,
        violations: 0,
        guarded: false,
        inspection: null,
        profile: resolve(req.profile),
        fixtureOrigin: fixture ? req.fixture_origin : null,
        uploads: [],
      };
      states.set(page, current);
      await page.goto(req.url, {
        waitUntil: "domcontentloaded",
        timeout: 20000,
      });
      if (manualLogin) {
        send({ state: "manual_sign_in", submitted: false });
        continue;
      }
      current.cdp = await context.newCDPSession(page);
      const tree = await current.cdp.send("Page.getFrameTree");
      const world = await current.cdp.send("Page.createIsolatedWorld", {
        frameId: tree.frameTree.frame.id,
        worldName: "automated-apply-private-inspector",
      });
      current.world = world.executionContextId;
      current.inspection = await evaluateForm(current);
      documents.set(current.inspection.document_id, current);
      send({
        inspection: current.inspection,
        violations: current.violations,
        browser: context.browser().version(),
      });
    } else if (req.operation === "close") {
      await context?.close();
      for (const state of states.values())
        for (const path of state.uploads || []) {
          if (existsSync(path)) unlinkSync(path);
        }
      send({ closed: true });
      break;
    } else {
      if (manualLogin) throw Error("manual_sign_in_has_no_agent_actions");
      if (req.document_id) {
        const saved = documents.get(req.document_id);
        if (!saved) throw Error("stale_document");
        current = saved;
        page = saved.page;
      }
      if (!current || page.isClosed() || page.url() !== current.url)
        throw Error("changed_page");
      if (req.operation === "inspect") {
        current.inspection = await evaluateForm(current);
        send({
          inspection: current.inspection,
          violations: current.violations,
        });
      } else if (req.operation === "submission_review") {
        if (current.violations || current.submissionAttempted)
          throw Error("unsafe_or_consumed_document");
        const contract = fixtureContract(
          current.url,
          current.fixtureOrigin,
          "pending",
        );
        const review = await evaluateSubmission(current, {
          operation: "review",
          ...contract,
          document_id: req.document_id,
          actions: req.actions,
        });
        current.submissionEntries = review.entries;
        delete review.entries; // Values stay in the browser process, never in receipt/audit output.
        send(review);
      } else if (req.operation === "submit_application") {
        if (
          current.violations ||
          current.submissionAttempted ||
          !current.submissionEntries
        )
          throw Error("unsafe_or_consumed_document");
        if (!/^[a-f0-9-]{36}$/.test(req.idempotency_key))
          throw Error("correlation_required");
        const contract = fixtureContract(
          current.url,
          current.fixtureOrigin,
          req.idempotency_key,
        );
        const deadline = Math.min(
          Date.parse(req.expires_at),
          Date.now() + 15000,
        );
        if (!Number.isFinite(deadline) || deadline <= Date.now())
          throw Error("expired_submission");
        // A failure here is proven pre-dispatch. After arming, all ambiguity is uncertain.
        try {
          await evaluateSubmission(current, {
            operation: "validate",
            document_digest: req.document_digest,
          });
        } catch {
          send({ state: "manual_required", preflight_failed: true });
          continue;
        }
        current.submissionAttempted = true;
        current.guarded = true;
        current.submission = {
          ...contract,
          correlation: req.idempotency_key,
          deadline,
          entries: current.submissionEntries,
          dispatched: false,
          confirmationRead: false,
        };
        const state = current;
        let response = null;
        const responseReady = page
          .waitForResponse(
            (r) =>
              (r.url() === contract.request_url &&
                r.request().method() === "POST" &&
                r.status() !== 303) ||
              (r.url() === contract.confirmation_url &&
                r.request().method() === "GET"),
            { timeout: Math.max(1, deadline - Date.now()) },
          )
          .then(
            (r) => r,
            () => null,
          );
        try {
          await evaluateSubmission(state, {
            operation: "submit",
            document_digest: req.document_digest,
          });
        } catch {} // Navigation can destroy the isolated context after the POST was dispatched.
        const received = await responseReady;
        if (received) {
          try {
            const raw = await received.body();
            if (raw.length <= 65536)
              response = {
                url: received.url(),
                status: received.status(),
                content_type: received.headers()["content-type"] || "",
                body: raw.toString("utf8"),
              };
          } catch {}
        }
        state.submission = null; // Return to default-deny even when acknowledgment was lost.
        send({
          state: "verification_required",
          response,
          dispatched: state.submissionAttempted,
          violations: state.violations,
        });
      } else if (req.operation === "fill") {
        if (current.violations)
          throw Error("unsafe_page_or_submission_attempt");
        current.guarded = true;
        const result = await evaluateForm(current, {
          operation: "fill",
          document_id: req.document_id,
          actions: req.actions.filter((a) => a.kind !== "file"),
          emit_events: true,
        });
        if (!["form_filled", "needs_input"].includes(result.state)) {
          send({ ...result, violations: current.violations });
          continue;
        }
        for (const action of req.actions.filter((a) => a.kind === "file")) {
          const metadata = current.inspection?.fields.find(
            (f) =>
              f.field_id === action.field_id &&
              f.kind === "file" &&
              /resume/i.test(f.label),
          );
          if (!metadata || !req.pdf || !action.safe_reference)
            throw Error("verified_pdf_required");
          const buffer = Buffer.from(req.pdf, "base64");
          if (
            "canonical_pdf:" +
              createHash("sha256").update(buffer).digest("hex") !==
            action.safe_reference
          )
            throw Error("pdf_digest_mismatch");
          const objectId = await evaluateForm(
            current,
            {
              operation: "upload_element",
              document_id: req.document_id,
              field_id: action.field_id,
            },
            false,
          );
          if (!objectId) throw Error("changed_upload");
          const upload = resolve(
            current.profile,
            "upload-" + crypto.randomUUID() + ".pdf",
          );
          writeFileSync(upload, buffer, { mode: 0o600, flag: "wx" });
          try {
            await current.cdp.send("DOM.setFileInputFiles", {
              files: [upload],
              objectId,
            });
          } finally {
            current.uploads.push(upload);
            await current.cdp.send("Runtime.releaseObject", { objectId });
          }
          result.results.push({ field_id: action.field_id, status: "filled" });
        }
        await page.waitForTimeout(200);
        const verified = await evaluateForm(current, {
          operation: "verify_fill",
          document_id: req.document_id,
        });
        // Framework state may revert an optional field asynchronously. Keep the
        // receipt truthful as well as the overall completion state.
        for (const check of verified.results || []) {
          const field = result.results.find(
            (r) => r.field_id === check.field_id,
          );
          if (field) field.status = check.status;
        }
        send({
          ...result,
          state:
            current.violations || verified.state === "manual_required"
              ? "manual_required"
              : result.results.some((r) => r.status !== "filled")
                ? "needs_input"
                : verified.state,
          violations: current.violations,
          submitted: false,
        });
      } else if (req.operation === "next") {
        if (current.violations)
          throw Error("unsafe_page_or_submission_attempt");
        current.guarded = true;
        const result = await evaluateForm(current, {
          operation: "next",
          document_id: req.document_id,
        });
        await page.waitForTimeout(200);
        current.inspection = await evaluateForm(current);
        send({
          ...result,
          violations: current.violations,
          inspection: current.inspection,
        });
      } else throw Error("unknown_operation");
    }
  } catch {
    send({
      state: "manual_required",
      error_code: "browser_operation_failed",
      violations: current?.violations || 0,
      submitted: false,
    });
  }
}
await context?.close();
for (const state of states.values())
  for (const path of state.uploads || []) {
    if (existsSync(path)) unlinkSync(path);
  }
