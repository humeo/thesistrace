import type { PoolClient } from "pg";

import {
  ResearcherAccessAuthorizationError,
  type ResearcherAccessService,
  type ResearcherSessionRevocationResult,
  ResearcherSessionTargetProtectedError,
} from "./access.js";
import type { OperatorPrincipal } from "./operator-directory.js";
import {
  OperatorProofInvalidError,
  type OperatorProofService,
} from "./operator-proof.js";

type SessionRevocationAccess = Pick<
  ResearcherAccessService,
  "revokeSessionsAuthorized"
>;

export class OperatorSessionTargetProtectedError extends Error {
  readonly code = "OPERATOR_SESSION_TARGET_PROTECTED";

  constructor() {
    super("OPERATOR_SESSION_TARGET_PROTECTED");
    this.name = "OperatorSessionTargetProtectedError";
  }
}

export class OperatorSessionRevocationService {
  readonly #access: SessionRevocationAccess;
  readonly #proofs: OperatorProofService;

  constructor(dependencies: Readonly<{
    access: SessionRevocationAccess;
    proofs: OperatorProofService;
  }>) {
    this.#access = dependencies.access;
    this.#proofs = dependencies.proofs;
  }

  async revoke(
    principal: OperatorPrincipal,
    input: Readonly<{ proof: string; researcherId: string }>,
  ): Promise<ResearcherSessionRevocationResult> {
    const claim = await this.#proofs.claim(principal, {
      operation: "researcher.sessions.revoke",
      proof: input.proof,
      researcherId: input.researcherId,
    });
    try {
      return await this.#access.revokeSessionsAuthorized(
        principal.researcherId,
        input.researcherId,
        {
          consume: (client: PoolClient) =>
            this.#proofs.consumeClaim(client, claim),
        },
      );
    } catch (error) {
      await this.#proofs.release(claim);
      if (error instanceof ResearcherAccessAuthorizationError) {
        throw new OperatorProofInvalidError();
      }
      if (error instanceof ResearcherSessionTargetProtectedError) {
        throw new OperatorSessionTargetProtectedError();
      }
      throw error;
    }
  }
}
