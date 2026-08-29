import { randomBytes, randomUUID } from "node:crypto";

import { verifyPassword } from "better-auth/crypto";
import type { Pool, PoolClient } from "pg";
import { z } from "zod";

import { lockAuthMutationShared } from "./auth-mutation-lock.js";
import { canonicalizeEmail } from "./identity.js";
import type { OperatorPrincipal } from "./operator-directory.js";
import { lockOperatorAssignment } from "./operator-lock.js";
import {
  createOpaqueToken,
  parseOpaqueToken,
  sha256,
  tokenHashMatches,
} from "./security.js";

const PROOF_LIFETIME_MS = 60_000;
const principalIdSchema = z.uuid();

export type OperatorProofOperation =
  | "invitation.issue"
  | "invitation.reissue";

export type OperatorProofClaim = Readonly<{
  claimedAt: Date;
  id: string;
  operation: OperatorProofOperation;
  requestHash: Buffer;
  sessionId: string;
  tokenHash: Buffer;
}>;

export class OperatorProofNotFoundError extends Error {
  readonly code = "OPERATOR_NOT_FOUND";

  constructor() {
    super("OPERATOR_NOT_FOUND");
    this.name = "OperatorProofNotFoundError";
  }
}

export class OperatorPasswordInvalidError extends Error {
  readonly code = "OPERATOR_PASSWORD_INVALID";

  constructor() {
    super("OPERATOR_PASSWORD_INVALID");
    this.name = "OperatorPasswordInvalidError";
  }
}

export class OperatorProofInvalidError extends Error {
  readonly code = "OPERATOR_PROOF_INVALID";

  constructor() {
    super("OPERATOR_PROOF_INVALID");
    this.name = "OperatorProofInvalidError";
  }
}

type OperatorProofDependencies = Readonly<{
  clock?: () => Date;
  createId?: () => string;
  pool: Pool;
  randomBytes?: (size: number) => Buffer;
}>;

type ProofRow = Readonly<{
  claimed_at: Date | null;
  expires_at: Date;
  operation: OperatorProofOperation;
  request_hash: Buffer;
  state: "available" | "claimed" | "consumed";
  token_hash: Buffer;
}>;

type SessionProofRow = ProofRow & Readonly<{
  session_expires_at: Date;
}>;

export class OperatorProofService {
  readonly #clock: () => Date;
  readonly #createId: () => string;
  readonly #pool: Pool;
  readonly #randomBytes: (size: number) => Buffer;

  constructor(dependencies: OperatorProofDependencies) {
    this.#clock = dependencies.clock ?? (() => new Date());
    this.#createId = dependencies.createId ?? randomUUID;
    this.#pool = dependencies.pool;
    this.#randomBytes = dependencies.randomBytes ?? randomBytes;
  }

