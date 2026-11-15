import { type Schema } from "@/lib/api";
type Packet = Schema<"PacketRead">;
export function pipelineColumn(
  packet: Pick<Packet, "tracking_state" | "lifecycle_state">,
) {
  const tracking: Record<string, string> = {
    interview_scheduled: "Interview",
    offer_received: "Offer",
    application_rejected: "Rejected",
    archived: "Archived",
  };
  return (
    tracking[packet.tracking_state] ||
    {
      created: "Preparing",
      preparing: "Preparing",
      needs_input: "Needs Input",
      ready_for_review: "Ready for Review",
      reviewed: "Ready for Review",
      approved_for_manual_handoff: "Approved / Manual Handoff",
      external_application_opened: "External Application Opened",
      submitting: "Submitting",
      submission_unknown: "Submission Unknown",
      user_reported_submitted: "Applied — User Reported",
      provider_confirmed_submitted: "Applied — Provider Confirmed",
      abandoned: "Archived",
      withdrawn: "Archived",
    }[packet.lifecycle_state] ||
    "Preparing"
  );
}
