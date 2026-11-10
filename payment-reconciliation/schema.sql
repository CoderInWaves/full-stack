CREATE TABLE orders (
    id               BIGSERIAL PRIMARY KEY,
    gateway_order_id TEXT UNIQUE NOT NULL,
    amount_paise     BIGINT NOT NULL,
    status           TEXT NOT NULL DEFAULT 'pending',
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE webhook_events (
    id              BIGSERIAL PRIMARY KEY,
    idempotency_key TEXT UNIQUE NOT NULL,
    event_type      TEXT NOT NULL,
    payload         JSONB NOT NULL,
    status          TEXT NOT NULL DEFAULT 'received',
    attempts        INT NOT NULL DEFAULT 0,
    last_error      TEXT,
    next_retry_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    received_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    processed_at    TIMESTAMPTZ
);

CREATE INDEX ON webhook_events (status, next_retry_at);
