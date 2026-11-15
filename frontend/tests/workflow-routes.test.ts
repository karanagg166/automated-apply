import { describe, it, expect } from "vitest";
import { permittedWorkflowRoute } from "../src/lib/workflow-routes";
describe("closed workflow discovery routes", () => {
  it("allows only fixed public feed reads/intake and owner schedule methods", () => {
    expect(permittedWorkflowRoute("discovery/schedule", "GET")).toBe(true);
    expect(permittedWorkflowRoute("discovery/schedule", "PUT")).toBe(true);
    expect(permittedWorkflowRoute("discovery/schedule", "POST")).toBe(false);
    for (const platform of ["himalayas", "we_work_remotely"])
      for (const op of ["discover", "ingest"])
        expect(
          permittedWorkflowRoute(`platforms/${platform}/${op}`, "POST"),
        ).toBe(true);
    for (const path of [
      "platforms/naukri/ingest",
      "platforms/himalayas/apply",
      "platforms/himalayas/ingest/extra",
      "../operations/status",
      "platforms/himalayas/../ingest",
    ])
      expect(permittedWorkflowRoute(path, "POST")).toBe(false);
  });
});
