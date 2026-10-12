import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";

import { Pool } from "pg";
import { afterAll, beforeAll, describe, expect, it } from "vitest";

import { initializeAuthSchema } from "./schema-initialize.js";

const ownerDatabaseUrl = process.env.THESISTRACE_AUTH_TEST_OWNER_DATABASE_URL;
if (ownerDatabaseUrl === undefined) {
  throw new Error("THESISTRACE_AUTH_TEST_OWNER_DATABASE_URL is required");
}
const authRuntimeDatabaseUrl = roleDatabaseUrl(
  ownerDatabaseUrl,
  "auth_runtime",
  "auth-test-password",
);
const owner = new Pool({ connectionString: ownerDatabaseUrl, max: 2 });
const operatorPath = fileURLToPath(new URL("../dist/operator.js", import.meta.url));
const authRoot = fileURLToPath(new URL("..", import.meta.url));
const fixedNow = new Date("2026-08-29T06:00:00.000Z");
const mcpEnvironment = {
  THESISTRACE_AGENT_RUN_MAX_WALL_SECONDS: "300",
  THESISTRACE_MCP_ACCESS_TOKEN_TTL_SECONDS: "360",
  THESISTRACE_MCP_AGENT_SCOPES:
    '["research:read","research:execute","tracking:read","tracking:execute"]',
  THESISTRACE_MCP_CLIENT_ID: "thesistrace-agent",
  THESISTRACE_MCP_CLOCK_SKEW_SECONDS: "30",
  THESISTRACE_MCP_ISSUER_URL: "http://127.0.0.1:5173/api/auth",
  THESISTRACE_MCP_RESOURCE_URL: "https://core.test/mcp",
  THESISTRACE_MCP_SIGNING_PRIVATE_JWK:
    '{"alg":"EdDSA","crv":"Ed25519","d":"2SCCVM_DYKEJvq18KV1M4UNFhxTHLKtdXxQFXLGlEBs","kid":"test-signing-key-01","kty":"OKP","use":"sig","x":"3d8K_V0qubfzURRlfRFt44Yk4LeNW6HkQMaeiPIhJA8"}',
  THESISTRACE_MCP_VERIFYING_PUBLIC_JWK:
    '{"alg":"EdDSA","crv":"Ed25519","kid":"test-signing-key-01","kty":"OKP","use":"sig","x":"3d8K_V0qubfzURRlfRFt44Yk4LeNW6HkQMaeiPIhJA8"}',
} as const;

