import type { Pool, PoolClient } from "pg";
import { z } from "zod";

import {
  OperatorCursorCodec,
} from "./operator-cursor.js";

export { OperatorCursorInvalidError } from "./operator-cursor.js";

const PAGE_SIZE = 50;
const researcherIdSchema = z.uuid();

export type OperatorPrincipal = Readonly<{
  researcherId: string;
  sessionId: string;
}>;

export type OperatorResearcherSummary = Readonly<{
  active: boolean;
  createdAt: string;
  currentSessionCount: number;
  displayLabel: string;
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
  email: string;
  id: string;
  latest_successful_login_at: Date | null;
  name: string;
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
            current_sessions.current_session_count
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
        items: pageRows.map((row) => researcherSummary(row)),
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

function researcherSummary(row: ResearcherRow): OperatorResearcherSummary {
  return {
    active: row.active,
    createdAt: isoDate(row.created_at),
    currentSessionCount: Number(row.current_session_count),
    displayLabel: row.name,
    email: row.email,
    id: row.id,
    latestSuccessfulLoginAt:
      row.latest_successful_login_at === null
        ? null
        : isoDate(row.latest_successful_login_at),
  };
}

function isoDate(value: Date): string {
  if (!(value instanceof Date) || !Number.isFinite(value.getTime())) {
    throw new Error("OPERATOR_DIRECTORY_ROW_INVALID");
  }
  return value.toISOString();
}
