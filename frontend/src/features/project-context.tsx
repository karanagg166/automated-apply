"use client";
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, post, type Schema } from "@/lib/api";
import {
  Badge,
  Button,
  ErrorState,
  Field,
  Input,
  Notice,
} from "@/components/ui";
type Configuration = Schema<"CandidateConfiguration">;
type Project = Schema<"ProjectConfiguration">;
type Record = { revision: number; configuration: Configuration };
type Fact = {
  id: string;
  text: string;
  verification: string;
  evidence: Array<{
    file: string;
    url?: string | null;
    content_sha256: string;
  }>;
};
type Knowledge = {
  candidate: {
    revision: string;
    facts: Fact[];
    candidate_contexts: { explanation_100: string };
  } | null;
  approved: { revision: string; contexts: { explanation_100: string } } | null;
};
export function ProjectContext() {
  const client = useQueryClient();
  const query = useQuery({
    queryKey: ["candidate-context"],
    queryFn: () => api<Record>("dashboard/candidate-context/configuration"),
  });
  const [draft, setDraft] = useState<Configuration | null>(null);
  useEffect(() => {
    if (query.data) setDraft(query.data.configuration);
  }, [query.data]);
  const save = useMutation({
    retry: false,
    mutationFn: () =>
      api("dashboard/candidate-context/configuration", {
        method: "PUT",
        body: JSON.stringify({
          configuration: draft,
          expected_revision: query.data?.revision,
        }),
      }),
    onSuccess: () =>
      client.invalidateQueries({ queryKey: ["candidate-context"] }),
  });
  if (query.isError) return <ErrorState error={query.error} />;
  if (!draft || !query.data) return null;
  const update = (index: number, values: Partial<Project>) =>
    setDraft({
      ...draft,
      projects: draft.projects!.map((project, i) =>
        i === index ? { ...project, ...values } : project,
      ),
    });
  return (
    <section className="panel spaced">
      <div className="panel-header">
        <h2>Ranked project context & profile links</h2>
        <Badge>Review required</Badge>
      </div>
      <div className="panel-body stack">
        <p>
          Save your project names, importance and supported technologies. Blank
          fields stay empty. Source changes create pending context for your
          review.
        </p>
        {(draft.projects || []).map((project, index) => (
          <div className="evidence-item stack" key={project.id}>
            <div className="form-grid">
              <Field label={`Ranked project ${index + 1} name`}>
                <Input
                  maxLength={200}
                  value={project.name || ""}
                  onChange={(e) => update(index, { name: e.target.value })}
                />
              </Field>
              <Field
                label={`Ranked project ${index + 1} importance (1 is highest)`}
              >
                <Input
                  type="number"
                  min={1}
                  max={100}
                  value={project.priority}
                  onChange={(e) =>
                    update(index, { priority: Number(e.target.value) })
                  }
                />
              </Field>
              <Field label={`Ranked project ${index + 1} GitHub repository`}>
                <Input
                  type="url"
                  value={project.repository_url || ""}
                  onChange={(e) =>
                    update(index, { repository_url: e.target.value || null })
                  }
                />
              </Field>
              <Field label={`Ranked project ${index + 1} technology stack`}>
                <Input
                  value={(project.tech_stack || []).join(", ")}
                  onChange={(e) =>
                    update(index, {
                      tech_stack: e.target.value
                        .split(",")
                        .map((s) => s.trim())
                        .filter(Boolean),
                    })
                  }
                />
              </Field>
              <Field
                label={`Ranked project ${index + 1} context template`}
                hint="Use your completed candidate_context/ Markdown template for architecture, APIs, database, caching, deployment, challenges, contribution and references."
              >
                <Input
                  value={project.context_file || ""}
                  onChange={(e) =>
                    update(index, { context_file: e.target.value })
                  }
                />
              </Field>
            </div>
            <ProjectReview
              id={project.id}
              configurationRevision={query.data!.revision}
            />
          </div>
        ))}
        <Notice>
          Summaries use deterministic extraction. Only approved facts are
          available to answers and Telegram. Repository access requires an
          owner-authorized local checkout.
        </Notice>
        {save.isError && <ErrorState error={save.error} />}
        <Button
          type="button"
          disabled={save.isPending}
          onClick={() => save.mutate()}
        >
          Save ranked projects
        </Button>
        {save.isSuccess && (
          <p role="status">
            Project configuration saved. Review facts before approving context.
          </p>
        )}
      </div>
    </section>
  );
}
function ProjectReview({
  id,
  configurationRevision,
}: {
  id: string;
  configurationRevision: number;
}) {
  const client = useQueryClient();
  const query = useQuery({
    queryKey: ["project-review", id, configurationRevision],
    refetchInterval: 30000,
    queryFn: () => api<Knowledge>(`dashboard/candidate-context/projects/${id}`),
  });
  const [selected, setSelected] = useState<string[]>([]),
    [confirmed, setConfirmed] = useState(false);
  useEffect(() => {
    setSelected([]);
    setConfirmed(false);
  }, [query.data?.candidate?.revision, configurationRevision]);
  const refresh = () =>
    client.invalidateQueries({ queryKey: ["project-review", id] });
  const build = useMutation({
    retry: false,
    mutationFn: () =>
      post(`dashboard/candidate-context/projects/${id}/build`, {
        expected_configuration_revision: configurationRevision,
      }),
    onSuccess: refresh,
  });
  const approve = useMutation({
    retry: false,
    mutationFn: () =>
      post(`dashboard/candidate-context/projects/${id}/approve`, {
        expected_revision: query.data?.candidate?.revision,
        fact_ids: selected,
        owner_confirmed: confirmed,
      }),
    onSuccess: refresh,
  });
  const candidate = query.data?.candidate;
  return (
    <div className="stack">
      <Button
        type="button"
        disabled={build.isPending}
        onClick={() => build.mutate()}
      >
        Recompute context for {id}
      </Button>
      {[query, build, approve].map((operation, index) =>
        operation.isError ? (
          <ErrorState key={index} error={operation.error} />
        ) : null,
      )}
      {candidate && (
        <>
          <p>
            <strong>Pending compact summary · deterministic extraction</strong>
          </p>
          <p>
            {candidate.candidate_contexts.explanation_100 ||
              "No supported summary facts yet."}
          </p>
          {candidate.facts.map((fact) => (
            <label key={fact.id}>
              <input
                type="checkbox"
                disabled={
                  fact.verification === "inferred" || !fact.evidence.length
                }
                checked={selected.includes(fact.id)}
                onChange={(e) =>
                  setSelected(
                    e.target.checked
                      ? [...selected, fact.id]
                      : selected.filter((id) => id !== fact.id),
                  )
                }
              />{" "}
              {fact.text}
              <small>
                {" "}
                Evidence:{" "}
                {fact.evidence
                  .map((e) => `${e.file} (${e.content_sha256.slice(0, 12)})`)
                  .join(", ")}
              </small>
            </label>
          ))}
          <label>
            <input
              type="checkbox"
              checked={confirmed}
              onChange={(e) => setConfirmed(e.target.checked)}
            />{" "}
            I reviewed these facts and their evidence, including any personal
            contributions.
          </label>
          <Button
            type="button"
            disabled={!confirmed || !selected.length || approve.isPending}
            onClick={() => approve.mutate()}
          >
            Approve selected project facts
          </Button>
        </>
      )}
      {query.data?.approved && (
        <p>
          <strong>
            {query.data.approved.revision === candidate?.revision
              ? "Approved compact summary"
              : "Historical summary · source changed, review required"}
          </strong>
          : {query.data.approved.contexts.explanation_100}
        </p>
      )}
    </div>
  );
}
