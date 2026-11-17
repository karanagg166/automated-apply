import { expect, it } from "vitest";
import { permittedRoute } from "@/lib/gateway";
it("permits only exact native research UUID reads/PUTs and the saved status GET", () => {
  const path =
    "rust-agent/research/people/requests/10000000-0000-0000-0000-000000000001";
  expect(permittedRoute(path, "GET")).toBe(true);
  expect(permittedRoute(path, "PUT")).toBe(true);
  for (const method of ["POST", "DELETE", "PATCH"])
    expect(permittedRoute(path, method)).toBe(false);
  for (const bad of [
    path + "/retry",
    "rust-agent/research/people/requests/private",
    path.replace("10000000", "%31"),
    path + "..",
    "rust-agent/research/people/status/reset",
  ])
    expect(permittedRoute(bad, "PUT")).toBe(false);
  expect(permittedRoute("rust-agent/research/people/status", "GET")).toBe(true);
  expect(permittedRoute("rust-agent/research/people/status", "PUT")).toBe(
    false,
  );
});
