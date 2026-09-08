import type { Pool, PoolClient } from "pg";
import { z } from "zod";

import {
  OperatorCursorCodec,
} from "./operator-cursor.js";

export { OperatorCursorInvalidError } from "./operator-cursor.js";

const PAGE_SIZE = 50;
const TERMINAL_RETENTION_MS = 30 * 24 * 60 * 60 * 1_000;
const researcherIdSchema = z.uuid();

export type OperatorPrincipal = Readonly<{
  researcherId: string;
  sessionId: string;
}>;

type InvitationStatus =
  | "consumed"
  | "delivered"
  | "delivery_failed"
  | "delivery_pending"
  | "expired"
  | "revoked";

export type OperatorInvitationSummary = Readonly<{
  createdAt: string;
  deliveredAt: string | null;
  effective: boolean;
  email: string;
  expiresAt: string;
  id: string;
  researcherId: string | null;
  status: InvitationStatus;
  terminalAt: string | null;
}>;

export type OperatorResearcherSummary = Readonly<{
  active: boolean;
  createdAt: string;
  currentSessionCount: number;
  displayLabel: string;
  effectiveInvitation: OperatorInvitationSummary | null;
  email: string;
  id: string;
  latestSuccessfulLoginAt: string | null;
}>;

export type OperatorPage<T> = Readonly<{
  items: readonly T[];
  nextCursor: string | null;
}>;

export class OperatorAccessNotFoundError extends Error {
  readonly code = "OPERATOR_NOT_FOUND";

  constructor() {
    super("OPERATOR_NOT_FOUND");
    this.name = "OperatorAccessNotFoundError";
  }
}

export class OperatorQueryInvalidError extends Error {
  readonly code = "OPERATOR_QUERY_INVALID";

  constructor() {
    super("OPERATOR_QUERY_INVALID");
    this.name = "OperatorQueryInvalidError";
  }
}

type DirectoryDependencies = Readonly<{
  authSecret: string;
  clock?: () => Date;
  pool: Pool;
  randomBytes?: (size: number) => Buffer;
}>;

type ResearcherRow = Readonly<{
  active: boolean;
  created_at: Date;
  current_session_count: string;
  effective_created_at: Date | null;
  effective_delivered_at: Date | null;
  effective_email: string | null;
  effective_expires_at: Date | null;
  effective_id: string | null;
  effective_status: InvitationStatus | null;
  email: string;
  id: string;
  latest_successful_login_at: Date | null;
  name: string;
}>;

type InvitationRow = Readonly<{
  created_at: Date;
  delivered_at: Date | null;
  email: string;
  expires_at: Date;
  id: string;
  researcher_id: string | null;
  status: InvitationStatus;
  terminal_at: Date | null;
}>;

export class OperatorDirectoryService {
  readonly #clock: () => Date;
  readonly #cursor: OperatorCursorCodec;
  readonly #pool: Pool;

  constructor(dependencies: DirectoryDependencies) {
    this.#clock = dependencies.clock ?? (() => new Date());
    this.#cursor = new OperatorCursorCodec(dependencies);
    this.#pool = dependencies.pool;
  }

  async hasCapability(principal: OperatorPrincipal): Promise<boolean> {
    if (!validPrincipal(principal)) return false;
    const result = await this.#pool.query<{ authorized: boolean }>(
      authorizationQuery,
      [principal.sessionId, principal.researcherId, this.#clock()],
    );
    return result.rows[0]?.authorized === true;
  }

