import { randomUUID } from "node:crypto";

import type { AGUIEvent, Message, RunAgentInput } from "@ag-ui/core";
import { createTool } from "@mastra/core/tools";
import {
  getMcpCallToolContent,
  MCP_CALL_TOOL_CONTENT,
  MCP_CALL_TOOL_META,
} from "@mastra/mcp";
import { Pool, type PoolClient } from "pg";
import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { z } from "zod";

import { BATCH_ID, BATCH_TOOL_NAMES, CHILD_IDS, batchFixtureOutput } from "../test-fixtures/batch-research.js";
import { DAILY_TRACK_TOOL_NAMES, ORIGIN_RUN_ID, TRACK_ID, dailyTrackFixtureOutput } from "../test-fixtures/daily-track.js";

import {
  RESEARCH_A2UI_ACTIVITY_TYPE,
  RESEARCH_A2UI_CATALOG_ID,
  RESEARCH_A2UI_PROTOCOL_VERSION,
  safeResearchA2UIErrorContent,
} from "../../contracts/research-a2ui.mjs";
import {
  canonicalSubmittedBrowserMessages,
  SAFE_TOOL_COMPLETED,
  SAFE_TOOL_FAILED,
} from "./browser-message-safety.js";
import { parseSafeToolResult } from "./safe-tool-result.js";
import type { AgentSettings } from "./config.js";
import { chatRunFingerprint, readValidatedChatRun } from "./chat-request.js";
import { createMcpRunFactory, type McpRun } from "./mcp-run.js";
import { readModelRegistry } from "./model-registry.js";
import { createResearchRuntime, type ResearchRuntime } from "./research-runtime.js";
import { initializeAgentSchema } from "./schema-initialize.js";
import {
  SCRIPTED_FACTOR_IDEA_PROMPT,
  SCRIPTED_RESUME_RESEARCH_PROMPT,
  SCRIPTED_DISCOVERY_PROMPT,
  SCRIPTED_RELOAD_DAILY_TRACK_PROMPT,
  SCRIPTED_FACTOR_BATCH_PROMPT,
  SCRIPTED_STRATEGY_SWEEP_PROMPT,
  SCRIPTED_INVALID_A2UI_PROMPT,
  SCRIPTED_INVALID_A2UI_TOP_LEVEL_PROMPT,
  SCRIPTED_INVALID_A2UI_DATA_PROMPT,
  SCRIPTED_TOOL_PROMPT,
} from "./scripted-language-model.js";
import {
  ResearchSessionRepository,
  SessionActiveRunError,
  SessionNotFoundError,
  SessionVersionConflictError,
  TranscriptConflictError,
  type RenamedSession,
} from "./session-repository.js";
import {
  SessionInputError,
  UNTITLED_SESSION_TITLE,
  decodeSessionCursor,
} from "./session-management.js";
import { parseGeneratedSessionTitle } from "./session-title.js";
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
const agentStore = new Pool({ connectionString: runtimeDatabaseUrl, max: 2 });
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
  mcpClockSkewSeconds: 30,
  mcpInternalUrl: "http://core.invalid/mcp",
  modelRegistry,
  port: 8400,
  publicOrigin: "http://127.0.0.1:4317",
  runMaxWallSeconds: 300,
};

const createIntegrationRuntime = () => createResearchRuntime(settings, {
  mcpRunFactory: async () => ({
    close: async () => undefined,
    hasFatalToolFailure: () => false,
    toolFailure: () => undefined,
    tools: {},
  }),
});

