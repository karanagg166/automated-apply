"use client";

import { useState } from "react";
import { Automation } from "@/features/automation";
import { JobDiscovery } from "@/features/job-discovery";
import { SearchPreferencesEditor } from "@/features/search-preferences";
import { ApifySourceManagement } from "@/features/apify-sources";
import { PageTitle } from "@/components/ui";
import { StartupDiscovery } from "./startup-discovery";

export function Discover() {
  const [tab, setTab] = useState<"jobs" | "startups" | "apify">("jobs");

  return (
    <>
      <PageTitle
        eyebrow="DISCOVER WITH INTENTION"
        title="A fresh set of possibilities."
        description="Run a bounded search using an approved public API. Preview first, then choose to proceed."
      />
      <SearchPreferencesEditor />

      <div
        className="status-tabs"
        aria-label="Discovery workflow"
        role="tablist"
      >
        <button
          type="button"
          role="tab"
          id="tab-job-discovery"
          aria-controls="panel-job-discovery"
          aria-selected={tab === "jobs"}
          className={tab === "jobs" ? "selected" : ""}
          onClick={() => setTab("jobs")}
        >
          Job discovery
        </button>
        <button
          type="button"
          role="tab"
          id="tab-startup-discovery"
          aria-controls="panel-startup-discovery"
          aria-selected={tab === "startups"}
          className={tab === "startups" ? "selected" : ""}
          onClick={() => setTab("startups")}
        >
          Startup discovery
        </button>
        <button
          type="button"
          role="tab"
          id="tab-apify-sources"
          aria-controls="panel-apify-sources"
          aria-selected={tab === "apify"}
          className={tab === "apify" ? "selected" : ""}
          onClick={() => setTab("apify")}
        >
          Apify & sources
        </button>
      </div>

      {tab === "jobs" ? (
        <div
          id="panel-job-discovery"
          role="tabpanel"
          aria-labelledby="tab-job-discovery"
        >
          <JobDiscovery />
        </div>
      ) : tab === "startups" ? (
        <div
          id="panel-startup-discovery"
          role="tabpanel"
          aria-labelledby="tab-startup-discovery"
        >
          <StartupDiscovery onReviewChild={() => setTab("jobs")} />
        </div>
      ) : (
        <div
          id="panel-apify-sources"
          role="tabpanel"
          aria-labelledby="tab-apify-sources"
        >
          <ApifySourceManagement />
        </div>
      )}

      <Automation />
    </>
  );
}
