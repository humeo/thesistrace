import type { Pool } from "pg";
import type { ThesisTraceAuth } from "./auth.js";
import type { CredentialOperationCoordinator } from "./coordination.js";
import type { EmailCodeDelivery } from "./email-code.js";
import type { OperatorPrincipal } from "./operator-directory.js";
import { OperatorCodeInvalidError, OperatorProofNotFoundError } from "./operator-proof.js";

export class OperatorEmailCode {
  constructor(private readonly dependencies: Readonly<{
    auth: ThesisTraceAuth; pool: Pool; delivery: EmailCodeDelivery;
    coordinator: CredentialOperationCoordinator;
  }>) {}

  async send(principal: OperatorPrincipal): Promise<void> {
    await this.dependencies.delivery.send(await this.email(principal), "email-verification");
  }

  readonly verify = async (principal: OperatorPrincipal, otp: string): Promise<void> => {
    const email = await this.email(principal);
    await this.dependencies.coordinator.runForEmail(email, async () => {
      try { await this.dependencies.auth.api.verifyEmailOTP({body: {email, otp}}); }
      catch { throw new OperatorCodeInvalidError(); }
    });
  };

  private async email(principal: OperatorPrincipal): Promise<string> {
    const result = await this.dependencies.pool.query<{email: string}>(`
      SELECT u.email FROM auth."user" u
      JOIN auth.operator_assignment a ON a.researcher_id = u.id
      JOIN auth."session" s ON s."userId" = u.id
      WHERE u.id = $1 AND s.id = $2 AND s."expiresAt" > now()
        AND u.active IS TRUE AND a.singleton IS TRUE
    `, [principal.researcherId, principal.sessionId]);
    const email = result.rows[0]?.email;
    if (!email) throw new OperatorProofNotFoundError();
    return email;
  }
}
