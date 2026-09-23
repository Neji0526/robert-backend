-- Payment migration.
-- One row is one attempt to charge a cart.
-- A cart can have many failed attempts and at most one succeeded payment.
--
-- Run after 001_base_schema.sql.

CREATE TABLE payments (
    id                 UUID           PRIMARY KEY DEFAULT gen_random_uuid(),
    cart_id            UUID           NOT NULL REFERENCES carts(id),
    user_id            UUID           NOT NULL REFERENCES users(id),
    payment_method_id  UUID           NOT NULL REFERENCES user_payment_methods(id),
    amount             NUMERIC(12, 2) NOT NULL CHECK (amount > 0),
    currency           CHAR(3)        NOT NULL,
    status             TEXT           NOT NULL CHECK (status IN ('succeeded', 'failed')),
    provider_reference TEXT,
    failure_code       TEXT,
    idempotency_key    TEXT           NOT NULL,
    created_at         TIMESTAMPTZ    NOT NULL DEFAULT NOW(),
    updated_at         TIMESTAMPTZ    NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_payments_status_payload CHECK (
        (
            status = 'succeeded'
            AND provider_reference IS NOT NULL
            AND failure_code IS NULL
        )
        OR (
            status = 'failed'
            AND provider_reference IS NULL
            AND failure_code IS NOT NULL
        )
    ),
    CONSTRAINT uq_payments_idempotency_key UNIQUE (idempotency_key)
);

-- Failed attempts stay in the table. Only a successful charge is unique per cart.
CREATE UNIQUE INDEX uq_payments_one_success_per_cart
    ON payments (cart_id)
    WHERE status = 'succeeded';

CREATE INDEX idx_payments_cart_id ON payments (cart_id);
CREATE INDEX idx_payments_user_id ON payments (user_id);
