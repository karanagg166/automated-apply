// Edit contracts/http-security.json and run scripts/sync_http_security.py.
import policy from "./http-security.generated.json";

const approvals = policy.owner_approval.map((pattern) => new RegExp(pattern));

export function maximumBodyBytes(path: string): number {
  const absolute = `/api/v1/${path}`;
  if (absolute === "/api/v1/dashboard/resumes")
    return policy.request_limits.resume;
  if (absolute === "/api/v1/local-agent/chrome")
    return policy.request_limits.chrome;
  const application =
    policy.application_prefixes.some((prefix) => absolute.startsWith(prefix)) ||
    absolute.includes(policy.application_path_fragment);
  return application
    ? policy.request_limits.application
    : policy.request_limits.default;
}

export function requiresOwnerApproval(path: string, method: string): boolean {
  return method === "POST" && approvals.some((pattern) => pattern.test(path));
}
