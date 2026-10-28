import { Agent } from "@/features/agent";
import { notFound } from "next/navigation";
import { StartupExplorer } from "@/features/startups";
import { CompanyDetail } from "@/features/company";
import { Jobs } from "@/features/jobs";
import { Discover } from "@/features/discover";
import { People } from "@/features/people";
import { Applications, ApplicationDetail } from "@/features/applications";
import { Outreach, OutreachDetail } from "@/features/outreach";
import { Connections } from "@/features/connections";
import { Notifications, Settings } from "@/features/notifications";
import { ProfileWizard } from "@/features/profile";
import { UnansweredQuestionsQueue } from "@/features/unanswered-questions";
import { CandidateKnowledge } from "@/features/candidate-knowledge";
export default async function Page({
  params,
  searchParams,
}: {
  params: Promise<{ section: string; detail?: string[] }>;
  searchParams?: Promise<{ missing_input?: string; question_id?: string }>;
}) {
  const { section, detail } = await params;
  const sp = await searchParams;
  const rawId = sp?.missing_input || sp?.question_id;
  const initialRequestId =
    rawId && /^[a-f0-9-]{16,36}$/i.test(rawId) ? rawId : undefined;
  if (section === "profile" && initialRequestId)
    return <UnansweredQuestionsQueue initialRequestId={initialRequestId} />;
  if (detail?.length) {
    if (detail.length !== 1 || !/^[-a-f0-9]{36}$/.test(detail[0])) notFound();
    if (section === "startups") return <CompanyDetail id={detail[0]} />;
    if (section === "applications") return <ApplicationDetail id={detail[0]} />;
    if (section === "outreach") return <OutreachDetail id={detail[0]} />;
    notFound();
  }
  switch (section) {
    case "agent":
      return <Agent />;
    case "startups":
      return <StartupExplorer />;
    case "jobs":
      return <Jobs />;
    case "discover":
      return <Discover />;
    case "people":
      return <People />;
    case "applications":
      return <Applications />;
    case "needs-input":
      return <UnansweredQuestionsQueue initialRequestId={initialRequestId} />;
    case "outreach":
      return <Outreach />;
    case "connections":
      return <Connections />;
    case "candidate-facts":
      return <CandidateKnowledge />;
    case "notifications":
      return <Notifications />;
    case "profile":
      return <ProfileWizard />;
    case "settings":
      return <Settings />;
    default:
      notFound();
  }
}
