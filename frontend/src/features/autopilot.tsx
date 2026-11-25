"use client";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { GmailPermissionBadge, PageTitle } from "@/components/ui";
import { AIRouterPanel, SemanticCacheTable } from "@/features/autopilot-ai";
import { type PortalRules } from "@/features/autopilot-forms";
import { HitlInbox } from "@/features/autopilot-hitl";
import { ApplicationsLog } from "@/features/autopilot-log";
import { PortalRulesEditor, RULES_KEY } from "@/features/autopilot-rules";
import { ScreeningProfileEditor } from "@/features/autopilot-screening";
import { WorkerStatusPanel } from "@/features/autopilot-status";

export function Autopilot() {
  const rules = useQuery({
    queryKey: RULES_KEY,
    queryFn: () => api<PortalRules[]>("v2/portal-rules"),
  });
  return (
    <>
      <PageTitle
        eyebrow="AUTOPILOT · PYTHON V2 CONTROL PLANE"
        title="Autopilot"
        description="Run, pause and tune the unattended application worker. Every portal keeps its own caps, and anything uncertain comes back to you."
        actions={<GmailPermissionBadge />}
      />
      <WorkerStatusPanel />
      <HitlInbox />
      <PortalRulesEditor />
      <ScreeningProfileEditor />
      <AIRouterPanel />
      <SemanticCacheTable />
      <ApplicationsLog
        platforms={rules.data?.map((row) => row.platform) ?? []}
      />
    </>
  );
}
