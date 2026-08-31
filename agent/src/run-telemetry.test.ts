import { spawn } from "node:child_process";
import { once } from "node:events";
import { fileURLToPath } from "node:url";

import { build } from "esbuild";
import { expect, test } from "vitest";

import { createRunTelemetry, type AgentTelemetryEvent } from "./run-telemetry.js";

const identity = {
  modelKey: "scripted-research", providerModelId: "scripted-v1", reasoningEffort: "medium",
  researcherId: "00000000-0000-4000-8000-000000000101",
  threadId: "00000000-0000-4000-8000-000000000102",
  runId: "00000000-0000-4000-8000-000000000103",
  traceId: "00000000-0000-4000-8000-000000000104",
} as const;

test("emits closed content-free run and tool metadata with stable units and identity", () => {
  const events: AgentTelemetryEvent[] = [];
  let now = 1_000;
  const observer = createRunTelemetry(identity, {
    clock: () => new Date("2026-08-31T00:00:00.000Z"), monotonicMilliseconds: () => now,
    metrics: () => ({ steps: 2, usage: { reported: true, inputTokens: { total: 11, noCache: 9, cacheRead: 2, cacheWrite: null }, outputTokens: { total: 12, text: 8, reasoning: 4 } } }),
    write: (event) => events.push(event),
  });
  observer.accepted();
  now += 100;
  observer.toolFinished(null);
  observer.toolFinished("TOOL_REJECTION");
  now += 250;
  observer.finished("PROVIDER_TIMEOUT");
  observer.finished(null);
  expect(events.map((event) => [event.event, event.status, event.error_category])).toEqual([
    ["agent_run_accepted", "running", null],
    ["agent_tool_finished", "completed", null],
    ["agent_tool_finished", "failed", "TOOL_REJECTION"],
    ["agent_run_finished", "failed", "PROVIDER_TIMEOUT"],
  ]);
  expect(events[3]).toMatchObject({ duration_ms: 350, retry_classification: "retry", step_count: 2, trace_id: identity.traceId, token_usage: { inputTokens: { total: 11 }, outputTokens: { total: 12 } } });
  expect(events[0]?.researcher_correlation).toMatch(/^[a-f0-9]{64}$/);
  expect(JSON.stringify(events)).not.toContain(identity.researcherId);
  expect(Object.keys(events[3]!).sort()).toEqual([
    "component", "duration_ms", "error_category", "event", "level", "model_key", "provider_model_id", "reasoning_effort",
    "researcher_correlation", "retry_classification", "run_id", "status", "step_count", "thread_id", "timestamp", "token_usage", "trace_id",
  ]);
});

test("does not serialize unexpected fields, invalid metadata values or raw accounting", () => {
  const events: AgentTelemetryEvent[] = [];
  const privateValue = "/private/telemetry-content-canary?token=secret";
  const observer = createRunTelemetry({ ...identity, runId: privateValue, providerModelId: privateValue, message: privateValue, error: new Error(privateValue) } as never, {
    metrics: () => ({ steps: Infinity, usage: { reported: true, raw: privateValue, inputTokens: { total: privateValue }, outputTokens: { total: -1 } } as never }),
    write: (event) => events.push(event),
  });
  observer.accepted();
  observer.finished(privateValue as never);
  expect(events[1]).toMatchObject({ run_id: null, provider_model_id: null, step_count: null, error_category: "INTERNAL_FAILURE", token_usage: { inputTokens: { total: null }, outputTokens: { total: null } } });
  expect(JSON.stringify(events)).not.toContain("telemetry-content-canary");
});

test("a rejected or duplicate admission produces no invented run observation", () => {
  const events: AgentTelemetryEvent[] = [];
  const observer = createRunTelemetry(identity, { metrics: () => ({ steps: 0, usage: undefined }), write: (event) => events.push(event) });
  observer.finished("INTERNAL_FAILURE");
  expect(events).toEqual([]);
});

test("a failed logging sink cannot roll back successful work", () => {
  const observer = createRunTelemetry(identity, { metrics: () => ({ steps: 1, usage: undefined }), write: () => { throw new Error("private-sink-canary"); } });
  expect(() => { observer.accepted(); observer.finished(null); }).not.toThrow();
});

test("a broken stderr pipe cannot terminate an accepted Run", async () => {
  // Compile the actual source and its dependencies in memory, not a copied
  // writer or stale dist output. The child uses a real OS pipe and event loop.
  const source = await build({
    stdin: { contents: `
      import { createRunTelemetry } from "./run-telemetry.ts";
      const observer = createRunTelemetry(${JSON.stringify(identity)}, {
        metrics: () => ({ steps: 1, usage: undefined }),
      });
      process.on("uncaughtExceptionMonitor", error => process.send?.({ code: error.code }));
      process.once("message", () => {
        observer.accepted();
        setImmediate(() => {
          observer.finished(null);
          process.send("completed", () => process.disconnect());
        });
      });
      process.send("ready");
    `, resolveDir: fileURLToPath(new URL(".", import.meta.url)), loader: "ts" },
    bundle: true, platform: "node", format: "cjs", write: false, logLevel: "silent",
  });
  const child = spawn(process.execPath, ["--input-type=commonjs"], {
    stdio: ["pipe", "ignore", "pipe", "ipc"], timeout: 5_000,
  });
  const messages: unknown[] = [];
  child.on("message", (message) => messages.push(message));
  const ready = once(child, "message");
  const exited = once(child, "exit");
  try {
    child.stdin!.end(source.outputFiles[0]!.text);
    expect((await ready)[0]).toBe("ready");
    const pipeClosed = once(child.stderr!, "close");
    child.stderr!.destroy();
    await pipeClosed;
    child.send("run");
    expect(await exited).toEqual([0, null]);
    expect(messages).toEqual(["ready", "completed"]);
  } finally {
    if (child.exitCode === null && child.signalCode === null) child.kill("SIGKILL");
  }
}, 10_000);
