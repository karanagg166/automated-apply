// @vitest-environment node
import { expect, it } from "vitest";
import { permittedRoute } from "@/lib/gateway";

const id = "11111111-1111-4111-8111-111111111111";

it("exposes profile comparison and policy without a browser save proxy", () => {
  expect(permittedRoute("execution/naukri/profile-sync", "GET")).toBe(true);
  expect(permittedRoute("execution/naukri/profile-sync/policy", "PUT")).toBe(
    true,
  );
  for (const path of [
    "execution/naukri/profile-sync/save",
    "execution/naukri/profile-sync/execute",
  ])
    expect(permittedRoute(path, "POST")).toBe(false);
});

it("allows read-only extension task lists and exact application status", () => {
  expect(permittedRoute("browser/extension-tasks", "GET")).toBe(true);
  expect(
    permittedRoute(`browser/extension-tasks/application/${id}`, "GET"),
  ).toBe(true);
  expect(permittedRoute("browser/extension-tasks", "POST")).toBe(false);
  expect(
    permittedRoute(`browser/extension-tasks/application/${id}`, "POST"),
  ).toBe(false);
});

it("allows only the bounded owner task control mutation", () => {
  expect(permittedRoute(`browser/extension-tasks/${id}/control`, "POST")).toBe(
    true,
  );
  for (const method of ["GET", "PUT", "PATCH", "DELETE"])
    expect(
      permittedRoute(`browser/extension-tasks/${id}/control`, method),
    ).toBe(false);
});

it.each(["open", "fill", "authorize", "submit", "tabs", "cookies", "execute"])(
  "denies unapproved extension operation %s",
  (operation) => {
    expect(
      permittedRoute(`browser/extension-tasks/${id}/${operation}`, "POST"),
    ).toBe(false);
    expect(permittedRoute(`browser/extension-tasks/${operation}`, "GET")).toBe(
      false,
    );
  },
);

it.each(["../../operations/status", "%2e%2e", "not-an-id", `${id}/extra`])(
  "rejects malformed extension task paths: %s",
  (path) => {
    expect(
      permittedRoute(`browser/extension-tasks/application/${path}`, "GET"),
    ).toBe(false);
    expect(
      permittedRoute(`browser/extension-tasks/${path}/control`, "POST"),
    ).toBe(false);
  },
);
