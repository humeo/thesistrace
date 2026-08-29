import { readFile } from "node:fs/promises";

import type { Pool, PoolClient } from "pg";

import {
  AuthSchemaContractError,
  assertExactCatalog,
  catalogFingerprint,
  collectAuthSchemaCatalog,
  loadExpectedCatalog,
  verifyAuthSchema,
} from "./schema-contract.js";
import { schemaContractErrorFrom } from "./failure.js";

const schemaSqlUrl = new URL("../schema/schema.sql", import.meta.url);
const grantsSqlUrl = new URL("../schema/grants.sql", import.meta.url);

export async function initializeAuthSchema(database: Pool): Promise<void> {
  const client = await database.connect();
  try {
    await client.query("BEGIN");
    await client.query("SET LOCAL search_path = pg_catalog");
    await client.query("SET LOCAL lock_timeout = '2000ms'");
    await client.query("SET LOCAL statement_timeout = '30000ms'");
    await client.query("SET LOCAL idle_in_transaction_session_timeout = '30000ms'");
    await client.query(
      "SELECT pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended('thesistrace:auth-schema', 0))",
    );
    await assertOwnerRole(client);

    const state = await authScopeState(client);
    if (state === "absent") {
      await client.query("CREATE SCHEMA auth AUTHORIZATION thesistrace_owner");
      await installEmptyScope(client);
    } else if (state === "empty") {
      await installEmptyScope(client);
    } else {
      await verifyAuthSchema(client);
      await verifyAuthRoleGrants(client);
    }

    await client.query("COMMIT");
  } catch (error) {
    await client.query("ROLLBACK").catch(() => undefined);
    if (error instanceof AuthSchemaContractError) {
      throw error;
    }
    throw schemaContractErrorFrom(error);
  } finally {
    client.release();
  }
}

async function installEmptyScope(client: PoolClient): Promise<void> {
  const [schemaSql, grantsSql, expected] = await Promise.all([
    readContractFile(schemaSqlUrl),
    readContractFile(grantsSqlUrl),
    loadExpectedCatalog(),
  ]);
  await client.query(schemaSql);
  assertExactCatalog(expected, await collectAuthSchemaCatalog(client));
  await client.query(
    `
      INSERT INTO auth.schema_contract (singleton, schema_fingerprint)
      VALUES (TRUE, $1)
    `,
    [catalogFingerprint(expected)],
  );
  await client.query(grantsSql);
  await verifyAuthSchema(client);
  await verifyAuthRoleGrants(client);
}

async function assertOwnerRole(client: PoolClient): Promise<void> {
  const result = await client.query<{ current_user: string }>("SELECT current_user");
  if (result.rows[0]?.current_user !== "thesistrace_owner") {
    throw new AuthSchemaContractError("SCHEMA_ROLE_CONTRACT_INVALID");
  }
}

async function authScopeState(
  client: PoolClient,
): Promise<"absent" | "empty" | "populated"> {
  const result = await client.query<{ exists: boolean; object_count: string }>(`
    SELECT
      pg_catalog.to_regnamespace('auth') IS NOT NULL AS exists,
      (
        SELECT (
          (SELECT count(*)
           FROM pg_catalog.pg_class AS relation
           JOIN pg_catalog.pg_namespace AS namespace
             ON namespace.oid = relation.relnamespace
           WHERE namespace.nspname = 'auth')
          +
          (SELECT count(*)
           FROM pg_catalog.pg_proc AS routine
           JOIN pg_catalog.pg_namespace AS namespace
             ON namespace.oid = routine.pronamespace
           WHERE namespace.nspname = 'auth')
          +
          (SELECT count(*)
           FROM pg_catalog.pg_type AS type_record
           JOIN pg_catalog.pg_namespace AS namespace
             ON namespace.oid = type_record.typnamespace
           WHERE namespace.nspname = 'auth'
             AND type_record.typrelid = 0
             AND type_record.typelem = 0)
        )::text
      ) AS object_count
  `);
  const row = result.rows[0];
  if (row === undefined || !row.exists) {
    return "absent";
  }
  return row.object_count === "0" ? "empty" : "populated";
}

