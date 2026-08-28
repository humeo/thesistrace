import { spawn, type ChildProcess } from "node:child_process";
import { fileURLToPath } from "node:url";

import { Pool } from "pg";
import { afterAll, describe, expect, it } from "vitest";

const ownerDatabaseUrl = process.env.THESISTRACE_AUTH_TEST_OWNER_DATABASE_URL;
if (ownerDatabaseUrl === undefined) {
  throw new Error("THESISTRACE_AUTH_TEST_OWNER_DATABASE_URL is required");
}
const authRuntimeDatabaseUrl = roleDatabaseUrl(
  ownerDatabaseUrl,
  "auth_runtime",
  "auth-test-password",
);
const owner = new Pool({ connectionString: ownerDatabaseUrl, max: 1 });
const workerPath = fileURLToPath(
  new URL("../test-fixtures/coordination-worker.mjs", import.meta.url),
);

describe.sequential("Auth coordination process boundary", () => {
  afterAll(async () => {
    await owner.end();
  });

  it("fails closed without a native crash when a checked-out client disconnects", async () => {
    const running = runWorker();
    try {
      await running.started;
      const terminated = await owner.query<{ terminated: boolean }>(`
        SELECT pg_catalog.pg_terminate_backend(pid) AS terminated
        FROM pg_catalog.pg_stat_activity
        WHERE application_name = 'thesistrace_auth_coordination'
          AND usename = 'auth_runtime'
          AND pid <> pg_catalog.pg_backend_pid()
        ORDER BY backend_start DESC
        LIMIT 1
      `);
      expect(terminated.rows).toEqual([{ terminated: true }]);
      await running.connectionFailed;
      expect(await running.status()).toBe(false);
      running.child.send?.({ command: "release" });

      const result = await running.result;

      expect(result.code).toBe(1);
      expect(result.signal).toBeNull();
      expect(result.stdout).toBe("");
      expect(result.stderr).toBe(
        '{"code":"AUTH_COORDINATION_UNAVAILABLE","event":"coordination_failed"}\n',
      );
      expect(result.stderr).not.toContain("node_modules");
      expect(result.stderr).not.toContain("auth-test-password");
    } finally {
      if (running.child.connected) {
        running.child.send?.({ command: "release" });
      }
      await running.result.catch(() => undefined);
    }
  });
});

function runWorker(): Readonly<{
  child: ChildProcess;
  connectionFailed: Promise<void>;
  result: Promise<{
    code: number | null;
    signal: NodeJS.Signals | null;
    stderr: string;
    stdout: string;
  }>;
  started: Promise<void>;
  status: () => Promise<boolean>;
}> {
  const child = spawn(process.execPath, [workerPath], {
    env: {
      THESISTRACE_AUTH_DATABASE_URL: authRuntimeDatabaseUrl,
    },
    stdio: ["ignore", "pipe", "pipe", "ipc"],
  });
  let stdout = "";
  let stderr = "";
  child.stdout?.setEncoding("utf8");
  child.stderr?.setEncoding("utf8");
  child.stdout?.on("data", (chunk: string) => {
    stdout += chunk;
  });
  child.stderr?.on("data", (chunk: string) => {
    stderr += chunk;
  });
  let resolveConnectionFailed: () => void = () => undefined;
  const connectionFailed = new Promise<void>((resolve) => {
    resolveConnectionFailed = resolve;
  });
  let resolveStatus: ((settled: boolean) => void) | undefined;
  const started = new Promise<void>((resolve, reject) => {
    child.once("error", reject);
    child.once("exit", (code) => {
      if (code !== null) {
        reject(new Error("coordination worker exited before acquiring its lock"));
      }
    });
    child.on("message", (message) => {
      if (
        message !== null &&
        typeof message === "object" &&
        "event" in message &&
        message.event === "coordination_started"
      ) {
        resolve();
      } else if (
        message !== null &&
        typeof message === "object" &&
        "event" in message &&
        message.event === "coordination_connection_failed"
      ) {
        resolveConnectionFailed();
      } else if (
        message !== null &&
        typeof message === "object" &&
        "event" in message &&
        message.event === "coordination_status" &&
        "settled" in message &&
        typeof message.settled === "boolean"
      ) {
        resolveStatus?.(message.settled);
        resolveStatus = undefined;
      }
    });
  });
  const result = new Promise<{
    code: number | null;
    signal: NodeJS.Signals | null;
    stderr: string;
    stdout: string;
  }>((resolve, reject) => {
    child.once("error", reject);
    child.once("close", (code, signal) => {
      resolve({ code, signal, stderr, stdout });
    });
  });
  const status = () =>
    new Promise<boolean>((resolve, reject) => {
      if (!child.connected || resolveStatus !== undefined) {
        reject(new Error("coordination worker status is unavailable"));
        return;
      }
      resolveStatus = resolve;
      child.send({ command: "status" }, (error) => {
        if (error !== null) {
          resolveStatus = undefined;
          reject(error);
        }
      });
    });
  return { child, connectionFailed, result, started, status };
}

function roleDatabaseUrl(base: string, username: string, password: string): string {
  const url = new URL(base);
  url.username = username;
  url.password = password;
  return url.toString();
}
