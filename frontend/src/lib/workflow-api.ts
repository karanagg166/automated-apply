export async function workflowApi<T>(
  path: string,
  method = "GET",
  body?: unknown,
): Promise<T> {
  const csrf = document.cookie
    .split("; ")
    .find((item) => item.startsWith("aa_csrf="))
    ?.slice(8);
  const response = await fetch(`/api/workflow/${path}`, {
    method,
    credentials: "same-origin",
    cache: "no-store",
    headers: {
      "Content-Type": "application/json",
      ...(csrf ? { "x-csrf-token": decodeURIComponent(csrf) } : {}),
    },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  const result = await response.json();
  if (!response.ok)
    throw new Error(
      response.status === 409
        ? "The checkpoint changed. Refresh and review the latest results before deciding."
        : result.error || "Workflow unavailable",
    );
  return result as T;
}
