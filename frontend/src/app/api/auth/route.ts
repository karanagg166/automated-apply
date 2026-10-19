import { NextRequest, NextResponse } from "next/server";
import { readBoundedBody, RequestLimitError } from "@/lib/http-boundary";
import {
  allowedRequest,
  allowLogin,
  configuration,
  csrfFor,
  CSRF_COOKIE,
  issueSession,
  SESSION_COOKIE,
  SESSION_SECONDS,
  validCsrf,
  validSession,
  verifyPassword,
} from "@/lib/security";
export const runtime = "nodejs";
export const dynamic = "force-dynamic";
function json(body: object, status = 200) {
  return NextResponse.json(body, {
    status,
    headers: { "Cache-Control": "private, no-store" },
  });
}
export async function GET(req: NextRequest) {
  if (!allowedRequest(req))
    return json({ detail: "Origin or configuration rejected" }, 403);
  const session = req.cookies.get(SESSION_COOKIE)?.value;
  if (!validSession(session))
    return json({ detail: "Sign in to your private workspace" }, 401);
  return json({ authenticated: true, csrf: csrfFor(session!) });
}
export async function POST(req: NextRequest) {
  if (!allowedRequest(req, true))
    return json({ detail: "Origin or configuration rejected" }, 403);
  if (!allowLogin())
    return json({ detail: "Too many login attempts. Wait 15 minutes." }, 429);
  try {
    if (Number(req.headers.get("content-length")) > 2048)
      return json({ detail: "Request too large" }, 413);
    const text = (await readBoundedBody(req, 2048, 5000)).toString("utf8");
    if (text.length > 2048) return json({ detail: "Request too large" }, 413);
    const input = JSON.parse(text);
    if (typeof input.password !== "string" || !verifyPassword(input.password))
      return json(
        { detail: "Unable to sign in. Check your owner passphrase." },
        401,
      );
    const session = issueSession(),
      config = configuration();
    const response = json({ authenticated: true });
    response.cookies.set(SESSION_COOKIE, session, {
      httpOnly: true,
      secure: config.secure,
      sameSite: "strict",
      path: "/",
      maxAge: SESSION_SECONDS,
    });
    response.cookies.set(CSRF_COOKIE, csrfFor(session), {
      httpOnly: false,
      secure: config.secure,
      sameSite: "strict",
      path: "/",
      maxAge: SESSION_SECONDS,
    });
    return response;
  } catch (error) {
    if (error instanceof RequestLimitError)
      return json({ detail: error.message }, error.status);
    return json(
      { detail: "Owner login is not configured or input is invalid" },
      503,
    );
  }
}
export async function DELETE(req: NextRequest) {
  const session = req.cookies.get(SESSION_COOKIE)?.value;
  if (
    !allowedRequest(req, true) ||
    !validSession(session) ||
    !validCsrf(session!, req.headers.get("x-csrf-token"))
  )
    return json({ detail: "Sign in again" }, 403);
  const response = json({ signed_out: true });
  response.cookies.delete(SESSION_COOKIE);
  response.cookies.delete(CSRF_COOKIE);
  return response;
}
