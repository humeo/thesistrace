import { randomUUID } from "node:crypto";

import type { AGUIEvent, Message, RunAgentInput } from "@ag-ui/core";
import { Pool } from "pg";
import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import type { AgentSettings } from "./config.js";
import { chatRunFingerprint } from "./chat-request.js";
import { readModelRegistry } from "./model-registry.js";
import { createResearchRuntime, type ResearchRuntime } from "./research-runtime.js";
import { initializeAgentSchema } from "./schema-initialize.js";
import type { VerifiedResearcher } from "./session-verifier.js";

const ownerDatabaseUrl = process.env.THESISTRACE_AGENT_TEST_OWNER_DATABASE_URL;
if (ownerDatabaseUrl === undefined) {
  throw new Error("THESISTRACE_AGENT_TEST_OWNER_DATABASE_URL is required");
}

const owner = new Pool({ connectionString: ownerDatabaseUrl, max: 4 });
const runtimeDatabaseUrl = roleDatabaseUrl(
  ownerDatabaseUrl,
  "agent_runtime",
  "agent-test-password",
);
const primaryResearcher = researcher("00000000-0000-4000-8000-000000000101");
const foreignResearcher = researcher("00000000-0000-4000-8000-000000000102");
const modelRegistry = readModelRegistry(JSON.stringify({
  default_model_key: "scripted-research",
  models: [
    {
      default_reasoning_effort: "medium",
      display_name: "Scripted Research",
      enabled: true,
      key: "scripted-research",
      provider_adapter: "scripted",
      provider_model_id: "scripted-v1",
      reasoning_efforts: ["none", "medium"],
      secret_env: "THESISTRACE_AGENT_SCRIPTED_MODEL_SECRET",
    },
    {
      default_reasoning_effort: "medium",
      display_name: "Scripted Failure",
      enabled: true,
      key: "scripted-failure",
      provider_adapter: "scripted",
      provider_model_id: "scripted-failure-v1",
      reasoning_efforts: ["medium"],
      secret_env: "THESISTRACE_AGENT_SCRIPTED_MODEL_SECRET",
    },
  ],
}), { THESISTRACE_AGENT_SCRIPTED_MODEL_SECRET: "integration-secret" });
const settings: AgentSettings = {
  agentBuildRevision: "integration-build",
  authInternalOrigin: "http://auth.invalid",
  databaseUrl: runtimeDatabaseUrl,
  environment: "test",
  host: "127.0.0.1",
  modelRegistry,
  port: 8400,
  publicOrigin: "http://127.0.0.1:4317",
};

