import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";

import type { Pool, PoolClient } from "pg";

import {
  AuthSchemaContractError,
  schemaContractErrorFrom,
} from "./failure.js";

export { AuthSchemaContractError } from "./failure.js";

export type AuthSchemaCatalog = Readonly<{
  columns: ReadonlyArray<
    Readonly<{
      default: string | null;
      name: string;
      notNull: boolean;
      position: number;
      relation: string;
      type: string;
    }>
  >;
  constraints: ReadonlyArray<
    Readonly<{
      definition: string;
      name: string;
      relation: string;
      type: string;
    }>
  >;
  indexes: ReadonlyArray<
    Readonly<{
      definition: string;
      name: string;
      relation: string;
    }>
  >;
  policies: ReadonlyArray<Readonly<{ name: string; relation: string }>>;
  relations: ReadonlyArray<
    Readonly<{
      forceRowSecurity: boolean;
      kind: string;
      name: string;
      owner: string;
      persistence: string;
      rowSecurity: boolean;
    }>
  >;
  routines: ReadonlyArray<
    Readonly<{
      identityArguments: string;
      kind: string;
      name: string;
      result: string;
    }>
  >;
  schema: Readonly<{ owner: string }>;
  triggers: ReadonlyArray<
    Readonly<{ definition: string; name: string; relation: string }>
  >;
  types: ReadonlyArray<Readonly<{ category: string; kind: string; name: string }>>;
}>;

type Queryable = Pick<Pool | PoolClient, "query">;

const expectedCatalogUrl = new URL("../schema/catalog-contract.json", import.meta.url);

export function assertExactCatalog(
  expected: AuthSchemaCatalog,
  actual: AuthSchemaCatalog,
): void {
  if (canonicalJson(expected) !== canonicalJson(actual)) {
    throw new AuthSchemaContractError("SCHEMA_CATALOG_DRIFT");
  }
}

export function catalogFingerprint(catalog: AuthSchemaCatalog): string {
  return createHash("sha256").update(canonicalJson(catalog)).digest("hex");
}

export async function loadExpectedCatalog(): Promise<AuthSchemaCatalog> {
  try {
    return JSON.parse(await readFile(expectedCatalogUrl, "utf8")) as AuthSchemaCatalog;
  } catch {
    throw new AuthSchemaContractError("SCHEMA_ARTIFACT_INVALID");
  }
}

