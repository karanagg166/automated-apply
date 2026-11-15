// This fixed route list prevents the server-side bearer from becoming a general proxy.
import policy from "./http-security.generated.json";

const routes = policy.gateway_routes.map(
  ({ pattern, methods }) => [new RegExp(pattern), methods] as const,
);
export function permittedRoute(path: string, method: string) {
  return (
    !path.includes("..") &&
    !path.includes("%") &&
    routes.some(
      ([pattern, methods]) => pattern.test(path) && methods.includes(method),
    )
  );
}