describe.sequential("durable Research Agent runtime", () => {
  beforeAll(async () => {
    await owner.query("DROP SCHEMA IF EXISTS agent CASCADE");
    await initializeAgentSchema(owner);
  });

  beforeEach(async () => {
    await owner.query(`
      TRUNCATE
        agent.agent_run,
        agent.chat_session,
        agent."mastra_messages",
        agent."mastra_observational_memory",
        agent."mastra_resources",
        agent."mastra_threads",
        agent."mastra_workflow_snapshot"
      CASCADE
    `);
  });

  afterAll(async () => {
    await owner.query("DROP SCHEMA IF EXISTS agent CASCADE");
    await owner.end();
  });

  it("creates once, captures metadata, replays duplicates, and survives a host restart", async () => {
    const threadId = randomUUID();
    const runId = randomUUID();
    const messageId = randomUUID();
    const input = runInput({ messageId, runId, threadId });
    let runtime = await createResearchRuntime(settings);
    try {
      const first = await run(runtime, input, primaryResearcher);
      expect(first.map((event) => event.type)).toEqual([
        "RUN_STARTED",
        "TEXT_MESSAGE_START",
        "TEXT_MESSAGE_CONTENT",
        "TEXT_MESSAGE_CONTENT",
        "TEXT_MESSAGE_END",
        "RUN_FINISHED",
      ]);

      const duplicate = await run(runtime, input, primaryResearcher);
      expect(duplicate.map((event) => event.type)).toEqual([
        "RUN_STARTED",
        "MESSAGES_SNAPSHOT",
        "RUN_FINISHED",
      ]);
      const counts = await owner.query<{
        messages: string;
        runs: string;
        sessions: string;
        threads: string;
      }>(`
        SELECT
          (SELECT count(*) FROM agent.chat_session WHERE id = $1::uuid) AS sessions,
          (SELECT count(*) FROM agent.agent_run WHERE thread_id = $1::uuid) AS runs,
          (SELECT count(*) FROM agent."mastra_threads" WHERE id = $1::uuid::text) AS threads,
          (SELECT count(*) FROM agent."mastra_messages" WHERE thread_id = $1::uuid::text) AS messages
      `, [threadId]);
      expect(counts.rows).toEqual([{
        messages: "2",
        runs: "1",
        sessions: "1",
        threads: "1",
      }]);

      const metadata = await owner.query<{
        agent_build_revision: string;
        model_key: string;
        provider_model_id: string;
        reasoning_effort: string;
        status: string;
        token_usage: Record<string, unknown>;
      }>(`
        SELECT model_key, provider_model_id, reasoning_effort,
               agent_build_revision, status, token_usage
        FROM agent.agent_run
        WHERE id = $1
      `, [runId]);
      expect(metadata.rows[0]).toMatchObject({
        agent_build_revision: "integration-build",
        model_key: "scripted-research",
        provider_model_id: "scripted-v1",
        reasoning_effort: "medium",
        status: "completed",
        token_usage: {
          reported: true,
          inputTokens: { total: 11 },
          outputTokens: { total: 12 },
        },
      });
    } finally {
      await runtime.close();
    }

    runtime = await createResearchRuntime(settings);
    try {
      await expect(runtime.preference(threadId, primaryResearcher)).resolves.toEqual({
        model_key: "scripted-research",
        reasoning_effort: "medium",
      });
      await expect(runtime.preference(threadId, foreignResearcher)).resolves.toBeNull();
      await expect(runtime.preference("not-a-thread", primaryResearcher)).resolves.toBeNull();
      const replay = await connect(runtime, threadId, primaryResearcher);
      expect(replay.map((event) => event.type)).toEqual([
        "RUN_STARTED",
        "MESSAGES_SNAPSHOT",
        "RUN_FINISHED",
      ]);
      expect(replay[1]).toMatchObject({
        type: "MESSAGES_SNAPSHOT",
        messages: [
          { content: "Build a low volatility Alpha.", id: messageId, role: "user" },
          { content: "I can help turn that idea into a testable Alpha.", role: "assistant" },
        ],
      });

      const absentConnect = await runtime.handle(
        connectRequest(randomUUID()),
        primaryResearcher,
      );
      expect(absentConnect.status).toBe(404);
      await expect(absentConnect.json()).resolves.toEqual({
        code: "CHAT_SESSION_NOT_FOUND",
      });

      const foreignConnect = await runtime.handle(
        connectRequest(threadId),
        foreignResearcher,
      );
      expect(foreignConnect.status).toBe(404);
      await expect(foreignConnect.json()).resolves.toEqual({
        code: "CHAT_SESSION_NOT_FOUND",
      });
      const foreignRun = await runtime.handle(
        runRequest(input),
        foreignResearcher,
      );
      expect(foreignRun.status).toBe(404);
    } finally {
      await runtime.close();
    }
  });

  it("keeps transcript order exact and applies a changed selection only to the next run", async () => {
    const runtime = await createResearchRuntime(settings);
    try {
      const threadId = randomUUID();
      const firstRunId = randomUUID();
      await run(runtime, runInput({
        messageId: randomUUID(),
        runId: firstRunId,
        threadId,
      }), primaryResearcher);
      const snapshot = await connect(runtime, threadId, primaryResearcher);
      const durable = snapshotMessages(snapshot);
      const secondRunId = randomUUID();
      await run(runtime, runInput({
        messageId: randomUUID(),
        messages: [...durable, {
          content: "Now remove reasoning.",
          id: randomUUID(),
          role: "user",
        }],
        modelKey: "scripted-research",
        reasoningEffort: "none",
        runId: secondRunId,
        threadId,
      }), primaryResearcher);

      const runs = await owner.query<{
        id: string;
        reasoning_effort: string;
      }>(`
        SELECT id::text, reasoning_effort
        FROM agent.agent_run
        WHERE thread_id = $1
        ORDER BY started_at, id
      `, [threadId]);
      expect(runs.rows).toEqual([
        { id: firstRunId, reasoning_effort: "medium" },
        { id: secondRunId, reasoning_effort: "none" },
      ]);
      const session = await owner.query<{ selected_reasoning_effort: string }>(`
        SELECT selected_reasoning_effort
        FROM agent.chat_session
        WHERE id = $1
      `, [threadId]);
      expect(session.rows).toEqual([{ selected_reasoning_effort: "none" }]);
      await expect(runtime.preference(threadId, primaryResearcher)).resolves.toEqual({
        model_key: "scripted-research",
        reasoning_effort: "none",
      });
    } finally {
      await runtime.close();
    }
  });

  it("rolls back first-session metadata when the paired Mastra Thread cannot be created", async () => {
    const runtime = await createResearchRuntime(settings);
    try {
      const threadId = randomUUID();
      await owner.query(`
        INSERT INTO agent."mastra_threads" (
          id, "resourceId", title, "createdAt", "updatedAt"
        ) VALUES ($1, $2, 'orphan', pg_catalog.now(), pg_catalog.now())
      `, [threadId, primaryResearcher.researcher_id]);
      const events = await run(runtime, runInput({
        messageId: randomUUID(),
        runId: randomUUID(),
        threadId,
      }), primaryResearcher);
      expect(events.map((event) => event.type)).toEqual(["RUN_ERROR"]);
      const productRows = await owner.query<{ runs: string; sessions: string }>(`
        SELECT
          (SELECT count(*) FROM agent.chat_session WHERE id = $1::uuid) AS sessions,
          (SELECT count(*) FROM agent.agent_run WHERE thread_id = $1::uuid) AS runs
      `, [threadId]);
      expect(productRows.rows).toEqual([{ runs: "0", sessions: "0" }]);
    } finally {
      await runtime.close();
    }
  });

  it("does not mutate an existing running Run when its request fingerprint conflicts", async () => {
    const runtime = await createResearchRuntime(settings);
    try {
      const threadId = randomUUID();
      const runId = randomUUID();
      const original = runInput({
        messageId: randomUUID(),
        runId,
        threadId,
      });
      await owner.query(`
        INSERT INTO agent.chat_session (
          id, researcher_id, selected_model_key, selected_reasoning_effort
        ) VALUES ($1, $2, 'scripted-research', 'medium')
      `, [threadId, primaryResearcher.researcher_id]);
      await owner.query(`
        INSERT INTO agent."mastra_threads" (
          id, "resourceId", title, metadata, "createdAt", "updatedAt"
        ) VALUES ($1, $2, 'New chat', NULL, pg_catalog.now(), pg_catalog.now())
      `, [threadId, primaryResearcher.researcher_id]);
      await owner.query(`
        INSERT INTO agent.agent_run (
          id, thread_id, request_fingerprint, model_key, provider_model_id,
          reasoning_effort, agent_build_revision, status
        ) VALUES (
          $2, $1, $3, 'scripted-research', 'scripted-v1',
          'medium', 'integration-build', 'running'
        )
      `, [
        threadId,
        runId,
        chatRunFingerprint(original),
      ]);

      const conflicting = runInput({
        content: "A conflicting payload for the existing Run.",
        messageId: randomUUID(),
        runId,
        threadId,
      });
      const events = await run(runtime, conflicting, primaryResearcher);
      expect(events.map((event) => event.type)).toEqual(["RUN_ERROR"]);
      const persisted = await owner.query<{
        completed_at: Date | null;
        status: string;
        terminal_error_code: string | null;
      }>(`
        SELECT status, terminal_error_code, completed_at
        FROM agent.agent_run
        WHERE id = $1
      `, [runId]);
      expect(persisted.rows).toEqual([{
        completed_at: null,
        status: "running",
        terminal_error_code: null,
      }]);
    } finally {
      await runtime.close();
    }
  });

  it("rejects oversized text before persistence and redacts model failures", async () => {
    const runtime = await createResearchRuntime(settings);
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => undefined);
    try {
      const oversizedThread = randomUUID();
      const oversized = await runtime.handle(runRequest(runInput({
        content: `${"a".repeat(16 * 1024 - 2)}低`,
        messageId: randomUUID(),
        runId: randomUUID(),
        threadId: oversizedThread,
      })), primaryResearcher);
      expect(oversized.status).toBe(413);
      await expect(oversized.json()).resolves.toEqual({ code: "CHAT_MESSAGE_TOO_LARGE" });
      const absent = await owner.query<{ count: string }>(
        "SELECT count(*)::text FROM agent.chat_session WHERE id = $1",
        [oversizedThread],
      );
      expect(absent.rows).toEqual([{ count: "0" }]);

      const failureRunId = randomUUID();
      const events = await run(runtime, runInput({
        messageId: randomUUID(),
        modelKey: "scripted-failure",
        runId: failureRunId,
        threadId: randomUUID(),
      }), primaryResearcher);
      expect(events.map((event) => event.type)).toEqual([
        "RUN_STARTED",
        "RUN_ERROR",
      ]);
      expect(JSON.stringify(events)).not.toContain(
        "SCRIPTED_MODEL_FAILURE_INTERNAL_DETAIL",
      );
      expect(JSON.stringify(consoleError.mock.calls)).not.toContain(
        "SCRIPTED_MODEL_FAILURE_INTERNAL_DETAIL",
      );
      expect(events.at(-1)).toMatchObject({
        code: "AGENT_RUN_FAILED",
        message: "The Research Agent could not complete this run.",
      });
      const failed = await owner.query<{
        status: string;
        terminal_error_code: string;
        token_usage: Record<string, unknown>;
      }>(`
        SELECT status, terminal_error_code, token_usage
        FROM agent.agent_run
        WHERE id = $1
      `, [failureRunId]);
      expect(failed.rows).toEqual([{
        status: "failed",
        terminal_error_code: "AGENT_RUN_FAILED",
        token_usage: { reported: false },
      }]);
    } finally {
      consoleError.mockRestore();
      await runtime.close();
    }
  });
});