describe.sequential("durable Research Agent runtime", () => {
  beforeAll(async () => {
    await owner.query("DROP SCHEMA IF EXISTS agent CASCADE");
    await owner.query("DROP SCHEMA IF EXISTS core CASCADE");
    await owner.query("CREATE SCHEMA core");
    await owner.query("CREATE TABLE core.research_canary (id integer PRIMARY KEY)");
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
        agent."mastra_workflow_snapshot",
        core.research_canary
      CASCADE
    `);
  });

  afterAll(async () => {
    await agentStore.end();
    await owner.query("DROP SCHEMA IF EXISTS agent CASCADE");
    await owner.query("DROP SCHEMA IF EXISTS core CASCADE");
    await owner.end();
  });

  it("creates once, captures metadata, replays duplicates, and survives a host restart", async () => {
    const threadId = randomUUID();
    const runId = randomUUID();
    const messageId = randomUUID();
    const input = runInput({ messageId, runId, threadId });
    let runtime = await createIntegrationRuntime();
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

    runtime = await createIntegrationRuntime();
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

  it("rejects an overlapping Thread Run explicitly while another Thread runs independently", async () => {
    const threadId = fixedUuid(9001);
    const runId = fixedUuid(9002);
    const secondThreadId = fixedUuid(9011);
    const secondRunId = fixedUuid(9012);
    const barrier = toolBarrier();
    const toolRuns: string[] = [];
    const runtime = await createResearchRuntime(settings, {
      mcpRunFactory: async (_headers, acceptedRunId) => ({
        close: async () => undefined,
        hasFatalToolFailure: () => false,
        toolFailure: () => undefined,
        tools: {
          get_research_context: createTool({
            description: "Read the current research context.",
            execute: async () => {
              toolRuns.push(acceptedRunId);
              await barrier.promise;
              return { available: true };
            },
            id: "get_research_context",
            inputSchema: z.object({}).strict(),
          }),
        },
      }),
    });
    const first = run(runtime, runInput({
      content: SCRIPTED_TOOL_PROMPT,
      messageId: fixedUuid(9003),
      runId,
      threadId,
    }), primaryResearcher);
    try {
      await vi.waitFor(() => expect(toolRuns).toEqual([runId]));
      const attached = connect(runtime, threadId, primaryResearcher);
      await expect(runtime.deleteSession(threadId, primaryResearcher))
        .rejects.toBeInstanceOf(SessionActiveRunError);

      const overlap = await run(runtime, runInput({
        content: SCRIPTED_TOOL_PROMPT,
        messageId: fixedUuid(9004),
        runId: fixedUuid(9005),
        sessionMode: "existing",
        threadId,
      }), primaryResearcher);
      expect(overlap).toMatchObject([{ type: "RUN_ERROR", code: "AGENT_RUN_CONFLICT" }]);
      expect(overlap).toHaveLength(1);

      const independent = run(runtime, runInput({
        content: SCRIPTED_TOOL_PROMPT,
        messageId: fixedUuid(9013),
        runId: secondRunId,
        threadId: secondThreadId,
      }), primaryResearcher);
      await vi.waitFor(() => expect(toolRuns).toEqual([runId, secondRunId]));
      const active = await owner.query<{ id: string; status: string }>(`
        SELECT id::text, status FROM agent.agent_run
        WHERE thread_id = ANY($1::uuid[]) ORDER BY id
      `, [[threadId, secondThreadId]]);
      expect(active.rows).toEqual([
        { id: runId, status: "running" },
        { id: secondRunId, status: "running" },
      ]);
      for (const target of [threadId, fixedUuid(9099)]) {
        const foreign = await runtime.handle(connectRequest(target), foreignResearcher);
        expect(foreign.status).toBe(404);
        await expect(foreign.json()).resolves.toEqual({ code: "CHAT_SESSION_NOT_FOUND" });
        await expect(runtime.deleteSession(target, foreignResearcher))
          .rejects.toBeInstanceOf(SessionNotFoundError);
        const foreignRun = await runtime.handle(runRequest(runInput({
          messageId: fixedUuid(9097), runId: fixedUuid(9098), sessionMode: "existing", threadId: target,
        })), foreignResearcher);
        expect(foreignRun.status).toBe(404);
        await expect(foreignRun.json()).resolves.toEqual({ code: "CHAT_SESSION_NOT_FOUND" });
      }

      barrier.resolve();
      const [firstEvents, attachedEvents, independentEvents] = await Promise.all([
        first, attached, independent,
      ]);
      for (const events of [firstEvents, attachedEvents]) {
        expect(events[0]).toMatchObject({ type: "RUN_STARTED", threadId, runId });
        expect(events.at(-1)).toMatchObject({ type: "RUN_FINISHED", threadId, runId });
      }
      expect(independentEvents.at(-1)).toMatchObject({ runId: secondRunId });
      const persisted = snapshotMessages(await connect(runtime, threadId, primaryResearcher));
      expect(persisted.filter((message) => message.role === "user").map((message) => message.id))
        .toEqual([fixedUuid(9003)]);
      expect(persisted.filter((message) => message.role === "tool")).toHaveLength(1);
      await expect(runtime.session(threadId, primaryResearcher))
        .resolves.toMatchObject({ activeRun: false });
    } finally {
      barrier.resolve();
      await first;
      await runtime.close();
    }
  });

  it("does not expose framework Stop, inspector, memory, or unscoped Thread endpoints", async () => {
    const runtime = await createIntegrationRuntime();
    try {
      for (const [method, path] of [
        ["POST", `/agent/research/stop/${fixedUuid(9201)}`],
        ["POST", "/agent/research/stop"],
        ["POST", "/agent/research/resume"],
        ["GET", "/threads"],
        ["GET", `/threads/${fixedUuid(9201)}/messages`],
        ["GET", `/threads/${fixedUuid(9201)}/events`],
        ["GET", "/inspector/metadata"],
        ["GET", "/memories"],
        ["GET", "/cpk-debug/events"],
        ["POST", "/agent/research/connect?threadId=ignored"],
      ]) {
        const response = await runtime.handle(new Request(
          `http://agent.test/api/agent/copilotkit${path}`,
          { method },
        ), primaryResearcher);
        expect(response.status, path).toBe(404);
        await expect(response.json()).resolves.toEqual({ code: "CHAT_SESSION_NOT_FOUND" });
      }
    } finally {
      await runtime.close();
    }
  });

  it("fails an unfinished invocation on shutdown and replays completed Tool outcomes without resubmission", async () => {
    const warnings = vi.spyOn(console, "warn");
    const threadId = fixedUuid(9301);
    const runId = fixedUuid(9302);
    const coreRunId = "run_00000000000000009301";
    const calls: Array<Readonly<{ input: Record<string, unknown>; name: string }>> = [];
    const barrier = toolBarrier();
    let detailWaiting = false;
    let runtime = await createResearchRuntime(settings, {
      mcpRunFactory: async () => ({
        close: async () => { barrier.resolve(); },
        hasFatalToolFailure: () => false,
        toolFailure: () => undefined,
        tools: researchLoopTools(coreRunId, calls, async () => {
          detailWaiting = true;
          await barrier.promise;
        }),
      }),
    });
    const first = run(runtime, runInput({
      content: SCRIPTED_FACTOR_IDEA_PROMPT,
      messageId: fixedUuid(9303),
      runId,
      threadId,
    }), primaryResearcher);
    try {
      await vi.waitFor(() => expect(detailWaiting).toBe(true), { timeout: 3_000 });
      const repository = new ResearchSessionRepository(agentStore);
      const before = await repository.connectionSnapshot(threadId, primaryResearcher.researcher_id);
      expect(before.latestRun).toMatchObject({ id: runId, status: "running" });
      expect(before.messages.some((message) => message.role === "tool"
        && parseSafeToolResult(message.content)?.resource?.id === coreRunId)).toBe(true);

      let closed = false;
      const closing = runtime.close().then(() => { closed = true; });
      await vi.waitFor(() => expect(closed).toBe(true), { timeout: 3_000 });
      await closing;
      const interrupted = await first;
      expect(interrupted.filter((event) => event.type === "RUN_ERROR")).toHaveLength(1);
      expect(interrupted.some((event) => event.type === "RUN_FINISHED")).toBe(false);

      runtime = await createResearchRuntime(settings, {
        mcpRunFactory: async () => ({
          close: async () => undefined,
          hasFatalToolFailure: () => false,
          toolFailure: () => undefined,
          tools: researchLoopTools(coreRunId, calls),
        }),
      });
      const replay = await connect(runtime, threadId, primaryResearcher);
      expect(replay[0]).toMatchObject({ type: "RUN_STARTED", threadId, runId });
      expect(replay.at(-1)).toMatchObject({ type: "RUN_ERROR" });
      const retained = snapshotMessages(replay);
      expect(retained.filter((message) => message.role === "user").map((message) => message.id))
        .toEqual([fixedUuid(9303)]);
      expect(retained.some((message) => message.role === "tool"
        && parseSafeToolResult(message.content)?.resource?.id === coreRunId)).toBe(true);

      const resumed = await run(runtime, runInput({
        messageId: fixedUuid(9304),
        messages: [...retained.filter((message) => message.role !== "activity"), {
          content: SCRIPTED_RESUME_RESEARCH_PROMPT, id: fixedUuid(9304), role: "user",
        }],
        runId: fixedUuid(9305), threadId,
      }), primaryResearcher);
      expect(resumed.at(-1)).toMatchObject({ type: "RUN_FINISHED", runId: fixedUuid(9305) });
      expect(calls.filter((call) => call.name === "submit_research_run")).toHaveLength(1);
      const statuses = await owner.query<{ id: string; status: string }>(`
        SELECT id::text, status FROM agent.agent_run WHERE thread_id = $1 ORDER BY id
      `, [threadId]);
      expect(statuses.rows).toEqual([
        { id: runId, status: "failed" }, { id: fixedUuid(9305), status: "completed" },
      ]);
      expect(warnings.mock.calls.flat().map(String).join("\n"))
        .not.toContain("Cannot use a pool after calling end");
    } finally {
      barrier.resolve();
      await first;
      await runtime.close();
      warnings.mockRestore();
    }
  }, 15_000);

  it("orders durable history by exact UTC instants on a non-UTC host", async () => {
    expect(new Date("2026-08-30T00:00:00.000Z").getTimezoneOffset()).toBe(-540);
    const threadId = randomUUID();
    const userMessageId = randomUUID();
    const assistantMessageId = randomUUID();
    await owner.query(`
      INSERT INTO agent.chat_session (
        id, researcher_id, selected_model_key, selected_reasoning_effort
      ) VALUES ($1, $2, 'scripted-research', 'medium')
    `, [threadId, primaryResearcher.researcher_id]);
    await owner.query(`
      INSERT INTO agent."mastra_threads" (
        id, "resourceId", title, "createdAt", "updatedAt",
        "createdAtZ", "updatedAtZ"
      ) VALUES (
        $1, $2, 'UTC ordering',
        '2026-08-30 09:00:00', '2026-08-30 09:00:01',
        '2026-08-30T00:00:00.000Z', '2026-08-30T00:00:01.000Z'
      )
    `, [threadId, primaryResearcher.researcher_id]);
    await owner.query(`
      INSERT INTO agent."mastra_messages" (
        id, thread_id, content, role, type, "createdAt", "resourceId", "createdAtZ"
      ) VALUES
        ($1, $3, $5, 'user', 'v2', '2099-01-01 00:00:00', $4,
         '2026-08-30T00:00:00.123Z'),
        ($2, $3, $6, 'assistant', 'v2', '2000-01-01 00:00:00', $4,
         '2026-08-30T00:00:00.456Z')
    `, [
      userMessageId,
      assistantMessageId,
      threadId,
      primaryResearcher.researcher_id,
      durableTextContent("First by instant.", 1_788_048_000_123),
      durableTextContent("Second by instant.", 1_788_048_000_456),
    ]);

    const instants = await owner.query<{ created_at: Date; id: string }>(`
      SELECT id, "createdAtZ" AS created_at
      FROM agent."mastra_messages"
      WHERE thread_id = $1
      ORDER BY "createdAtZ", id
    `, [threadId]);
    expect(instants.rows.map((row) => ({
      id: row.id,
      instant: row.created_at.toISOString(),
    }))).toEqual([
      { id: userMessageId, instant: "2026-08-30T00:00:00.123Z" },
      { id: assistantMessageId, instant: "2026-08-30T00:00:00.456Z" },
    ]);

    const repository = new ResearchSessionRepository(owner);
    await expect(repository.durableMessages(
      threadId,
      primaryResearcher.researcher_id,
    )).resolves.toEqual([
      { content: "First by instant.", id: userMessageId, role: "user" },
      { content: "Second by instant.", id: assistantMessageId, role: "assistant" },
    ]);
  });

  it("paginates owner-scoped session history with an equal-time stable ID tie-break", async () => {
    const activityAt = new Date("2026-08-30T06:00:00.000Z");
    const sessionIds = Array.from({ length: 32 }, (_, index) => (
      `00000000-0000-4000-8000-${(index + 1).toString(16).padStart(12, "0")}`
    ));
    for (const [index, id] of sessionIds.entries()) {
      await seedSession({
        activityAt,
        id,
        researcherId: primaryResearcher.researcher_id,
        title: `Session ${index + 1}`,
      });
    }
    const foreignId = "00000000-0000-4000-8000-0000000000ff";
    await seedSession({
      activityAt: new Date("2026-08-30T07:00:00.000Z"),
      id: foreignId,
      researcherId: foreignResearcher.researcher_id,
      title: "Foreign Session",
    });

    const repository = new ResearchSessionRepository(agentStore);
    const first = await repository.listSessions(primaryResearcher.researcher_id);
    expect(first.sessions).toHaveLength(30);
    expect(first.sessions.map((session) => session.id)).toEqual(
      [...sessionIds].reverse().slice(0, 30),
    );
    expect(first.sessions.every((session) => (
      session.activityAt === "2026-08-30T06:00:00.000000Z"
    )))
      .toBe(true);
    expect(first.sessions.some((session) => session.id === foreignId)).toBe(false);
    expect(first.nextCursor).not.toBeNull();
    expect(decodeSessionCursor(first.nextCursor ?? "")).toEqual({
      activityAt: "2026-08-30T06:00:00.000000Z",
      id: sessionIds[2],
    });

    const second = await new ResearchSessionRepository(agentStore).listSessions(
      primaryResearcher.researcher_id,
      decodeSessionCursor(first.nextCursor ?? ""),
    );
    expect(second.sessions.map((session) => session.id)).toEqual([
      sessionIds[1],
      sessionIds[0],
    ]);
    expect(second.nextCursor).toBeNull();
    expect(new Set([...first.sessions, ...second.sessions].map((session) => session.id)).size)
      .toBe(32);

    for (const [index, id] of sessionIds.entries()) {
      await owner.query(`
        UPDATE agent.chat_session
        SET updated_at = $2::timestamp with time zone
        WHERE id = $1::uuid
      `, [
        id,
        `2026-08-30T06:00:00.${(index + 1).toString().padStart(6, "0")}Z`,
      ]);
    }
    const microsecondFirst = await repository.listSessions(primaryResearcher.researcher_id);
    expect(microsecondFirst.sessions.map((session) => session.id)).toEqual(
      [...sessionIds].reverse().slice(0, 30),
    );
    expect(decodeSessionCursor(microsecondFirst.nextCursor ?? "")).toEqual({
      activityAt: "2026-08-30T06:00:00.000003Z",
      id: sessionIds[2],
    });
    const microsecondSecond = await repository.listSessions(
      primaryResearcher.researcher_id,
      decodeSessionCursor(microsecondFirst.nextCursor ?? ""),
    );
    expect(microsecondSecond.sessions.map((session) => session.id)).toEqual([
      sessionIds[1],
      sessionIds[0],
    ]);

    const foreign = await repository.listSessions(foreignResearcher.researcher_id);
    expect(foreign.sessions.map((session) => session.id)).toEqual([foreignId]);
  });

  it("fails interrupted host Runs at startup so history and deletion cannot stay blocked", async () => {
    const threadId = fixedUuid(401);
    const runId = fixedUuid(402);
    await seedSession({
      id: threadId,
      researcherId: primaryResearcher.researcher_id,
      title: "Interrupted research",
    });
    await owner.query(`
      INSERT INTO agent.agent_run (
        id, thread_id, request_fingerprint, model_key, provider_model_id,
        reasoning_effort, agent_build_revision, status
      ) VALUES (
        $1, $2, decode(repeat('44', 32), 'hex'), 'scripted-research',
        'scripted-v1', 'medium', 'interrupted-build', 'running'
      )
    `, [runId, threadId]);
    await seedAssistantMessage(threadId, fixedUuid(403));
    await owner.query(`
      INSERT INTO agent.a2ui_message (
        thread_id, id, run_id, owner_message_id, activity_type,
        protocol_version, catalog_id, lifecycle_status, sequence, content
      ) VALUES ($1, $2, $3, $4, $5, $6, $7, 'loading', 1, $8::jsonb)
    `, [
      threadId,
      "a2ui-surface-interrupted-test",
      runId,
      fixedUuid(403),
      RESEARCH_A2UI_ACTIVITY_TYPE,
      RESEARCH_A2UI_PROTOCOL_VERSION,
      RESEARCH_A2UI_CATALOG_ID,
      JSON.stringify({ debugExposure: "hidden", status: "building" }),
    ]);

    const runtime = await createIntegrationRuntime();
    try {
      const interrupted = await owner.query<{
        completed_at: Date;
        status: string;
        terminal_error_code: string;
        token_usage: Record<string, unknown>;
      }>(`
        SELECT status, terminal_error_code, token_usage, completed_at
        FROM agent.agent_run
        WHERE id = $1
      `, [runId]);
      expect(interrupted.rows).toEqual([{
        completed_at: expect.any(Date),
        status: "failed",
        terminal_error_code: "AGENT_RUN_INTERRUPTED",
        token_usage: { reported: false },
      }]);
      const interruptedSurface = await owner.query<{
        content: Record<string, unknown>;
        lifecycle_status: string;
      }>(`
        SELECT lifecycle_status, content
        FROM agent.a2ui_message
        WHERE thread_id = $1::uuid
      `, [threadId]);
      expect(interruptedSurface.rows).toEqual([{
        content: safeResearchA2UIErrorContent(),
        lifecycle_status: "error",
      }]);
      await expect(runtime.session(threadId, primaryResearcher)).resolves.toMatchObject({
        activeRun: false,
      });
      await expect(runtime.deleteSession(threadId, primaryResearcher)).resolves.toBeUndefined();
    } finally {
      await runtime.close();
    }
  });

  it("renames one title optimistically and never lets generated text overwrite it", async () => {
    const threadId = fixedUuid(410);
    await seedSession({
      id: threadId,
      researcherId: primaryResearcher.researcher_id,
      title: UNTITLED_SESSION_TITLE,
    });
    const repository = new ResearchSessionRepository(agentStore);
    const generatedTitleRepository = new ResearchSessionRepository(agentStore);
    const before = (await repository.listSessions(primaryResearcher.researcher_id)).sessions[0];
    if (before === undefined) throw new Error("SEEDED_SESSION_MISSING");

    await expect(repository.renameSession(
      threadId,
      primaryResearcher.researcher_id,
      UNTITLED_SESSION_TITLE,
      new Date(before.version),
    )).rejects.toBeInstanceOf(SessionInputError);
    await expect(repository.storeGeneratedTitle(
      threadId,
      primaryResearcher.researcher_id,
      UNTITLED_SESSION_TITLE,
    )).rejects.toBeInstanceOf(SessionInputError);
    await expect(repository.session(threadId, primaryResearcher.researcher_id))
      .resolves.toMatchObject({ title: UNTITLED_SESSION_TITLE, version: before.version });

    const blocker = await holdSessionMutationLock(threadId);
    const renamePromise = repository.renameSession(
        threadId,
        primaryResearcher.researcher_id,
        "  Stable   Quality   Research  ",
        new Date(before.version),
      );
    const generatedTitlePromise = generatedTitleRepository.storeGeneratedTitle(
      threadId,
      primaryResearcher.researcher_id,
      "Concurrent generated title",
    );
    const concurrent = Promise.allSettled([renamePromise, generatedTitlePromise]);
    try {
      await waitForAdvisoryLockWaiters(2);
    } finally {
      await releaseSessionMutationLock(blocker);
    }
    const [renameOutcome, generatedTitleOutcome] = await concurrent;
    if (renameOutcome === undefined || generatedTitleOutcome === undefined) {
      throw new Error("SESSION_TITLE_RACE_RESULTS_MISSING");
    }

    let renamed: RenamedSession;
    if (renameOutcome.status === "fulfilled") {
      renamed = renameOutcome.value;
      expect(generatedTitleOutcome).toMatchObject({ status: "fulfilled", value: false });
    } else {
      expect(renameOutcome.reason).toBeInstanceOf(SessionVersionConflictError);
      expect(generatedTitleOutcome).toMatchObject({ status: "fulfilled", value: true });
      const generated = await repository.session(
        threadId,
        primaryResearcher.researcher_id,
      );
      renamed = await repository.renameSession(
        threadId,
        primaryResearcher.researcher_id,
        "Stable Quality Research",
        new Date(generated.version),
      );
    }
    expect(renamed).toMatchObject({
      id: threadId,
      title: "Stable Quality Research",
    });
    expect(renamed.version).not.toBe(before.version);
    await expect(repository.renameSession(
      threadId,
      primaryResearcher.researcher_id,
      "Stale rename",
      new Date(before.version),
    )).rejects.toBeInstanceOf(SessionVersionConflictError);
    await expect(generatedTitleRepository.storeGeneratedTitle(
      threadId,
      primaryResearcher.researcher_id,
      "Late generated title",
    )).resolves.toBe(false);
    await expect(repository.renameSession(
      threadId,
      foreignResearcher.researcher_id,
      "Foreign rename",
      new Date(renamed.version),
    )).rejects.toBeInstanceOf(SessionNotFoundError);

    const after = (await repository.listSessions(primaryResearcher.researcher_id)).sessions[0];
    expect(after?.title).toBe("Stable Quality Research");
  });

  it("keeps Run admission versions monotonic and rejects the stale pre-admission rename", async () => {
    const threadId = fixedUuid(411);
    const runId = fixedUuid(412);
    const futureVersion = new Date("2099-01-01T00:00:00.000Z");
    await seedSession({
      activityAt: futureVersion,
      id: threadId,
      researcherId: primaryResearcher.researcher_id,
      title: "Monotonic admission",
    });
    const repository = new ResearchSessionRepository(agentStore);
    const before = await repository.session(threadId, primaryResearcher.researcher_id);
    expect(before.version).toBe(futureVersion.toISOString());

    const validatedRun = await readValidatedChatRun(runRequest(runInput({
      messageId: fixedUuid(413),
      runId,
      sessionMode: "existing",
      threadId,
    })), modelRegistry);
    await expect(repository.prepareRun({
      agentBuildRevision: "monotonic-version-build",
      providerModelId: "scripted-v1",
      researcherId: primaryResearcher.researcher_id,
      run: validatedRun,
    })).resolves.toMatchObject({ kind: "new", status: "running" });

    const afterAdmission = await repository.session(
      threadId,
      primaryResearcher.researcher_id,
    );
    expect(new Date(afterAdmission.version).getTime())
      .toBe(futureVersion.getTime() + 1);
    await repository.markFailed(runId, undefined);
    await expect(repository.renameSession(
      threadId,
      primaryResearcher.researcher_id,
      "Stale rename",
      new Date(before.version),
    )).rejects.toBeInstanceOf(SessionVersionConflictError);
    await expect(repository.renameSession(
      threadId,
      primaryResearcher.researcher_id,
      "Current rename",
      new Date(afterAdmission.version),
    )).resolves.toMatchObject({ title: "Current rename" });
  });

  it("generates a bounded first title and retries after an independent title failure", async () => {
    const successfulThreadId = fixedUuid(420);
    let runtime = await createIntegrationRuntime();
    try {
      await run(runtime, runInput({
        content: "Build a low volatility quality Alpha.",
        messageId: fixedUuid(421),
        runId: fixedUuid(422),
        threadId: successfulThreadId,
      }), primaryResearcher);
    } finally {
      await runtime.close();
    }
    const successfulTitle = await owner.query<{ title: string }>(`
      SELECT title FROM agent."mastra_threads" WHERE id = $1
    `, [successfulThreadId]);
    expect(successfulTitle.rows).toHaveLength(1);
    const firstGeneratedTitle = successfulTitle.rows[0]?.title;
    if (firstGeneratedTitle === undefined) throw new Error("SESSION_TITLE_MISSING");
    expect(firstGeneratedTitle).not.toBe(UNTITLED_SESSION_TITLE);
    expect(parseGeneratedSessionTitle(firstGeneratedTitle)).toBe(firstGeneratedTitle);

    const retryThreadId = fixedUuid(423);
    runtime = await createIntegrationRuntime();
    try {
      const failed = await run(runtime, runInput({
        content: "Test an earnings stability Alpha.",
        messageId: fixedUuid(424),
        modelKey: "scripted-failure",
        runId: fixedUuid(425),
        threadId: retryThreadId,
      }), primaryResearcher);
      expect(failed.map((event) => event.type)).toEqual(["RUN_STARTED", "RUN_ERROR"]);
    } finally {
      await runtime.close();
    }
    const failedTitle = await owner.query<{ title: string }>(`
      SELECT title FROM agent."mastra_threads" WHERE id = $1
    `, [retryThreadId]);
    expect(failedTitle.rows).toEqual([{ title: UNTITLED_SESSION_TITLE }]);

    runtime = await createIntegrationRuntime();
    try {
      const durable = snapshotMessages(await connect(
        runtime,
        retryThreadId,
        primaryResearcher,
      ));
      await run(runtime, runInput({
        content: "Now refine it with balance-sheet quality.",
        messageId: fixedUuid(426),
        messages: [...durable, {
          content: "Now refine it with balance-sheet quality.",
          id: fixedUuid(427),
          role: "user",
        }],
        runId: fixedUuid(428),
        threadId: retryThreadId,
      }), primaryResearcher);
    } finally {
      await runtime.close();
    }
    const retriedTitle = await owner.query<{ title: string }>(`
      SELECT title FROM agent."mastra_threads" WHERE id = $1
    `, [retryThreadId]);
    expect(retriedTitle.rows).toHaveLength(1);
    const retriedGeneratedTitle = retriedTitle.rows[0]?.title;
    if (retriedGeneratedTitle === undefined) throw new Error("SESSION_TITLE_MISSING");
    expect(retriedGeneratedTitle).not.toBe(UNTITLED_SESSION_TITLE);
    expect(parseGeneratedSessionTitle(retriedGeneratedTitle)).toBe(retriedGeneratedTitle);
  });

  it("deletes only owned idle Agent records and preserves researcher-wide memory", async () => {
    const threadId = fixedUuid(430);
    const runId = fixedUuid(431);
    await seedSession({
      id: threadId,
      researcherId: primaryResearcher.researcher_id,
      title: "ResearchRun result explanation",
    });
    await owner.query(`
      INSERT INTO agent.agent_run (
        id, thread_id, request_fingerprint, model_key, provider_model_id,
        reasoning_effort, agent_build_revision, status, token_usage, completed_at
      ) VALUES (
        $1, $2, decode(repeat('00', 32), 'hex'), 'scripted-research',
        'scripted-v1', 'medium', 'integration-build', 'completed',
        '{"reported":false}'::jsonb, pg_catalog.now()
      )
    `, [runId, threadId]);
    await owner.query(`
      INSERT INTO agent."mastra_messages" (
        id, thread_id, content, role, type, "createdAt", "resourceId", "createdAtZ"
      ) VALUES ($1, $2, $3, 'assistant', 'v2', pg_catalog.now(), $4, pg_catalog.now())
    `, [
      fixedUuid(432),
      threadId,
      durableTextContent("Explain ResearchRun core-run-42.", 1_788_048_000_000),
      primaryResearcher.researcher_id,
    ]);
    await owner.query(`
      INSERT INTO agent."mastra_workflow_snapshot" (
        "workflow_name", run_id, "resourceId", snapshot, "createdAt", "updatedAt"
      ) VALUES ('durable-agent', $1, $2, '{"status":"completed"}'::jsonb,
                pg_catalog.now(), pg_catalog.now())
    `, [runId, primaryResearcher.researcher_id]);
    await owner.query(`
      INSERT INTO agent.a2ui_message (
        thread_id, id, run_id, owner_message_id, activity_type,
        protocol_version, catalog_id, lifecycle_status, sequence, content
      ) VALUES ($1, $2, $3, $4, $5, $6, $7, 'error', 1, $8::jsonb)
    `, [
      threadId,
      "a2ui-surface-deletion-test",
      runId,
      fixedUuid(432),
      RESEARCH_A2UI_ACTIVITY_TYPE,
      RESEARCH_A2UI_PROTOCOL_VERSION,
      RESEARCH_A2UI_CATALOG_ID,
      JSON.stringify(safeResearchA2UIErrorContent()),
    ]);
    await owner.query("INSERT INTO core.research_canary (id) VALUES (1)");
    await owner.query(`
      INSERT INTO agent."mastra_resources" (
        id, "workingMemory", metadata, "createdAt", "updatedAt"
      ) VALUES ($1, 'researcher-wide', '{}'::jsonb, pg_catalog.now(), pg_catalog.now())
    `, [primaryResearcher.researcher_id]);

    const repository = new ResearchSessionRepository(agentStore);
    await expect(repository.deleteSession(
      threadId,
      foreignResearcher.researcher_id,
    )).rejects.toBeInstanceOf(SessionNotFoundError);
    const before = await agentRecordCounts(threadId, runId);
    expect(before).toEqual({ a2ui: "1", messages: "1", runs: "1", sessions: "1", snapshots: "1", threads: "1" });

    await repository.deleteSession(threadId, primaryResearcher.researcher_id);
    expect(await agentRecordCounts(threadId, runId)).toEqual({
      a2ui: "0",
      messages: "0",
      runs: "0",
      sessions: "0",
      snapshots: "0",
      threads: "0",
    });
    const resources = await owner.query<{ count: string }>(`
      SELECT count(*)::text AS count
      FROM agent."mastra_resources"
      WHERE id = $1
    `, [primaryResearcher.researcher_id]);
    expect(resources.rows).toEqual([{ count: "1" }]);
    const coreResearch = await owner.query<{ count: string }>(
      "SELECT count(*)::text AS count FROM core.research_canary WHERE id = 1",
    );
    expect(coreResearch.rows).toEqual([{ count: "1" }]);

    const activeThreadId = fixedUuid(433);
    const activeRunId = fixedUuid(434);
    await seedSession({
      id: activeThreadId,
      researcherId: primaryResearcher.researcher_id,
      title: "Active session",
    });
    await owner.query(`
      INSERT INTO agent.agent_run (
        id, thread_id, request_fingerprint, model_key, provider_model_id,
        reasoning_effort, agent_build_revision, status
      ) VALUES (
        $1, $2, decode(repeat('11', 32), 'hex'), 'scripted-research',
        'scripted-v1', 'medium', 'integration-build', 'running'
      )
    `, [activeRunId, activeThreadId]);
    await expect(repository.deleteSession(
      activeThreadId,
      primaryResearcher.researcher_id,
    )).rejects.toBeInstanceOf(SessionActiveRunError);
    expect((await repository.listSessions(primaryResearcher.researcher_id)).sessions[0])
      .toMatchObject({ activeRun: true, id: activeThreadId });
  });

  it("serializes deletion with admission across repository instances and never recreates a deleted Session", async () => {
    const threadId = fixedUuid(440);
    await seedSession({
      id: threadId,
      researcherId: primaryResearcher.researcher_id,
      title: "Admission race",
    });
    const firstRunId = fixedUuid(441);
    const firstInput = runInput({
      messageId: fixedUuid(442),
      runId: firstRunId,
      sessionMode: "existing",
      threadId,
    });
    const firstRun = await readValidatedChatRun(runRequest(firstInput), modelRegistry);
    const firstRepository = new ResearchSessionRepository(agentStore);
    const secondRepository = new ResearchSessionRepository(agentStore);
    const blocker = await holdSessionMutationLock(threadId);
    const admissionPromise = firstRepository.prepareRun({
      agentBuildRevision: "concurrent-build",
      providerModelId: "scripted-v1",
      researcherId: primaryResearcher.researcher_id,
      run: firstRun,
    });
    const deletionPromise = secondRepository.deleteSession(
      threadId,
      primaryResearcher.researcher_id,
    );
    const concurrent = Promise.allSettled([admissionPromise, deletionPromise]);
    try {
      await waitForAdvisoryLockWaiters(2);
    } finally {
      await releaseSessionMutationLock(blocker);
    }
    const [admissionOutcome, deletionOutcome] = await concurrent;
    if (admissionOutcome === undefined || deletionOutcome === undefined) {
      throw new Error("SESSION_ADMISSION_DELETE_RACE_RESULTS_MISSING");
    }

    if (admissionOutcome.status === "fulfilled") {
      expect(admissionOutcome.value).toMatchObject({ kind: "new", status: "running" });
      expect(deletionOutcome.status).toBe("rejected");
      if (deletionOutcome.status === "rejected") {
        expect(deletionOutcome.reason).toBeInstanceOf(SessionActiveRunError);
      }
      await firstRepository.markFailed(firstRunId, undefined);
      await secondRepository.deleteSession(threadId, primaryResearcher.researcher_id);
    } else {
      expect(admissionOutcome.reason).toBeInstanceOf(SessionNotFoundError);
      expect(deletionOutcome.status).toBe("fulfilled");
    }

    const secondInput = runInput({
      messageId: fixedUuid(443),
      runId: fixedUuid(444),
      sessionMode: "existing",
      threadId,
    });
    const secondRun = await readValidatedChatRun(runRequest(secondInput), modelRegistry);
    await expect(firstRepository.prepareRun({
      agentBuildRevision: "concurrent-build",
      providerModelId: "scripted-v1",
      researcherId: primaryResearcher.researcher_id,
      run: secondRun,
    })).rejects.toBeInstanceOf(SessionNotFoundError);
    const recreated = await owner.query<{ count: string }>(`
      SELECT count(*)::text AS count
      FROM agent.chat_session
      WHERE id = $1
    `, [threadId]);
    expect(recreated.rows).toEqual([{ count: "0" }]);
  });

  it("keeps transcript order exact and applies a changed selection only to the next run", async () => {
    const runtime = await createIntegrationRuntime();
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

  it("executes a discovered Tool while exposing only safe Tool lifecycle events", async () => {
    let closes = 0;
    let discoveries = 0;
    let executions = 0;
    const runtime = await createResearchRuntime(settings, {
      mcpRunFactory: async (headers) => {
        discoveries += 1;
        expect(headers.get("cookie")).toBe("test-session-cookie=browser-only");
        return {
          close: async () => {
            closes += 1;
          },
          hasFatalToolFailure: () => false,
          toolFailure: () => undefined,
          tools: {
            get_research_context: createTool({
              description: "Read the current ThesisTrace research context.",
              execute: async () => {
                executions += 1;
                return {
                  dataset: "server-only-sensitive-result",
                  throughSession: "2026-08-28",
                };
              },
              id: "get_research_context",
              inputSchema: z.object({}).strict(),
              outputSchema: z.object({
                dataset: z.string(),
                throughSession: z.string(),
              }).strict(),
            }),
          },
        };
      },
    });
    try {
      const threadId = randomUUID();
      const runId = randomUUID();
      const input = runInput({
        content: SCRIPTED_TOOL_PROMPT,
        messageId: randomUUID(),
        runId,
        threadId,
      });
      const events = await run(runtime, input, primaryResearcher);
      expect(events.map((event) => event.type)).toEqual([
        "RUN_STARTED",
        "TOOL_CALL_START",
        "TOOL_CALL_ARGS",
        "TOOL_CALL_END",
        "TOOL_CALL_RESULT",
        "TEXT_MESSAGE_START",
        "TEXT_MESSAGE_CONTENT",
        "TEXT_MESSAGE_CONTENT",
        "TEXT_MESSAGE_END",
        "RUN_FINISHED",
      ]);
      expect(events.find((event) => event.type === "TOOL_CALL_START")).toMatchObject({
        toolCallName: "get_research_context",
      });
      expect(events.find((event) => event.type === "TOOL_CALL_ARGS")).toMatchObject({
        delta: "{}",
      });
      expect(events.find((event) => event.type === "TOOL_CALL_RESULT")).toMatchObject({
        content: SAFE_TOOL_COMPLETED,
      });
      expect(JSON.stringify(events)).not.toContain("server-only-sensitive-result");
      expect({ closes, discoveries, executions }).toEqual({
        closes: 1,
        discoveries: 1,
        executions: 1,
      });

      const persisted = await owner.query<{ content: string }>(`
        SELECT content
        FROM agent."mastra_messages"
        WHERE thread_id = $1
        ORDER BY "createdAt", id
      `, [threadId]);
      expect(JSON.stringify(persisted.rows)).toContain("server-only-sensitive-result");

      const duplicate = await run(runtime, input, primaryResearcher);
      expect(duplicate.map((event) => event.type)).toEqual([
        "RUN_STARTED",
        "MESSAGES_SNAPSHOT",
        "RUN_FINISHED",
      ]);
      expect(JSON.stringify(duplicate)).not.toContain("server-only-sensitive-result");
      expect({ closes, discoveries, executions }).toEqual({
        closes: 1,
        discoveries: 1,
        executions: 1,
      });

      const followUpMessageId = randomUUID();
      const durableSnapshot = snapshotMessages(duplicate);
      const submittedHistory = splitAssistantTextForCopilotKit(durableSnapshot);
      expect(canonicalSubmittedBrowserMessages(submittedHistory)).toEqual(
        durableSnapshot,
      );
      const followUp = await run(runtime, runInput({
        messageId: followUpMessageId,
        messages: [
          ...submittedHistory,
          {
            content: "Explain the next research step.",
            id: followUpMessageId,
            role: "user",
          },
        ],
        runId: randomUUID(),
        threadId,
      }), primaryResearcher);
      expect(followUp.map((event) => event.type)).toEqual([
        "RUN_STARTED",
        "TEXT_MESSAGE_START",
        "TEXT_MESSAGE_CONTENT",
        "TEXT_MESSAGE_CONTENT",
        "TEXT_MESSAGE_END",
        "RUN_FINISHED",
      ]);
      expect({ closes, discoveries, executions }).toEqual({
        closes: 2,
        discoveries: 2,
        executions: 1,
      });
      const afterFollowUp = await owner.query<{ content: string }>(`
        SELECT content
        FROM agent."mastra_messages"
        WHERE thread_id = $1
        ORDER BY "createdAt", id
      `, [threadId]);
      expect(afterFollowUp.rows.slice(0, persisted.rows.length)).toEqual(persisted.rows);
      expect(JSON.stringify(afterFollowUp.rows)).toContain(
        "server-only-sensitive-result",
      );
      expect(JSON.stringify(afterFollowUp.rows)).not.toContain(SAFE_TOOL_COMPLETED);
    } finally {
      await runtime.close();
    }
  });

  it("keeps reconnect safe before the owner commits and replays equal-time surfaces by sequence", async () => {
    const threadId = fixedUuid(470);
    const runId = fixedUuid(471);
    const ownerMessageId = fixedUuid(472);
    const repository = new ResearchSessionRepository(agentStore);
    let runtime = await createIntegrationRuntime();
    try {
      await prepareA2UIRepositoryRun(repository, threadId, runId, fixedUuid(473));
      let persisted = false;
      const first = {
        content: safeResearchA2UIErrorContent(),
        lifecycle: "error" as const,
        messageId: "a2ui-surface-z-first",
        ownerMessageId,
        runId,
        sequence: 1,
        threadId,
      };
      const pending = repository.persistA2UIActivity(first).then(() => { persisted = true; });
      const beforeOwner = await connect(runtime, threadId, primaryResearcher);
      expect(snapshotMessages(beforeOwner).map((message) => message.role)).toEqual(["user"]);
      expect(a2uiMessages(snapshotMessages(beforeOwner))).toEqual([]);
      expect(persisted).toBe(false);
      expect((await owner.query("SELECT count(*)::int AS count FROM agent.a2ui_message")).rows)
        .toEqual([{ count: 0 }]);

      await seedAssistantMessage(threadId, ownerMessageId);
      await pending;
      await repository.persistA2UIActivity({
        ...first,
        messageId: "a2ui-surface-a-second",
        sequence: 2,
      });
      const largeTable = largeA2UITableContent();
      expect(Buffer.byteLength(JSON.stringify(largeTable))).toBeLessThanOrEqual(65_536);
      await repository.persistA2UIActivity({
        ...first,
        content: largeTable,
        lifecycle: "ready",
        messageId: "a2ui-surface-large-table",
        sequence: 3,
      });
      await owner.query(`
        UPDATE agent.a2ui_message
        SET created_at = '2026-08-30T05:00:00Z', updated_at = '2026-08-30T05:00:00Z'
        WHERE thread_id = $1::uuid
      `, [threadId]);
      const storedBytes = await owner.query<{ bytes: number }>(`
        SELECT octet_length(content::text) AS bytes
        FROM agent.a2ui_message WHERE id = 'a2ui-surface-large-table'
      `);
      expect(storedBytes.rows[0]?.bytes).toBeGreaterThan(65_536);
      const expectedIds = [
        "a2ui-surface-z-first",
        "a2ui-surface-a-second",
        "a2ui-surface-large-table",
      ];
      expect(a2uiMessages(await repository.durableBrowserMessages(
        threadId,
        primaryResearcher.researcher_id,
      )).map((message) => message.id)).toEqual(expectedIds);
      await repository.markCompleted(runId, undefined);
      await runtime.close();
      runtime = await createIntegrationRuntime();
      const replay = a2uiMessages(snapshotMessages(await connect(runtime, threadId, primaryResearcher)));
      expect(replay.map((message) => message.id)).toEqual(expectedIds);
      expect(replay[2]?.content).toEqual(largeTable);
    } finally {
      await runtime.close();
    }
  });

  it("leaves no orphaned A2UI when the host stops before its owner commits", async () => {
    const threadId = fixedUuid(480);
    const runId = fixedUuid(481);
    const repository = new ResearchSessionRepository(agentStore);
    let runtime = await createIntegrationRuntime();
    try {
      await prepareA2UIRepositoryRun(repository, threadId, runId, fixedUuid(483));
      const pending = repository.persistA2UIActivity({
        content: safeResearchA2UIErrorContent(),
        lifecycle: "error",
        messageId: "a2ui-surface-never-owned",
        ownerMessageId: fixedUuid(482),
        runId,
        sequence: 1,
        threadId,
      }).then(() => null, (error: unknown) => error);
      expect(snapshotMessages(await connect(runtime, threadId, primaryResearcher)))
        .toHaveLength(1);
      expect(await repository.failInterruptedRunsAfterHostRestart()).toBe(1);
      expect(await pending).toBeInstanceOf(TranscriptConflictError);
      expect((await owner.query("SELECT count(*)::int AS count FROM agent.a2ui_message")).rows)
        .toEqual([{ count: 0 }]);
      await runtime.close();
      runtime = await createIntegrationRuntime();
      const replay = await connect(runtime, threadId, primaryResearcher);
      expect(snapshotMessages(replay).map((message) => message.role)).toEqual(["user"]);
      expect(replay.at(-1)?.type).toBe("RUN_ERROR");
      await expect(runtime.session(threadId, primaryResearcher)).resolves.toMatchObject({
        activeRun: false,
      });
    } finally {
      await runtime.close();
    }
  });

  it("persists completed A2UI steps while a later MCP call is still running", async () => {
    const threadId = fixedUuid(491);
    const runId = fixedUuid(492);
    const calls: Array<Readonly<{ input: Record<string, unknown>; name: string }>> = [];
    let entered: () => void = () => undefined;
    let release: () => void = () => undefined;
    const enteredRead = new Promise<void>((resolve) => { entered = resolve; });
    const heldRead = new Promise<void>((resolve) => { release = resolve; });
    const runtime = await createResearchRuntime(settings, {
      mcpRunFactory: async () => ({
        close: async () => undefined,
        hasFatalToolFailure: () => false,
        toolFailure: () => undefined,
        tools: researchLoopTools("run_0123456789abcdef0123", calls, async () => {
          entered();
          await heldRead;
        }),
      }),
    });
    const response = await runtime.handle(runRequest(runInput({
      content: SCRIPTED_FACTOR_IDEA_PROMPT,
      messageId: fixedUuid(493),
      runId,
      threadId,
    })), primaryResearcher);
    const terminal = response.text().then(sseEvents);
    try {
      await enteredRead;
      await vi.waitFor(async () => {
        const persisted = await owner.query(`
          SELECT activity.lifecycle_status, message.role
          FROM agent.a2ui_message AS activity
          JOIN agent.mastra_messages AS message ON message.id = activity.owner_message_id
          WHERE activity.thread_id = $1::uuid
          ORDER BY activity.sequence
        `, [threadId]);
        expect(persisted.rows).toEqual([
          { lifecycle_status: "ready", role: "assistant" },
          { lifecycle_status: "ready", role: "assistant" },
        ]);
      }, { interval: 20, timeout: 1_500 });
      const run = await owner.query("SELECT status FROM agent.agent_run WHERE id = $1::uuid", [runId]);
      expect(run.rows).toEqual([{ status: "running" }]);
    } finally {
      release();
      await terminal;
      await runtime.close();
    }
  });

  it.each([
    ["factor_evaluation", SCRIPTED_FACTOR_BATCH_PROMPT],
    ["strategy_sweep", SCRIPTED_STRATEGY_SWEEP_PROMPT],
  ] as const)("persists and replays a model-owned %s comparison without another MCP admission", async (mode, prompt) => {
    const calls: Array<{ input: Record<string, unknown>; name: string }> = [];
    const makeRuntime = () => createResearchRuntime(settings, {
      mcpRunFactory: async () => ({
        close: async () => undefined,
        hasFatalToolFailure: () => false,
        toolFailure: () => undefined,
        tools: Object.fromEntries(BATCH_TOOL_NAMES.map((name) => [name, createTool({
          id: name,
          description: `Discovered Batch fixture capability: ${name}`,
          inputSchema: z.record(z.string(), z.unknown()),
          execute: async (input) => {
            const call = { name, input };
            calls.push(call);
            return batchFixtureOutput(mode, call);
          },
        })])),
      }),
    });
    let runtime = await makeRuntime();
    const threadId = randomUUID();
    const agentRunId = randomUUID();
    const input = runInput({ content: prompt, messageId: randomUUID(), runId: agentRunId, threadId });
    try {
      const events = await run(runtime, input, primaryResearcher);
      expect(events.at(-1)?.type).toBe("RUN_FINISHED");
      const json = JSON.stringify(events);
      expect(json).toContain(BATCH_ID);
      expect(json).toContain("Ordered child ResearchRun results");
      expect(json).not.toContain("private-batch-core-provenance");
      for (const childId of CHILD_IDS) expect(json).toContain(`/research-runs/${childId}`);
      const admission = calls.find((call) => call.name === "submit_research_batch");
      expect(admission?.input).toMatchObject({
        batch_kind: mode,
        request_id: `agent_${agentRunId.replaceAll("-", "")}_batch_v1`,
      });
      expect(admission?.input).not.toHaveProperty("folder_id");
      const surfaces = a2uiMessages(events);
      expect(surfaces).toHaveLength(2);
      const stored = await owner.query<{ content: unknown; lifecycle_status: string }>(`
        SELECT content, lifecycle_status FROM agent.a2ui_message
        WHERE thread_id = $1::uuid ORDER BY sequence
      `, [threadId]);
      expect(stored.rows.map((row) => row.lifecycle_status)).toEqual(["ready", "ready"]);
      expect(stored.rows.map((row) => row.content)).toEqual(surfaces.map((surface) => surface.content));
      const outcomes = await owner.query<{ content: string }>(`
        SELECT content FROM agent.mastra_messages WHERE thread_id = $1
      `, [threadId]);
      expect(JSON.stringify(outcomes.rows)).toContain("private-batch-core-provenance");
      const beforeReplay = [...calls];
      const replay = await run(runtime, input, primaryResearcher);
      expect(a2uiMessages(snapshotMessages(replay)).map((surface) => surface.content)).toEqual(stored.rows.map((row) => row.content));
      expect(calls).toEqual(beforeReplay);
      await runtime.close();
      runtime = await makeRuntime();
      const restarted = await connect(runtime, threadId, primaryResearcher);
      expect(a2uiMessages(snapshotMessages(restarted)).map((surface) => surface.content)).toEqual(stored.rows.map((row) => row.content));
      expect(calls).toEqual(beforeReplay);
    } finally {
      await runtime.close();
    }
  });

  it("persists successive current DailyTrack views while replay and restart leave the original view and Start unchanged", async () => {
    const calls: Array<{ input: Record<string, unknown>; name: string }> = [];
    let session = "2024-01-31";
    const makeRuntime = () => createResearchRuntime(settings, {
      mcpRunFactory: async () => ({
        close: async () => undefined, hasFatalToolFailure: () => false, toolFailure: () => undefined,
        tools: Object.fromEntries(DAILY_TRACK_TOOL_NAMES.map((name) => [name, createTool({
          id: name, description: `Discovered DailyTrack capability: ${name}`,
          inputSchema: z.record(z.string(), z.unknown()),
          execute: async (input) => {
            const call = { name, input };
            calls.push(call);
            return dailyTrackFixtureOutput(call, session);
          },
        })])),
      }),
    });
    let runtime = await makeRuntime();
    const threadId = randomUUID();
    const agentRunId = randomUUID();
    const input = runInput({ content: `Start daily tracking for ${ORIGIN_RUN_ID}.`, messageId: randomUUID(), runId: agentRunId, threadId });
    try {
      const events = await run(runtime, input, primaryResearcher);
      expect(events.at(-1)?.type).toBe("RUN_FINISHED");
      expect(JSON.stringify(events)).toContain(`/daily-tracks/${TRACK_ID}`);
      expect(JSON.stringify(events)).not.toContain("private-daily-track-provenance");
      const initial = a2uiMessages(events);
      expect(initial).toHaveLength(1);
      expect(JSON.stringify(initial)).toContain("2024-01-31");
      const submitted = calls.filter((call) => call.name === "start_daily_track");
      expect(submitted.map((call) => call.input)).toEqual([{
        run_id: ORIGIN_RUN_ID, request_id: `agent_${agentRunId.replaceAll("-", "")}_track_start_v1`,
      }]);
      const beforeReplay = [...calls];
      await run(runtime, input, primaryResearcher);
      await runtime.close();
      runtime = await makeRuntime();
      expect(a2uiMessages(snapshotMessages(await connect(runtime, threadId, primaryResearcher)))).toEqual(initial);
      expect(calls).toEqual(beforeReplay);
      session = "2024-02-01";
      const refreshMessageId = randomUUID();
      const refresh = runInput({
        messageId: refreshMessageId, runId: randomUUID(), threadId,
        messages: [...snapshotMessages(await connect(runtime, threadId, primaryResearcher)).filter((message) => message.role !== "activity"), {
          id: refreshMessageId, role: "user", content: SCRIPTED_RELOAD_DAILY_TRACK_PROMPT,
        }],
      });
      expect((await run(runtime, refresh, primaryResearcher)).at(-1)?.type).toBe("RUN_FINISHED");
      const history = a2uiMessages(snapshotMessages(await connect(runtime, threadId, primaryResearcher)));
      expect(history).toHaveLength(2);
      expect(history[0]).toEqual(initial[0]);
      expect(JSON.stringify(history[1])).toContain("2024-02-01");
      expect(calls.filter((call) => call.name === "start_daily_track")).toEqual(submitted);
      expect(calls.some((call) => call.name === "retry_daily_track" || call.name === "stop_daily_track")).toBe(false);
    } finally {
      await runtime.close();
    }
  });

  it("passes every four-scope capability and subsequent discovery changes through to the native Mastra model", async () => {
    const completeDiscovery = [
      "get_research_context", "get_alpha_catalog", "diagnose_alpha_formula",
      "list_research_runs", "get_research_run", "get_research_run_result", "submit_research_run",
      "list_research_batches", "get_research_batch", "submit_research_batch",
      "list_daily_tracks", "get_daily_track", "get_daily_track_result", "start_daily_track", "retry_daily_track",
    ];
    let discovered = completeDiscovery;
    const runtime = await createResearchRuntime(settings, {
      mcpRunFactory: async () => ({
        close: async () => undefined, hasFatalToolFailure: () => false, toolFailure: () => undefined,
        tools: Object.fromEntries(discovered.map((name) => [name, createTool({
          id: name, description: `Current discovered capability ${name}`,
          inputSchema: z.record(z.string(), z.unknown()),
          execute: async () => { throw new Error("Discovery inspection must not execute a business Tool"); },
        })])),
      }),
    });
    const threadId = randomUUID();
    try {
      let history: Message[] | undefined;
      for (const names of [completeDiscovery, [...completeDiscovery.filter((name) => name !== "retry_daily_track"), "newly_discovered_tracking_capability"]]) {
        discovered = names;
        const messageId = randomUUID();
        const events = await run(runtime, runInput({
          content: SCRIPTED_DISCOVERY_PROMPT, messageId, runId: randomUUID(), threadId,
          ...(history === undefined ? {} : { messages: [...history, { id: messageId, role: "user" as const, content: SCRIPTED_DISCOVERY_PROMPT }] }),
        }), primaryResearcher);
        expect(events.at(-1)?.type).toBe("RUN_FINISHED");
        const reply = events.filter((event) => event.type === "TEXT_MESSAGE_CONTENT").map((event) => event.delta).join("");
        expect(reply).toBe(`Available capabilities: ${[...names, "render_a2ui"].sort().join(", ")}`);
        expect(reply).not.toContain("stop_daily_track");
        expect(reply).not.toContain("cancel_research_run");
        history = snapshotMessages(await connect(runtime, threadId, primaryResearcher));
      }
    } finally {
      await runtime.close();
    }
  });

  it("persists a complete model-owned Factor trajectory and replays only safe Run resources", async () => {
    const coreRunId = "run_0123456789abcdef0123";
    const calls: Array<Readonly<{ input: Record<string, unknown>; name: string }>> = [];
    let runtime = await createResearchRuntime(settings, {
      mcpRunFactory: async () => ({
        close: async () => undefined,
        hasFatalToolFailure: () => false,
        toolFailure: () => undefined,
        tools: researchLoopTools(coreRunId, calls),
      }),
    });
    let runtimeOpen = true;
    let restarted: ResearchRuntime | undefined;
    const threadId = randomUUID();
    const agentRunId = randomUUID();
    const input = runInput({
      content: SCRIPTED_FACTOR_IDEA_PROMPT,
      messageId: randomUUID(),
      runId: agentRunId,
      threadId,
    });
    try {
      const events = await run(runtime, input, primaryResearcher);
      expect(events.filter((event) => event.type === "TOOL_CALL_START").map((event) => (
        event.toolCallName
      ))).toEqual([
        "get_research_context",
        "get_alpha_catalog",
        "diagnose_alpha_formula",
        "submit_research_run",
        "get_research_run",
        "get_research_run",
        "get_research_run_result",
      ]);
      expect(calls.map((call) => call.name)).toEqual([
        "get_research_context",
        "get_alpha_catalog",
        "diagnose_alpha_formula",
        "submit_research_run",
        "get_research_run",
        "get_research_run",
        "get_research_run_result",
      ]);
      const submission = calls.find((call) => call.name === "submit_research_run");
      expect(submission?.input).toMatchObject({
        folder_id: "folder_default",
        formula: "rank(-abs(pct_change(close, 1)))",
        neutralization: "none",
        request_id: `agent_${agentRunId.replaceAll("-", "")}_research_v1`,
        research_kind: "factor_evaluation",
        universe: "top1000",
      });

      const safeResults = events
        .filter((event) => event.type === "TOOL_CALL_RESULT")
        .map((event) => parseSafeToolResult(event.content));
      expect(safeResults).toContainEqual({
        outcome: "completed",
        resource: {
          id: coreRunId,
          kind: "research_run",
          status: "queued",
        },
      });
      expect(safeResults).toContainEqual({
        outcome: "completed",
        resource: {
          id: coreRunId,
          kind: "research_run",
          status: "succeeded",
        },
      });
      const browserJson = JSON.stringify(events);
      expect(browserJson).toContain("rank(-abs(pct_change(close, 1)))");
      expect(browserJson).toContain("0.1200");
      expect(browserJson).toContain("3.40%");
      expect(browserJson).toContain(`/research-runs/${coreRunId}`);
      expect(browserJson).toContain("AlphaProposal");
      expect(browserJson).toContain("ResearchRunStatus");
      expect(browserJson).toContain("ResultMetrics");
      expect(browserJson).toContain("Provenance");
      expect(browserJson).not.toMatch(/generate_a2ui|render_a2ui/);
      expect(browserJson).not.toContain("private-core-provenance");
      const readySurfaceEvents = a2uiMessages(events).filter((message) => (
        isRecord(message.content) && Array.isArray(message.content.a2ui_operations)
      ));
      expect(readySurfaceEvents).toHaveLength(4);
      expect(new Set(readySurfaceEvents.map((message) => message.id)).size).toBe(4);
      expect(JSON.stringify(readySurfaceEvents)).toContain('"phase":"research"');
      expect(JSON.stringify(readySurfaceEvents)).toContain('"status":"running"');

      const durable = await owner.query<{ content: string }>(`
        SELECT content
        FROM agent."mastra_messages"
        WHERE thread_id = $1
        ORDER BY "createdAtZ", id
      `, [threadId]);
      const durableJson = JSON.stringify(durable.rows);
      expect(durableJson).toContain("private-core-provenance");
      expect(durableJson).toContain("rank(-abs(pct_change(close, 1)))");
      expect(durableJson).toContain("0.1200");
      expect(durableJson).toContain(`/research-runs/${coreRunId}`);
      const storedSurfaces = await owner.query<{
        content: Record<string, unknown>;
        id: string;
        lifecycle_status: string;
      }>(`
        SELECT id, lifecycle_status, content
        FROM agent.a2ui_message
        WHERE thread_id = $1::uuid
        ORDER BY sequence
      `, [threadId]);
      expect(storedSurfaces.rows).toHaveLength(4);
      expect(storedSurfaces.rows.every((row) => row.lifecycle_status === "ready")).toBe(true);
      expect(JSON.stringify(storedSurfaces.rows)).not.toContain("private-core-provenance");
      const workflowRows = await owner.query<{ count: string }>(`
        SELECT count(*)::text AS count
        FROM agent."mastra_workflow_snapshot"
      `);
      expect(workflowRows.rows).toEqual([{ count: "0" }]);

      const duplicate = await run(runtime, input, primaryResearcher);
      expect(duplicate.map((event) => event.type)).toEqual([
        "RUN_STARTED",
        "MESSAGES_SNAPSHOT",
        "RUN_FINISHED",
      ]);
      const duplicateJson = JSON.stringify(duplicate);
      expect(duplicateJson).toContain(coreRunId);
      expect(duplicateJson).not.toContain("private-core-provenance");
      expect(a2uiMessages(snapshotMessages(duplicate))).toHaveLength(4);
      expect(calls).toHaveLength(7);

      await runtime.close();
      runtimeOpen = false;
      restarted = await createResearchRuntime(settings, {
        mcpRunFactory: async () => ({
          close: async () => undefined,
          hasFatalToolFailure: () => false,
          toolFailure: () => undefined,
          tools: researchLoopTools(coreRunId, calls),
        }),
      });
      const afterRestart = await connect(restarted, threadId, primaryResearcher);
      const restartedSurfaces = a2uiMessages(snapshotMessages(afterRestart));
      expect(restartedSurfaces.map((message) => message.content)).toEqual(
        storedSurfaces.rows.map((row) => row.content),
      );
      expect(calls).toHaveLength(7);
    } finally {
      if (runtimeOpen) await runtime.close();
      await restarted?.close();
    }
  });

  it.each([
    SCRIPTED_INVALID_A2UI_PROMPT,
    SCRIPTED_INVALID_A2UI_TOP_LEVEL_PROMPT,
    SCRIPTED_INVALID_A2UI_DATA_PROMPT,
  ])("turns a fully rejected A2UI input into only a durable safe error: %s", async (prompt) => {
    const runtime = await createResearchRuntime(settings, {
      mcpRunFactory: async () => ({
        close: async () => undefined,
        hasFatalToolFailure: () => false,
        toolFailure: () => undefined,
        tools: {},
      }),
    });
    const threadId = randomUUID();
    const input = runInput({
      content: prompt,
      messageId: randomUUID(),
      runId: randomUUID(),
      threadId,
    });
    const frameworkLogs = (["debug", "info", "log", "warn", "error"] as const)
      .map((method) => vi.spyOn(console, method).mockImplementation(() => undefined));
    try {
      const events = await run(runtime, input, primaryResearcher);
      expect(events.at(-1)?.type).toBe("RUN_FINISHED");
      const surfaces = a2uiMessages(events);
      expect(surfaces).toHaveLength(1);
      expect(surfaces.at(-1)?.content).toEqual(safeResearchA2UIErrorContent());
      const browserJson = JSON.stringify(events);
      expect(browserJson).toContain("unsafe research surface was rejected");
      expect(browserJson).not.toContain("MALICIOUS_A2UI_SHOULD_NOT_RENDER");
      expect(browserJson).not.toContain("delete_research");
      expect(browserJson).not.toContain("render_a2ui");

      const stored = await owner.query<{
        content: Record<string, unknown>;
        lifecycle_status: string;
      }>(`
        SELECT lifecycle_status, content
        FROM agent.a2ui_message
        WHERE thread_id = $1::uuid
      `, [threadId]);
      expect(stored.rows).toEqual([{
        content: safeResearchA2UIErrorContent(),
        lifecycle_status: "error",
      }]);

      const duplicate = await run(runtime, input, primaryResearcher);
      expect(a2uiMessages(snapshotMessages(duplicate))).toEqual([{
        content: safeResearchA2UIErrorContent(),
        id: surfaces.at(-1)?.id,
      }]);
      expect(JSON.stringify(frameworkLogs.flatMap((log) => log.mock.calls)))
        .not.toContain("MALICIOUS_A2UI_SHOULD_NOT_RENDER");
    } finally {
      await runtime.close();
      for (const log of frameworkLogs) log.mockRestore();
    }
  });

  it("keeps an accepted User message durable when MCP preparation fails", async () => {
    let failNextPreparation = true;
    const runtime = await createResearchRuntime(settings, {
      mcpRunFactory: async () => {
        if (failNextPreparation) {
          failNextPreparation = false;
          throw new Error("private-pre-model-mcp-failure");
        }
        return {
          close: async () => undefined,
          hasFatalToolFailure: () => false,
          toolFailure: () => undefined,
          tools: {
            get_research_context: createTool({
              description: "Read the current ThesisTrace research context.",
              execute: async () => ({ status: "ok" }),
              id: "get_research_context",
              inputSchema: z.object({}).strict(),
            }),
          },
        };
      },
    });
    const threadId = randomUUID();
    const firstInput = runInput({
      content: SCRIPTED_TOOL_PROMPT,
      messageId: randomUUID(),
      runId: randomUUID(),
      threadId,
    });
    try {
      const failed = await run(runtime, firstInput, primaryResearcher);
      expect(failed.map((event) => event.type)).toEqual([
        "RUN_STARTED",
        "RUN_ERROR",
      ]);
      expect(JSON.stringify(failed)).not.toContain("private-pre-model-mcp-failure");

      const persistedAfterFailure = await owner.query<{ content: string }>(`
        SELECT content
        FROM agent."mastra_messages"
        WHERE thread_id = $1
        ORDER BY "createdAt", id
      `, [threadId]);
      expect(persistedAfterFailure.rows).toHaveLength(1);
      expect(persistedAfterFailure.rows[0]?.content).toContain(SCRIPTED_TOOL_PROMPT);

      const replay = await run(runtime, firstInput, primaryResearcher);
      expect(replay.map((event) => event.type)).toEqual([
        "RUN_STARTED",
        "MESSAGES_SNAPSHOT",
        "RUN_ERROR",
      ]);
      expect(snapshotMessages(replay)).toEqual([firstInput.messages[0]]);
      const stateAfterReplay = await owner.query<{ messages: string; runs: string }>(`
        SELECT
          (SELECT count(*) FROM agent."mastra_messages" WHERE thread_id = $1) AS messages,
          (SELECT count(*) FROM agent.agent_run WHERE thread_id = $1::uuid) AS runs
      `, [threadId]);
      expect(stateAfterReplay.rows).toEqual([{ messages: "1", runs: "1" }]);

      const followUpMessageId = randomUUID();
      const followUp = await run(runtime, runInput({
        content: "Continue with the available research context.",
        messageId: followUpMessageId,
        messages: [
          ...snapshotMessages(replay),
          {
            content: "Continue with the available research context.",
            id: followUpMessageId,
            role: "user",
          },
        ],
        runId: randomUUID(),
        threadId,
      }), primaryResearcher);
      expect(followUp.map((event) => event.type)).toContain("TOOL_CALL_START");
      expect(followUp.find((event) => event.type === "TOOL_CALL_START")).toMatchObject({
        toolCallName: "get_research_context",
      });
      expect(followUp.at(-1)?.type).toBe("RUN_FINISHED");
      const outcomes = await owner.query<{
        status: string;
        terminal_error_code: string | null;
      }>(`
        SELECT status, terminal_error_code
        FROM agent.agent_run
        WHERE thread_id = $1::uuid
        ORDER BY status
      `, [threadId]);
      expect(outcomes.rows).toEqual([
        { status: "completed", terminal_error_code: null },
        { status: "failed", terminal_error_code: "AGENT_RUN_FAILED" },
      ]);
    } finally {
      await runtime.close();
    }
  });

  it("turns a rejected MCP transport call into one safe failed Tool and terminal Run", async () => {
    let observedMcpRun: McpRun | undefined;
    const disconnect = vi.fn(async () => undefined);
    const transportFactory = createMcpRunFactory(settings, {
      fetch: async () => Response.json({
        access_token: "integration-mcp-token",
        expires_in: 360,
        token_type: "Bearer",
      }),
      mcpClient: () => ({
        __setLogger: vi.fn(),
        disconnect,
        listToolsetsWithErrors: async () => ({
          errorDetails: {},
          errors: {},
          toolsets: {
            thesistrace: {
              get_research_context: createTool({
                description: "Read the current ThesisTrace research context.",
                execute: async () => {
                  throw new Error("private-disconnect-canary");
                },
                id: "get_research_context",
                inputSchema: z.object({}).strict(),
              }),
            },
          },
        }),
      }),
    });
    const runtime = await createResearchRuntime(settings, {
      mcpRunFactory: async (_headers, runId) => {
        observedMcpRun = await transportFactory(new Headers({
          cookie: "thesistrace.session_token=integration-session",
        }), runId);
        return observedMcpRun;
      },
    });
    const runId = randomUUID();
    const input = runInput({
      content: SCRIPTED_TOOL_PROMPT,
      messageId: randomUUID(),
      runId,
      threadId: randomUUID(),
    });
    try {
      const events = await run(runtime, input, primaryResearcher);

      expect(observedMcpRun?.toolFailure("scripted-tool-call-1")).toBe("transport");
      expect(events.map((event) => event.type)).toEqual([
        "RUN_STARTED",
        "TOOL_CALL_START",
        "TOOL_CALL_ARGS",
        "TOOL_CALL_END",
        "TOOL_CALL_RESULT",
        "RUN_ERROR",
      ]);
      expect(events.find((event) => event.type === "TOOL_CALL_RESULT")).toMatchObject({
        content: SAFE_TOOL_FAILED,
      });
      expect(JSON.stringify(events)).not.toContain("private-disconnect-canary");
      expect(disconnect).toHaveBeenCalledOnce();
      const persisted = await owner.query<{
        status: string;
        terminal_error_code: string;
      }>(`
        SELECT status, terminal_error_code
        FROM agent.agent_run
        WHERE id = $1
      `, [runId]);
      expect(persisted.rows).toEqual([{
        status: "failed",
        terminal_error_code: "AGENT_RUN_FAILED",
      }]);
      const persistedMessages = await owner.query<{ content: string }>(`
        SELECT content
        FROM agent."mastra_messages"
        WHERE thread_id = $1
        ORDER BY "createdAt", id
      `, [input.threadId]);
      expect(JSON.stringify(persistedMessages.rows)).not.toContain(
        "I checked the available ThesisTrace research data",
      );

      const replay = await run(runtime, input, primaryResearcher);
      expect(replay.map((event) => event.type)).toEqual([
        "RUN_STARTED",
        "MESSAGES_SNAPSHOT",
        "RUN_ERROR",
      ]);
      expect(snapshotMessages(replay)).toContainEqual(expect.objectContaining({
        content: SAFE_TOOL_FAILED,
        role: "tool",
      }));
      expect(JSON.stringify(replay)).not.toContain(
        "I checked the available ThesisTrace research data",
      );
      expect(JSON.stringify(replay)).not.toContain("private-disconnect-canary");
      expect(disconnect).toHaveBeenCalledOnce();
    } finally {
      await runtime.close();
    }
  });

  it("keeps a structured Core business rejection model-visible and browser-safe", async () => {
    let observedMcpRun: McpRun | undefined;
    const businessError = {
      code: "TEMPORARILY_UNAVAILABLE",
      context: { tool_name: "get_research_context" },
      message: "Business error model detail",
      retry_after_seconds: 3,
      retryable: true,
      trace_id: "private-business-trace-canary",
    };
    const disconnect = vi.fn(async () => undefined);
    const businessFactory = createMcpRunFactory(settings, {
      fetch: async () => Response.json({
        access_token: "integration-mcp-token",
        expires_in: 360,
        token_type: "Bearer",
      }),
      mcpClient: () => ({
        __setLogger: vi.fn(),
        disconnect,
        listToolsetsWithErrors: async () => ({
          errorDetails: {},
          errors: {},
          toolsets: {
            thesistrace: {
              get_research_context: createTool({
                description: "Read the current ThesisTrace research context.",
                execute: async () => adaptedCoreResult({
                  content: [{
                    text: JSON.stringify(businessError),
                    type: "text",
                  }],
                  isError: true,
                  structuredContent: businessError,
                  _meta: { "thesistrace/tool-outcome": "failed" },
                }),
                id: "get_research_context",
                inputSchema: z.object({}).strict(),
                toModelOutput: (output) => ({
                  type: "text",
                  value: modelTextFromMcpOutput(output),
                }),
              }),
            },
          },
        }),
      }),
    });
    const runtime = await createResearchRuntime(settings, {
      mcpRunFactory: async (_headers, runId) => {
        observedMcpRun = await businessFactory(
          new Headers({ cookie: "thesistrace.session_token=integration-session" }),
          runId,
        );
        return observedMcpRun;
      },
    });
    const threadId = randomUUID();
    const runId = randomUUID();
    const input = runInput({
      content: SCRIPTED_TOOL_PROMPT,
      messageId: randomUUID(),
      runId,
      threadId,
    });
    try {
      const events = await run(runtime, input, primaryResearcher);

      expect(observedMcpRun?.toolFailure("scripted-tool-call-1")).toBe("business");
      expect(events.map((event) => event.type)).toEqual([
        "RUN_STARTED",
        "TOOL_CALL_START",
        "TOOL_CALL_ARGS",
        "TOOL_CALL_END",
        "TOOL_CALL_RESULT",
        "TEXT_MESSAGE_START",
        "TEXT_MESSAGE_CONTENT",
        "TEXT_MESSAGE_CONTENT",
        "TEXT_MESSAGE_END",
        "RUN_FINISHED",
      ]);
      expect(events.find((event) => event.type === "TOOL_CALL_RESULT")).toMatchObject({
        content: SAFE_TOOL_FAILED,
      });
      expect(JSON.stringify(events)).not.toContain(businessError.code);
      expect(JSON.stringify(events)).not.toContain(businessError.trace_id);
      expect(disconnect).toHaveBeenCalledOnce();

      const persisted = await owner.query<{ content: string }>(`
        SELECT content
        FROM agent."mastra_messages"
        WHERE thread_id = $1
        ORDER BY "createdAt", id
      `, [threadId]);
      const durableJson = JSON.stringify(persisted.rows);
      expect(durableJson).toContain(businessError.code);
      expect(durableJson).toContain(businessError.message);
      expect(durableJson).toContain(businessError.trace_id);
      expect(durableJson).toContain("modelOutput");

      const productRun = await owner.query<{ status: string }>(`
        SELECT status FROM agent.agent_run WHERE id = $1
      `, [runId]);
      expect(productRun.rows).toEqual([{ status: "completed" }]);

      const replay = await run(runtime, input, primaryResearcher);
      expect(replay.map((event) => event.type)).toEqual([
        "RUN_STARTED",
        "MESSAGES_SNAPSHOT",
        "RUN_FINISHED",
      ]);
      expect(snapshotMessages(replay)).toContainEqual(expect.objectContaining({
        content: SAFE_TOOL_FAILED,
        role: "tool",
      }));
      expect(JSON.stringify(replay)).not.toContain(businessError.code);
      expect(JSON.stringify(replay)).not.toContain(businessError.trace_id);
      expect(disconnect).toHaveBeenCalledOnce();
    } finally {
      await runtime.close();
    }
  });

  it("rolls back first-session metadata when the paired Mastra Thread cannot be created", async () => {
    const runtime = await createIntegrationRuntime();
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
    const runtime = await createIntegrationRuntime();
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
        ) VALUES ($1, $2, $3, NULL, pg_catalog.now(), pg_catalog.now())
      `, [threadId, primaryResearcher.researcher_id, UNTITLED_SESSION_TITLE]);
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

  it("rejects non-canonical UUIDs at the authenticated runtime boundary", async () => {
    const runtime = await createIntegrationRuntime();
    try {
      const invalidInputs = [
        runInput({
          messageId: "00000000-0000-4000-8000-000000001481",
          runId: "00000000-0000-4000-8000-000000001482",
          threadId: "00000000-0000-0000-0000-000000000000",
        }),
        runInput({
          messageId: "00000000-0000-4000-8000-000000001483",
          runId: "ffffffff-ffff-ffff-ffff-ffffffffffff",
          threadId: "00000000-0000-4000-8000-000000001484",
        }),
      ];
      for (const input of invalidInputs) {
        const response = await runtime.handle(runRequest(input), primaryResearcher);
        expect(response.status).toBe(400);
        await expect(response.json()).resolves.toEqual({ code: "INVALID_CHAT_REQUEST" });
      }

      const nilSession = await owner.query<{ count: string }>(
        "SELECT count(*)::text FROM agent.chat_session WHERE id = $1",
        ["00000000-0000-0000-0000-000000000000"],
      );
      expect(nilSession.rows).toEqual([{ count: "0" }]);
    } finally {
      await runtime.close();
    }
  });

  it("rejects oversized text before persistence and redacts model failures", async () => {
    let closes = 0;
    const runtime = await createResearchRuntime(settings, {
      mcpRunFactory: async () => ({
        close: async () => {
          closes += 1;
        },
        hasFatalToolFailure: () => false,
        toolFailure: () => undefined,
        tools: {},
      }),
    });
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
      expect(closes).toBe(1);
    } finally {
      consoleError.mockRestore();
      await runtime.close();
    }
  });
});

function toolBarrier(): Readonly<{ promise: Promise<void>; resolve: () => void }> {
  let resolve = () => undefined as void;
  const promise = new Promise<void>((release) => { resolve = release; });
  return { promise, resolve };
}

function researchLoopTools(
  coreRunId: string,
  calls: Array<Readonly<{ input: Record<string, unknown>; name: string }>>,
  beforeDetail?: () => Promise<void>,
) {
  const record = (name: string, input: Record<string, unknown>) => {
    calls.push({ input: { ...input }, name });
  };
  return {
    get_research_context: createTool({
      description: "Read current Research Context and authoring constraints.",
      execute: async (input) => {
        record("get_research_context", input);
        return {
          authoring_constraints: {
            holdings_count: { maximum: 100, minimum: 1 },
            neutralizations: ["none", "industry"],
            rebalance_every_sessions: { maximum: 20, minimum: 1 },
            universes: ["top300", "top1000"],
          },
          data_overview: {
            market_coverage: { end: "2024-01-31", start: "2024-01-02" },
          },
          folders: {
            items: [{ id: "folder_default", is_default: true, name: "Research" }],
          },
          private_provenance: "private-core-provenance",
        };
      },
      id: "get_research_context",
      inputSchema: z.object({}).strict(),
    }),
    get_alpha_catalog: createTool({
      description: "Inspect Alpha fields and operators.",
      execute: async (input) => {
        record("get_alpha_catalog", input);
        return {
          builtins: [
            { identifier: "abs" },
            { identifier: "pct_change" },
            { identifier: "rank" },
          ],
          fields: [{ identifier: "close" }],
          unknown_identifiers: [],
        };
      },
      id: "get_alpha_catalog",
      inputSchema: z.object({ identifiers: z.array(z.string()) }).strict(),
    }),
    diagnose_alpha_formula: createTool({
      description: "Diagnose an Alpha Formula.",
      execute: async (input) => {
        record("diagnose_alpha_formula", input);
        return { diagnostics: [], valid: true };
      },
      id: "diagnose_alpha_formula",
      inputSchema: z.object({ source: z.string() }).strict(),
    }),
    submit_research_run: createTool({
      description: "Admit a ResearchRun with a caller-stable request ID.",
      execute: async (input) => {
        record("submit_research_run", input);
        return {
          outcome: "accepted",
          replayed: false,
          run_id: coreRunId,
          status: "queued",
        };
      },
      id: "submit_research_run",
      inputSchema: z.object({
        end_date: z.string(),
        folder_id: z.string(),
        formula: z.string(),
        holdings_count: z.number().int().optional(),
        hypothesis: z.string(),
        name: z.string(),
        neutralization: z.string(),
        rebalance_every_sessions: z.number().int().optional(),
        request_id: z.string(),
        research_kind: z.enum(["factor_evaluation", "strategy_backtest"]),
        start_date: z.string(),
        universe: z.string(),
      }).strict(),
    }),
    get_research_run: createTool({
      description: "Read a ResearchRun lifecycle and available Result sections.",
      execute: async (input) => {
        await beforeDetail?.();
        record("get_research_run", input);
        const running = calls.filter((call) => call.name === "get_research_run").length === 1;
        return {
          available_result_sections: running ? [] : ["factor", "provenance"],
          id: coreRunId,
          input: {
            formula: "rank(-abs(pct_change(close, 1)))",
            hypothesis: "Stocks with smaller recent absolute returns should be stable.",
            research_kind: "factor_evaluation",
          },
          progress: { phase: running ? "research" : "succeeded" },
          retry_after_seconds: running ? 1 : null,
          status: running ? "running" : "succeeded",
        };
      },
      id: "get_research_run",
      inputSchema: z.object({ run_id: z.string() }).strict(),
    }),
    get_research_run_result: createTool({
      description: "Read one authoritative ResearchRun Result section.",
      execute: async (input) => {
        record("get_research_run_result", input);
        return {
          factor: {
            horizons: {
              "5": {
                summary: {
                  rank_ic: { mean: 0.12 },
                  top_bottom_return: 0.034,
                },
              },
            },
          },
          private_provenance: "private-core-provenance",
          research_kind: "factor_evaluation",
          run_id: coreRunId,
          section: "factor",
        };
      },
      id: "get_research_run_result",
      inputSchema: z.object({
        run_id: z.string(),
        section: z.literal("factor"),
      }).strict(),
    }),
  };
}

async function prepareA2UIRepositoryRun(
  repository: ResearchSessionRepository,
  threadId: string,
  runId: string,
  messageId: string,
): Promise<void> {
  const validated = await readValidatedChatRun(runRequest(runInput({
    messageId,
    runId,
    threadId,
  })), modelRegistry);
  await repository.prepareRun({
    agentBuildRevision: "a2ui-persistence-test",
    providerModelId: "scripted-v1",
    researcherId: primaryResearcher.researcher_id,
    run: validated,
  });
}

async function seedAssistantMessage(threadId: string, messageId: string): Promise<void> {
  await owner.query(`
    WITH instant AS (
      SELECT COALESCE(MAX("createdAtZ"), '2026-08-30T05:00:00Z'::timestamptz)
             + interval '1 millisecond' AS value
      FROM agent."mastra_messages" WHERE thread_id = $2
    )
    INSERT INTO agent."mastra_messages" (
      id, thread_id, content, role, type, "createdAt", "resourceId", "createdAtZ"
    )
    SELECT $1, $2, $3, 'assistant', 'v2', value AT TIME ZONE 'UTC', $4, value
    FROM instant
  `, [messageId, threadId, durableTextContent("", 1_788_048_000_000), primaryResearcher.researcher_id]);
}

function largeA2UITableContent(): Record<string, unknown> {
  return {
    a2ui_operations: [{
      createSurface: { catalogId: RESEARCH_A2UI_CATALOG_ID, surfaceId: "large-table" },
      version: RESEARCH_A2UI_PROTOCOL_VERSION,
    }, {
      updateComponents: {
        components: [{
          caption: "Large authoritative table",
          columns: Array.from({ length: 12 }, (_, index) => `Column ${index + 1}`),
          component: "Table",
          id: "root",
          rows: Array.from({ length: 100 }, () => Array.from({ length: 12 }, () => "x".repeat(51))),
          summary: "Inspect all result fields",
        }],
        surfaceId: "large-table",
      },
      version: RESEARCH_A2UI_PROTOCOL_VERSION,
    }],
  };
}

async function seedSession(options: Readonly<{
  activityAt?: Date;
  id: string;
  researcherId: string;
  title: string;
}>): Promise<void> {
  const activityAt = options.activityAt ?? new Date("2026-08-30T05:00:00.000Z");
  const createdAt = new Date(activityAt.getTime() - 60_000);
  await owner.query(`
    INSERT INTO agent.chat_session (
      id, researcher_id, selected_model_key, selected_reasoning_effort,
      created_at, updated_at
    ) VALUES ($1, $2, 'scripted-research', 'medium', $3, $4)
  `, [options.id, options.researcherId, createdAt, activityAt]);
  await owner.query(`
    INSERT INTO agent."mastra_threads" (
      id, "resourceId", title, metadata, "createdAt", "updatedAt",
      "createdAtZ", "updatedAtZ"
    ) VALUES (
      $1, $2, $3, NULL,
      $4::timestamp without time zone,
      $5::timestamp without time zone,
      $6::timestamp with time zone,
      $7::timestamp with time zone
    )
  `, [
    options.id,
    options.researcherId,
    options.title,
    createdAt.toISOString().replace("Z", ""),
    activityAt.toISOString().replace("Z", ""),
    createdAt,
    activityAt,
  ]);
}

async function agentRecordCounts(
  threadId: string,
  runId: string,
): Promise<Readonly<{
  a2ui: string;
  messages: string;
  runs: string;
  sessions: string;
  snapshots: string;
  threads: string;
}>> {
  const result = await owner.query<{
    a2ui: string;
    messages: string;
    runs: string;
    sessions: string;
    snapshots: string;
    threads: string;
  }>(`
    SELECT
      (SELECT count(*)::text FROM agent.a2ui_message WHERE thread_id = $1::uuid) AS a2ui,
      (SELECT count(*)::text FROM agent.chat_session WHERE id = $1::uuid) AS sessions,
      (SELECT count(*)::text FROM agent.agent_run WHERE thread_id = $1::uuid) AS runs,
      (SELECT count(*)::text FROM agent."mastra_threads" WHERE id = $1::uuid::text) AS threads,
      (SELECT count(*)::text FROM agent."mastra_messages" WHERE thread_id = $1::uuid::text) AS messages,
      (SELECT count(*)::text FROM agent."mastra_workflow_snapshot" WHERE run_id = $2) AS snapshots
  `, [threadId, runId]);
  const counts = result.rows[0];
  if (counts === undefined) throw new Error("AGENT_RECORD_COUNTS_MISSING");
  return counts;
}

async function holdSessionMutationLock(threadId: string): Promise<PoolClient> {
  const client = await owner.connect();
  try {
    await client.query("BEGIN");
    await client.query("SET LOCAL search_path = pg_catalog");
    await client.query(
      "SELECT pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended($1, 0))",
      [`thesistrace:agent-thread:${threadId}`],
    );
    return client;
  } catch (error) {
    await client.query("ROLLBACK").catch(() => undefined);
    client.release();
    throw error;
  }
}

async function releaseSessionMutationLock(client: PoolClient): Promise<void> {
  try {
    await client.query("COMMIT");
  } finally {
    client.release();
  }
}

async function waitForAdvisoryLockWaiters(expected: number): Promise<void> {
  const deadline = Date.now() + 3_000;
  let observed = 0;
  while (Date.now() < deadline) {
    const result = await owner.query<{ count: string }>(`
      SELECT count(*)::text AS count
      FROM pg_catalog.pg_locks
      WHERE locktype = 'advisory'
        AND NOT granted
        AND database = (
          SELECT oid
          FROM pg_catalog.pg_database
          WHERE datname = pg_catalog.current_database()
        )
    `);
    observed = Number(result.rows[0]?.count ?? "0");
    if (observed >= expected) return;
    await new Promise<void>((resolve) => setTimeout(resolve, 10));
  }
  throw new Error(`ADVISORY_LOCK_WAITERS_TIMEOUT: expected ${expected}, observed ${observed}`);
}

function researcher(id: string): VerifiedResearcher {
  return {
    active: true,
    display_label: `Researcher ${id.slice(-3)}`,
    email: `${id.slice(-3)}@example.test`,
    researcher_id: id,
  };
}

type RawCoreResult = Readonly<{
  _meta: Record<string, unknown>;
  content: readonly unknown[];
  isError: boolean;
  structuredContent: Record<string, unknown>;
}>;

function adaptedCoreResult(result: RawCoreResult): Record<string, unknown> {
  const output = { ...result.structuredContent };
  Object.defineProperties(output, {
    [MCP_CALL_TOOL_CONTENT]: { value: result.content },
    [MCP_CALL_TOOL_META]: { value: result._meta },
  });
  return output;
}

function modelTextFromMcpOutput(output: unknown): string {
  const content = getMcpCallToolContent(output);
  if (!Array.isArray(content)) throw new Error("MCP_MODEL_CONTENT_MISSING");
  const text = content.find((part) => (
    part !== null
    && typeof part === "object"
    && "type" in part
    && part.type === "text"
    && "text" in part
    && typeof part.text === "string"
  ));
  if (
    text === undefined
    || !("text" in text)
    || typeof text.text !== "string"
  ) {
    throw new Error("MCP_MODEL_TEXT_MISSING");
  }
  return text.text;
}

function runInput(options: Readonly<{
  content?: string;
  messageId: string;
  messages?: Message[];
  modelKey?: string;
  reasoningEffort?: "medium" | "none";
  sessionMode?: "new" | "existing";
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
        sessionMode: options.sessionMode ?? (options.messages === undefined ? "new" : "existing"),
      },
    },
  };
}

function runRequest(input: Record<string, unknown>): Request {
  return new Request(
    "http://agent.test/api/agent/copilotkit/agent/research/run",
    {
      body: JSON.stringify(input),
      headers: {
        "content-type": "application/json",
        cookie: "test-session-cookie=browser-only",
      },
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

function a2uiMessages(values: readonly unknown[]): Array<Readonly<{
  content: unknown;
  id: string;
}>> {
  return values.flatMap((value) => {
    if (!isRecord(value)) return [];
    if (
      value.type === "ACTIVITY_SNAPSHOT"
      && value.activityType === RESEARCH_A2UI_ACTIVITY_TYPE
      && typeof value.messageId === "string"
    ) {
      return [{ content: value.content, id: value.messageId }];
    }
    if (
      value.role === "activity"
      && value.activityType === RESEARCH_A2UI_ACTIVITY_TYPE
      && typeof value.id === "string"
    ) {
      return [{ content: value.content, id: value.id }];
    }
    return [];
  });
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function splitAssistantTextForCopilotKit(messages: readonly Message[]): Message[] {
  const assistantIndex = messages.findIndex((message) => (
    message.role === "assistant"
    && message.toolCalls !== undefined
    && typeof message.content === "string"
    && message.content.length > 0
  ));
  const assistant = messages[assistantIndex];
  if (assistant?.role !== "assistant" || typeof assistant.content !== "string") {
    throw new Error("expected one Tool-calling Assistant message with text");
  }
  let toolEnd = assistantIndex + 1;
  while (messages[toolEnd]?.role === "tool") toolEnd += 1;
  return [
    ...messages.slice(0, assistantIndex),
    { ...assistant, content: undefined },
    ...messages.slice(assistantIndex + 1, toolEnd),
    {
      content: assistant.content,
      id: `${assistant.id}-agui-text`,
      role: "assistant",
    },
    ...messages.slice(toolEnd),
  ];
}

function durableTextContent(text: string, createdAt: number): string {
  return JSON.stringify({
    format: 2,
    parts: [{ createdAt, text, type: "text" }],
    content: text,
  });
}

function roleDatabaseUrl(base: string, username: string, password: string): string {
  const url = new URL(base);
  url.username = username;
  url.password = password;
  return url.toString();
}

function fixedUuid(suffix: number): string {
  return `00000000-0000-4000-8000-${suffix.toString().padStart(12, "0")}`;
}