  async isOperator(researcherId: string): Promise<boolean> {
    const result = await this.#pool.query<{ unlimited: boolean }>(`
      SELECT EXISTS (
        SELECT 1 FROM auth.operator_assignment AS assignment
        JOIN auth."user" AS researcher ON researcher.id = assignment.researcher_id
        WHERE assignment.researcher_id = $1 AND researcher.active = TRUE
      ) AS unlimited
    `, [researcherId]);
    return result.rows[0]!.unlimited;
  }

  async listResearchers(
    principal: OperatorPrincipal,
    input: Readonly<{ cursor: string | null; search: string | null }>,
  ): Promise<OperatorPage<OperatorResearcherSummary>> {
    const search = normalizeSearch(input.search);
    const after = this.#cursor.decode(input.cursor, "researchers", search);
    return await this.#authorizedRead(principal, async (client, now) => {
      const pattern = search === null ? null : `%${escapeLike(search)}%`;
      const result = await client.query<ResearcherRow>(
        `
          SELECT
            researcher.active,
            researcher."createdAt" AS created_at,
            researcher.email,
            researcher.id,
            researcher.name,
            latest_login.latest_successful_login_at,
            current_sessions.current_session_count,
            effective_invitation.created_at AS effective_created_at,
            effective_invitation.delivered_at AS effective_delivered_at,
            effective_invitation.email AS effective_email,
            effective_invitation.expires_at AS effective_expires_at,
            effective_invitation.id AS effective_id,
            effective_invitation.status AS effective_status
          FROM auth."user" AS researcher
          LEFT JOIN LATERAL (
            SELECT pg_catalog.max(audit.occurred_at) AS latest_successful_login_at
            FROM auth.security_audit AS audit
            WHERE audit.researcher_id = researcher.id
              AND audit.event = 'sign_in_succeeded'
              AND audit.outcome = 'succeeded'
          ) AS latest_login ON TRUE
          LEFT JOIN LATERAL (
            SELECT pg_catalog.count(*)::text AS current_session_count
            FROM auth."session" AS login_session
            WHERE login_session."userId" = researcher.id
              AND login_session."expiresAt" > $5
          ) AS current_sessions ON TRUE
          LEFT JOIN LATERAL (
            SELECT
              invitation.created_at,
              invitation.delivered_at,
              invitation.email,
              invitation.expires_at,
              invitation.id,
              invitation.status
            FROM auth.researcher_invitation AS invitation
            WHERE invitation.email = researcher.email
              AND invitation.status IN ('delivery_pending', 'delivered')
              AND invitation.expires_at > $5
            ORDER BY invitation.created_at DESC, invitation.id DESC
            LIMIT 1
          ) AS effective_invitation ON TRUE
          WHERE (
            $1::text IS NULL
            OR pg_catalog.lower(researcher.email) LIKE $2 ESCAPE '\\'
            OR pg_catalog.lower(researcher.name) LIKE $2 ESCAPE '\\'
          )
            AND (
              $3::timestamptz IS NULL
              OR researcher."createdAt" < $3
              OR (researcher."createdAt" = $3 AND researcher.id < $4)
            )
          ORDER BY researcher."createdAt" DESC, researcher.id DESC
          LIMIT 51
        `,
        [search, pattern, after?.createdAt ?? null, after?.id ?? null, now],
      );
      const pageRows = result.rows.slice(0, PAGE_SIZE);
      return {
        items: pageRows.map((row) => researcherSummary(row, now)),
        nextCursor:
          result.rows.length > PAGE_SIZE && pageRows[PAGE_SIZE - 1] !== undefined
            ? this.#cursor.encode(
                "researchers",
                pageRows[PAGE_SIZE - 1],
                search,
              )
            : null,
      };
    });
  }

  async listInvitations(
    principal: OperatorPrincipal,
    input: Readonly<{ cursor: string | null }>,
  ): Promise<OperatorPage<OperatorInvitationSummary>> {
    const after = this.#cursor.decode(input.cursor, "invitations", null);
    return await this.#authorizedRead(principal, async (client, now) => {
      const result = await client.query<InvitationRow>(
        `
          SELECT
            invitation.created_at,
            invitation.delivered_at,
            invitation.email,
            invitation.expires_at,
            invitation.id,
            COALESCE(invitation.user_id, researcher.id)
              AS researcher_id,
            CASE
              WHEN invitation.status IN ('delivery_pending', 'delivered')
                AND invitation.expires_at <= $4
                THEN 'expired'
              ELSE invitation.status
            END AS status,
            CASE
              WHEN invitation.status IN ('delivery_pending', 'delivered')
                AND invitation.expires_at <= $4
                THEN invitation.expires_at
              ELSE invitation.terminal_at
            END AS terminal_at
          FROM auth.researcher_invitation AS invitation
          LEFT JOIN auth."user" AS researcher
            ON researcher.email = invitation.email
          WHERE (
            (
              invitation.status IN ('delivery_pending', 'delivered')
              AND invitation.expires_at >= $3
            )
            OR (
              invitation.status IN ('delivery_failed', 'consumed', 'revoked')
              AND invitation.terminal_at >= $3
            )
          )
            AND (
              $1::timestamptz IS NULL
              OR invitation.created_at < $1
              OR (invitation.created_at = $1 AND invitation.id < $2)
            )
          ORDER BY invitation.created_at DESC, invitation.id DESC
          LIMIT 51
        `,
        [
          after?.createdAt ?? null,
          after?.id ?? null,
          new Date(now.getTime() - TERMINAL_RETENTION_MS),
          now,
        ],
      );
      const pageRows = result.rows.slice(0, PAGE_SIZE);
      return {
        items: pageRows.map((row) => invitationSummary(row, now)),
        nextCursor:
          result.rows.length > PAGE_SIZE && pageRows[PAGE_SIZE - 1] !== undefined
            ? this.#cursor.encode(
                "invitations",
                pageRows[PAGE_SIZE - 1],
                null,
              )
            : null,
      };
    });
  }

  async #authorizedRead<T>(
    principal: OperatorPrincipal,
    operation: (client: PoolClient, now: Date) => Promise<T>,
  ): Promise<T> {
    if (!validPrincipal(principal)) throw new OperatorAccessNotFoundError();
    const client = await this.#pool.connect();
    try {
      await client.query(
        "BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY",
      );
      const now = this.#clock();
      const authorization = await client.query<{ authorized: boolean }>(
        authorizationQuery,
        [principal.sessionId, principal.researcherId, now],
      );
      if (authorization.rows[0]?.authorized !== true) {
        throw new OperatorAccessNotFoundError();
      }
      const result = await operation(client, now);
      await client.query("COMMIT");
      return result;
    } catch (error) {
      await client.query("ROLLBACK").catch(() => undefined);
      throw error;
    } finally {
      client.release();
    }
  }

}

const authorizationQuery = `
  SELECT EXISTS (
    SELECT 1
    FROM auth.operator_assignment AS assignment
    JOIN auth."user" AS researcher
      ON researcher.id = assignment.researcher_id
    JOIN auth."session" AS login_session
      ON login_session."userId" = researcher.id
    WHERE assignment.singleton IS TRUE
      AND assignment.researcher_id = $2
      AND researcher.active IS TRUE
      AND login_session.id = $1
      AND login_session."expiresAt" > $3
  ) AS authorized
`;

function validPrincipal(principal: OperatorPrincipal): boolean {
  return researcherIdSchema.safeParse(principal.researcherId).success
    && researcherIdSchema.safeParse(principal.sessionId).success;
}

function normalizeSearch(value: string | null): string | null {
  if (value === null) return null;
  const normalized = value.trim().toLowerCase();
  if (normalized.length === 0) return null;
  if (normalized.length > 100 || /[\u0000-\u001f\u007f]/.test(normalized)) {
    throw new OperatorQueryInvalidError();
  }
  return normalized;
}

function escapeLike(value: string): string {
  return value
    .replaceAll("\\", "\\\\")
    .replaceAll("%", "\\%")
    .replaceAll("_", "\\_");
}

function researcherSummary(row: ResearcherRow, now: Date): OperatorResearcherSummary {
  const effectiveInvitation = row.effective_id === null
    ? null
    : invitationSummary({
        created_at: requiredDate(row.effective_created_at),
        delivered_at: row.effective_delivered_at,
        email: requiredString(row.effective_email),
        expires_at: requiredDate(row.effective_expires_at),
        id: row.effective_id,
        researcher_id: row.id,
        status: requiredInvitationStatus(row.effective_status),
        terminal_at: null,
      }, now);
  return {
    active: row.active,
    createdAt: isoDate(row.created_at),
    currentSessionCount: Number(row.current_session_count),
    displayLabel: row.name,
    effectiveInvitation,
    email: row.email,
    id: row.id,
    latestSuccessfulLoginAt:
      row.latest_successful_login_at === null
        ? null
        : isoDate(row.latest_successful_login_at),
  };
}

function invitationSummary(row: InvitationRow, now: Date): OperatorInvitationSummary {
  return {
    createdAt: isoDate(row.created_at),
    deliveredAt: row.delivered_at === null ? null : isoDate(row.delivered_at),
    effective:
      (row.status === "delivery_pending" || row.status === "delivered")
      && row.expires_at.getTime() > now.getTime(),
    email: row.email,
    expiresAt: isoDate(row.expires_at),
    id: row.id,
    researcherId: row.researcher_id,
    status: row.status,
    terminalAt: row.terminal_at === null ? null : isoDate(row.terminal_at),
  };
}

function isoDate(value: Date): string {
  if (!(value instanceof Date) || !Number.isFinite(value.getTime())) {
    throw new Error("OPERATOR_DIRECTORY_ROW_INVALID");
  }
  return value.toISOString();
}

function requiredDate(value: Date | null): Date {
  if (value === null) throw new Error("OPERATOR_DIRECTORY_ROW_INVALID");
  return value;
}

function requiredString(value: string | null): string {
  if (value === null) throw new Error("OPERATOR_DIRECTORY_ROW_INVALID");
  return value;
}

function requiredInvitationStatus(value: InvitationStatus | null): InvitationStatus {
  if (value === null) throw new Error("OPERATOR_DIRECTORY_ROW_INVALID");
  return value;
}
