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
export default async function Page({
  params,
}: {
  params: Promise<{ section: string; detail?: string[] }>;
}) {
  const { section, detail } = await params;
  if (detail?.length) {
    if (detail.length !== 1 || !/^[-a-f0-9]{36}$/.test(detail[0])) notFound();
    if (section === "startups") return <CompanyDetail id={detail[0]} />;
    if (section === "applications") return <ApplicationDetail id={detail[0]} />;
    if (section === "outreach") return <OutreachDetail id={detail[0]} />;
    notFound();
  }
  switch (section) {
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
    case "outreach":
      return <Outreach />;
    case "connections":
      return <Connections />;
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
