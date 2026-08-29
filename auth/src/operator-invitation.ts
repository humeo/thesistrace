import type { PoolClient } from "pg";

import {
  InvitationAuthorizationError,
  type InvitationIssueResult,
  type ResearcherInvitationService,
} from "./invitation.js";
import type { OperatorPrincipal } from "./operator-directory.js";
import {
  OperatorProofInvalidError,
  type OperatorProofOperation,
  type OperatorProofService,
} from "./operator-proof.js";

type InvitationOperations = Pick<
  ResearcherInvitationService,
  "issueAuthorized" | "reissueAuthorized"
>;

export class OperatorInvitationService {
  readonly #invitations: InvitationOperations;
  readonly #proofs: OperatorProofService;

  constructor(dependencies: Readonly<{
    invitations: InvitationOperations;
    proofs: OperatorProofService;
  }>) {
    this.#invitations = dependencies.invitations;
    this.#proofs = dependencies.proofs;
  }

  issue(
    principal: OperatorPrincipal,
    input: Readonly<{ email: string; proof: string }>,
  ): Promise<InvitationIssueResult> {
    return this.#run(principal, "invitation.issue", input);
  }

  reissue(
    principal: OperatorPrincipal,
    input: Readonly<{ email: string; proof: string }>,
  ): Promise<InvitationIssueResult> {
    return this.#run(principal, "invitation.reissue", input);
  }

  async #run(
    principal: OperatorPrincipal,
    operation: OperatorProofOperation,
    input: Readonly<{ email: string; proof: string }>,
  ): Promise<InvitationIssueResult> {
    const claim = await this.#proofs.claim(principal, {
      email: input.email,
      operation,
      proof: input.proof,
    });
    try {
      const authorization = {
        consume: (client: PoolClient) =>
          this.#proofs.consumeClaim(client, claim),
        release: (client: PoolClient) =>
          this.#proofs.releaseClaim(client, claim),
      };
      return operation === "invitation.issue"
        ? await this.#invitations.issueAuthorized(input.email, authorization)
        : await this.#invitations.reissueAuthorized(input.email, authorization);
    } catch (error) {
      await this.#proofs.release(claim);
      if (error instanceof InvitationAuthorizationError) {
        throw new OperatorProofInvalidError();
      }
      throw error;
    }
  }
}
