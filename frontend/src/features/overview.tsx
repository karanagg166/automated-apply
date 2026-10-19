"use client";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowRight,
  ArrowUpRight,
  BriefcaseBusiness,
  Building2,
  ChevronRight,
  Compass,
  FileCheck2,
  Mail,
  Plug,
  Sparkles,
  Target,
  UserRound,
} from "lucide-react";
import { api, type Schema } from "@/lib/api";
import {
  Badge,
  Button,
  Empty,
  ErrorState,
  PageTitle,
  Skeleton,
} from "@/components/ui";
type Metrics = Record<string, number>;
export function Overview() {
  const overview = useQuery({
    queryKey: ["overview"],
    queryFn: () => api<Metrics>("dashboard/overview"),
  });
  const profile = useQuery({
    queryKey: ["profile"],
    queryFn: () => api<Schema<"CandidateProfileRead">>("profile"),
  });
  const connections = useQuery({
    queryKey: ["connections"],
    queryFn: () =>
      api<{ connectors: Array<{ platform: string; live_verified: boolean }> }>(
        "integrations",
      ),
  });
  const metrics = [
    ["Startups discovered", "startups_discovered", Building2],
    ["Relevant jobs", "relevant_jobs", BriefcaseBusiness],
    ["Not yet applied", "not_yet_applied", Target],
    ["Applications prepared", "applications_prepared", FileCheck2],
  ] as const;
  return (
    <>
      <PageTitle
        eyebrow="YOUR NEXT CHAPTER STARTS HERE"
        title={
          profile.data
            ? `Good to see you, ${profile.data.full_name.split(" ")[0]}.`
            : "A little closer to what’s next."
        }
        description="A clear view of your search. Every opportunity, every next step."
        actions={
          <Link href="/startups" className="button primary">
            <Compass size={15} />
            Explore startups
            <ArrowUpRight size={15} />
          </Link>
        }
      />
      <div className="welcome-banner">
        <div>
          <div className="eyebrow">
            {profile.data
              ? "MAKE YOUR NEXT MOVE COUNT"
              : "FIRST, MAKE THIS SPACE YOURS"}
          </div>
          <h2>
            {profile.data
              ? "The right team changes everything."
              : "Your experience. Your direction."}
          </h2>
          <p>
            {profile.data
              ? "Find teams that fit your skills, inspect the evidence, and prepare an application that sounds like you."
              : "Bring your resume and review your profile. Your confirmed experience becomes the foundation for relevant matches and grounded applications."}
          </p>
          <div className="actions">
            <Link
              href={profile.data ? "/startups" : "/profile"}
              className="button primary"
            >
              {profile.data ? "Find your next team" : "Set up my profile"}
              <ArrowRight size={14} />
            </Link>
            <Link href="/connections" className="button ghost">
              Review connections
              <ArrowUpRight size={13} />
            </Link>
          </div>
        </div>
        <div className="banner-symbol">
          <Compass size={42} strokeWidth={1} />
        </div>
      </div>
      {overview.isPending ? (
        <Skeleton />
      ) : overview.isError ? (
        <ErrorState error={overview.error} retry={() => overview.refetch()} />
      ) : (
        <div className="metrics">
          {metrics.map(([label, key, Icon]) => (
            <div className="metric" key={key}>
              <div className="metric-label">
                {label}
                <Icon size={15} />
              </div>
              <strong>{overview.data[key]}</strong>
              <small>
                <span className="status-dot" />
                {key === "relevant_jobs"
                  ? "Saved match score ≥ 70"
                  : "From your saved workspace"}
              </small>
            </div>
          ))}
        </div>
      )}
      <div className="overview-grid">
        <section className="panel">
          <div className="panel-header">
            <div>
              <h2>Make your next move</h2>
              <p>Thoughtful steps, from discovery to conversation.</p>
            </div>
            <Badge>OWNER CONTROLLED</Badge>
          </div>
          {[
            [
              Building2,
              "Explore emerging teams",
              "Filter by location, technology and evidenced team size.",
              "/startups",
            ],
            [
              FileCheck2,
              "Prepare a strong application",
              "Review every field, then hand off to the official site.",
              "/applications",
            ],
            [
              Mail,
              "Start a relevant conversation",
              "Grounded drafts, exact-content approval, secondary Gmail.",
              "/outreach",
            ],
          ].map(([Icon, title, text, href]) => {
            const I = Icon as typeof Building2;
            return (
              <Link
                className="row-link"
                href={href as string}
                key={title as string}
              >
                <span className="row-icon">
                  <I size={18} />
                </span>
                <div>
                  <strong>{title as string}</strong>
                  <p>{text as string}</p>
                </div>
                <ChevronRight size={15} />
              </Link>
            );
          })}
        </section>
        <section className="panel">
          <div className="panel-header">
            <div>
              <h2>Workspace readiness</h2>
              <p>A truthful picture of what’s ready.</p>
            </div>
            <Sparkles size={17} className="muted" />
          </div>
          <Link className="row-link" href="/profile">
            <UserRound size={18} className="muted" />
            <div>
              <strong>Candidate profile</strong>
              <p>
                {profile.data
                  ? "Saved · review your latest facts"
                  : profile.isError &&
                      "status" in profile.error &&
                      profile.error.status !== 404
                    ? "Profile unavailable"
                    : "Awaiting your review"}
              </p>
            </div>
            <ArrowUpRight size={15} />
          </Link>
          <Link className="row-link" href="/connections">
            <Plug size={18} className="muted" />
            <div>
              <strong>Account connections</strong>
              <p>
                {connections.data
                  ? `${connections.data.connectors.filter((c) => c.live_verified).length} independently live-verified · ${connections.data.connectors.filter((c) => !c.live_verified).length} need setup or verification`
                  : "Checking connection health"}
              </p>
            </div>
            <ArrowUpRight size={15} />
          </Link>
          <div className="panel-body">
            <div className="tag-list">
              <Badge>{overview.data?.shortlisted ?? "—"} shortlisted</Badge>
              <Badge>{overview.data?.outstanding_reviews ?? "—"} reviews</Badge>
              <Badge>
                {overview.data?.approved_gmail_messages ?? "—"} approved drafts
              </Badge>
            </div>
            <p className="section-intro spaced">
              Opening a job is a first step. Applications are counted as
              submitted only when reported or supported by provider evidence.
            </p>
          </div>
        </section>
      </div>
      <section className="spaced">
        <div className="split">
          <h2>Your search, in motion</h2>
          <Link className="external" href="/applications">
            Open pipeline
            <ArrowUpRight size={14} />
          </Link>
        </div>
        {overview.data?.applications_prepared ? (
          <div className="metrics spaced">
            {[
              ["User-reported submissions", "applications_reported_submitted"],
              [
                "Provider-confirmed submissions",
                "applications_provider_confirmed",
              ],
            ].map(([label, key]) => (
              <div className="metric" key={key}>
                <div className="metric-label">{label}</div>
                <strong>{overview.data[key]}</strong>
              </div>
            ))}
          </div>
        ) : (
          <div className="spaced">
            <Empty
              title="A fresh start. A focused search."
              description="Your pipeline will take shape as you save opportunities and prepare applications. Start with a team you’d like to join."
              action={
                <Link href="/startups" className="button">
                  Find a team
                  <ArrowRight size={14} />
                </Link>
              }
            />
          </div>
        )}
      </section>
    </>
  );
}
