ALTER TABLE auth.billing_payment DROP CONSTRAINT billing_payment_amount_check;
ALTER TABLE auth.billing_payment ADD CONSTRAINT billing_payment_amount_check CHECK (amount >= 0);
ALTER TABLE auth.billing_payment ADD COLUMN fully_refunded boolean NOT NULL DEFAULT false;
ALTER TABLE auth.billing_adjustment ADD COLUMN fully_refunded boolean NOT NULL DEFAULT false;
UPDATE auth.billing_payment SET fully_refunded=true WHERE refunded_amount=amount;
UPDATE auth.billing_adjustment AS adjustment SET fully_refunded=true
FROM auth.billing_payment AS payment
WHERE adjustment.transaction_id=payment.transaction_id AND payment.fully_refunded;
