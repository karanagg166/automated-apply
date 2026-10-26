import { createHash, createHmac, randomUUID } from "node:crypto";
import { NextRequest, NextResponse } from "next/server";
import { readBoundedBody, RequestLimitError } from "@/lib/http-boundary";
import { permittedRoute } from "@/lib/gateway";
import {
  allowedRequest,
  SESSION_COOKIE,
  validCsrf,
  validSession,
} from "@/lib/security";
export const runtime = "nodejs";
export const dynamic = "force-dynamic";
async function proxy(
  req: NextRequest,
  { params }: { params: Promise<{ path: string[] }> },
) {
  const fail = (detail: string, status: number) =>
    NextResponse.json(
      { detail },
      { status, headers: { "Cache-Control": "private, no-store" } },
    );
  const mutation = !["GET", "HEAD"].includes(req.method);
  if (!allowedRequest(req, mutation))
    return fail("Origin or configuration rejected", 403);
  const session = req.cookies.get(SESSION_COOKIE)?.value;
  if (!validSession(session))
    return fail("Sign in to your private workspace", 401);
  if (mutation && !validCsrf(session!, req.headers.get("x-csrf-token")))
    return fail("Security token expired. Reload this page.", 403);
  const path = (await params).path.join("/");
  if (!permittedRoute(path, req.method))
    return fail("Operation is not available", 404);
  const token = process.env.JOB_AGENT_API_TOKEN;
  if (!token)
    return fail("Backend owner token is not configured on the server", 503);
  try {
    const origin = new URL(
      process.env.BACKEND_ORIGIN || "http://127.0.0.1:8000",
    );
    if (
      origin.username ||
      origin.password ||
      origin.pathname !== "/" ||
      origin.search ||
      origin.hash
    )
      return fail("Invalid backend origin", 503);
    if (
      origin.protocol !== "https:" &&
      !["localhost", "127.0.0.1", "[::1]"].includes(origin.hostname)
    )
      return fail("Backend requires HTTPS", 503);
    const url = new URL(`/api/v1/${path}`, origin);
    url.search = req.nextUrl.search;
    const headers = new Headers({ Authorization: `Bearer ${token}` });
    for (const name of ["content-type", "if-match"]) {
      const value = req.headers.get(name);
      if (value) headers.set(name, value);
    }
    const maximum =
      path === "dashboard/resumes" ? 5 * 1024 * 1024 : 1024 * 1024;
    const body = mutation
      ? await readBoundedBody(req, maximum, 20000)
      : undefined;
    if (
      mutation &&
      (/^browser-applications\/[a-f0-9-]{36}\/(authorize-submission|consent|opportunity-approve|company-source-preview|advance-step|resume-page)$/.test(
        path,
      ) ||
        /^application-answers\/drafts\/[a-f0-9-]{36}\/approve-reuse$/.test(
          path,
        ))
    ) {
      const approvalKey = process.env.BROWSER_OWNER_APPROVAL_KEY;
      if (!approvalKey || approvalKey.length < 32)
        return fail("Dashboard owner approval is not configured", 503);
      const timestamp = Math.floor(Date.now() / 1000).toString();
      const nonce = randomUUID().replaceAll("-", "");
      const digest = createHash("sha256")
        .update(body || new Uint8Array())
        .digest("hex");
      const signature = createHmac("sha256", approvalKey)
        .update([req.method, url.pathname, timestamp, nonce, digest].join("\n"))
        .digest("hex");
      headers.set(
        "X-Browser-Owner-Approval",
        `v1:${timestamp}:${nonce}:${signature}`,
      );
    }
    const upstream = await fetch(url, {
      method: req.method,
      headers,
      body: body ? new Uint8Array(body) : undefined,
      cache: "no-store",
      redirect: "error",
      signal: AbortSignal.timeout(path === "dashboard/resumes" ? 20000 : 90000),
    });
    const out = new Headers({
      "Cache-Control": "private, no-store",
      "Content-Type":
        upstream.headers.get("content-type") || "application/json",
      "X-Content-Type-Options": "nosniff",
    });
    for (const name of ["etag", "content-disposition"]) {
      const v = upstream.headers.get(name);
      if (v) out.set(name, v);
    }
    // Google callback goes directly to the backend on the same host. Retain its browser binding.
    if (path === "integrations/gmail/connect/start")
      for (const cookie of upstream.headers.getSetCookie())
        out.append("Set-Cookie", cookie);
    if (upstream.status >= 500)
      return fail(
        "Backend unavailable. Check database and provider health, then retry.",
        upstream.status,
      );
    return new Response(upstream.body, {
      status: upstream.status,
      headers: out,
    });
  } catch (error) {
    if (error instanceof RequestLimitError)
      return fail(error.message, error.status);
    return fail(
      error instanceof Error && error.name === "TimeoutError"
        ? "Request timed out. Check operation history before retrying."
        : "Backend could not be reached",
      504,
    );
  }
}
export {
  proxy as GET,
  proxy as POST,
  proxy as PATCH,
  proxy as PUT,
  proxy as DELETE,
};
