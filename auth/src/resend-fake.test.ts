import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { fileURLToPath } from "node:url";

import { afterAll, beforeAll, describe, expect, it } from "vitest";

const fakePath = fileURLToPath(
  new URL("../test-fixtures/resend-fake.mjs", import.meta.url),
);
let child: ChildProcessWithoutNullStreams;
let origin: string;
let capturedStdout = "";
let capturedStderr = "";

describe.sequential("local Resend HTTP fake", () => {
  beforeAll(async () => {
    child = spawn(process.execPath, [fakePath], {
      env: {
        THESISTRACE_RESEND_FAKE_MODE: "success",
        THESISTRACE_RESEND_FAKE_PORT: "0",
      },
      stdio: ["pipe", "pipe", "pipe"],
    });
    child.stdout.setEncoding("utf8");
    child.stderr.setEncoding("utf8");
    child.stdout.on("data", (chunk: string) => {
      capturedStdout += chunk;
    });
    child.stderr.on("data", (chunk: string) => {
      capturedStderr += chunk;
    });
    origin = await readyOrigin(child);
  });

  afterAll(async () => {
    if (child.exitCode === null && child.signalCode === null) {
      child.kill("SIGTERM");
      await new Promise<void>((resolve) => child.once("close", () => resolve()));
    }
    expect(capturedStdout).not.toContain("token-canary");
    expect(capturedStderr).not.toContain("token-canary");
  });

  it("captures an accepted email only on its private Test endpoint", async () => {
    const response = await sendEmail("token-canary-success");
    const captured = await fetch(`${origin}/__test/emails`);

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ id: "resend-fake-1" });
    expect(await captured.json()).toEqual({
      emails: [expect.objectContaining({ html: "token-canary-success" })],
    });
  });

  it("supports provider rejection, bounded delay, and transport unavailability", async () => {
    await setMode("rejected");
    expect((await sendEmail("token-canary-rejected")).status).toBe(422);

    await setMode("delayed");
    let delayedSettled = false;
    const delayed = sendEmail("token-canary-delayed").finally(() => {
      delayedSettled = true;
    });
    await new Promise<void>((resolve) => setImmediate(resolve));
    expect(delayedSettled).toBe(false);
    expect((await delayed).status).toBe(200);

    await setMode("unavailable");
    await expect(sendEmail("token-canary-unavailable")).rejects.toThrow();
  });
});

function sendEmail(html: string): Promise<Response> {
  return fetch(`${origin}/emails`, {
    body: JSON.stringify({
      from: "ThesisTrace <noreply@thesistrace.test>",
      html,
      subject: "Test",
      text: "Test",
      to: ["researcher@example.com"],
    }),
    headers: { "content-type": "application/json" },
    method: "POST",
  });
}

async function setMode(mode: string): Promise<void> {
  const response = await fetch(`${origin}/__test/mode`, {
    body: JSON.stringify({ mode }),
    headers: { "content-type": "application/json" },
    method: "PUT",
  });
  expect(response.status).toBe(200);
}

function readyOrigin(process: ChildProcessWithoutNullStreams): Promise<string> {
  return new Promise((resolve, reject) => {
    let buffer = "";
    const onData = (chunk: Buffer | string) => {
      buffer += chunk.toString();
      const newline = buffer.indexOf("\n");
      if (newline < 0) {
        return;
      }
      process.stdout.off("data", onData);
      const event = JSON.parse(buffer.slice(0, newline)) as {
        event?: string;
        port?: number;
      };
      if (event.event !== "resend_fake_ready" || typeof event.port !== "number") {
        reject(new Error("Resend fake emitted an invalid readiness event"));
        return;
      }
      resolve(`http://127.0.0.1:${event.port}`);
    };
    process.stdout.on("data", onData);
    process.once("error", reject);
    process.once("exit", (code) => {
      if (code !== null && code !== 0) {
        reject(new Error("Resend fake exited before readiness"));
      }
    });
  });
}
