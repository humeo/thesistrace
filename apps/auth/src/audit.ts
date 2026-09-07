import type { PoolClient } from "pg";

import { unknownEmailHmac } from "./security.js";

export type SecurityAuditEvent =
  | "display_label_corrected"
  | "invitation_accepted"
  | "invitation_issued"
  | "invitation_revoked"
  | "password_changed"
  | "password_reset_failed"
  | "password_reset_requested"
  | "password_reset_succeeded"
  | "researcher_deactivated"
  | "researcher_reactivated"
  | "sessions_revoked"
  | "sign_in_failed"
  | "sign_in_succeeded";

export type SecurityAuditOutcome =
  | "failed"
  | "no_change"
  | "rejected"
  | "succeeded";

type AuditIdentity =
  | Readonly<{ email: string; researcherId?: never }>
  | Readonly<{ email?: never; researcherId: string }>;

export async function recordSecurityAudit(
  client: PoolClient,
  input: Readonly<{
    authSecret: string;
    event: SecurityAuditEvent;
    identity: AuditIdentity;
    occurredAt: Date;
    outcome: SecurityAuditOutcome;
  }>,
): Promise<void> {
  const researcherId = input.identity.researcherId ?? null;
  const emailHmac =
    input.identity.email === undefined
      ? null
      : unknownEmailHmac(input.authSecret, input.identity.email);
  await client.query(
    `
      INSERT INTO auth.security_audit (
        occurred_at,
        event,
        outcome,
        researcher_id,
        unknown_email_hmac
      )
      VALUES ($1, $2, $3, $4, $5)
    `,
    [input.occurredAt, input.event, input.outcome, researcherId, emailHmac],
  );
}
