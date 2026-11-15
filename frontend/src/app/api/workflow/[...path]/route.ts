import { request as httpRequest } from "node:http";
import { NextRequest } from "next/server";
import { privateSocketPath } from "@/lib/private-socket";
import { permittedWorkflowRoute } from "@/lib/workflow-routes";
import {
  allowedRequest,
  configuration,
  SESSION_COOKIE,
  validCsrf,
  validSession,
} from "@/lib/security";
import { readBoundedBody, RequestLimitError } from "@/lib/http-boundary";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
function reply(value: unknown, status: number) {
  return Response.json(value, {
    status,
    headers: { "Cache-Control": "no-store" },
  });
}
async function proxy(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> },
) {
  const mutation = request.method !== "GET";
  const session = request.cookies.get(SESSION_COOKIE)?.value;
  if (!allowedRequest(request, mutation) || !validSession(session))
    return reply({ error: "owner_authentication_required" }, 401);
  if (mutation && !validCsrf(session!, request.headers.get("x-csrf-token")))
    return reply({ error: "csrf_required" }, 403);
  const { path } = await context.params;
  const route = path.join("/");
  if (request.nextUrl.search || !permittedWorkflowRoute(route, request.method))
    return reply({ error: "workflow_route_not_found" }, 404);
  try {
    const target = new URL(
      process.env.RUST_AGENT_URL || "http://127.0.0.1:8011",
    );
    const token = process.env.JOB_AGENT_API_TOKEN;
    if (
      target.protocol !== "http:" ||
      target.hostname !== "127.0.0.1" ||
      !target.port ||
      Number(target.port) <= 1024 ||
      target.pathname !== "/" ||
      target.username ||
      target.password ||
      target.search ||
      target.hash ||
      !token ||
      !/^[\x21-\x7e]{32,512}$/.test(token)
    )
      return reply({ error: "workflow_configuration_required" }, 503);
    if (
      mutation &&
      request.headers.get("content-type")?.split(";")[0] !== "application/json"
    )
      return reply({ error: "json_required" }, 415);
    const socketPath = await privateSocketPath(
      process.env.RUST_AGENT_UNIX_SOCKET,
    );
    const body = mutation
      ? await readBoundedBody(request, 65536)
      : Buffer.alloc(0);
    const headers: Record<string, string> = {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
      "Content-Length": String(body.length),
    };
    if (
      !socketPath &&
      configuration().secure &&
      process.env.RUST_AGENT_TRUST_LOOPBACK_PROXY === "true"
    )
      headers["X-Forwarded-Proto"] = "https";
    // A single direct loopback request: no proxy environment, redirects or write retries.
    return await new Promise<Response>((resolve) => {
      const upstream = httpRequest(
        {
          socketPath,
          hostname: target.hostname,
          port: target.port,
          path: `/api/v1/rust-agent/${route}`,
          method: request.method,
          headers,
          agent: false,
        },
        (incoming) => {
          const chunks: Buffer[] = [];
          let size = 0;
          incoming.on("data", (chunk: Buffer) => {
            size += chunk.length;
            if (size > 524288) upstream.destroy();
            else chunks.push(chunk);
          });
          incoming.on("error", () =>
            resolve(reply({ error: "workflow_response_unavailable" }, 502)),
          );
          incoming.on("end", () => {
            const status = incoming.statusCode || 502;
            try {
              const data: unknown = JSON.parse(
                Buffer.concat(chunks).toString("utf8"),
              );
              resolve(
                status >= 200 && status < 300
                  ? reply(data, status)
                  : reply(
                      {
                        error:
                          typeof data === "object" &&
                          data !== null &&
                          "error" in data &&
                          typeof data.error === "string" &&
                          /^[a-z_]{1,96}$/.test(data.error)
                            ? data.error
                            : "workflow_request_failed",
                      },
                      status >= 400 && status <= 599 ? status : 502,
                    ),
              );
            } catch {
              resolve(reply({ error: "workflow_response_unavailable" }, 502));
            }
          });
        },
      );
      const deadline = setTimeout(() => upstream.destroy(), 25000);
      upstream.on("close", () => clearTimeout(deadline));
      upstream.on("error", () =>
        resolve(
          reply(
            { error: "workflow_unavailable_check_status_before_retry" },
            502,
          ),
        ),
      );
      upstream.end(body);
    });
  } catch (error) {
    return reply(
      {
        error:
          error instanceof RequestLimitError
            ? "workflow_request_limit"
            : "workflow_unavailable",
      },
      error instanceof RequestLimitError ? error.status : 503,
    );
  }
}
export { proxy as GET, proxy as PUT, proxy as POST };
