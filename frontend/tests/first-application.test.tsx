import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { PasteJobUrlCard } from "@/features/jobs";
import {
  ExecutionQuestionAnswer,
  type ExecutionQuestion,
} from "@/features/execution-question-answer";
import { post } from "@/lib/api";

const push = vi.hoisted(() => vi.fn());
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("@/lib/api", async (original) => ({
  ...(await original<typeof import("@/lib/api")>()),
  post: vi.fn(),
}));
const question: ExecutionQuestion = {
  id: "question-1",
  packet_id: "packet-1",
  packet_revision: 7,
  execution_id: "execution-1",
  question: "Interview availability",
  state: "sent",
  answer: null,
  employer: "Fictional",
  role: "Engineer",
  answer_type: "availability",
  options: ["Yes", "No"],
  expires_at: "2099-01-01T00:00:00Z",
};
beforeEach(() => {
  vi.resetAllMocks();
});

it("prepares a named destination once without silently starting a Naukri execution", async () => {
  vi.mocked(post).mockResolvedValue({ id: "packet-1" });
  render(<PasteJobUrlCard />);
  expect(
    screen.getByRole("button", { name: "Prepare application from URL" }),
  ).toBeDisabled();
  await userEvent.type(
    screen.getByRole("textbox", { name: "Paste Job URL" }),
    "https://www.naukri.com/job-listings-fictional-281026123456",
  );
  await userEvent.type(
    screen.getByLabelText("Import company name"),
    "Fictional",
  );
  await userEvent.type(screen.getByLabelText("Import job title"), "Engineer");
  await userEvent.click(
    screen.getByRole("button", { name: "Prepare application from URL" }),
  );
  expect(post).toHaveBeenCalledTimes(1);
  expect(post).toHaveBeenCalledWith(
    "application-packets/intake",
    expect.objectContaining({
      application_url:
        "https://www.naukri.com/job-listings-fictional-281026123456",
      company_name: "Fictional",
      job_title: "Engineer",
    }),
  );
  expect(push).toHaveBeenCalledWith("/applications/packet-1");
});

it("preserves an intake rejection without navigating or falling through", async () => {
  vi.mocked(post).mockRejectedValue(
    Error("Destination requires manual handoff"),
  );
  render(<PasteJobUrlCard />);
  await userEvent.type(
    screen.getByRole("textbox", { name: "Paste Job URL" }),
    "https://example.com/jobs/1",
  );
  await userEvent.type(
    screen.getByLabelText("Import company name"),
    "Fictional",
  );
  await userEvent.type(screen.getByLabelText("Import job title"), "Engineer");
  await userEvent.click(
    screen.getByRole("button", { name: "Prepare application from URL" }),
  );
  expect(
    await screen.findByText("Destination requires manual handoff"),
  ).toBeVisible();
  expect(push).not.toHaveBeenCalled();
});

it("never assumes the first availability option and can save No without inventing a time", async () => {
  const saved = vi.fn();
  render(<ExecutionQuestionAnswer question={question} onSaved={saved} />);
  expect(screen.getByRole("combobox")).toHaveValue("");
  expect(screen.getByRole("button")).toBeDisabled();
  await userEvent.selectOptions(screen.getByRole("combobox"), "No");
  expect(
    screen.queryByLabelText("Interview date, time and time zone"),
  ).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button"));
  await waitFor(() => expect(saved).toHaveBeenCalledOnce());
  expect(post).toHaveBeenCalledWith("execution/questions/question-1/answer", {
    answer: "No",
    expected_revision: 7,
  });
  expect(screen.getByText(/fresh packet review and approval/)).toBeVisible();
});

it("rejects an expired question in the UI and shows backend stale-answer errors", async () => {
  const saved = vi.fn();
  const view = render(
    <ExecutionQuestionAnswer
      question={{ ...question, expires_at: "2020-01-01T00:00:00Z" }}
      onSaved={saved}
    />,
  );
  expect(screen.getByRole("button")).toBeDisabled();
  expect(post).not.toHaveBeenCalled();
  view.rerender(
    <ExecutionQuestionAnswer question={question} onSaved={saved} />,
  );
  vi.mocked(post).mockRejectedValue(Error("question_revision_conflict"));
  await userEvent.selectOptions(screen.getByRole("combobox"), "No");
  await userEvent.click(screen.getByRole("button"));
  expect(await screen.findByText("question_revision_conflict")).toBeVisible();
  expect(saved).not.toHaveBeenCalled();
});