function researcher(id: string): VerifiedResearcher {
  return {
    active: true,
    display_label: `Researcher ${id.slice(-3)}`,
    email: `${id.slice(-3)}@example.test`,
    researcher_id: id,
  };
}

function runInput(options: Readonly<{
  content?: string;
  messageId: string;
  messages?: Message[];
  modelKey?: string;
  reasoningEffort?: "medium" | "none";
  runId: string;
  threadId: string;
}>): RunAgentInput {
  return {
    threadId: options.threadId,
    runId: options.runId,
    messages: options.messages ?? [{
      content: options.content ?? "Build a low volatility Alpha.",
      id: options.messageId,
      role: "user",
    }],
    state: {},
    tools: [],
    context: [],
    forwardedProps: {
      thesistrace: {
        modelKey: options.modelKey ?? "scripted-research",
        reasoningEffort: options.reasoningEffort ?? "medium",
      },
    },
  };
}

function runRequest(input: Record<string, unknown>): Request {
  return new Request(
    "http://agent.test/api/agent/copilotkit/agent/research/run",
    {
      body: JSON.stringify(input),
      headers: { "content-type": "application/json" },
      method: "POST",
    },
  );
}

function connectRequest(threadId: string): Request {
  return new Request(
    "http://agent.test/api/agent/copilotkit/agent/research/connect",
    {
      body: JSON.stringify({
        threadId,
        runId: randomUUID(),
        messages: [],
        state: {},
        tools: [],
        context: [],
        forwardedProps: {},
      }),
      headers: { "content-type": "application/json" },
      method: "POST",
    },
  );
}