export async function collectAuthSchemaCatalog(
  database: Queryable,
): Promise<AuthSchemaCatalog> {
  try {
    const schema = await database.query<Readonly<{ owner: string }>>(
      `
        SELECT pg_catalog.pg_get_userbyid(namespace.nspowner) AS owner
        FROM pg_catalog.pg_namespace AS namespace
        WHERE namespace.nspname = 'auth'
      `,
    );
    if (schema.rowCount !== 1 || schema.rows[0] === undefined) {
      throw new AuthSchemaContractError("SCHEMA_CATALOG_DRIFT");
    }
    const relations = await database.query<
      Readonly<{
        forceRowSecurity: boolean;
        kind: string;
        name: string;
        owner: string;
        persistence: string;
        rowSecurity: boolean;
      }>
    >(
      `
          SELECT
            relation.relforcerowsecurity AS "forceRowSecurity",
            relation.relkind::text AS kind,
            relation.relname AS name,
            pg_catalog.pg_get_userbyid(relation.relowner) AS owner,
            relation.relpersistence::text AS persistence,
            relation.relrowsecurity AS "rowSecurity"
          FROM pg_catalog.pg_class AS relation
          JOIN pg_catalog.pg_namespace AS namespace
            ON namespace.oid = relation.relnamespace
          WHERE namespace.nspname = 'auth'
            AND relation.relkind IN ('r', 'p', 'v', 'm', 'S', 'f', 'c')
          ORDER BY relation.relname
        `,
    );
    const columns = await database.query<
      Readonly<{
        default: string | null;
        name: string;
        notNull: boolean;
        position: number;
        relation: string;
        type: string;
      }>
    >(
      `
          SELECT
            pg_catalog.pg_get_expr(default_value.adbin, default_value.adrelid) AS default,
            attribute.attname AS name,
            attribute.attnotnull AS "notNull",
            attribute.attnum AS position,
            relation.relname AS relation,
            pg_catalog.format_type(attribute.atttypid, attribute.atttypmod) AS type
          FROM pg_catalog.pg_attribute AS attribute
          JOIN pg_catalog.pg_class AS relation ON relation.oid = attribute.attrelid
          JOIN pg_catalog.pg_namespace AS namespace
            ON namespace.oid = relation.relnamespace
          LEFT JOIN pg_catalog.pg_attrdef AS default_value
            ON default_value.adrelid = attribute.attrelid
            AND default_value.adnum = attribute.attnum
          WHERE namespace.nspname = 'auth'
            AND relation.relkind IN ('r', 'p')
            AND attribute.attnum > 0
            AND NOT attribute.attisdropped
          ORDER BY relation.relname, attribute.attnum
        `,
    );
    const constraints = await database.query<
      Readonly<{
        definition: string;
        name: string;
        relation: string;
        type: string;
      }>
    >(
      `
          SELECT
            pg_catalog.pg_get_constraintdef(constraint_record.oid, false)
              AS definition,
            constraint_record.conname AS name,
            relation.relname AS relation,
            constraint_record.contype::text AS type
          FROM pg_catalog.pg_constraint AS constraint_record
          JOIN pg_catalog.pg_class AS relation
            ON relation.oid = constraint_record.conrelid
          JOIN pg_catalog.pg_namespace AS namespace
            ON namespace.oid = relation.relnamespace
          WHERE namespace.nspname = 'auth'
          ORDER BY relation.relname, constraint_record.conname
        `,
    );
    const indexes = await database.query<
      Readonly<{ definition: string; name: string; relation: string }>
    >(
      `
          SELECT
            pg_catalog.pg_get_indexdef(index_relation.oid, 0, false) AS definition,
            index_relation.relname AS name,
            table_relation.relname AS relation
          FROM pg_catalog.pg_index AS index_record
          JOIN pg_catalog.pg_class AS index_relation
            ON index_relation.oid = index_record.indexrelid
          JOIN pg_catalog.pg_class AS table_relation
            ON table_relation.oid = index_record.indrelid
          JOIN pg_catalog.pg_namespace AS namespace
            ON namespace.oid = table_relation.relnamespace
          WHERE namespace.nspname = 'auth'
          ORDER BY table_relation.relname, index_relation.relname
        `,
    );
    const policies = await database.query<Readonly<{ name: string; relation: string }>>(
      `
        SELECT policy.polname AS name, relation.relname AS relation
        FROM pg_catalog.pg_policy AS policy
        JOIN pg_catalog.pg_class AS relation ON relation.oid = policy.polrelid
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = relation.relnamespace
        WHERE namespace.nspname = 'auth'
        ORDER BY relation.relname, policy.polname
      `,
    );
    const routines = await database.query<
      Readonly<{
        identityArguments: string;
        kind: string;
        name: string;
        result: string;
      }>
    >(
      `
        SELECT
          pg_catalog.pg_get_function_identity_arguments(routine.oid)
            AS "identityArguments",
          routine.prokind::text AS kind,
          routine.proname AS name,
          pg_catalog.pg_get_function_result(routine.oid) AS result
        FROM pg_catalog.pg_proc AS routine
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = routine.pronamespace
        WHERE namespace.nspname = 'auth'
        ORDER BY routine.proname, "identityArguments"
      `,
    );
    const triggers = await database.query<
      Readonly<{ definition: string; name: string; relation: string }>
    >(
      `
        SELECT
          pg_catalog.pg_get_triggerdef(trigger_record.oid, false) AS definition,
          trigger_record.tgname AS name,
          relation.relname AS relation
        FROM pg_catalog.pg_trigger AS trigger_record
        JOIN pg_catalog.pg_class AS relation
          ON relation.oid = trigger_record.tgrelid
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = relation.relnamespace
        WHERE namespace.nspname = 'auth'
          AND NOT trigger_record.tgisinternal
        ORDER BY relation.relname, trigger_record.tgname
      `,
    );
    const types = await database.query<
      Readonly<{ category: string; kind: string; name: string }>
    >(
      `
        SELECT
          type_record.typcategory::text AS category,
          type_record.typtype::text AS kind,
          type_record.typname AS name
        FROM pg_catalog.pg_type AS type_record
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = type_record.typnamespace
        WHERE namespace.nspname = 'auth'
          AND type_record.typrelid = 0
          AND type_record.typelem = 0
        ORDER BY type_record.typname
      `,
    );
    return {
      columns: columns.rows,
      constraints: constraints.rows,
      indexes: indexes.rows,
      policies: policies.rows,
      relations: relations.rows,
      routines: routines.rows,
      schema: schema.rows[0],
      triggers: triggers.rows,
      types: types.rows,
    };
  } catch (error) {
    throw schemaContractErrorFrom(error);
  }
}

export async function verifyAuthSchema(database: Pool | PoolClient): Promise<void> {
  if ("release" in database) {
    await verifyAuthSchemaOnConnection(database);
    return;
  }

  let client: PoolClient | undefined;
  try {
    client = await database.connect();
    await client.query("BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY");
    await client.query("SET LOCAL search_path = pg_catalog");
    await verifyAuthSchemaOnConnection(client);
    await client.query("COMMIT");
  } catch (error) {
    await client?.query("ROLLBACK").catch(() => undefined);
    throw schemaContractErrorFrom(error);
  } finally {
    client?.release();
  }
}

async function verifyAuthSchemaOnConnection(database: Queryable): Promise<void> {
  try {
    const expected = await loadExpectedCatalog();
    const actual = await collectAuthSchemaCatalog(database);
    assertExactCatalog(expected, actual);
    const result = await database.query<Readonly<{ schema_fingerprint: string }>>(
      `
        SELECT schema_fingerprint
        FROM auth.schema_contract
        WHERE singleton IS TRUE
      `,
    );
    if (
      result.rowCount !== 1 ||
      result.rows[0]?.schema_fingerprint !== catalogFingerprint(expected)
    ) {
      throw new AuthSchemaContractError("SCHEMA_FINGERPRINT_MISMATCH");
    }
  } catch (error) {
    if (error instanceof AuthSchemaContractError) {
      throw error;
    }
    throw schemaContractErrorFrom(error);
  }
}

function canonicalJson(value: unknown): string {
  if (Array.isArray(value)) {
    return `[${value.map(canonicalJson).join(",")}]`;
  }
  if (value !== null && typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>).sort(([left], [right]) =>
      left.localeCompare(right),
    );
    return `{${entries
      .map(([key, item]) => `${JSON.stringify(key)}:${canonicalJson(item)}`)
      .join(",")}}`;
  }
  return JSON.stringify(value);
}
