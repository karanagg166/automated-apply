"use client";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, post, type Schema } from "@/lib/api";
import {
  Badge,
  Button,
  ErrorState,
  External,
  Field,
  Input,
  Select,
} from "@/components/ui";
type Resource = Schema<"ResourceRead">;
type Kind = Schema<"ResourceWrite">["resource_type"];
const kinds: Kind[] = [
  "leetcode",
  "codeforces",
  "geeksforgeeks",
  "hackerrank",
  "kaggle",
  "other",
];
export function ProfileResources({ enabled = true }: { enabled?: boolean }) {
  const client = useQueryClient();
  const query = useQuery({
    enabled,
    queryKey: ["resources"],
    queryFn: () => api<Schema<"ResourceList">>("candidate/resources"),
  });
  const [kind, setKind] = useState<Kind>("leetcode"),
    [label, setLabel] = useState(""),
    [url, setUrl] = useState(""),
    [confirmed, setConfirmed] = useState(false),
    [editing, setEditing] = useState<Resource | null>(null);
  const save = useMutation({
    retry: false,
    mutationFn: () =>
      post("candidate/resources", {
        ...(editing ? { id: editing.id } : {}),
        resource_type: kind,
        label,
        url,
        user_confirmed: confirmed,
        is_primary: editing?.is_primary || false,
      }),
    onSuccess: () => {
      setConfirmed(false);
      setEditing(null);
      setUrl("");
      setLabel("");
      client.invalidateQueries({ queryKey: ["resources"] });
    },
  });
  return (
    <section className="panel spaced">
      <div className="panel-header">
        <h2>Additional profile links</h2>
        <Badge>Owner review required</Badge>
      </div>
      <div className="panel-body stack">
        <p>
          Save LeetCode, Codeforces and other links used by factual answers. Use
          Other with a specific label for CodeChef or another profile. GitHub,
          LinkedIn and portfolio are in the profile wizard.
        </p>
        {query.isError && <ErrorState error={query.error} />}
        {(query.data?.resources || [])
          .filter((resource) => kinds.includes(resource.resource_type))
          .map((resource) => (
            <div className="evidence-item split" key={resource.id}>
              <div>
                <strong>{resource.label}</strong>
                <Badge>
                  {resource.user_confirmed ? "Owner confirmed" : "Needs review"}
                </Badge>
              </div>
              <External href={resource.url}>Review link</External>
              <Button
                type="button"
                onClick={() => {
                  setEditing(resource);
                  setKind(resource.resource_type);
                  setLabel(resource.label);
                  setUrl(resource.url);
                  setConfirmed(false);
                }}
              >
                Edit {resource.label}
              </Button>
            </div>
          ))}
        <form
          className="stack"
          onSubmit={(e) => {
            e.preventDefault();
            save.mutate();
          }}
        >
          <div className="form-grid">
            <Field label="Profile link type">
              <Select
                disabled={!!editing}
                value={kind}
                onChange={(e) => {
                  setKind(e.target.value as Kind);
                  setConfirmed(false);
                }}
              >
                {kinds.map((value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Profile link label">
              <Input
                required
                maxLength={200}
                value={label}
                onChange={(e) => {
                  setLabel(e.target.value);
                  setConfirmed(false);
                }}
              />
            </Field>
            <Field label="Reviewed profile URL">
              <Input
                type="url"
                required
                maxLength={2048}
                value={url}
                onChange={(e) => {
                  setUrl(e.target.value);
                  setConfirmed(false);
                }}
              />
            </Field>
          </div>
          <label>
            <input
              type="checkbox"
              checked={confirmed}
              onChange={(e) => setConfirmed(e.target.checked)}
            />{" "}
            I reviewed this profile URL and confirm it belongs to me.
          </label>
          <Button
            type="submit"
            disabled={!confirmed || !url || !label || save.isPending}
          >
            Save reviewed profile link
          </Button>
          {editing && (
            <Button
              type="button"
              onClick={() => {
                setEditing(null);
                setLabel("");
                setUrl("");
                setConfirmed(false);
              }}
            >
              Cancel link edit
            </Button>
          )}
          {save.isError && <ErrorState error={save.error} />}
          {save.isSuccess && <p role="status">Reviewed profile link saved.</p>}
        </form>
      </div>
    </section>
  );
}
