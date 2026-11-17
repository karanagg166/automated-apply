import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { JobDiscovery } from "@/features/job-discovery";
import { api, post, ApiError } from "@/lib/api";

vi.mock("@/lib/api", async (original) => ({
  ...(await original<typeof import("@/lib/api")>()),
  api: vi.fn(),
  post: vi.fn(),
}));

const mockSources = {
  sources: [
    {
      id: "arbeitnow",
      display_name: "Arbeitnow",
      adapter_type: "direct_api" as const,
      operations: ["jobs"],
      authentication: "none",
      availability: "available" as const,
      pricing: "free" as const,
      enabled: true,
      read_only: true,
      mutation_capabilities: [],
      configuration: {},
      live_verified: false,
    },
    {
      id: "remotive",
      display_name: "Remotive",
      adapter_type: "direct_api" as const,
      operations: ["jobs"],
      authentication: "none",
      availability: "available" as const,
      pricing: "free" as const,
      enabled: true,
      read_only: true,
      mutation_capabilities: [],
      configuration: {},
      live_verified: false,
    },
    {
      id: "greenhouse",
      display_name: "Greenhouse",
      adapter_type: "direct_api" as const,
      operations: ["jobs"],
      authentication: "none",
      availability: "configuration_required" as const,
      pricing: "free" as const,
      enabled: true,
      read_only: true,
      mutation_capabilities: [],
      configuration: { boards_configured: false },
      live_verified: false,
    },
    {
      id: "naukri",
      display_name: "Naukri",
      adapter_type: "apify" as const,
      operations: ["jobs"],
      authentication: "none",
      availability: "configuration_required" as const,
      pricing: "paid" as const,
      enabled: false,
      read_only: true,
      mutation_capabilities: [],
      configuration: {},
      live_verified: false,
    },
  ],
};

const mockPreview = {
  source: mockSources.sources[0],
  query: {
    keywords: ["Python", "FastAPI"],
    locations: ["Berlin"],
    remote_preference: "remote" as const,
    employment_types: [],
    page: 1,
    limit: 20,
    max_age_days: null,
  },
  jobs: [],
  provider_calls: 0,
  estimated_usd: null,
  estimate_only: true,
  message: "Planning only; no providers called and no jobs or runs written",
};

const mockRunSuccess = {
  id: "20000000-0000-0000-0000-000000000002",
  source: "arbeitnow",
  status: "success",
  counts: {
    discovered: 15,
    inserted: 12,
    updated: 3,
    duplicate: 3,
    rejected: 0,
    failed: 0,
    skipped: 0,
  },
  errors: [],
  started_at: "2026-10-27T10:00:00Z",
  finished_at: "2026-10-27T10:00:02Z",
  provider_run_id: null,
  usage: {},
  rankings: [],
  job_ids: Array.from(
    { length: 15 },
    (_, index) =>
      `30000000-0000-0000-0000-${(index + 1).toString(16).padStart(12, "0")}`,
  ),
  local_intake_complete: true,
  rankings_complete: true,
};

