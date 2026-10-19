import {
  createHmac,
  randomBytes,
  scryptSync,
  timingSafeEqual,
} from "node:crypto";
export const SESSION_COOKIE = "aa_owner";
export const CSRF_COOKIE = "aa_csrf";
export const SESSION_SECONDS = 60 * 60 * 8;
export function configuration() {
  const origin = new URL(
    process.env.FRONTEND_ORIGIN || "http://localhost:3000",
  );
  if (
    origin.pathname !== "/" ||
    origin.search ||
    origin.hash ||
    origin.username ||
    origin.password
  )
    throw new Error("Invalid frontend origin");
  const local = ["localhost", "127.0.0.1", "[::1]"].includes(origin.hostname);
  if (
    origin.protocol !== "https:" &&
    !(local && process.env.FRONTEND_LOCAL_HTTP === "true")
  )
    throw new Error("HTTPS is required");
  const secret = process.env.FRONTEND_SESSION_SECRET;
  if (!secret || secret.length < 32)
    throw new Error("Configure frontend session secret");
  return {
    origin: origin.origin,
    secret,
    secure: origin.protocol === "https:",
  };
}
function sign(value: string) {
  return createHmac("sha256", configuration().secret)
    .update(value)
    .digest("base64url");
}
function equal(a: string, b: string) {
  const aa = Buffer.from(a),
    bb = Buffer.from(b);
  return aa.length === bb.length && timingSafeEqual(aa, bb);
}
export function issueSession(now = Date.now()) {
  const payload = Buffer.from(
    JSON.stringify({
      nonce: randomBytes(32).toString("base64url"),
      expires: now + SESSION_SECONDS * 1000,
    }),
  ).toString("base64url");
  return `${payload}.${sign(payload)}`;
}
export function validSession(value: string | undefined, now = Date.now()) {
  try {
    if (!value || value.length > 512) return false;
    const [payload, signature, ...extra] = value.split(".");
    if (extra.length || !signature || !equal(sign(payload), signature))
      return false;
    const claims = JSON.parse(Buffer.from(payload, "base64url").toString());
    return (
      typeof claims.nonce === "string" &&
      claims.nonce.length === 43 &&
      Number.isSafeInteger(claims.expires) &&
      claims.expires > now &&
      claims.expires <= now + SESSION_SECONDS * 1000
    );
  } catch {
    return false;
  }
}
export function csrfFor(session: string) {
  return sign(`csrf:${session}`);
}
export function validCsrf(session: string, value: string | null) {
  return !!value && equal(csrfFor(session), value);
}
export function allowedRequest(request: Request, mutation = false) {
  try {
    const { origin } = configuration();
    const url = new URL(request.url);
    const expected = new URL(origin);
    // Standalone Next.js constructs request URLs with its internal bind address.
    // Authenticate the exact external Host and Origin; never trust forwarded Host.
    const internal = ["localhost", "127.0.0.1", "[::1]", "0.0.0.0"].includes(
      url.hostname,
    );
    if (
      url.protocol !== expected.protocol ||
      (!internal && url.origin !== origin) ||
      request.headers.get("host") !== expected.host
    )
      return false;
    const supplied = request.headers.get("origin");
    return mutation ? supplied === origin : !supplied || supplied === origin;
  } catch {
    return false;
  }
}
export function verifyPassword(password: string) {
  const configured = process.env.FRONTEND_PASSWORD_HASH;
  if (!configured || password.length > 256) return false;
  const [salt, hash, ...extra] = configured.split(":");
  if (
    extra.length ||
    !/^[a-f0-9]{32}$/.test(salt) ||
    !/^[a-f0-9]{128}$/.test(hash || "")
  )
    return false;
  return equal(scryptSync(password, salt, 64).toString("hex"), hash);
}
// Single-owner, single Node instance: global login throttle, independent of spoofable forwarding headers.
const attempts: number[] = [];
export function allowLogin(now = Date.now()) {
  while (attempts.length && attempts[0] < now - 15 * 60 * 1000)
    attempts.shift();
  if (attempts.length >= 10) return false;
  attempts.push(now);
  return true;
}
