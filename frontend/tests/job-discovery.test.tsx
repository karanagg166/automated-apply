import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
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
  id: "run-uuid-1234-5678",
  source: "arbeitnow",
  status: "success",
  counts: {
    discovered: 15,
    inserted: 12,
    updated: 0,
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
  job_ids: ["job-1", "job-2"],
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

describe("JobDiscovery", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api).mockImplementation(async (path) => {
      if (path === "discovery/sources") return structuredClone(mockSources);
      throw new Error(`Unhandled api path: ${path}`);
    });
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
    vi.mocked(post)
      .mockResolvedValueOnce(structuredClone(mockPreview))
      .mockResolvedValueOnce(structuredClone(mockRunSuccess));

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
      expect(post).toHaveBeenCalledTimes(2);
    });

    const [runPath, runPayload] = vi.mocked(post).mock.calls[1] as [
      string,
      { source: string; idempotency_key: string },
    ];
    expect(runPath).toBe("discovery/runs");
    expect(runPayload.source).toBe("arbeitnow");
    expect(runPayload.idempotency_key).toBeTruthy();

    await waitFor(() => {
      expect(screen.getByText(/Saved \(New\): 12/i)).toBeInTheDocument();
      expect(screen.getByText(/Duplicate: 3/i)).toBeInTheDocument();
    });
  });

  it("reuses the exact same idempotency key on retry after a failure", async () => {
    const user = userEvent.setup();
    vi.mocked(post)
      .mockResolvedValueOnce(structuredClone(mockPreview))
      .mockRejectedValueOnce(
        new ApiError(504, "The request timed out or network is unavailable."),
      )
      .mockResolvedValueOnce(structuredClone(mockRunSuccess));

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
        screen.getByRole("button", {
          name: /Retry discovery with same key/i,
        }),
      ).toBeInTheDocument();
    });

    const firstRunKey = (
      vi.mocked(post).mock.calls[1][1] as { idempotency_key: string }
    ).idempotency_key;

    const retryButton = screen.getByRole("button", {
      name: /Retry discovery with same key/i,
    });
    await user.click(retryButton);

    await waitFor(() => {
      expect(post).toHaveBeenCalledTimes(3);
    });

    const retryKey = (
      vi.mocked(post).mock.calls[2][1] as { idempotency_key: string }
    ).idempotency_key;

    expect(retryKey).toBe(firstRunKey);

    await waitFor(() => {
      expect(screen.getByText(/Saved \(New\): 12/i)).toBeInTheDocument();
    });
  });

  it("handles no_results, rate_limited, and source_unavailable states honestly", async () => {
    const user = userEvent.setup();
    const noResultsRun = {
      ...mockRunSuccess,
      status: "no_results",
      counts: { discovered: 0, inserted: 0, duplicate: 0, rejected: 0 },
    };

    vi.mocked(post)
      .mockResolvedValueOnce(structuredClone(mockPreview))
      .mockResolvedValueOnce(noResultsRun);

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
      errors: ["Upstream rate limit exceeded for provider arbeitnow"],
    };

    vi.mocked(post)
      .mockResolvedValueOnce(structuredClone(mockPreview))
      .mockResolvedValueOnce(rateLimitedRun);

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
    vi.mocked(post)
      .mockResolvedValueOnce(mockPreview)
      .mockReturnValueOnce(pending);
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
    vi.mocked(api).mockImplementation(async (path) => {
      if (path === "discovery/sources") return structuredClone(mockSources);
      if (path === `discovery/runs/${mockRunSuccess.id}`)
        return { ...mockRunSuccess, status: "recovery_required" };
      throw new Error(`Unexpected API path ${path}`);
    });
    vi.mocked(post)
      .mockResolvedValueOnce(mockPreview)
      .mockResolvedValueOnce({ ...mockRunSuccess, status: "running" });
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
    expect(post).toHaveBeenCalledTimes(2);
  });
});
