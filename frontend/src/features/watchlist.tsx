"use client";
import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, post } from "@/lib/api";
import {
  Badge,
  Button,
  Empty,
  ErrorState,
  External,
  Field,
  Input,
  Notice,
  PageTitle,
  Skeleton,
} from "@/components/ui";
import { stamp } from "@/features/autopilot-forms";
import { portalName } from "@/features/applied-model";

export type WatchPlatform =
  "greenhouse" | "lever" | "ashby" | "smartrecruiters";
export type Watcher = {
  platform: WatchPlatform | string;
  slug: string;
  active: boolean;
  board_url?: string | null;
  last_polled_at?: string | null;
  last_status?: string | number | null;
  jobs_found?: number | null;
};
export type ProbeResult = {
  platform: WatchPlatform | string;
  slug: string;
  board_url?: string | null;
  job_count: number;
  matched_count: number;
  sample: Array<{
    title: string;
    location?: string | null;
    url?: string | null;
    passes: boolean;
    reasons: string[];
  }>;
  already_watched: boolean;
};

export const WATCHERS_KEY = ["v2-watchers"] as const;

function useSaveWatcher() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: { platform: string; slug: string; active: boolean }) =>
      post<Watcher>("v2/portals/watchers", body),
    onSuccess: () => client.invalidateQueries({ queryKey: WATCHERS_KEY }),
  });
}

function ProbeBar() {
  const [target, setTarget] = useState("");
  const probe = useMutation({
    mutationFn: () =>
      post<ProbeResult>("v2/portals/watchers/probe", { target: target.trim() }),
  });
  const save = useSaveWatcher();
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (target.trim()) {
      save.reset();
      probe.mutate();
    }
  };
  const result = probe.data;
  return (
    <section className="panel" aria-labelledby="probe-heading">
      <div className="panel-header">
        <div>
          <h2 id="probe-heading">Auto-detect ATS</h2>
          <p>
            Paste a company careers URL or <code>greenhouse:stripe</code>. Only
            public Greenhouse, Lever, Ashby and SmartRecruiters boards are read.
          </p>
        </div>
      </div>
      <form className="panel-body stack" onSubmit={submit}>
        <Field label="Careers URL or platform:slug">
          <Input
            value={target}
            maxLength={500}
            placeholder="https://boards.greenhouse.io/acme"
            onChange={(e) => setTarget(e.target.value)}
          />
        </Field>
        <div className="actions">
          <Button
            type="submit"
            variant="primary"
            busy={probe.isPending}
            disabled={!target.trim()}
          >
            Detect board
          </Button>
        </div>
        {probe.isError && <ErrorState error={probe.error} />}
        {result && (
          <div className="stack" aria-label="Probe result">
            <div className="tag-list">
              <Badge tone="green">
                {portalName(result.platform)} · {result.slug}
              </Badge>
              <Badge tone="neutral">{result.job_count} open jobs</Badge>
              <Badge tone={result.matched_count ? "green" : "amber"}>
                {result.matched_count} match your rules
              </Badge>
            </div>
            {result.sample.length > 0 && (
              <ul className="stack">
                {result.sample.map((job, i) => (
                  <li key={`${job.title}-${i}`}>
                    <Badge tone={job.passes ? "green" : "neutral"}>
                      {job.passes ? "Match" : "Filtered"}
                    </Badge>{" "}
                    {job.title}
                    {job.location ? ` · ${job.location}` : ""}
                    {!job.passes && job.reasons.length > 0 && (
                      <small className="muted">
                        {" "}
                        — {job.reasons.join("; ")}
                      </small>
                    )}
                  </li>
                ))}
              </ul>
            )}
            {result.already_watched || save.isSuccess ? (
              <Notice>This board is on your watchlist.</Notice>
            ) : (
              <Button
                variant="primary"
                busy={save.isPending}
                onClick={() =>
                  save.mutate({
                    platform: result.platform,
                    slug: result.slug,
                    active: true,
                  })
                }
              >
                Add to watchlist
              </Button>
            )}
            {save.isError && <ErrorState error={save.error} />}
          </div>
        )}
      </form>
    </section>
  );
}

function WatcherRow({ watcher }: { watcher: Watcher }) {
  const save = useSaveWatcher();
  return (
    <tr>
      <td>{portalName(watcher.platform)}</td>
      <td>
        {watcher.board_url ? (
          <External href={watcher.board_url}>{watcher.slug}</External>
        ) : (
          watcher.slug
        )}
      </td>
      <td>
        <Badge tone={watcher.active ? "green" : "neutral"}>
          {watcher.active ? "Active" : "Paused"}
        </Badge>
      </td>
      <td>
        <small>
          {stamp(watcher.last_polled_at, "Not polled yet")}
          {watcher.last_status != null ? ` · ${watcher.last_status}` : ""}
        </small>
      </td>
      <td>{watcher.jobs_found ?? 0}</td>
      <td>
        <Button
          busy={save.isPending}
          aria-label={`${watcher.active ? "Pause" : "Resume"} ${watcher.platform}:${watcher.slug}`}
          onClick={() =>
            save.mutate({
              platform: watcher.platform,
              slug: watcher.slug,
              active: !watcher.active,
            })
          }
        >
          {watcher.active ? "Pause" : "Resume"}
        </Button>
        {save.isError && (
          <small className="portal-hint" role="alert">
            {save.error.message}
          </small>
        )}
      </td>
    </tr>
  );
}

export function Watchlist() {
  const watchers = useQuery({
    queryKey: WATCHERS_KEY,
    queryFn: () => api<Watcher[]>("v2/portals/watchers"),
    refetchInterval: 60000,
  });
  return (
    <>
      <PageTitle
        eyebrow="DISCOVERY · ATS WATCHLIST"
        title="Watchlist"
        description="Company job boards polled for fresh postings. New matches jump the queue."
      />
      <ProbeBar />
      <section className="panel" aria-labelledby="watchers-heading">
        <div className="panel-header">
          <div>
            <h2 id="watchers-heading">Watched boards</h2>
            <p>Paused boards keep their history but are not polled.</p>
          </div>
        </div>
        <div className="panel-body">
          {watchers.isPending ? (
            <Skeleton />
          ) : watchers.isError ? (
            <ErrorState
              error={watchers.error}
              retry={() => watchers.refetch()}
            />
          ) : watchers.data.length === 0 ? (
            <Empty description="No boards watched yet. Detect one above." />
          ) : (
            <div className="table-wrap">
              <table>
                <caption className="visually-hidden">
                  Watched ATS boards
                </caption>
                <thead>
                  <tr>
                    <th scope="col">ATS</th>
                    <th scope="col">BOARD</th>
                    <th scope="col">STATUS</th>
                    <th scope="col">LAST POLL</th>
                    <th scope="col">JOBS</th>
                    <th scope="col">
                      <span className="visually-hidden">Actions</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {watchers.data.map((w) => (
                    <WatcherRow key={`${w.platform}:${w.slug}`} watcher={w} />
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </section>
    </>
  );
}
