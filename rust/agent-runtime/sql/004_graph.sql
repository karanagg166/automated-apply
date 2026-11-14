-- Additive observable graph checkpoints; no policy, quota, history or provider grants change.
ALTER TABLE rust_agent_events ADD COLUMN graph_node text NOT NULL DEFAULT 'planning';
ALTER TABLE rust_agent_events ADD COLUMN graph_iteration integer NOT NULL DEFAULT 0;
ALTER TABLE rust_agent_events ADD COLUMN approval_required boolean NOT NULL DEFAULT false;
