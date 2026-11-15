import { lstat, realpath } from "node:fs/promises";
import { request as httpRequest } from "node:http";
import { basename, dirname, isAbsolute, join } from "node:path";
import { Readable } from "node:stream";

// Match the native clients. Never fall back to TCP after a configured IPC failure.
export async function privateSocketPath(raw: string | undefined) {
  if (raw === undefined) return undefined;
  if (
    !isAbsolute(raw) ||
    Buffer.byteLength(raw) > 100 ||
    raw.includes("\0") ||
    join(dirname(raw), basename(raw)) !== raw
  )
    throw new Error("private_socket_path_required");
  const parent = dirname(raw);
  const uid = process.geteuid?.();
  const directory = await lstat(parent);
  if (
    uid === undefined ||
    !directory.isDirectory() ||
    directory.isSymbolicLink() ||
    directory.uid !== uid ||
    (directory.mode & 0o777) !== 0o700 ||
    (await realpath(parent)) !== parent
  )
    throw new Error("private_socket_directory_required");
  const socket = await lstat(raw);
  if (
    !socket.isSocket() ||
    socket.isSymbolicLink() ||
    socket.uid !== uid ||
    (socket.mode & 0o777) !== 0o600
  )
    throw new Error("private_socket_identity_required");
  return raw;
}

export function privateSocketFetch(
  socketPath: string,
  url: URL,
  options: {
    method: string;
    headers: Headers;
    body?: Uint8Array;
    timeoutMs: number;
  },
): Promise<Response> {
  if (
    url.protocol !== "http:" ||
    url.hostname !== "127.0.0.1" ||
    !url.port ||
    Number(url.port) <= 1024 ||
    url.username ||
    url.password ||
    url.hash
  )
    return Promise.reject(new Error("private_socket_endpoint_required"));
  return new Promise((resolve, reject) => {
    const headers = Object.fromEntries(options.headers.entries());
    // This numeric host identifies the configured service, without DNS or TLS claims.
    headers.host = url.host;
    if (options.body) headers["content-length"] = String(options.body.length);
    const upstream = httpRequest(
      {
        socketPath,
        path: url.pathname + url.search,
        method: options.method,
        headers,
        agent: false,
      },
      (incoming) => {
        const status = incoming.statusCode || 502;
        if (status >= 300 && status < 400 && status !== 304) {
          incoming.destroy();
          reject(new Error("private_socket_redirect_denied"));
          return;
        }
        const responseHeaders = new Headers();
        for (let i = 0; i < incoming.rawHeaders.length; i += 2)
          responseHeaders.append(
            incoming.rawHeaders[i],
            incoming.rawHeaders[i + 1],
          );
        const empty =
          options.method === "HEAD" || [204, 205, 304].includes(status);
        if (empty) incoming.resume();
        resolve(
          new Response(
            empty
              ? null
              : (Readable.toWeb(incoming) as ReadableStream<Uint8Array>),
            { status, headers: responseHeaders },
          ),
        );
      },
    );
    const deadline = setTimeout(() => {
      const error = new Error("private_socket_timeout");
      error.name = "TimeoutError";
      upstream.destroy(error);
    }, options.timeoutMs);
    upstream.on("close", () => clearTimeout(deadline));
    upstream.on("error", reject);
    upstream.end(options.body);
  });
}