async function verifyAuthRoleGrants(client: PoolClient): Promise<void> {
  const roles = await client.query<{
    rolbypassrls: boolean;
    rolcanlogin: boolean;
    rolconfig: string[] | null;
    rolcreatedb: boolean;
    rolcreaterole: boolean;
    rolinherit: boolean;
    rolname: string;
    rolreplication: boolean;
    rolsuper: boolean;
  }>(`
    SELECT
      rolname,
      rolcanlogin,
      rolsuper,
      rolcreatedb,
      rolcreaterole,
      rolinherit,
      rolreplication,
      rolbypassrls,
      rolconfig
    FROM pg_catalog.pg_roles
    WHERE rolname IN ('auth_runtime', 'core_runtime')
    ORDER BY rolname
  `);
  const expectedRoleNames = ["auth_runtime", "core_runtime"];
  if (
    roles.rows.length !== expectedRoleNames.length ||
    roles.rows.some(
      (role, index) =>
        role.rolname !== expectedRoleNames[index] ||
        !role.rolcanlogin ||
        role.rolsuper ||
        role.rolcreatedb ||
        role.rolcreaterole ||
        !role.rolinherit ||
        role.rolreplication ||
        role.rolbypassrls ||
        role.rolconfig !== null,
    )
  ) {
    throw new AuthSchemaContractError("SCHEMA_ROLE_CONTRACT_INVALID");
  }

  const memberships = await client.query<{ member: string; role: string }>(`
    SELECT
      pg_catalog.pg_get_userbyid(membership.member) AS member,
      pg_catalog.pg_get_userbyid(membership.roleid) AS role
    FROM pg_catalog.pg_auth_members AS membership
    WHERE pg_catalog.pg_get_userbyid(membership.member)
        IN ('auth_runtime', 'core_runtime')
       OR pg_catalog.pg_get_userbyid(membership.roleid)
        IN ('auth_runtime', 'core_runtime')
  `);
  if (memberships.rowCount !== 0) {
    throw new AuthSchemaContractError("SCHEMA_ROLE_CONTRACT_INVALID");
  }

  const schema = await client.query<{ owner: string }>(`
    SELECT pg_catalog.pg_get_userbyid(namespace.nspowner) AS owner
    FROM pg_catalog.pg_namespace AS namespace
    WHERE namespace.nspname = 'auth'
  `);
  if (schema.rows[0]?.owner !== "thesistrace_owner") {
    throw new AuthSchemaContractError("SCHEMA_ROLE_CONTRACT_INVALID");
  }

  const expected = new Set<string>();
  for (const table of [
    "account",
    "auth_secret_contract",
    "operator_assignment",
    "operator_proof",
    "password_reset",
    "rateLimit",
    "researcher_invitation",
    "security_audit",
    "session",
    "user",
    "verification",
  ]) {
    for (const privilege of ["DELETE", "INSERT", "SELECT", "UPDATE"]) {
      expected.add(`auth_runtime:${table}:${privilege}:false`);
    }
  }
  expected.add("auth_runtime:schema_contract:SELECT:false");

  const grants = await client.query<{
    grantee: string;
    is_grantable: boolean;
    privilege_type: string;
    table_name: string;
  }>(`
    SELECT
      CASE
        WHEN privilege.grantee = 0 THEN 'PUBLIC'
        ELSE pg_catalog.pg_get_userbyid(privilege.grantee)
      END AS grantee,
      privilege.is_grantable,
      relation.relname AS table_name,
      privilege.privilege_type
    FROM pg_catalog.pg_class AS relation
    JOIN pg_catalog.pg_namespace AS namespace
      ON namespace.oid = relation.relnamespace
    CROSS JOIN LATERAL pg_catalog.aclexplode(
      COALESCE(
        relation.relacl,
        pg_catalog.acldefault('r', relation.relowner)
      )
    ) AS privilege
    WHERE namespace.nspname = 'auth'
      AND relation.relkind IN ('r', 'p')
      AND privilege.grantee <> relation.relowner
    ORDER BY grantee, table_name, privilege_type
  `);
  const actual = new Set(
    grants.rows.map(
      (row) =>
        `${row.grantee}:${row.table_name}:${row.privilege_type}:${row.is_grantable}`,
    ),
  );
  if (!sameSet(expected, actual)) {
    throw new AuthSchemaContractError("SCHEMA_ROLE_CONTRACT_INVALID");
  }

  const schemaPrivileges = await client.query<{
    grantee: string;
    is_grantable: boolean;
    privilege_type: string;
  }>(`
    SELECT
      CASE
        WHEN privilege.grantee = 0 THEN 'PUBLIC'
        ELSE pg_catalog.pg_get_userbyid(privilege.grantee)
      END AS grantee,
      privilege.is_grantable,
      privilege.privilege_type
    FROM pg_catalog.pg_namespace AS namespace
    CROSS JOIN LATERAL pg_catalog.aclexplode(
      COALESCE(
        namespace.nspacl,
        pg_catalog.acldefault('n', namespace.nspowner)
      )
    ) AS privilege
    WHERE namespace.nspname = 'auth'
      AND privilege.grantee <> namespace.nspowner
    ORDER BY grantee, privilege_type
  `);
  const actualSchemaPrivileges = new Set(
    schemaPrivileges.rows.map(
      (row) => `${row.grantee}:${row.privilege_type}:${row.is_grantable}`,
    ),
  );
  if (!sameSet(new Set(["auth_runtime:USAGE:false"]), actualSchemaPrivileges)) {
    throw new AuthSchemaContractError("SCHEMA_ROLE_CONTRACT_INVALID");
  }

  const routineGrants = await client.query<{
    grantee: string;
    is_grantable: boolean;
    privilege_type: string;
    routine_name: string;
  }>(`
    SELECT
      CASE
        WHEN privilege.grantee = 0 THEN 'PUBLIC'
        ELSE pg_catalog.pg_get_userbyid(privilege.grantee)
      END AS grantee,
      privilege.is_grantable,
      routine.proname AS routine_name,
      privilege.privilege_type
    FROM pg_catalog.pg_proc AS routine
    JOIN pg_catalog.pg_namespace AS namespace
      ON namespace.oid = routine.pronamespace
    CROSS JOIN LATERAL pg_catalog.aclexplode(
      COALESCE(
        routine.proacl,
        pg_catalog.acldefault('f', routine.proowner)
      )
    ) AS privilege
    WHERE namespace.nspname = 'auth'
      AND privilege.grantee <> routine.proowner
    ORDER BY grantee, routine_name, privilege_type
  `);
  const actualRoutinePrivileges = new Set(
    routineGrants.rows.map(
      (row) =>
        `${row.grantee}:${row.routine_name}:${row.privilege_type}:${row.is_grantable}`,
    ),
  );
  if (
    !sameSet(
      new Set([
        "auth_runtime:enforce_active_session_owner:EXECUTE:false",
      ]),
      actualRoutinePrivileges,
    )
  ) {
    throw new AuthSchemaContractError("SCHEMA_ROLE_CONTRACT_INVALID");
  }
}

async function readContractFile(url: URL): Promise<string> {
  try {
    return await readFile(url, "utf8");
  } catch (error) {
    throw new AuthSchemaContractError("SCHEMA_ARTIFACT_INVALID", error);
  }
}

function sameSet(left: ReadonlySet<string>, right: ReadonlySet<string>): boolean {
  return left.size === right.size && [...left].every((item) => right.has(item));
}
