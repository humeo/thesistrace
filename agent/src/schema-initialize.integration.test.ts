import { Pool } from "pg";
import { afterAll, beforeEach, describe, expect, it } from "vitest";

import { AgentSchemaContractError } from "./failure.js";
import { initializeAgentSchema } from "./schema-initialize.js";
import {
  catalogFingerprint,
  loadExpectedCatalog,
  verifyAgentSchema,
} from "./schema-contract.js";

const ownerDatabaseUrl = process.env.THESISTRACE_AGENT_TEST_OWNER_DATABASE_URL;
if (ownerDatabaseUrl === undefined) {
  throw new Error("THESISTRACE_AGENT_TEST_OWNER_DATABASE_URL is required");
}

const owner = new Pool({ connectionString: ownerDatabaseUrl, max: 4 });
const runtime = new Pool({
  connectionString: roleDatabaseUrl(
    ownerDatabaseUrl,
    "agent_runtime",
    "agent-test-password",
  ),
  max: 2,
});

describe.sequential("Agent physical schema", () => {
  beforeEach(async () => {
    await owner.query("DROP SCHEMA IF EXISTS agent CASCADE");
    await owner.query("DROP SCHEMA IF EXISTS auth CASCADE");
    await owner.query("DROP SCHEMA IF EXISTS core CASCADE");
    await owner.query("DROP SCHEMA IF EXISTS data CASCADE");
    await owner.query("CREATE SCHEMA auth AUTHORIZATION thesistrace_owner");
    await owner.query("CREATE SCHEMA core AUTHORIZATION thesistrace_owner");
    await owner.query("CREATE SCHEMA data AUTHORIZATION thesistrace_owner");
    await owner.query("CREATE TABLE auth.session_canary (id integer PRIMARY KEY)");
    await owner.query("CREATE TABLE core.research_canary (id integer PRIMARY KEY)");
    await owner.query("CREATE TABLE data.dataset_canary (id integer PRIMARY KEY)");
    await owner.query("GRANT USAGE ON SCHEMA auth TO auth_runtime");
    await owner.query("GRANT USAGE ON SCHEMA core TO core_runtime");
  });

  afterAll(async () => {
    await runtime.end();
    await owner.query("DROP SCHEMA IF EXISTS agent CASCADE");
    await owner.query("DROP SCHEMA IF EXISTS auth CASCADE");
    await owner.query("DROP SCHEMA IF EXISTS core CASCADE");
    await owner.query("DROP SCHEMA IF EXISTS data CASCADE");
    await owner.end();
  });

  it.each(["absent", "empty"])(
    "installs an %s scope once and then only verifies it",
    async (initialState) => {
      if (initialState === "empty") {
        await owner.query("CREATE SCHEMA agent AUTHORIZATION thesistrace_owner");
      }

      await initializeAgentSchema(owner);
      await verifyAgentSchema(owner);
      const expected = await loadExpectedCatalog();
      const fingerprint = await owner.query<{ schema_fingerprint: string }>(`
        SELECT schema_fingerprint
        FROM agent.schema_contract
        WHERE singleton IS TRUE
      `);
      expect(fingerprint.rows).toEqual([
        { schema_fingerprint: catalogFingerprint(expected) },
      ]);
      await expect(initializeAgentSchema(owner)).resolves.toBeUndefined();
    },
  );

  it("serializes concurrent initializers", async () => {
    await Promise.all([
      initializeAgentSchema(owner),
      initializeAgentSchema(owner),
    ]);
    await expect(verifyAgentSchema(owner)).resolves.toBeUndefined();
  });

  it("fails closed on partial, extra, fingerprint, and row-security drift", async () => {
    await owner.query("CREATE SCHEMA agent AUTHORIZATION thesistrace_owner");
    await owner.query("CREATE TABLE agent.partial (id integer)");
    await expect(initializeAgentSchema(owner)).rejects.toBeInstanceOf(
      AgentSchemaContractError,
    );

    await owner.query("DROP SCHEMA agent CASCADE");
    await initializeAgentSchema(owner);
    await owner.query("CREATE TABLE agent.extra (id integer)");
    await expect(verifyAgentSchema(owner)).rejects.toBeInstanceOf(
      AgentSchemaContractError,
    );
    await owner.query("DROP TABLE agent.extra");
    await owner.query(
      "UPDATE agent.schema_contract SET schema_fingerprint = repeat('0', 64)",
    );
    await expect(verifyAgentSchema(owner)).rejects.toBeInstanceOf(
      AgentSchemaContractError,
    );
    await owner.query("DROP SCHEMA agent CASCADE");
    await initializeAgentSchema(owner);
    await owner.query("ALTER TABLE agent.chat_session ENABLE ROW LEVEL SECURITY");
    await expect(verifyAgentSchema(owner)).rejects.toBeInstanceOf(
      AgentSchemaContractError,
    );
  });

  it("rolls back a fresh install when the runtime role contract is invalid", async () => {
    await owner.query("CREATE SCHEMA agent AUTHORIZATION thesistrace_owner");
    await owner.query("ALTER ROLE agent_runtime NOLOGIN");
    try {
      await expect(initializeAgentSchema(owner)).rejects.toBeInstanceOf(
        AgentSchemaContractError,
      );
      const relations = await owner.query<{ count: string }>(`
        SELECT count(*)::text
        FROM pg_catalog.pg_class AS relation
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = relation.relnamespace
        WHERE namespace.nspname = 'agent'
      `);
      expect(relations.rows).toEqual([{ count: "0" }]);
    } finally {
      await owner.query("ALTER ROLE agent_runtime LOGIN");
    }
  });

  it("gives agent_runtime only the exact Agent schema boundary", async () => {
    await initializeAgentSchema(owner);
    await expect(runtime.query("SELECT count(*) FROM agent.chat_session")).resolves.toBeDefined();
    await expect(runtime.query("SELECT * FROM auth.session_canary")).rejects.toMatchObject({
      code: "42501",
    });
    await expect(runtime.query("SELECT * FROM core.research_canary")).rejects.toMatchObject({
      code: "42501",
    });
    await expect(runtime.query("SELECT * FROM data.dataset_canary")).rejects.toMatchObject({
      code: "42501",
    });
    await expect(runtime.query("CREATE TABLE agent.forbidden (id integer)")).rejects.toMatchObject({
      code: "42501",
    });
  });

  it("fails startup verification on foreign or broadened Agent grants", async () => {
    await initializeAgentSchema(owner);
    await owner.query("GRANT USAGE ON SCHEMA data TO agent_runtime");
    await owner.query("GRANT SELECT ON data.dataset_canary TO agent_runtime");
    await expect(verifyAgentSchema(runtime)).rejects.toMatchObject({
      reason: "SCHEMA_ROLE_CONTRACT_INVALID",
    });

    await owner.query("REVOKE ALL ON data.dataset_canary FROM agent_runtime");
    await owner.query("REVOKE ALL ON SCHEMA data FROM agent_runtime");
    await owner.query("GRANT USAGE ON SCHEMA agent TO PUBLIC");
    await expect(verifyAgentSchema(runtime)).rejects.toMatchObject({
      reason: "SCHEMA_ROLE_CONTRACT_INVALID",
    });
  });
});

function roleDatabaseUrl(base: string, username: string, password: string): string {
  const url = new URL(base);
  url.username = username;
  url.password = password;
  return url.toString();
}
