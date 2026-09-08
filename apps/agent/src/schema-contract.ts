import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";

import type { Pool, PoolClient } from "pg";

import {
  AgentSchemaContractError,
  schemaContractErrorFrom,
} from "./failure.js";

export type AgentSchemaCatalog = Readonly<{
  columns: ReadonlyArray<Readonly<{
    default: string | null;
    name: string;
    notNull: boolean;
    position: number;
    relation: string;
    type: string;
  }>>;
  constraints: ReadonlyArray<Readonly<{
    definition: string;
    name: string;
    relation: string;
    type: string;
  }>>;
  indexes: ReadonlyArray<Readonly<{
    definition: string;
    name: string;
    relation: string;
  }>>;
  policies: ReadonlyArray<Readonly<{ name: string; relation: string }>>;
  relations: ReadonlyArray<Readonly<{
    forceRowSecurity: boolean;
    kind: string;
    name: string;
    owner: string;
    persistence: string;
    rowSecurity: boolean;
  }>>;
  routines: ReadonlyArray<Readonly<{
    configuration: string[];
    identityArguments: string;
    kind: string;
    language: string;
    leakproof: boolean;
    name: string;
    owner: string;
    parallel: string;
    result: string;
    securityDefiner: boolean;
    source: string;
    strict: boolean;
    volatility: string;
  }>>;
  schema: Readonly<{ owner: string }>;
  triggers: ReadonlyArray<Readonly<{
    definition: string;
    name: string;
    relation: string;
  }>>;
  types: ReadonlyArray<Readonly<{ category: string; kind: string; name: string }>>;
}>;

type Queryable = Pick<Pool | PoolClient, "query">;

const expectedCatalogUrl = new URL("../schema/catalog-contract.json", import.meta.url);
const writableTables = [
  "model_charge",
  "a2ui_message",
  "agent_run",
  "chat_command",
  "chat_interrupt",
  "chat_session",
  "chat_timeline_entry",
  "mastra_messages",
  "mastra_observational_memory",
  "mastra_resources",
  "mastra_threads",
  "mastra_workflow_snapshot",
  "session_context_checkpoint",
  "model_step_recovery",
] as const;

export function assertExactCatalog(
  expected: AgentSchemaCatalog,
  actual: AgentSchemaCatalog,
): void {
  if (canonicalJson(expected) !== canonicalJson(actual)) {
    throw new AgentSchemaContractError("SCHEMA_CATALOG_DRIFT");
  }
}

export function catalogFingerprint(catalog: AgentSchemaCatalog): string {
  return createHash("sha256").update(canonicalJson(catalog)).digest("hex");
}

export async function loadExpectedCatalog(): Promise<AgentSchemaCatalog> {
  try {
    return JSON.parse(await readFile(expectedCatalogUrl, "utf8")) as AgentSchemaCatalog;
  } catch {
    throw new AgentSchemaContractError("SCHEMA_ARTIFACT_INVALID");
  }
}

