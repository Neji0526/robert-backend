-- Declined card for the local checkout page.
-- The mock provider declines a token when it contains "fail".

INSERT INTO user_payment_methods (id, user_id, provider_token, last_four, is_default) VALUES
    ('11111111-2222-3333-4444-666666666666',
     '11111111-1111-1111-1111-111111111111',
     'tok_fail_alice', '0002', FALSE);
