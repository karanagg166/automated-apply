import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import {
  ExecutionQuestionDelivery,
  isPendingExecutionQuestion,
  type ExecutionQuestion,
} from "@/features/execution-question-answer";
import { post } from "@/lib/api";
vi.mock("@/lib/api", async (original) => ({
  ...(await original<typeof import("@/lib/api")>()),
  post: vi.fn(),
}));
const question: ExecutionQuestion = {
  id: "question-1",
  packet_id: "packet-1",
  packet_revision: 7,
  execution_id: "execution-1",
  question: "Preferred shift?",
  state: "delivery_unknown",
  answer: null,
  employer: "Fictional",
  role: "Engineer",
  expires_at: "2099-01-01T00:00:00Z",
  delivery_attempt: "00000000-0000-4000-8000-000000000001",
  delivery_lease: "2000-01-01T00:00:00Z",
};
beforeEach(() => vi.resetAllMocks());
it("retains uncertain and confirmed-not-sent questions as dashboard answerable without auto-confirming delivery", () => {
  expect(isPendingExecutionQuestion(question)).toBe(true);
  expect(
    isPendingExecutionQuestion({ ...question, state: "delivery_not_sent" }),
  ).toBe(true);
  render(<ExecutionQuestionDelivery question={question} onSaved={vi.fn()} />);
  expect(
    screen.getByRole("button", { name: "Record delivery outcome" }),
  ).toBeDisabled();
  expect(post).not.toHaveBeenCalled();
});
it("records verified not-sent outcome for the exact attempt without a resend request", async () => {
  vi.mocked(post).mockResolvedValue({});
  const saved = vi.fn();
  render(<ExecutionQuestionDelivery question={question} onSaved={saved} />);
  await userEvent.selectOptions(
    screen.getByLabelText("Verified Telegram delivery outcome"),
    "not_sent",
  );
  await userEvent.click(
    screen.getByRole("button", { name: "Record delivery outcome" }),
  );
  await waitFor(() => expect(saved).toHaveBeenCalledTimes(1));
  expect(post).toHaveBeenCalledTimes(1);
  expect(post).toHaveBeenCalledWith(
    "execution/questions/question-1/delivery-reconciliation",
    {
      expected_delivery_attempt: question.delivery_attempt,
      outcome: "not_sent",
      message_id: null,
    },
  );
});
it("requires a positive safely represented exact message ID before reporting sent", async () => {
  vi.mocked(post).mockResolvedValue({});
  render(<ExecutionQuestionDelivery question={question} onSaved={vi.fn()} />);
  await userEvent.selectOptions(
    screen.getByLabelText("Verified Telegram delivery outcome"),
    "sent",
  );
  const button = screen.getByRole("button", {
    name: "Record delivery outcome",
  });
  const input = screen.getByLabelText("Exact Telegram message ID");
  expect(button).toBeDisabled();
  await userEvent.type(input, "9007199254740993");
  expect(button).toBeDisabled();
  await userEvent.clear(input);
  await userEvent.type(input, "33");
  await userEvent.click(button);
  expect(post).toHaveBeenCalledTimes(1);
  expect(post).toHaveBeenCalledWith(
    "execution/questions/question-1/delivery-reconciliation",
    {
      expected_delivery_attempt: question.delivery_attempt,
      outcome: "sent",
      message_id: 33,
    },
  );
});
it("preserves old unbound prompts and blocks reconciliation while the original send lease is active", async () => {
  const { rerender } = render(
    <ExecutionQuestionDelivery
      question={{ ...question, delivery_attempt: null }}
      onSaved={vi.fn()}
    />,
  );
  expect(
    screen.queryByRole("form", { name: "Record Telegram delivery outcome" }),
  ).not.toBeInTheDocument();
  rerender(
    <ExecutionQuestionDelivery
      question={{ ...question, delivery_lease: "2099-01-01T00:00:00Z" }}
      onSaved={vi.fn()}
    />,
  );
  await userEvent.selectOptions(
    screen.getByLabelText("Verified Telegram delivery outcome"),
    "not_sent",
  );
  expect(
    screen.getByRole("button", { name: "Record delivery outcome" }),
  ).toBeDisabled();
  expect(post).not.toHaveBeenCalled();
});