async function run(
  runtime: ResearchRuntime,
  input: RunAgentInput,
  verifiedResearcher: VerifiedResearcher,
): Promise<AGUIEvent[]> {
  const response = await runtime.handle(runRequest(input), verifiedResearcher);
  expect(response.status).toBe(200);
  return sseEvents(await response.text());
}

async function connect(
  runtime: ResearchRuntime,
  threadId: string,
  verifiedResearcher: VerifiedResearcher,
): Promise<AGUIEvent[]> {
  const response = await runtime.handle(connectRequest(threadId), verifiedResearcher);
  expect(response.status).toBe(200);
  return sseEvents(await response.text());
}

function sseEvents(body: string): AGUIEvent[] {
  return body.split("\n\n").flatMap((frame) => {
    if (!frame.startsWith("data: ")) return [];
    return [JSON.parse(frame.slice(6)) as AGUIEvent];
  });
}

function snapshotMessages(events: readonly AGUIEvent[]): Message[] {
  const snapshot = events.find((event) => event.type === "MESSAGES_SNAPSHOT");
  if (snapshot === undefined) {
    throw new Error("expected message snapshot");
  }
  return [...snapshot.messages];
}

function roleDatabaseUrl(base: string, username: string, password: string): string {
  const url = new URL(base);
  url.username = username;
  url.password = password;
  return url.toString();
}
