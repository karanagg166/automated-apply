-- Additive Rust metadata only. Existing Telegram offsets, bot pin and deliveries are retained.
-- Requires the existing agent_telegram_state / agent_telegram_deliveries tables.
CREATE TABLE rust_telegram_runtime (
    key text PRIMARY KEY CHECK(key='primary'),
    binding text NOT NULL CHECK(binding ~ '^[0-9a-f]{64}$'),
    next_request_at timestamptz NOT NULL DEFAULT '-infinity',
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE rust_telegram_outbox (
    id uuid PRIMARY KEY,
    update_id bigint UNIQUE REFERENCES agent_telegram_deliveries(update_id),
    binding text NOT NULL CHECK(binding ~ '^[0-9a-f]{64}$'),
    reply text NOT NULL CHECK(length(reply) BETWEEN 1 AND 3500),
    state text NOT NULL CHECK(state IN('pending','sending','sent')),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    attempted_at timestamptz,
    receipt_message_id bigint CHECK(receipt_message_id>0)
);
CREATE INDEX rust_telegram_pending ON rust_telegram_outbox(created_at,id)WHERE state='pending';
ALTER TABLE rust_telegram_runtime ENABLE ROW LEVEL SECURITY;
ALTER TABLE rust_telegram_outbox ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON rust_telegram_runtime,rust_telegram_outbox FROM PUBLIC;
DO $block$
DECLARE client_role text;
BEGIN
    FOREACH client_role IN ARRAY ARRAY['anon','authenticated']LOOP
        IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname=client_role)THEN
            EXECUTE format('REVOKE ALL ON rust_telegram_runtime,rust_telegram_outbox FROM %I',client_role);
        END IF;
    END LOOP;
END
$block$;
