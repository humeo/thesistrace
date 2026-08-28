import { spawn } from "node:child_process";
import { createServer, type Server } from "node:http";
import type { AddressInfo } from "node:net";
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
const requests: string[] = [];
let resendServer: Server;
let resendOrigin: string;
let resendHold:
  | Readonly<{ release: Promise<void>; started: () => void }>
  | undefined;

describe.sequential("Auth operator process boundary", () => {
  beforeAll(async () => {
    await owner.query("DROP SCHEMA IF EXISTS auth CASCADE");
    await initializeAuthSchema(owner);
    resendServer = createServer((request, response) => {
      const chunks: Buffer[] = [];
      request.on("data", (chunk: Buffer) => chunks.push(chunk));
      request.on("end", () => {
        requests.push(Buffer.concat(chunks).toString("utf8"));
        const finish = () => {
          response.writeHead(200, { "content-type": "application/json" });
          response.end('{"id":"resend-fake-id"}');
        };
        const hold = resendHold;
        if (hold === undefined) {
          finish();
          return;
        }
        hold.started();
        void hold.release.then(finish);
      });
    });
    await new Promise<void>((resolve, reject) => {
      resendServer.once("error", reject);
      resendServer.listen(0, "127.0.0.1", resolve);
    });
    const address = resendServer.address() as AddressInfo;
    resendOrigin = `http://127.0.0.1:${address.port}`;
  });

  afterAll(async () => {
    await new Promise<void>((resolve, reject) => {
      resendServer.close((error) => (error === undefined ? resolve() : reject(error)));
    });
    await owner.query("DROP SCHEMA IF EXISTS auth CASCADE");
    await owner.end();
  });

  it("emits one token-free stdout result and one identity-free safe event", async () => {
    const result = await runOperator([
      "invite",
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
      command: "invite",
      email: "operator-process@example.com",
      status: "delivered",
    });
    expect(result.stdout).not.toContain("#token=");
    expect(result.stdout).not.toContain("accept-invitation");
    expect(result.stderr).not.toContain("operator-process@example.com");
    expect(result.stderr).not.toContain("#token=");
    expect(JSON.parse(stderrLines[0] ?? "null")).toEqual({
      command: "invite",
      event: "auth_operator_completed",
      status: "delivered",
    });
    expect(requests).toHaveLength(1);
    expect(requests[0]).toContain("/accept-invitation#token=");
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

  it("handles an idle PostgreSQL failure without a native stack or secret leak", async () => {
    let notifyStarted: () => void = () => undefined;
    const started = new Promise<void>((resolve) => {
      notifyStarted = resolve;
    });
    let releaseResend: () => void = () => undefined;
    const release = new Promise<void>((resolve) => {
      releaseResend = resolve;
    });
    resendHold = { release, started: notifyStarted };
    try {
      const resultPromise = runOperator([
        "invite",
        "--email",
        "idle-failure@example.com",
      ]);
      await started;
      const backend = await owner.query<{ terminated: boolean }>(`
        SELECT pg_catalog.pg_terminate_backend(pid) AS terminated
        FROM pg_catalog.pg_stat_activity
        WHERE application_name = 'thesistrace_auth'
          AND usename = 'auth_runtime'
          AND pid <> pg_catalog.pg_backend_pid()
        ORDER BY backend_start DESC
        LIMIT 1
      `);
      expect(backend.rows).toEqual([{ terminated: true }]);
      releaseResend();
      const result = await resultPromise;
      const stderrEvents = result.stderr
        .trim()
        .split("\n")
        .map((line) => JSON.parse(line) as Record<string, unknown>);

      expect(result.code).toBe(0);
      expect(result.stdout.trim().split("\n")).toHaveLength(1);
      expect(stderrEvents).toEqual(
        expect.arrayContaining([
          expect.objectContaining({
            code: "AUTH_DATABASE_UNAVAILABLE",
            event: "auth_database_pool_error",
            reason: "DATABASE_UNAVAILABLE",
          }),
          {
            command: "invite",
            event: "auth_operator_completed",
            status: "delivered",
          },
        ]),
      );
      expect(result.stderr).not.toContain("idle-failure@example.com");
      expect(result.stderr).not.toContain("auth-test-password");
      expect(result.stderr).not.toContain("node_modules");
    } finally {
      releaseResend();
      resendHold = undefined;
    }
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
        BETTER_AUTH_SECRET: "0123456789abcdef0123456789abcdef",
        RESEND_API_KEY: "resend-fake-key",
        RESEND_FROM_EMAIL: "ThesisTrace <noreply@thesistrace.test>",
        THESISTRACE_AUTH_DATABASE_URL: authRuntimeDatabaseUrl,
        THESISTRACE_ENVIRONMENT: "test",
        THESISTRACE_PUBLIC_ORIGIN: "http://127.0.0.1:5173",
        THESISTRACE_RESEND_API_URL: resendOrigin,
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
