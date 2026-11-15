"use client";
import { type ExtensionTask } from "@/features/extension-assistant";
import { type Schema } from "@/lib/api";
export type FieldReviewStatus =
  | "Ready"
  | "Needs Answer"
  | "Pending Review"
  | "Manual Only"
  | "Challenge Required"
  | "Failed Validation";

export function getFieldReviewStatus({
  field,
  task,
  isReviewed,
  isDirty,
  exceedsLimit,
}: {
  field: Schema<"PacketField">;
  task?: ExtensionTask | null;
  isReviewed: boolean;
  isDirty?: boolean;
  exceedsLimit?: boolean;
}): {
  status: FieldReviewStatus;
  nextAction: string;
  tone: "green" | "amber" | "neutral" | "red";
} {
  // Receipt field IDs address a DOM snapshot, not PacketField UUIDs. The API
  // provides no mapping, so receipt verification belongs in the history only.
  // 2. Failed Validation
  const hasValidationError = Boolean(
    field.validation_status === "validation_failed" || exceedsLimit,
  );
  if (hasValidationError) {
    return {
      status: "Failed Validation",
      nextAction: exceedsLimit
        ? "Shorten answer to satisfy character or word limit constraints."
        : "Correct the answer to pass format and validation checks.",
      tone: "red",
    };
  }

  // 3. Challenge Required
  const isChallenge = Boolean(
    task?.challenge_state === "CHALLENGE_BLOCKING" ||
    task?.challenge_state === "WIDGET_PRESENT_UNVERIFIED" ||
    task?.challenge_state === "UNKNOWN" ||
    task?.state === "CHALLENGE_REQUIRED" ||
    (field.category as string) === "challenge" ||
    (field.category as string) === "captcha",
  );
  if (isChallenge) {
    return {
      status: "Challenge Required",
      nextAction:
        "Complete the security challenge on the official page before filling.",
      tone: "red",
    };
  }

  // 4. Manual Only
  const isManualOnly = Boolean(
    field.field_type === "file" ||
    field.validation_status === "file_upload_required" ||
    field.category === "resume_upload",
  );
  if (isManualOnly) {
    return {
      status: "Manual Only",
      nextAction:
        field.field_type === "file" || field.category === "resume_upload"
          ? "Download approved resume PDF and upload manually on employer portal."
          : "Complete manually on the employer portal.",
      tone: "neutral",
    };
  }

  // 5. Needs Answer
  const isExpired = Boolean(
    field.provenance?.answer_expires_at &&
    Date.parse(field.provenance.answer_expires_at) <= Date.now(),
  );
  const isNeedsAnswer = Boolean(
    field.validation_status === "needs_input" ||
    field.validation_status === "provider_unavailable" ||
    (!field.effective_answer && field.required) ||
    isExpired,
  );
  if (isNeedsAnswer) {
    return {
      status: "Needs Answer",
      nextAction: "Provide an answer below or queue for Telegram.",
      tone: "amber",
    };
  }

  // 6. Ready (checked by owner or already reviewed in packet, not dirty)
  if (isReviewed && !isDirty) {
    return {
      status: "Ready",
      nextAction: "Ready to fill in Chrome once packet is approved.",
      tone: "green",
    };
  }

  // 7. Pending Review
  return {
    status: "Pending Review",
    nextAction: "Review proposed answer and mark reviewed.",
    tone: "amber",
  };
}