describe.sequential("Auth operator process boundary", () => {
  beforeAll(async () => {
    await owner.query("DROP SCHEMA IF EXISTS auth CASCADE");
    await initializeAuthSchema(owner);
  });

  afterAll(async () => {
    await owner.query("DROP SCHEMA IF EXISTS auth CASCADE");
    await owner.end();
  });

  it("emits one token-free stdout result and one identity-free safe event", async () => {
    await owner.query(`INSERT INTO auth."user" (name,email,"emailVerified",active) VALUES ('existing','operator-process@example.com',TRUE,TRUE)`);
    const result = await runOperator([
      "resolve",
      "--email",
      "operator-process@example.com",
    ]);
    const stdoutLines = result.stdout.trim().split("\n");
    const stderrLines = result.stderr.trim().split("\n");
    const output = JSON.parse(stdoutLines[0] ?? "null") as Record<string, unknown>;

    expect(result.code).toBe(0);
    expect(stdoutLines).toHaveLength(1);
    expect(stderrLines).toHaveLength(1);
    expect(output).toMatchObject({
      command: "resolve",
      researcher_id: expect.any(String),
      status: "resolved",
    });
    expect(result.stderr).not.toContain("operator-process@example.com");
    expect(result.stderr).not.toContain("#token=");
    expect(JSON.parse(stderrLines[0] ?? "null")).toEqual({
      command: "resolve",
      event: "auth_operator_completed",
      status: "resolved",
    });
  });

  it("establishes and transfers the singleton Operator through the private process", async () => {
    const firstId = "00000000-0000-4000-8000-000000000201";
    const secondId = "00000000-0000-4000-8000-000000000202";
    await owner.query(
      `
        INSERT INTO auth."user" (
          id, name, email, "emailVerified", "createdAt", "updatedAt", active
        )
        VALUES
          ($1, 'first', 'process-operator-first@example.com', TRUE,
            $3, $3, TRUE),
          ($2, 'second', 'process-operator-second@example.com', TRUE,
            $3, $3, TRUE)
      `,
      [firstId, secondId, fixedNow],
    );

    const established = await runOperator([
      "assign-operator",
      "--researcher-id",
      firstId,
    ]);
    expect(established.code).toBe(0);
    expect(JSON.parse(established.stdout)).toEqual({
      command: "assign-operator",
      researcher_id: firstId,
      status: "assigned",
    });
    expect(JSON.parse(established.stderr)).toEqual({
      command: "assign-operator",
      event: "auth_operator_completed",
      status: "assigned",
    });

    const conflicting = await runOperator([
      "assign-operator",
      "--researcher-id",
      secondId,
    ]);
    expect(conflicting.code).toBe(1);
    expect(conflicting.stdout).toBe("");
    expect(JSON.parse(conflicting.stderr)).toEqual({
      code: "OPERATOR_ALREADY_ASSIGNED",
      event: "auth_operator_failed",
    });

    await owner.query(
      `
        INSERT INTO auth."session" (
          id, "expiresAt", token, "createdAt", "updatedAt", "userId"
        )
        VALUES (
          '00000000-0000-4000-8000-000000000203',
          $2,
          'process-former-operator-session',
          $3,
          $3,
          $1
        )
      `,
      [firstId, new Date(fixedNow.getTime() + 24 * 60 * 60 * 1_000), fixedNow],
    );
    const transferred = await runOperator([
      "transfer-operator",
      "--email",
      " Process-Operator-Second@Example.COM ",
    ]);
    expect(transferred.code).toBe(0);
    expect(JSON.parse(transferred.stdout)).toEqual({
      command: "transfer-operator",
      former_researcher_id: firstId,
      researcher_id: secondId,
      status: "transferred",
    });
    expect(JSON.parse(transferred.stderr)).toEqual({
      command: "transfer-operator",
      event: "auth_operator_completed",
      status: "transferred",
    });
    expect(
      await owner.query<{ researcher_id: string }>(
        "SELECT researcher_id FROM auth.operator_assignment",
      ),
    ).toMatchObject({ rows: [{ researcher_id: secondId }] });
    expect(
      await owner.query<{ count: string }>(
        'SELECT count(*) FROM auth."session" WHERE "userId" = $1',
        [firstId],
      ),
    ).toMatchObject({ rows: [{ count: "0" }] });
  });

  it("fails with a sanitized stderr event and no stdout reflection", async () => {
    const result = await runOperator([
      "revoke-sessions",
      "--unexpected",
      "secret-canary",
    ]);

    expect(result.code).toBe(1);
    expect(result.stdout).toBe("");
    expect(result.stderr).not.toContain("secret-canary");
    expect(result.stderr.trim().split("\n")).toHaveLength(1);
    expect(JSON.parse(result.stderr)).toEqual({
      code: "AUTH_OPERATOR_ARGUMENT_INVALID",
      event: "auth_operator_failed",
    });
  });
});

function runOperator(args: string[]): Promise<{
  code: number | null;
  stderr: string;
  stdout: string;
}> {
  return new Promise((resolve, reject) => {
    const child = spawn(process.execPath, [operatorPath, ...args], {
      cwd: authRoot,
      env: {
        ...mcpEnvironment,
        THESISTRACE_TURNSTILE_SITE_KEY: "1x00000000000000000000AA",
        THESISTRACE_TURNSTILE_SECRET_KEY: "1x0000000000000000000000000000000AA",
        THESISTRACE_TURNSTILE_VERIFY_URL: "https://challenges.cloudflare.com/turnstile/v0/siteverify",
        THESISTRACE_EMAIL_CODE_GLOBAL_HOURLY_LIMIT: "25",
        THESISTRACE_EMAIL_CODE_GLOBAL_DAILY_LIMIT: "100",
        BETTER_AUTH_SECRET: "0123456789abcdef0123456789abcdef",
        RESEND_API_KEY: "resend-fake-key",
        RESEND_FROM_EMAIL: "ThesisTrace <noreply@thesistrace.test>",
        THESISTRACE_RESEND_API_URL: "http://resend-fake:8300",
        THESISTRACE_AUTH_DATABASE_URL: authRuntimeDatabaseUrl,
        THESISTRACE_ENVIRONMENT: "test",
        THESISTRACE_PUBLIC_ORIGIN: "http://127.0.0.1:5173",
      },
      stdio: ["ignore", "pipe", "pipe"],
    });
    let stdout = "";
    let stderr = "";
    child.stdout.setEncoding("utf8");
    child.stderr.setEncoding("utf8");
    child.stdout.on("data", (chunk: string) => {
      stdout += chunk;
    });
    child.stderr.on("data", (chunk: string) => {
      stderr += chunk;
    });
    child.once("error", reject);
    child.once("close", (code) => resolve({ code, stderr, stdout }));
  });
}

function roleDatabaseUrl(base: string, username: string, password: string): string {
  const url = new URL(base);
  url.username = username;
  url.password = password;
  return url.toString();
}
