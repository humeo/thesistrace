import { Pool } from "pg";
import { afterAll, beforeEach, describe, expect, it } from "vitest";

import { initializeAuthSchema } from "./schema-initialize.js";
import { checkAuthReadiness } from "./readiness.js";
import { createAuthInitializerPool } from "./database.js";
import {
  AuthSchemaContractError,
  catalogFingerprint,
  loadExpectedCatalog,
  verifyAuthSchema,
} from "./schema-contract.js";

const ownerDatabaseUrl = process.env.THESISTRACE_AUTH_TEST_OWNER_DATABASE_URL;
if (ownerDatabaseUrl === undefined) {
  throw new Error("THESISTRACE_AUTH_TEST_OWNER_DATABASE_URL is required");
}

const owner = new Pool({ connectionString: ownerDatabaseUrl, max: 2 });
const authRuntime = new Pool({
  connectionString: roleDatabaseUrl(ownerDatabaseUrl, "auth_runtime", "auth-test-password"),
  max: 2,
  options: "-c search_path=auth",
});
const coreRuntime = new Pool({
  connectionString: roleDatabaseUrl(ownerDatabaseUrl, "core_runtime", "core-test-password"),
  max: 2,
});

describe.sequential("Auth physical schema", () => {
  beforeEach(async () => {
    await owner.query("DROP SCHEMA IF EXISTS auth CASCADE");
    await owner.query("DROP SCHEMA IF EXISTS product_contract_test CASCADE");
    await owner.query("CREATE SCHEMA product_contract_test");
    await owner.query(
      "CREATE TABLE product_contract_test.resource (id integer PRIMARY KEY)",
    );
    await owner.query("GRANT USAGE ON SCHEMA product_contract_test TO core_runtime");
    await owner.query(
      "GRANT SELECT, INSERT, UPDATE, DELETE ON product_contract_test.resource TO core_runtime",
    );
  });

  afterAll(async () => {
    await Promise.all([authRuntime.end(), coreRuntime.end()]);
    await owner.query("DROP SCHEMA IF EXISTS auth CASCADE");
    await owner.query("DROP SCHEMA IF EXISTS product_contract_test CASCADE");
    await owner.end();
  });

  it.each(["absent", "empty"])(
    "initializes an %s Auth scope once and then only verifies it",
    async (initialState) => {
      if (initialState === "empty") {
        await owner.query("CREATE SCHEMA auth");
      }

      await initializeAuthSchema(owner);
      await verifyAuthSchema(owner);
      const expected = await loadExpectedCatalog();
      const fingerprint = await owner.query<{ schema_fingerprint: string }>(
        "SELECT schema_fingerprint FROM auth.schema_contract WHERE singleton IS TRUE",
      );
      expect(fingerprint.rows).toEqual([
        { schema_fingerprint: catalogFingerprint(expected) },
      ]);

      await initializeAuthSchema(owner);
      await verifyAuthSchema(owner);
    },
  );

  it("serializes concurrent empty-scope initializers", async () => {
    await Promise.all([initializeAuthSchema(owner), initializeAuthSchema(owner)]);

    await expect(verifyAuthSchema(owner)).resolves.toBeUndefined();
  });

  it("bounds the initializer advisory-lock wait", async () => {
    const blocker = await owner.connect();
    const boundedInitializer = createAuthInitializerPool(ownerDatabaseUrl);
    try {
      await blocker.query("BEGIN");
      await blocker.query(
        "SELECT pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended('thesistrace:auth-schema', 0))",
      );
      const startedAt = performance.now();

      await expect(initializeAuthSchema(boundedInitializer)).rejects.toBeInstanceOf(
        AuthSchemaContractError,
      );
      expect(performance.now() - startedAt).toBeLessThan(5_000);
    } finally {
      await blocker.query("ROLLBACK").catch(() => undefined);
      blocker.release();
      await boundedInitializer.end();
    }
  });

  it("rejects an empty Auth scope owned by a runtime role", async () => {
    await owner.query("CREATE SCHEMA auth AUTHORIZATION core_runtime");

    await expect(initializeAuthSchema(owner)).rejects.toBeInstanceOf(
      AuthSchemaContractError,
    );
  });

  it("rejects a partial, extra, or fingerprint-mismatched Auth scope", async () => {
    await owner.query("CREATE SCHEMA auth");
    await owner.query("CREATE TABLE auth.partial (id integer)");
    await expect(initializeAuthSchema(owner)).rejects.toBeInstanceOf(
      AuthSchemaContractError,
    );

    await owner.query("DROP TABLE auth.partial");
    await owner.query(
      "CREATE FUNCTION auth.unexpected() RETURNS integer LANGUAGE sql IMMUTABLE AS 'SELECT 1'",
    );
    await expect(initializeAuthSchema(owner)).rejects.toBeInstanceOf(
      AuthSchemaContractError,
    );

    await owner.query("DROP SCHEMA auth CASCADE");
    await initializeAuthSchema(owner);
    await owner.query("CREATE TABLE auth.extra (id integer)");
    await expect(verifyAuthSchema(owner)).rejects.toBeInstanceOf(
      AuthSchemaContractError,
    );

    await owner.query("DROP TABLE auth.extra");
    await owner.query(
      "UPDATE auth.schema_contract SET schema_fingerprint = repeat('0', 64)",
    );
    await expect(verifyAuthSchema(owner)).rejects.toBeInstanceOf(
      AuthSchemaContractError,
    );
  });

  it("rejects row-security drift and reports the runtime unavailable", async () => {
    await initializeAuthSchema(owner);
    await owner.query('ALTER TABLE auth."session" ENABLE ROW LEVEL SECURITY');

    await expect(verifyAuthSchema(owner)).rejects.toBeInstanceOf(
      AuthSchemaContractError,
    );
    await expect(checkAuthReadiness(authRuntime)).resolves.toBe(false);
  });

  it("rejects unlogged relation durability drift", async () => {
    await initializeAuthSchema(owner);
    await owner.query('ALTER TABLE auth."session" SET UNLOGGED');

    await expect(verifyAuthSchema(owner)).rejects.toBeInstanceOf(
      AuthSchemaContractError,
    );
    await expect(checkAuthReadiness(authRuntime)).resolves.toBe(false);
  });

  it("rejects any unexpected non-owner Auth grant", async () => {
    await initializeAuthSchema(owner);
    await owner.query('GRANT SELECT ON auth."session" TO pg_monitor');
    await expect(initializeAuthSchema(owner)).rejects.toBeInstanceOf(
      AuthSchemaContractError,
    );

    await owner.query('REVOKE SELECT ON auth."session" FROM pg_monitor');
    await owner.query("GRANT USAGE ON SCHEMA auth TO pg_monitor");
    await expect(initializeAuthSchema(owner)).rejects.toBeInstanceOf(
      AuthSchemaContractError,
    );
  });

  it("rejects grant option on every Auth runtime privilege", async () => {
    await initializeAuthSchema(owner);
    await owner.query(
      'GRANT SELECT ON auth."session" TO auth_runtime WITH GRANT OPTION',
    );
    await expect(initializeAuthSchema(owner)).rejects.toBeInstanceOf(
      AuthSchemaContractError,
    );

    await owner.query(
      'REVOKE GRANT OPTION FOR SELECT ON auth."session" FROM auth_runtime',
    );
    await owner.query("GRANT USAGE ON SCHEMA auth TO auth_runtime WITH GRANT OPTION");
    await expect(initializeAuthSchema(owner)).rejects.toBeInstanceOf(
      AuthSchemaContractError,
    );
  });

  it("rejects unexpected or grantable Auth trigger-function execution", async () => {
    await initializeAuthSchema(owner);
    await owner.query(
      "GRANT EXECUTE ON FUNCTION auth.enforce_active_session_owner() TO pg_monitor",
    );
    await expect(initializeAuthSchema(owner)).rejects.toBeInstanceOf(
      AuthSchemaContractError,
    );

    await owner.query(
      "REVOKE EXECUTE ON FUNCTION auth.enforce_active_session_owner() FROM pg_monitor",
    );
    await owner.query(
      "GRANT EXECUTE ON FUNCTION auth.enforce_active_session_owner() TO auth_runtime WITH GRANT OPTION",
    );
    await expect(initializeAuthSchema(owner)).rejects.toBeInstanceOf(
      AuthSchemaContractError,
    );
  });

  it("rejects runtime role capability and membership drift", async () => {
    await initializeAuthSchema(owner);
    try {
      await owner.query("ALTER ROLE auth_runtime SUPERUSER");
      await expect(initializeAuthSchema(owner)).rejects.toBeInstanceOf(
        AuthSchemaContractError,
      );
    } finally {
      await owner.query("ALTER ROLE auth_runtime NOSUPERUSER");
    }

    try {
      await owner.query("GRANT auth_runtime TO core_runtime");
      await expect(initializeAuthSchema(owner)).rejects.toBeInstanceOf(
        AuthSchemaContractError,
      );
    } finally {
      await owner.query("REVOKE auth_runtime FROM core_runtime");
    }
  });

  it("enforces canonical email in PostgreSQL", async () => {
    await initializeAuthSchema(owner);

    await expect(
      owner.query(`
        INSERT INTO auth."user" (name, email, "emailVerified", active)
        VALUES ('invalid', 'Uppercase@Example.com', FALSE, TRUE)
      `),
    ).rejects.toMatchObject({ code: "23514" });
    await expect(
      owner.query(
        `
          INSERT INTO auth."user" (name, email, "emailVerified", active)
          VALUES ('invalid', $1, FALSE, TRUE)
        `,
        [`a@${"b".repeat(63)}.${"c".repeat(63)}.${"d".repeat(63)}.${"e".repeat(61)}`],
      ),
    ).rejects.toMatchObject({ code: "23514" });
  });

  it("installs the complete Auth-owned access lifecycle schema", async () => {
    await initializeAuthSchema(owner);

    const relations = await owner.query<{ name: string }>(`
      SELECT relation.relname AS name
      FROM pg_catalog.pg_class AS relation
      JOIN pg_catalog.pg_namespace AS namespace
        ON namespace.oid = relation.relnamespace
      WHERE namespace.nspname = 'auth'
        AND relation.relkind = 'r'
      ORDER BY relation.relname
    `);

    expect(relations.rows.map((row) => row.name)).toEqual([
      "account",
      "auth_secret_contract",
      "operator_assignment",
      "password_reset",
      "rateLimit",
      "researcher_invitation",
      "schema_contract",
      "security_audit",
      "session",
      "user",
      "verification",
    ]);
  });

  it("gives each runtime role access only to its own schema", async () => {
    await initializeAuthSchema(owner);

    await expect(authRuntime.query('SELECT count(*) FROM auth."session"')).resolves.toBeDefined();
    await expect(
      authRuntime.query("SELECT count(*) FROM product_contract_test.resource"),
    ).rejects.toThrow(/permission denied/);
    await expect(
      coreRuntime.query("SELECT count(*) FROM product_contract_test.resource"),
    ).resolves.toBeDefined();
    await expect(coreRuntime.query('SELECT count(*) FROM auth."session"')).rejects.toThrow(
      /permission denied/,
    );

    const roles = await owner.query<{
      rolbypassrls: boolean;
      rolcanlogin: boolean;
      rolcreatedb: boolean;
      rolcreaterole: boolean;
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
        rolreplication,
        rolbypassrls
      FROM pg_catalog.pg_roles
      WHERE rolname IN ('auth_runtime', 'core_runtime')
      ORDER BY rolname
    `);
    expect(roles.rows).toEqual([
      {
        rolbypassrls: false,
        rolcanlogin: true,
        rolcreatedb: false,
        rolcreaterole: false,
        rolname: "auth_runtime",
        rolreplication: false,
        rolsuper: false,
      },
      {
        rolbypassrls: false,
        rolcanlogin: true,
        rolcreatedb: false,
        rolcreaterole: false,
        rolname: "core_runtime",
        rolreplication: false,
        rolsuper: false,
      },
    ]);

    const privileges = await owner.query<{
      auth_connect: boolean;
      core_connect: boolean;
      public_connect: boolean;
      public_create: boolean;
    }>(`
      SELECT
        pg_catalog.has_database_privilege(
          'auth_runtime', current_database(), 'CONNECT'
        ) AS auth_connect,
        pg_catalog.has_database_privilege(
          'core_runtime', current_database(), 'CONNECT'
        ) AS core_connect,
        EXISTS (
          SELECT 1
          FROM pg_catalog.pg_database AS database_record,
            LATERAL pg_catalog.aclexplode(
              COALESCE(
                database_record.datacl,
                pg_catalog.acldefault('d', database_record.datdba)
              )
            ) AS privilege
          WHERE database_record.datname = current_database()
            AND privilege.grantee = 0
            AND privilege.privilege_type = 'CONNECT'
        ) AS public_connect,
        pg_catalog.has_schema_privilege('public', 'public', 'CREATE') AS public_create
    `);
    expect(privileges.rows).toEqual([
      {
        auth_connect: true,
        core_connect: true,
        public_connect: false,
        public_create: false,
      },
    ]);
  });
});

function roleDatabaseUrl(base: string, username: string, password: string): string {
  const url = new URL(base);
  url.username = username;
  url.password = password;
  return url.toString();
}