let runReply: (path: string, options?: RequestInit) => Promise<unknown>;
const readyPaidSource = {
  ...mockSources.sources[3],
  enabled: true,
  availability: "available" as const,
  owner_run_supported: true,
  configuration: {
    native_execution: {
      ready: true,
      run_cap_usd: "0.100001",
      monthly_limit_usd: "2.000001",
    },
  },
};
function paidSources() {
  vi.mocked(api).mockImplementation(async (path, options) => {
    if (path === "discovery/sources")
      return { sources: [...mockSources.sources.slice(0, 3), readyPaidSource] };
    if (path.startsWith("discovery/runs/")) return runReply(path, options);
    throw new Error(`Unhandled api path: ${path}`);
  });
}
const paidPreview = {
  ...mockPreview,
  source: readyPaidSource,
  estimated_usd: 0.02,
  paid_execution: {
    ready: true,
    run_cap_usd: "0.100001",
    monthly_limit_usd: "2.000001",
  },
};
function mount() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <JobDiscovery />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  vi.restoreAllMocks();
  Reflect.deleteProperty(navigator, "locks");
});
describe("JobDiscovery", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    vi.spyOn(crypto, "randomUUID").mockReturnValue(
      mockRunSuccess.id as ReturnType<typeof crypto.randomUUID>,
    );
    let pending: Promise<unknown> = Promise.resolve();
    Object.defineProperty(navigator, "locks", {
      configurable: true,
      value: {
        request: vi.fn((_name: string, work: () => Promise<unknown>) => {
          const result = pending.then(work);
          pending = result.catch(() => undefined);
          return result;
        }),
      },
    });
    runReply = async () => structuredClone(mockRunSuccess);
    vi.mocked(api).mockImplementation(async (path, options) => {
      if (path === "discovery/sources") return structuredClone(mockSources);
      if (path.startsWith("discovery/runs/")) return runReply(path, options);
      throw new Error(`Unhandled api path: ${path}`);
    });
  });

  it("requires separate paid opt-in then reviewed run consent and shows full retained reservation", async () => {
    paidSources();
    vi.mocked(post).mockResolvedValueOnce(paidPreview);
    const paidResult = {
      ...mockRunSuccess,
      source: "naukri",
      original_scope_available: true,
      billing_final: false,
      reservation: {
        reserved_usd: "0.100001",
        accounting: "full_cap_retained",
        billing_final: false,
      },
    };
    runReply = async () => paidResult;
    const user = userEvent.setup();
    mount();
    const provider = await screen.findByRole("combobox", {
      name: "Discovery source provider",
    });
    await user.selectOptions(provider, "naukri");
    expect(
      screen.getByRole("button", { name: /Preview discovery plan/ }),
    ).toBeDisabled();
    await user.click(
      screen.getByRole("checkbox", { name: "Allow this paid discovery" }),
    );
    await user.click(
      screen.getByRole("button", { name: /Preview discovery plan/ }),
    );
    expect(
      await screen.findByRole("button", { name: /Run approved discovery/ }),
    ).toBeDisabled();
    expect(vi.mocked(post).mock.calls[0][1]).toMatchObject({
      source: "naukri",
      allow_paid: true,
    });
    await user.click(
      screen.getByRole("checkbox", { name: /Run this approved/ }),
    );
    await user.click(
      screen.getByRole("button", { name: /Run approved discovery/ }),
    );
    expect(
      await screen.findByText(/Retained reservation: \$0.100001/),
    ).toBeInTheDocument();
    const put = vi
      .mocked(api)
      .mock.calls.find(([, options]) => options?.method === "PUT");
    expect(JSON.parse(put![1]!.body as string)).toMatchObject({
      source: "naukri",
      allow_paid: true,
    });
    expect(localStorage.getItem("job-discovery-attempt:v1")).not.toContain(
      "0.100001",
    );
  });
  it("clears paid consent and the reviewed preview when search criteria change", async () => {
    paidSources();
    vi.mocked(post).mockResolvedValueOnce(paidPreview);
    const user = userEvent.setup();
    mount();
    await user.selectOptions(
      await screen.findByRole("combobox", {
        name: "Discovery source provider",
      }),
      "naukri",
    );
    const paid = screen.getByRole("checkbox", {
      name: "Allow this paid discovery",
    });
    await user.click(paid);
    await user.click(
      screen.getByRole("button", { name: /Preview discovery plan/ }),
    );
    await screen.findByRole("button", { name: /Run approved discovery/ });
    await user.type(
      screen.getByRole("textbox", { name: "Role or technology keywords" }),
      "Rust",
    );
    expect(paid).not.toBeChecked();
    expect(
      screen.queryByRole("button", { name: /Run approved discovery/ }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Preview discovery plan/ }),
    ).toBeDisabled();
    expect(
      vi
        .mocked(api)
        .mock.calls.every(([, options]) => options?.method !== "PUT"),
    ).toBe(true);
  });
  it("keeps execution disabled for a blocked paid preview and never labels an unknown estimate free", async () => {
    paidSources();
    vi.mocked(post).mockResolvedValueOnce({
      ...paidPreview,
      estimated_usd: null,
      paid_execution: {
        ...paidPreview.paid_execution,
        ready: false,
        blocker: "apify_estimate_exceeds_reserved_cap",
      },
    });
    const user = userEvent.setup();
    mount();
    await user.selectOptions(
      await screen.findByRole("combobox", {
        name: "Discovery source provider",
      }),
      "naukri",
    );
    await user.click(
      screen.getByRole("checkbox", { name: "Allow this paid discovery" }),
    );
    await user.click(
      screen.getByRole("button", { name: /Preview discovery plan/ }),
    );
    await screen.findByText(/Unavailable; review the saved paid limits/);
    await user.click(
      screen.getByRole("checkbox", { name: /Run this approved/ }),
    );
    expect(
      screen.getByRole("button", { name: /Run approved discovery/ }),
    ).toBeDisabled();
    expect(screen.queryByText("Free ($0.00)")).not.toBeInTheDocument();
  });
  it("reloads a paid unknown start with GET only and keeps new search disabled", async () => {
    paidSources();
    localStorage.setItem(
      "job-discovery-attempt:v1",
      JSON.stringify({ requestId: mockRunSuccess.id, source: "naukri" }),
    );
    runReply = async () => ({
      ...mockRunSuccess,
      source: "naukri",
      status: "recovery_required",
      finished_at: null,
      local_intake_complete: false,
      rankings_complete: false,
      usage: { finding_retained: false },
      original_scope_available: true,
      billing_final: false,
      reservation: {
        reserved_usd: "0.100001",
        accounting: "full_cap_retained",
        billing_final: false,
      },
    });
    mount();
    await screen.findByText(/Retained reservation: \$0.100001/);
    expect(
      screen.getByRole("button", { name: "Start new search" }),
    ).toBeDisabled();
    expect(post).not.toHaveBeenCalled();
    expect(
      vi.mocked(api).mock.calls.every(([, options]) => !options?.method),
    ).toBe(true);
    expect(localStorage.getItem("job-discovery-attempt:v1")).toContain(
      "naukri",
    );
  });

  it("recovers a persisted completed search on reload using GET only and releases criteria after terminal review", async () => {
    localStorage.setItem(
      "job-discovery-attempt:v1",
      JSON.stringify({ requestId: mockRunSuccess.id, source: "arbeitnow" }),
    );
    const user = userEvent.setup();
    mount();
    expect(await screen.findByText(/Saved \(New\): 12/)).toBeInTheDocument();
    expect(post).not.toHaveBeenCalled();
    expect(
      vi.mocked(api).mock.calls.every(([, options]) => !options?.method),
    ).toBe(true);
    expect(
      screen.getByRole("combobox", { name: "Discovery source provider" }),
    ).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Start new search" }));
    await waitFor(() =>
      expect(localStorage.getItem("job-discovery-attempt:v1")).toBeNull(),
    );
    expect(
      screen.getByRole("combobox", { name: "Discovery source provider" }),
    ).toBeEnabled();
    expect(
      vi
        .mocked(api)
        .mock.calls.filter(
          ([path]) => path === `discovery/runs/${mockRunSuccess.id}`,
        ),
    ).toHaveLength(2);
  });

  it("displays free available providers as selectable and paid/unconfigured providers as disabled", async () => {
    mount();

    await waitFor(() => {
      expect(
        screen.getByRole("combobox", { name: "Discovery source provider" }),
      ).toBeInTheDocument();
    });

    const select = screen.getByRole("combobox", {
      name: "Discovery source provider",
    });
    const options = within(select).getAllByRole("option");

    const arbeitnowOption = options.find((o) =>
      o.textContent?.includes("Arbeitnow"),
    );
    expect(arbeitnowOption).toBeEnabled();

    const greenhouseOption = options.find((o) =>
      o.textContent?.includes("Greenhouse"),
    );
    expect(greenhouseOption).toBeDisabled();

    const naukriOption = options.find((o) => o.textContent?.includes("Naukri"));
    expect(naukriOption).toBeDisabled();
  });

  it("previews discovery plan without executing a live run", async () => {
    const user = userEvent.setup();
    vi.mocked(post).mockResolvedValueOnce(structuredClone(mockPreview));

    mount();

    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: /Preview discovery plan/i }),
      ).toBeEnabled();
    });

    const keywordsInput = screen.getByRole("textbox", {
      name: "Role or technology keywords",
    });
    await user.type(keywordsInput, "Python, FastAPI");

    const locationInput = screen.getByRole("textbox", {
      name: "Search locations",
    });
    await user.type(locationInput, "Berlin");

    const previewButton = screen.getByRole("button", {
      name: /Preview discovery plan/i,
    });
    await user.click(previewButton);

    await waitFor(() => {
      expect(post).toHaveBeenCalledTimes(1);
    });

    const [calledPath, calledBody] = vi.mocked(post).mock.calls[0] as [
      string,
      { source: string; query: { keywords: string[]; locations: string[] } },
    ];
    expect(calledPath).toBe("discovery/preview");
    expect(calledBody.source).toBe("arbeitnow");
    expect(calledBody.query.keywords).toEqual(["Python", "FastAPI"]);
    expect(calledBody.query.locations).toEqual(["Berlin"]);

    expect(
      screen.getByText("Review your job discovery plan"),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Planning only; no providers called/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/Free \(\$0\.00\)/i)).toBeInTheDocument();

    const runButton = screen.getByRole("button", {
      name: /Run approved discovery/i,
    });
    expect(runButton).toBeDisabled();
  });

  it("requires explicit user consent before executing discovery and triggers run", async () => {
    const user = userEvent.setup();
    vi.mocked(post).mockResolvedValueOnce(structuredClone(mockPreview));

    mount();

    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: /Preview discovery plan/i }),
      ).toBeEnabled();
    });

    await user.click(
      screen.getByRole("button", { name: /Preview discovery plan/i }),
    );

    await waitFor(() => {
      expect(
        screen.getByText("Review your job discovery plan"),
      ).toBeInTheDocument();
    });

    const runButton = screen.getByRole("button", {
      name: /Run approved discovery/i,
    });
    expect(runButton).toBeDisabled();

    const consentCheckbox = screen.getByRole("checkbox", {
      name: /Run this approved job discovery on Arbeitnow now/i,
    });
    await user.click(consentCheckbox);
    expect(runButton).toBeEnabled();

    await user.click(runButton);

    await waitFor(() => {
      expect(
        vi
          .mocked(api)
          .mock.calls.some(([, options]) => options?.method === "PUT"),
      ).toBe(true);
    });
    const [runPath, options] = vi
      .mocked(api)
      .mock.calls.find(([, options]) => options?.method === "PUT")!;
    expect(runPath).toBe(`discovery/runs/${mockRunSuccess.id}`);
    const runPayload = JSON.parse(options!.body as string);
    expect(runPayload.source).toBe("arbeitnow");
    expect(runPayload.idempotency_key).toBeTruthy();
    expect(post).toHaveBeenCalledTimes(1);

    await waitFor(() => {
      expect(screen.getByText(/Saved \(New\): 12/i)).toBeInTheDocument();
      expect(screen.getByText(/Duplicate: 3/i)).toBeInTheDocument();
    });
  });

  it("recovers the persisted original UUID by GET after response loss without a second PUT", async () => {
    const user = userEvent.setup();
    vi.mocked(post).mockResolvedValueOnce(mockPreview);
    runReply = async (_path, options) => {
      if (options?.method === "PUT") throw new ApiError(504, "Response lost");
      return structuredClone(mockRunSuccess);
    };
    mount();
    await user.click(
      await screen.findByRole("button", { name: /Preview discovery plan/ }),
    );
    await user.click(
      await screen.findByRole("checkbox", { name: /Run this approved/ }),
    );
    await user.click(
      screen.getByRole("button", { name: /Run approved discovery/ }),
    );
    await user.click(
      await screen.findByRole("button", { name: "Recover saved discovery" }),
    );
    expect(await screen.findByText(/Saved \(New\): 12/)).toBeInTheDocument();
    expect(
      vi
        .mocked(api)
        .mock.calls.filter(([, options]) => options?.method === "PUT"),
    ).toHaveLength(1);
    expect(api).toHaveBeenCalledWith(`discovery/runs/${mockRunSuccess.id}`);
  });

  it("handles no_results, rate_limited, and source_unavailable states honestly", async () => {
    const user = userEvent.setup();
    const noResultsRun = {
      ...mockRunSuccess,
      status: "no_results",
      counts: { discovered: 0, inserted: 0, duplicate: 0, rejected: 0 },
      job_ids: [],
    };

    vi.mocked(post).mockResolvedValueOnce(structuredClone(mockPreview));
    runReply = async () => noResultsRun;

    mount();

    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: /Preview discovery plan/i }),
      ).toBeEnabled();
    });

    await user.click(
      screen.getByRole("button", { name: /Preview discovery plan/i }),
    );

    await waitFor(() => {
      expect(
        screen.getByText("Review your job discovery plan"),
      ).toBeInTheDocument();
    });

    await user.click(
      screen.getByRole("checkbox", {
        name: /Run this approved job discovery on Arbeitnow now/i,
      }),
    );

    await user.click(
      screen.getByRole("button", { name: /Run approved discovery/i }),
    );

    await waitFor(() => {
      expect(
        screen.getByText(/No jobs matching your criteria were found/i),
      ).toBeInTheDocument();
    });
  });

  it("handles rate limits and shows honest throttle notice", async () => {
    const user = userEvent.setup();
    const rateLimitedRun = {
      ...mockRunSuccess,
      status: "rate_limited",
      counts: { discovered: 0, inserted: 0, duplicate: 0, rejected: 0 },
      job_ids: [],
      errors: ["Upstream rate limit exceeded for provider arbeitnow"],
    };

    vi.mocked(post).mockResolvedValueOnce(structuredClone(mockPreview));
    runReply = async () => rateLimitedRun;

    mount();

    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: /Preview discovery plan/i }),
      ).toBeEnabled();
    });

    await user.click(
      screen.getByRole("button", { name: /Preview discovery plan/i }),
    );

    await waitFor(() => {
      expect(
        screen.getByText("Review your job discovery plan"),
      ).toBeInTheDocument();
    });

    await user.click(
      screen.getByRole("checkbox", {
        name: /Run this approved job discovery on Arbeitnow now/i,
      }),
    );

    await user.click(
      screen.getByRole("button", { name: /Run approved discovery/i }),
    );

    await waitFor(() => {
      expect(
        screen.getByText(/Provider rate limit reached/i),
      ).toBeInTheDocument();
      expect(
        screen.getByText(
          /Upstream rate limit exceeded for provider arbeitnow/i,
        ),
      ).toBeInTheDocument();
    });
  });
  it("keeps disabled direct APIs and manual import sources unavailable", async () => {
    vi.mocked(api).mockResolvedValueOnce({
      sources: [
        { ...mockSources.sources[0], enabled: false },
        {
          ...mockSources.sources[0],
          id: "manual",
          display_name: "Manual import",
          adapter_type: "manual",
        },
      ],
    });
    mount();
    expect(
      await screen.findByRole("option", { name: /Manual import/ }),
    ).toBeDisabled();
    expect(screen.getByRole("option", { name: /Arbeitnow/ })).toBeDisabled();
    expect(
      screen.getByRole("button", { name: /Preview discovery plan/ }),
    ).toBeDisabled();
  });

  it("holds reviewed criteria stable while an approved run is pending", async () => {
    const user = userEvent.setup();
    let finish!: (value: typeof mockRunSuccess) => void;
    const pending = new Promise<typeof mockRunSuccess>((resolve) => {
      finish = resolve;
    });
    vi.mocked(post).mockResolvedValueOnce(mockPreview);
    runReply = () => pending;
    mount();
    await user.click(
      await screen.findByRole("button", { name: /Preview discovery plan/ }),
    );
    await user.click(
      await screen.findByRole("checkbox", { name: /Run this approved/ }),
    );
    await user.click(
      screen.getByRole("button", { name: /Run approved discovery/ }),
    );
    expect(
      screen.getByRole("textbox", { name: "Role or technology keywords" }),
    ).toBeDisabled();
    expect(
      screen.getByRole("combobox", { name: "Discovery source provider" }),
    ).toBeDisabled();
    expect(screen.getByRole("button", { name: "Cancel plan" })).toBeDisabled();
    await act(async () => {
      finish(mockRunSuccess);
    });
    expect(await screen.findByText(/Saved \(New\): 12/)).toBeInTheDocument();
  });

  it("inspects an interrupted saved run with GET without replaying discovery", async () => {
    const user = userEvent.setup();
    vi.mocked(api).mockImplementation(async (path, options) => {
      if (path === "discovery/sources") return structuredClone(mockSources);
      if (path === `discovery/runs/${mockRunSuccess.id}`)
        return {
          ...mockRunSuccess,
          status: options?.method === "PUT" ? "running" : "recovery_required",
          local_intake_complete: false,
          rankings_complete: false,
          finished_at: null,
        };
      throw new Error(`Unexpected API path ${path}`);
    });
    vi.mocked(post).mockResolvedValueOnce(mockPreview);
    mount();
    await user.click(
      await screen.findByRole("button", { name: /Preview discovery plan/ }),
    );
    await user.click(
      await screen.findByRole("checkbox", { name: /Run this approved/ }),
    );
    await user.click(
      screen.getByRole("button", { name: /Run approved discovery/ }),
    );
    expect(
      await screen.findByText(/Discovery is still running/),
    ).toBeInTheDocument();
    await user.click(
      screen.getByRole("button", { name: /Refresh saved run status/ }),
    );
    expect(
      await screen.findByText(/This discovery run was interrupted/),
    ).toBeInTheDocument();
    expect(api).toHaveBeenCalledWith(`discovery/runs/${mockRunSuccess.id}`);
    expect(post).toHaveBeenCalledTimes(1);
  });
});
