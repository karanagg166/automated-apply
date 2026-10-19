"use client";
import { Plus, Trash2 } from "lucide-react";
import { Badge, Button, Field, Input } from "./ui";
import type { Schema } from "@/lib/api";
type Project = Schema<"VerifiedProject">;
export function ProjectsEditor({
  value,
  onChange,
}: {
  value: string;
  onChange: (value: string) => void;
}) {
  let projects: Project[] = [];
  try {
    projects = JSON.parse(value);
  } catch {}
  const update = (index: number, change: Partial<Project>) =>
    onChange(
      JSON.stringify(
        projects.map((p, i) => (i === index ? { ...p, ...change } : p)),
      ),
    );
  return (
    <div className="stack">
      <div className="split">
        <h3>Project evidence</h3>
        <Badge>Owner review required</Badge>
      </div>
      <p className="section-intro">
        Describe what you built and your own contribution. Add source links and
        technologies you can support.
      </p>
      {projects.map((p, index) => (
        <div className="evidence-item stack" key={index}>
          <div className="split">
            <strong>Project {index + 1}</strong>
            <Button
              type="button"
              variant="ghost"
              aria-label={`Remove project ${index + 1}`}
              onClick={() =>
                onChange(JSON.stringify(projects.filter((_, i) => i !== index)))
              }
            >
              <Trash2 size={13} />
            </Button>
          </div>
          <div className="form-grid">
            <Field label={`Project ${index + 1} name`}>
              <Input
                required
                maxLength={200}
                value={p.name}
                onChange={(e) => update(index, { name: e.target.value })}
              />
            </Field>
            <Field label={`Project ${index + 1} source or live URL`}>
              <Input
                type="url"
                value={p.url || ""}
                onChange={(e) => update(index, { url: e.target.value || null })}
              />
            </Field>
          </div>
          <Field label={`Project ${index + 1} description`}>
            <textarea
              className="input"
              value={p.description || ""}
              maxLength={4000}
              onChange={(e) => update(index, { description: e.target.value })}
            />
          </Field>
          <Field
            label={`Project ${index + 1} technologies`}
            hint="Comma-separated"
          >
            <Input
              value={p.technologies?.join(", ") || ""}
              onChange={(e) =>
                update(index, {
                  technologies: e.target.value
                    .split(",")
                    .map((x) => x.trim())
                    .filter(Boolean),
                })
              }
            />
          </Field>
          <Field
            label={`Project ${index + 1} contribution`}
            hint="Explain your own work. Grounded answers and outreach rely on this evidence."
          >
            <textarea
              className="input"
              value={p.contribution || ""}
              maxLength={4000}
              onChange={(e) => update(index, { contribution: e.target.value })}
            />
          </Field>
        </div>
      ))}
      <Button
        type="button"
        onClick={() =>
          onChange(
            JSON.stringify([
              ...projects,
              {
                name: "",
                description: "",
                technologies: [],
                contribution: "",
                url: null,
              },
            ]),
          )
        }
      >
        <Plus size={13} />
        Add project entry
      </Button>
    </div>
  );
}
