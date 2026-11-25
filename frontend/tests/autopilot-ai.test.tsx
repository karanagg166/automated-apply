import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { beforeEach, expect, it, vi } from "vitest";
import {
  AIRouterPanel,
  SemanticCacheTable,
  cachePath,
  providerTone,
} from "@/features/autopilot-ai";
import { api, del, post } from "@/lib/api";

vi.mock("@/lib/api", async (original) => ({
  ...(await original<typeof import("@/lib/api")>()),
  api: vi.fn(),
  post: vi.fn(),
  del: vi.fn(),
}));

const provider = (overrides: Record<string, unknown>) => ({
  provider: "groq",
  label: "Groq",
  status: "healthy",
  model: "llama-3.3-70b-versatile",
  problem: null,
  api_style: "openai",
  requests_today: 12,
  requests_this_minute: 1,
  tokens_today: 4200,
  rpm_limit: 25,
  rpd_limit: 900,
  tpd_limit: 90000,
  circuit_open_until: null,
  last_error: null,
  consecutive_failures: 0,
  key_envs: ["GROQ_API_KEY"],
  ...overrides,
});

const aiStatus = {
  providers: [
    provider({}),
    provider({
      provider: "gemini",
      label: "Google AI Studio (Gemini)",
      status: "circuit_open",
      model: "gemini-2.5-flash",
      circuit_open_until: "2026-11-26T10:20:00Z",
      last_error: "http_503",
      tpd_limit: null,
    }),
    provider({
      provider: "mistral",
      label: "Mistral (Experiment tier)",
      status: "unconfigured",
      problem: "missing MISTRAL_API_KEY",
      key_envs: ["MISTRAL_API_KEY"],
    }),
  ],
  chains: {
    screening_qa: ["groq", "gemini", "mistral"],
    jd_scoring: ["gemini", "groq", "mistral"],
  },
  semantic_cache: {
    backend: "postgres",
    total_entries: 14,
    total_hits: 37,
    threshold: 0.88,
    embedding_model: "BAAI/bge-small-en-v1.5",
    embedding_dimensions: 384,
    embedding_ready: false,
  },
  local_generative_llm: "disabled",
};

const entry = {
  id: "22222222-2222-4222-8222-222222222222",
  kind: "screening_qa",
  question_text: "Are you willing to work night shifts?",
  answer_text: "No",
  source: "user",
  hits: 3,
  updated_at: "2026-11-26T09:00:00Z",
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
    if (path === "v2/ai/status") return structuredClone(aiStatus);
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

it("maps provider states to badge tones and builds the cache query", () => {
  expect(providerTone("healthy")).toBe("green");
  expect(providerTone("cooldown")).toBe("amber");
  expect(providerTone("circuit_open")).toBe("red");
  expect(providerTone("unconfigured")).toBe("neutral");
  expect(cachePath("  python ", 25)).toBe(
    "v2/semantic-cache?kind=screening_qa&limit=25&offset=25&q=python",
  );
  expect(cachePath("")).toBe(
    "v2/semantic-cache?kind=screening_qa&limit=25&offset=0",
  );
});

it("shows every provider's state, usage and how to configure missing keys", async () => {
  mount(<AIRouterPanel />);
  const groq = await screen.findByLabelText("Groq status");
  expect(within(groq).getByText("Healthy")).toBeInTheDocument();
  expect(
    within(groq).getByRole("progressbar", {
      name: "Requests today: 12 of 900",
    }),
  ).toBeInTheDocument();
  const gemini = screen.getByLabelText("Google AI Studio (Gemini) status");
  expect(within(gemini).getByText("Circuit open")).toBeInTheDocument();
  expect(within(gemini).getByText(/http_503/)).toBeInTheDocument();
  const mistral = screen.getByLabelText("Mistral (Experiment tier) status");
  expect(within(mistral).getByText("Not configured")).toBeInTheDocument();
  expect(within(mistral).getByText("MISTRAL_API_KEY")).toBeInTheDocument();
  expect(screen.getByText("2 of 3 providers configured")).toBeInTheDocument();
  expect(
    screen.getByText("Local generative LLM: disabled"),
  ).toBeInTheDocument();
  expect(screen.getByText("37")).toBeInTheDocument();
  expect(screen.getByText(/groq → gemini → mistral/)).toBeInTheDocument();
});

it("adds a verified Q&A pair and deletes a wrong cached answer", async () => {
  const user = userEvent.setup();
  vi.mocked(post).mockResolvedValue({ ...entry, id: "new" });
  vi.mocked(del).mockResolvedValue(undefined);
  mount(<SemanticCacheTable />);
  expect(await screen.findByText(entry.question_text)).toBeInTheDocument();
  const add = screen.getByRole("button", { name: "Add Q&A" });
  expect(add).toBeDisabled();
  await user.type(screen.getByLabelText("Question"), "Do you have a passport?");
  await user.type(screen.getByLabelText("Answer"), "Yes");
  await user.click(add);
  await waitFor(() =>
    expect(post).toHaveBeenCalledWith("v2/semantic-cache", {
      kind: "screening_qa",
      question_text: "Do you have a passport?",
      answer_text: "Yes",
    }),
  );
  expect(
    await screen.findByText(/outranks profile and LLM/),
  ).toBeInTheDocument();
  await user.click(
    screen.getByRole("button", {
      name: `Delete cached answer: ${entry.question_text}`,
    }),
  );
  await waitFor(() =>
    expect(del).toHaveBeenCalledWith(`v2/semantic-cache/${entry.id}`),
  );
});