export async function collectAgentSchemaCatalog(
  database: Queryable,
): Promise<AgentSchemaCatalog> {
  try {
    const schema = await database.query<Readonly<{ owner: string }>>(`
      SELECT pg_catalog.pg_get_userbyid(namespace.nspowner) AS owner
      FROM pg_catalog.pg_namespace AS namespace
      WHERE namespace.nspname = 'agent'
    `);
    if (schema.rowCount !== 1 || schema.rows[0] === undefined) {
      throw new AgentSchemaContractError("SCHEMA_CATALOG_DRIFT");
    }

    const relations = await database.query<AgentSchemaCatalog["relations"][number]>(`
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
      WHERE namespace.nspname = 'agent'
        AND relation.relkind IN ('r', 'p', 'v', 'm', 'S', 'f', 'c')
      ORDER BY relation.relname
    `);
    const columns = await database.query<AgentSchemaCatalog["columns"][number]>(`
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
      WHERE namespace.nspname = 'agent'
        AND relation.relkind IN ('r', 'p')
        AND attribute.attnum > 0
        AND NOT attribute.attisdropped
      ORDER BY relation.relname, attribute.attnum
    `);
    const constraints = await database.query<AgentSchemaCatalog["constraints"][number]>(`
      SELECT
        pg_catalog.pg_get_constraintdef(constraint_record.oid, false) AS definition,
        constraint_record.conname AS name,
        relation.relname AS relation,
        constraint_record.contype::text AS type
      FROM pg_catalog.pg_constraint AS constraint_record
      JOIN pg_catalog.pg_class AS relation
        ON relation.oid = constraint_record.conrelid
      JOIN pg_catalog.pg_namespace AS namespace
        ON namespace.oid = relation.relnamespace
      WHERE namespace.nspname = 'agent'
      ORDER BY relation.relname, constraint_record.conname
    `);
    const indexes = await database.query<AgentSchemaCatalog["indexes"][number]>(`
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
      WHERE namespace.nspname = 'agent'
      ORDER BY table_relation.relname, index_relation.relname
    `);
    const policies = await database.query<AgentSchemaCatalog["policies"][number]>(`
      SELECT policy.polname AS name, relation.relname AS relation
      FROM pg_catalog.pg_policy AS policy
      JOIN pg_catalog.pg_class AS relation ON relation.oid = policy.polrelid
      JOIN pg_catalog.pg_namespace AS namespace
        ON namespace.oid = relation.relnamespace
      WHERE namespace.nspname = 'agent'
      ORDER BY relation.relname, policy.polname
    `);
    const routines = await database.query<AgentSchemaCatalog["routines"][number]>(`
      SELECT
        COALESCE(routine.proconfig, ARRAY[]::text[]) AS configuration,
        pg_catalog.pg_get_function_identity_arguments(routine.oid) AS "identityArguments",
        routine.prokind::text AS kind,
        language.lanname AS language,
        routine.proleakproof AS leakproof,
        routine.proname AS name,
        pg_catalog.pg_get_userbyid(routine.proowner) AS owner,
        routine.proparallel::text AS parallel,
        pg_catalog.pg_get_function_result(routine.oid) AS result,
        routine.prosecdef AS "securityDefiner",
        routine.prosrc AS source,
        routine.proisstrict AS strict,
        routine.provolatile::text AS volatility
      FROM pg_catalog.pg_proc AS routine
      JOIN pg_catalog.pg_namespace AS namespace
        ON namespace.oid = routine.pronamespace
      JOIN pg_catalog.pg_language AS language ON language.oid = routine.prolang
      WHERE namespace.nspname = 'agent'
      ORDER BY routine.proname, "identityArguments"
    `);
    const triggers = await database.query<AgentSchemaCatalog["triggers"][number]>(`
      SELECT
        pg_catalog.pg_get_triggerdef(trigger_record.oid, false) AS definition,
        trigger_record.tgname AS name,
        relation.relname AS relation
      FROM pg_catalog.pg_trigger AS trigger_record
      JOIN pg_catalog.pg_class AS relation ON relation.oid = trigger_record.tgrelid
      JOIN pg_catalog.pg_namespace AS namespace
        ON namespace.oid = relation.relnamespace
      WHERE namespace.nspname = 'agent'
        AND NOT trigger_record.tgisinternal
      ORDER BY relation.relname, trigger_record.tgname
    `);
    const types = await database.query<AgentSchemaCatalog["types"][number]>(`
      SELECT
        type_record.typcategory::text AS category,
        type_record.typtype::text AS kind,
        type_record.typname AS name
      FROM pg_catalog.pg_type AS type_record
      JOIN pg_catalog.pg_namespace AS namespace
        ON namespace.oid = type_record.typnamespace
      WHERE namespace.nspname = 'agent'
        AND type_record.typrelid = 0
        AND type_record.typelem = 0
      ORDER BY type_record.typname
    `);

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

export async function verifyAgentSchema(database: Pool | PoolClient): Promise<void> {
  if ("release" in database) {
    await verifyAgentSchemaOnConnection(database);
    return;
  }

  let client: PoolClient | undefined;
  try {
    client = await database.connect();
    await client.query("BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY");
    await client.query("SET LOCAL search_path = pg_catalog");
    await verifyAgentSchemaOnConnection(client);
    await client.query("COMMIT");
  } catch (error) {
    await client?.query("ROLLBACK").catch(() => undefined);
    throw schemaContractErrorFrom(error);
  } finally {
    client?.release();
  }
}

async function verifyAgentSchemaOnConnection(database: Queryable): Promise<void> {
  const expected = await loadExpectedCatalog();
  assertExactCatalog(expected, await collectAgentSchemaCatalog(database));
  const result = await database.query<Readonly<{ schema_fingerprint: string }>>(`
    SELECT schema_fingerprint
    FROM agent.schema_contract
    WHERE singleton IS TRUE
  `);
  if (
    result.rowCount !== 1
    || result.rows[0]?.schema_fingerprint !== catalogFingerprint(expected)
  ) {
    throw new AgentSchemaContractError("SCHEMA_FINGERPRINT_MISMATCH");
  }
  await verifyAgentRoleContract(database);
}

async function verifyAgentRoleContract(database: Queryable): Promise<void> {
  const role = await database.query<{
    rolbypassrls: boolean;
    rolcanlogin: boolean;
    rolconfig: string[] | null;
    rolcreatedb: boolean;
    rolcreaterole: boolean;
    rolinherit: boolean;
    rolreplication: boolean;
    rolsuper: boolean;
  }>(`
    SELECT rolcanlogin, rolsuper, rolcreatedb, rolcreaterole, rolinherit,
           rolreplication, rolbypassrls, rolconfig
    FROM pg_catalog.pg_roles
    WHERE rolname = 'agent_runtime'
  `);
  const record = role.rows[0];
  if (
    role.rowCount !== 1
    || record === undefined
    || !record.rolcanlogin
    || record.rolsuper
    || record.rolcreatedb
    || record.rolcreaterole
    || !record.rolinherit
    || record.rolreplication
    || record.rolbypassrls
    || record.rolconfig !== null
  ) {
    throw new AgentSchemaContractError("SCHEMA_ROLE_CONTRACT_INVALID");
  }

  const memberships = await database.query(`
    SELECT 1
    FROM pg_catalog.pg_auth_members AS membership
    WHERE pg_catalog.pg_get_userbyid(membership.member) = 'agent_runtime'
       OR pg_catalog.pg_get_userbyid(membership.roleid) = 'agent_runtime'
  `);
  if (memberships.rowCount !== 0) {
    throw new AgentSchemaContractError("SCHEMA_ROLE_CONTRACT_INVALID");
  }

  const boundary = await database.query<{
    agent_create: boolean;
    agent_usage: boolean;
    database_connect: boolean;
    foreign_object_grant: boolean;
    foreign_schema_access: boolean;
  }>(`
    WITH runtime_role AS (
      SELECT oid FROM pg_catalog.pg_roles WHERE rolname = 'agent_runtime'
    )
    SELECT
      pg_catalog.has_schema_privilege('agent_runtime', 'agent', 'CREATE')
        AS agent_create,
      pg_catalog.has_schema_privilege('agent_runtime', 'agent', 'USAGE')
        AS agent_usage,
      pg_catalog.has_database_privilege('agent_runtime', current_database(), 'CONNECT')
        AS database_connect,
      EXISTS (
        SELECT 1
        FROM pg_catalog.pg_namespace AS namespace
        WHERE namespace.nspname NOT IN ('agent', 'information_schema', 'public')
          AND namespace.nspname !~ '^pg_'
          AND (
            pg_catalog.has_schema_privilege(
              'agent_runtime', namespace.oid, 'USAGE'
            )
            OR pg_catalog.has_schema_privilege(
              'agent_runtime', namespace.oid, 'CREATE'
            )
          )
      ) AS foreign_schema_access,
      EXISTS (
        SELECT 1
        FROM pg_catalog.pg_class AS relation
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = relation.relnamespace
        CROSS JOIN runtime_role
        CROSS JOIN LATERAL pg_catalog.aclexplode(
          relation.relacl
        ) AS privilege
        WHERE namespace.nspname <> 'agent'
          AND privilege.grantee = runtime_role.oid
        UNION ALL
        SELECT 1
        FROM pg_catalog.pg_proc AS routine
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = routine.pronamespace
        CROSS JOIN runtime_role
        CROSS JOIN LATERAL pg_catalog.aclexplode(
          routine.proacl
        ) AS privilege
        WHERE namespace.nspname <> 'agent'
          AND privilege.grantee = runtime_role.oid
        UNION ALL
        SELECT 1
        FROM pg_catalog.pg_type AS type_record
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = type_record.typnamespace
        CROSS JOIN runtime_role
        CROSS JOIN LATERAL pg_catalog.aclexplode(
          type_record.typacl
        ) AS privilege
        WHERE namespace.nspname <> 'agent'
          AND privilege.grantee = runtime_role.oid
      ) AS foreign_object_grant
  `);
  const access = boundary.rows[0];
  if (
    access === undefined
    || access.agent_create
    || !access.agent_usage
    || !access.database_connect
    || access.foreign_schema_access
    || access.foreign_object_grant
  ) {
    throw new AgentSchemaContractError("SCHEMA_ROLE_CONTRACT_INVALID");
  }

  const schemaGrants = await database.query<{
    grantee: string;
    is_grantable: boolean;
    privilege_type: string;
  }>(`
    SELECT
      CASE WHEN privilege.grantee = 0 THEN 'PUBLIC'
           ELSE pg_catalog.pg_get_userbyid(privilege.grantee)
      END AS grantee,
      privilege.is_grantable,
      privilege.privilege_type
    FROM pg_catalog.pg_namespace AS namespace
    CROSS JOIN LATERAL pg_catalog.aclexplode(
      COALESCE(namespace.nspacl, pg_catalog.acldefault('n', namespace.nspowner))
    ) AS privilege
    WHERE namespace.nspname = 'agent'
      AND privilege.grantee <> namespace.nspowner
    ORDER BY grantee, privilege_type
  `);
  const actualSchemaGrants = new Set(schemaGrants.rows.map((row) =>
    `${row.grantee}:${row.privilege_type}:${row.is_grantable}`
  ));
  if (!sameSet(
    new Set(["agent_runtime:USAGE:false"]),
    actualSchemaGrants,
  )) {
    throw new AgentSchemaContractError("SCHEMA_ROLE_CONTRACT_INVALID");
  }

  const expectedTableGrants = new Set<string>();
  for (const table of writableTables) {
    for (const privilege of ["DELETE", "INSERT", "SELECT", "UPDATE"]) {
      expectedTableGrants.add(`agent_runtime:${table}:${privilege}:false`);
    }
  }
  expectedTableGrants.add("agent_runtime:schema_contract:SELECT:false");

  const tableGrants = await database.query<{
    grantee: string;
    is_grantable: boolean;
    privilege_type: string;
    table_name: string;
  }>(`
    SELECT
      CASE WHEN privilege.grantee = 0 THEN 'PUBLIC'
           ELSE pg_catalog.pg_get_userbyid(privilege.grantee)
      END AS grantee,
      privilege.is_grantable,
      relation.relname AS table_name,
      privilege.privilege_type
    FROM pg_catalog.pg_class AS relation
    JOIN pg_catalog.pg_namespace AS namespace
      ON namespace.oid = relation.relnamespace
    CROSS JOIN LATERAL pg_catalog.aclexplode(
      COALESCE(relation.relacl, pg_catalog.acldefault('r', relation.relowner))
    ) AS privilege
    WHERE namespace.nspname = 'agent'
      AND relation.relkind IN ('r', 'p')
      AND privilege.grantee <> relation.relowner
    ORDER BY grantee, table_name, privilege_type
  `);
  const actualTableGrants = new Set(tableGrants.rows.map((row) =>
    `${row.grantee}:${row.table_name}:${row.privilege_type}:${row.is_grantable}`
  ));
  if (!sameSet(expectedTableGrants, actualTableGrants)) {
    throw new AgentSchemaContractError("SCHEMA_ROLE_CONTRACT_INVALID");
  }
}

function canonicalJson(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  if (value !== null && typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>)
      .sort(([left], [right]) => left.localeCompare(right));
    return `{${entries
      .map(([key, item]) => `${JSON.stringify(key)}:${canonicalJson(item)}`)
      .join(",")}}`;
  }
  return JSON.stringify(value);
}

function sameSet(left: ReadonlySet<string>, right: ReadonlySet<string>): boolean {
  return left.size === right.size && [...left].every((value) => right.has(value));
}
