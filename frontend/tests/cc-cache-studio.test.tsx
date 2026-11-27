import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { beforeEach, expect, it, vi } from "vitest";
import {
  CacheStudio,
  matchesSource,
  parseOptions,
  staleCount,
  studioPath,
} from "@/features/cache-studio";
import { api, del, post } from "@/lib/api";

vi.mock("@/lib/api", async (original) => ({
  ...(await original<typeof import("@/lib/api")>()),
  api: vi.fn(),
  post: vi.fn(),
  del: vi.fn(),
}));

const entry = {
  id: "22222222-2222-4222-8222-222222222222",
  kind: "screening_qa",
  question_text: "Are you willing to relocate to Bengaluru?",
  answer_text: "Yes",
  source: "user",
  hits: 4,
  updated_at: "2026-11-26T09:00:00Z",
};
const stats = {
  total_entries: 12,
  total_hits: 41,
  status_counts: { active: 11, quarantined: 1 },
  decisions: {
    since: "2026-11-28T00:00:00Z",
    lookups: 20,
    hits: 9,
    hit_rate: 0.45,
    counters: {
      exact_hit: 6,
      semantic_hit: 3,
      rejected_polarity_flip: 2,
      rejected_cross_company: 1,
      rejected_stale_profile: 3,
    },
  },
};

function mount(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>{children}</QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api).mockImplementation(async (path: string) => {
    if (path === "v2/semantic-cache/stats") return structuredClone(stats);
    if (path.startsWith("v2/semantic-cache?"))
      return {
        items: [structuredClone(entry)],
        total: 1,
        limit: 25,
        offset: 0,
      };
    throw new Error(path);
  });
});

it("builds explorer paths and helper values", () => {
  expect(studioPath("stale", " py ", 25)).toBe(
    "v2/semantic-cache?kind=screening_qa&limit=25&offset=25&status=expired&q=py",
  );
  expect(studioPath("quarantined", "", 0)).toContain("status=quarantined");
  expect(parseOptions("Yes, No ,, Maybe")).toEqual(["Yes", "No", "Maybe"]);
  expect(matchesSource({ ...entry, source: "llm" }, "human_verified")).toBe(
    false,
  );
  expect(matchesSource({ ...entry, source: "llm" }, "llm_verified")).toBe(true);
  expect(staleCount(stats)).toBe(3);
  expect(
    staleCount(stats, { stamped: 5, profile_hash: "x", stale_remaining: 0 }),
  ).toBe(0);
});

it("renders telemetry, the explain trace and quarantines an entry", async () => {
  const user = userEvent.setup();
  vi.mocked(post).mockImplementation(async (path: string) => {
    if (path === "v2/semantic-cache/explain")
      return {
        intent_bucket: "relocation",
        field_type: "radio",
        cache_policy: "cacheable",
        invalidation_scope: "profile",
        polarity: "positive",
        entities: { geo: ["bengaluru"] },
        candidates: [
          {
            id: "c1",
            question_text: "Relocate to Pune?",
            similarity: 0.91,
            passed: false,
            reason: "entity_mismatch",
          },
        ],
        hit: {
          id: entry.id,
          match: "semantic",
          similarity: 0.962,
          answer: "Yes",
        },
      };
    return {};
  });
  mount(<CacheStudio />);
  const telemetry = await screen.findByLabelText("Rejections by reason");
  expect(
    within(telemetry).getByText("Polarity flip").nextSibling,
  ).toHaveTextContent("2");
  expect(screen.getByText("41 LLM calls saved")).toBeInTheDocument();
  expect(
    screen.getByText(/3 cached answers were given for an older profile/),
  ).toBeInTheDocument();

  await user.type(
    screen.getByLabelText("Question"),
    "Can you relocate to Bengaluru?",
  );
  await user.type(
    screen.getByLabelText("Options (comma-separated)"),
    "Yes, No",
  );
  await user.selectOptions(screen.getByLabelText("Field type"), "radio");
  await user.click(screen.getByRole("button", { name: "Explain decision" }));
  await waitFor(() =>
    expect(post).toHaveBeenCalledWith("v2/semantic-cache/explain", {
      question: "Can you relocate to Bengaluru?",
      field_kind: "radio",
      company: null,
      options: ["Yes", "No"],
    }),
  );
  const trace = await screen.findByLabelText("Decision trace");
  expect(
    within(trace).getByText("Would answer (semantic · 0.96)"),
  ).toBeInTheDocument();
  expect(within(trace).getByText("relocation")).toBeInTheDocument();
  expect(within(trace).getByText("positive")).toBeInTheDocument();
  expect(within(trace).getByText("bengaluru")).toBeInTheDocument();
  expect(within(trace).getByText("entity_mismatch")).toBeInTheDocument();

  await user.click(
    await screen.findByRole("button", {
      name: `Quarantine: ${entry.question_text}`,
    }),
  );
  await waitFor(() =>
    expect(post).toHaveBeenCalledWith(
      `v2/semantic-cache/${entry.id}/quarantine`,
      {
        reason: "owner_quarantine",
      },
    ),
  );
  await user.click(
    screen.getByRole("button", { name: `Delete: ${entry.question_text}` }),
  );
  await waitFor(() =>
    expect(del).toHaveBeenCalledWith(`v2/semantic-cache/${entry.id}`),
  );
});

it("stamps the profile hash", async () => {
  const user = userEvent.setup();
  vi.mocked(post).mockResolvedValue({
    stamped: 7,
    profile_hash: "abc123",
    stale_remaining: 0,
  });
  mount(<CacheStudio />);
  await screen.findByText(/older profile/);
  await user.click(screen.getByRole("button", { name: "Stamp profile hash" }));
  expect(await screen.findByText(/Stamped 7 entries/)).toBeInTheDocument();
  expect(post).toHaveBeenCalledWith("v2/semantic-cache/stamp-profile");
  await waitFor(() =>
    expect(screen.queryByText(/older profile/)).not.toBeInTheDocument(),
  );
});
