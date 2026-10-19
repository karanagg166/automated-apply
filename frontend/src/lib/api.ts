"use client";
import type { components } from "@/types/api";
export type Schema<Name extends keyof components["schemas"]> =
  components["schemas"][Name];
export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}
export async function api<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const csrf = document.cookie
    .split("; ")
    .find((x) => x.startsWith("aa_csrf="))
    ?.split("=")[1];
  const headers = new Headers(options.headers);
  if (options.body && !(options.body instanceof File))
    headers.set("Content-Type", "application/json");
  if (csrf) headers.set("X-CSRF-Token", csrf);
  let response: Response;
  try {
    response = await fetch(`/api/backend/${path}`, {
      ...options,
      headers,
      cache: "no-store",
      signal: options.signal || AbortSignal.timeout(95000),
    });
  } catch {
    throw new ApiError(
      504,
      "The request timed out or the network is unavailable. Check history before repeating an action.",
    );
  }
  if (!response.ok) {
    const data = await response
      .json()
      .catch(() => ({ detail: "Request failed" }));
    const detail = data.detail;
    const message =
      typeof detail === "string"
        ? detail
        : detail?.blockers?.join(", ") ||
          "This operation needs additional configuration or review.";
    throw new ApiError(response.status, message);
  }
  return response.json();
}
export function post<T>(path: string, body: unknown = {}) {
  return api<T>(path, { method: "POST", body: JSON.stringify(body) });
}
export function patch<T>(path: string, body: unknown) {
  return api<T>(path, { method: "PATCH", body: JSON.stringify(body) });
}
export function readable(value: string | undefined | null) {
  return value?.replaceAll("_", " ").replaceAll("-", " ") || "Unknown";
}
export function dateLabel(value?: string | null) {
  return value
    ? new Date(value).toLocaleDateString("en-IN", {
        day: "numeric",
        month: "short",
        year: "numeric",
      })
    : "Not observed";
}
export function externalUrl(value?: string | null) {
  try {
    const url = new URL(value || "");
    return url.protocol === "https:" && !url.username && !url.password
      ? url.href
      : undefined;
  } catch {
    return undefined;
  }
}