  async confirm(
    principal: OperatorPrincipal,
    input: Readonly<{
      email: string;
      operation: OperatorProofOperation;
      password: string;
    }>,
  ): Promise<Readonly<{ expiresAt: string; proof: string }>> {
    assertPrincipal(principal);
    const email = canonicalizeEmail(input.email);
    const proofId = this.#createId();
    const proof = createOpaqueToken(proofId, this.#randomBytes);
    const parsedProof = parseOpaqueToken(proof);
    if (parsedProof === null) throw new Error("OPERATOR_PROOF_GENERATION_FAILED");
    const requestHash = operatorRequestHash(input.operation, email);
    const client = await this.#pool.connect();
    try {
      await client.query("BEGIN");
      await lockAuthMutationShared(client);
      await lockOperatorAssignment(client);
      const credential = await client.query<{
        password: string;
        session_expires_at: Date;
      }>(
        `
          SELECT
            credential.password,
            login_session."expiresAt" AS session_expires_at
          FROM auth.operator_assignment AS assignment
          JOIN auth."user" AS researcher
            ON researcher.id = assignment.researcher_id
          JOIN auth."session" AS login_session
            ON login_session."userId" = researcher.id
          JOIN auth."account" AS credential
            ON credential."userId" = researcher.id
           AND credential."providerId" = 'credential'
           AND credential.password IS NOT NULL
          WHERE assignment.singleton IS TRUE
            AND assignment.researcher_id = $1
            AND researcher.active IS TRUE
            AND login_session.id = $2
          FOR UPDATE OF assignment, researcher, login_session, credential
        `,
        [principal.researcherId, principal.sessionId],
      );
      const credentialRow = credential.rows[0];
      const authorizationAt = this.#clock();
      if (
        credentialRow === undefined
        || credentialRow.session_expires_at.getTime() <= authorizationAt.getTime()
      ) {
        throw new OperatorProofNotFoundError();
      }
      if (!(await verifyPassword({
        hash: credentialRow.password,
        password: input.password,
      }))) {
        throw new OperatorPasswordInvalidError();
      }
      const issuedAt = this.#clock();
      if (credentialRow.session_expires_at.getTime() <= issuedAt.getTime()) {
        throw new OperatorProofNotFoundError();
      }
      const expiresAt = new Date(issuedAt.getTime() + PROOF_LIFETIME_MS);
      await client.query(
        `
          INSERT INTO auth.operator_proof (
            id,
            token_hash,
            session_id,
            operation,
            request_hash,
            state,
            expires_at,
            created_at
          )
          VALUES ($1, $2, $3, $4, $5, 'available', $6, $7)
        `,
        [
          proofId,
          parsedProof.hash,
          principal.sessionId,
          input.operation,
          requestHash,
          expiresAt,
          issuedAt,
        ],
      );
      await client.query("COMMIT");
      return { expiresAt: expiresAt.toISOString(), proof };
    } catch (error) {
      await client.query("ROLLBACK").catch(() => undefined);
      throw error;
    } finally {
      client.release();
    }
  }

  async claim(
    principal: OperatorPrincipal,
    input: Readonly<{
      email: string;
      operation: OperatorProofOperation;
      proof: string;
    }>,
  ): Promise<OperatorProofClaim> {
    assertPrincipal(principal);
    const email = canonicalizeEmail(input.email);
    const parsedProof = parseOpaqueToken(input.proof);
    if (parsedProof === null) throw new OperatorProofInvalidError();
    const requestHash = operatorRequestHash(input.operation, email);
    const client = await this.#pool.connect();
    try {
      await client.query("BEGIN");
      await lockAuthMutationShared(client);
      await lockOperatorAssignment(client);
      const result = await client.query<SessionProofRow>(
        `
          SELECT
            proof.claimed_at,
            proof.expires_at,
            proof.operation,
            proof.request_hash,
            proof.state,
            proof.token_hash,
            login_session."expiresAt" AS session_expires_at
          FROM auth.operator_proof AS proof
          JOIN auth."session" AS login_session
            ON login_session.id = proof.session_id
          JOIN auth."user" AS researcher
            ON researcher.id = login_session."userId"
          JOIN auth.operator_assignment AS assignment
            ON assignment.researcher_id = researcher.id
           AND assignment.singleton IS TRUE
          WHERE proof.id = $1
            AND proof.session_id = $2
            AND researcher.id = $3
            AND researcher.active IS TRUE
          FOR UPDATE OF proof
        `,
        [parsedProof.id, principal.sessionId, principal.researcherId],
      );
      const row = result.rows[0];
      const claimedAt = this.#clock();
      if (
        row === undefined
        || row.state !== "available"
        || row.expires_at.getTime() <= claimedAt.getTime()
        || row.session_expires_at.getTime() <= claimedAt.getTime()
        || row.operation !== input.operation
        || !tokenHashMatches(row.token_hash, parsedProof.hash)
        || !tokenHashMatches(row.request_hash, requestHash)
      ) {
        throw new OperatorProofInvalidError();
      }
      const claimed = await client.query(
        `
          UPDATE auth.operator_proof
          SET state = 'claimed', claimed_at = $2
          WHERE id = $1 AND state = 'available'
        `,
        [parsedProof.id, claimedAt],
      );
      if (claimed.rowCount !== 1) throw new OperatorProofInvalidError();
      await client.query("COMMIT");
      return {
        claimedAt,
        id: parsedProof.id,
        operation: input.operation,
        requestHash,
        sessionId: principal.sessionId,
        tokenHash: parsedProof.hash,
      };
    } catch (error) {
      await client.query("ROLLBACK").catch(() => undefined);
      throw error;
    } finally {
      client.release();
    }
  }

  async consumeClaim(
    client: PoolClient,
    claim: OperatorProofClaim,
  ): Promise<boolean> {
    await lockAuthMutationShared(client);
    await lockOperatorAssignment(client);
    const locked = await client.query<SessionProofRow>(
      `
        SELECT
          proof.claimed_at,
          proof.expires_at,
          proof.operation,
          proof.request_hash,
          proof.state,
          proof.token_hash,
          login_session."expiresAt" AS session_expires_at
        FROM auth.operator_proof AS proof
        JOIN auth."session" AS login_session
          ON login_session.id = proof.session_id
        JOIN auth."user" AS researcher
          ON researcher.id = login_session."userId"
         AND researcher.active IS TRUE
        JOIN auth.operator_assignment AS assignment
          ON assignment.researcher_id = researcher.id
         AND assignment.singleton IS TRUE
        WHERE proof.id = $1 AND proof.session_id = $2
        FOR UPDATE OF proof, login_session, researcher, assignment
      `,
      [claim.id, claim.sessionId],
    );
    const row = locked.rows[0];
    const consumedAt = this.#clock();
    if (
      row === undefined
      || !proofMatchesClaim(row, claim)
      || row.expires_at.getTime() <= consumedAt.getTime()
      || row.session_expires_at.getTime() <= consumedAt.getTime()
    ) {
      return false;
    }
    const consumed = await client.query(
      `
        UPDATE auth.operator_proof
        SET state = 'consumed', consumed_at = $3
        WHERE id = $1
          AND state = 'claimed'
          AND claimed_at = $2
      `,
      [claim.id, claim.claimedAt, consumedAt],
    );
    return consumed.rowCount === 1;
  }

  async releaseClaim(
    client: PoolClient,
    claim: OperatorProofClaim,
  ): Promise<void> {
    await lockAuthMutationShared(client);
    await lockOperatorAssignment(client);
    const locked = await client.query<ProofRow>(
      `
        SELECT
          claimed_at,
          expires_at,
          operation,
          request_hash,
          state,
          token_hash
        FROM auth.operator_proof
        WHERE id = $1 AND session_id = $2
        FOR UPDATE
      `,
      [claim.id, claim.sessionId],
    );
    const row = locked.rows[0];
    const releasedAt = this.#clock();
    if (
      row === undefined
      || !proofMatchesClaim(row, claim)
      || row.expires_at.getTime() <= releasedAt.getTime()
    ) {
      return;
    }
    await client.query(
      `
        UPDATE auth.operator_proof
        SET state = 'available', claimed_at = NULL
        WHERE id = $1
          AND state = 'claimed'
          AND claimed_at = $2
      `,
      [claim.id, claim.claimedAt],
    );
  }

  async release(claim: OperatorProofClaim): Promise<void> {
    const client = await this.#pool.connect();
    try {
      await client.query("BEGIN");
      await this.releaseClaim(client, claim);
      await client.query("COMMIT");
    } catch (error) {
      await client.query("ROLLBACK").catch(() => undefined);
      throw error;
    } finally {
      client.release();
    }
  }
}

function operatorRequestHash(
  operation: OperatorProofOperation,
  email: string,
): Buffer {
  return sha256(JSON.stringify({ email, operation, version: 1 }));
}

function proofMatchesClaim(
  row: ProofRow,
  claim: OperatorProofClaim,
): boolean {
  return row.state === "claimed"
    && row.claimed_at?.getTime() === claim.claimedAt.getTime()
    && row.operation === claim.operation
    && tokenHashMatches(row.token_hash, claim.tokenHash)
    && tokenHashMatches(row.request_hash, claim.requestHash);
}

function assertPrincipal(principal: OperatorPrincipal): void {
  if (
    !principalIdSchema.safeParse(principal.researcherId).success
    || !principalIdSchema.safeParse(principal.sessionId).success
  ) {
    throw new OperatorProofNotFoundError();
  }
}
