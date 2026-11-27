import { expect, it } from "vitest";
import { permittedRoute } from "@/lib/gateway";

const ID = "11111111-1111-4111-8111-111111111111";

it("allows exactly the Milestone 2 command-center routes", () => {
  for (const [path, method] of [
    ["v2/events/stream", "GET"],
    ["v2/worker/telemetry", "GET"],
    ["v2/worker/dry-run", "POST"],
    ["v2/telegram/mute", "POST"],
    ["v2/rules/explain", "POST"],
    ["v2/portal-rules/greenhouse/breaker/reset", "POST"],
    ["v2/semantic-cache/stats", "GET"],
    ["v2/semantic-cache/explain", "POST"],
    ["v2/semantic-cache/purge", "POST"],
    ["v2/semantic-cache/stamp-profile", "POST"],
    [`v2/semantic-cache/${ID}`, "GET"],
    [`v2/semantic-cache/${ID}/quarantine`, "POST"],
    [`v2/semantic-cache/${ID}/unquarantine`, "POST"],
    ["v2/portals/watchers", "GET"],
    ["v2/portals/watchers", "POST"],
    ["v2/portals/watchers/probe", "POST"],
    [`v2/applications/${ID}/proof`, "GET"],
    [`v2/applications/${ID}/reconcile`, "POST"],
  ] as const)
    expect(permittedRoute(path, method), `${method} ${path}`).toBe(true);
  for (const [path, method] of [
    ["v2/events/stream", "POST"],
    ["v2/worker/dry-run", "GET"],
    ["v2/portal-rules/Greenhouse/breaker/reset", "POST"],
    [`v2/applications/${ID}/reconcile`, "DELETE"],
    ["integrations/apple-mail/accounts", "GET"],
    ["dashboard/automation/run", "POST"],
  ] as const)
    expect(permittedRoute(path, method), `${method} ${path}`).toBe(false);
});
