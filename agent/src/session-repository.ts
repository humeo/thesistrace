import { convertMessages, type MastraDBMessage } from "@mastra/core/agent";
import type { Message } from "@ag-ui/core";
import type { Pool, PoolClient } from "pg";

import {
  projectDurableUiMessages,
  safeBrowserMessages,
} from "./browser-message-safety.js";
import {
  chatRunFingerprint,
  type ValidatedChatRun,
} from "./chat-request.js";
import type { PersistedTokenUsage } from "./usage-capture.js";

export type SessionOwnership = "absent" | "foreign" | "owned";
export type PreparedRun = Readonly<{
  durableMessages: readonly Message[];
  kind: "duplicate" | "new";
  status: "completed" | "failed" | "running";
}>;
export type TerminalRun = Readonly<{
  id: string;
  status: "completed" | "failed" | "running";
  terminalErrorCode: string | null;
}>;
export type ThreadPreference = Readonly<{
  modelKey: string;
  reasoningEffort: import("./model-registry.js").ReasoningEffort;
}>;

export class SessionNotFoundError extends Error {
  constructor() {
    super("CHAT_SESSION_NOT_FOUND");
    this.name = "SessionNotFoundError";
  }
}

export class ChatRunConflictError extends Error {
  constructor() {
    super("CHAT_RUN_CONFLICT");
    this.name = "ChatRunConflictError";
  }
}

export class TranscriptConflictError extends Error {
  constructor() {
    super("CHAT_TRANSCRIPT_CONFLICT");
    this.name = "TranscriptConflictError";
  }
}

type PrepareRunOptions = Readonly<{
  agentBuildRevision: string;
  providerModelId: string;
  researcherId: string;
  run: ValidatedChatRun;
}>;

export class ResearchSessionRepository {
  constructor(private readonly pool: Pool) {}

  async ownership(threadId: string, researcherId: string): Promise<SessionOwnership> {
    const result = await this.pool.query<{ researcher_id: string }>(`
      SELECT researcher_id::text
      FROM agent.chat_session
      WHERE id = $1::uuid
    `, [threadId]);
    const owner = result.rows[0]?.researcher_id;
    if (owner === undefined) return "absent";
    return owner === researcherId ? "owned" : "foreign";
  }

  async threadPreference(
    threadId: string,
    researcherId: string,
  ): Promise<ThreadPreference | null> {
    const result = await this.pool.query<{
      selected_model_key: string;
      selected_reasoning_effort: ThreadPreference["reasoningEffort"];
    }>(`
      SELECT selected_model_key, selected_reasoning_effort
      FROM agent.chat_session
      WHERE id = $1::uuid AND researcher_id = $2::uuid
    `, [threadId, researcherId]);
    const preference = result.rows[0];
    return preference === undefined ? null : {
      modelKey: preference.selected_model_key,
      reasoningEffort: preference.selected_reasoning_effort,
    };
  }

  async prepareRun(options: PrepareRunOptions): Promise<PreparedRun> {
    const client = await this.pool.connect();
    try {
      await client.query("BEGIN");
      await client.query("SET LOCAL search_path = pg_catalog");
      await client.query("SET LOCAL statement_timeout = '10000ms'");
      await client.query(
        "SELECT pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended($1, 0))",
        [`thesistrace:agent-thread:${options.run.input.threadId}`],
      );

      const fingerprint = chatRunFingerprint(options.run.input);
      const existingRun = await client.query<{
        request_fingerprint: Buffer;
        researcher_id: string;
        status: "completed" | "failed" | "running";
        thread_id: string;
      }>(`
        SELECT
          run.request_fingerprint,
          session.researcher_id::text,
          run.status,
          run.thread_id::text
        FROM agent.agent_run AS run
        JOIN agent.chat_session AS session ON session.id = run.thread_id
        WHERE run.id = $1::uuid
        FOR UPDATE OF run, session
      `, [options.run.input.runId]);
      const duplicate = existingRun.rows[0];
      if (duplicate !== undefined) {
        if (
          duplicate.researcher_id !== options.researcherId
          || duplicate.thread_id !== options.run.input.threadId
        ) {
          throw new SessionNotFoundError();
        }
        if (!duplicate.request_fingerprint.equals(fingerprint)) {
          throw new ChatRunConflictError();
        }
        const durableMessages = await loadDurableMessages(
          client,
          options.run.input.threadId,
          options.researcherId,
        );
        await client.query("COMMIT");
        return {
          durableMessages,
          kind: "duplicate",
          status: duplicate.status,
        };
      }

      const sessionResult = await client.query<{ researcher_id: string }>(`
        SELECT researcher_id::text
        FROM agent.chat_session
        WHERE id = $1::uuid
        FOR UPDATE
      `, [options.run.input.threadId]);
      const existingOwner = sessionResult.rows[0]?.researcher_id;
      if (existingOwner !== undefined && existingOwner !== options.researcherId) {
        throw new SessionNotFoundError();
      }

      const durableMessages = existingOwner === undefined
        ? []
        : await loadDurableMessages(
            client,
            options.run.input.threadId,
            options.researcherId,
          );
      assertOneNewUserMessage(options.run.input.messages, durableMessages);
      const acceptedAt = new Date();
      const acceptedAtUtc = acceptedAt.toISOString();
      const acceptedUserMessage = durableUserMessage(
        options.run.latestUserMessage,
        options.run.input.threadId,
        options.researcherId,
        acceptedAt,
      );

      if (existingOwner === undefined) {
        await client.query(`
          INSERT INTO agent.chat_session (
            id,
            researcher_id,
            selected_model_key,
            selected_reasoning_effort
          ) VALUES ($1::uuid, $2::uuid, $3, $4)
        `, [
          options.run.input.threadId,
          options.researcherId,
          options.run.modelKey,
          options.run.reasoningEffort,
        ]);
        await client.query(`
          INSERT INTO agent."mastra_threads" (
            id,
            "resourceId",
            title,
            metadata,
            "createdAt",
            "updatedAt"
          ) VALUES ($1, $2, $3, NULL, $4, $4)
        `, [
          options.run.input.threadId,
          options.researcherId,
          "New chat",
          acceptedAtUtc,
        ]);
      } else {
        await client.query(`
          UPDATE agent.chat_session
          SET selected_model_key = $2,
              selected_reasoning_effort = $3,
              updated_at = pg_catalog.now()
          WHERE id = $1::uuid
        `, [
          options.run.input.threadId,
          options.run.modelKey,
          options.run.reasoningEffort,
        ]);
      }

      // Acceptance is one atomic product boundary: Session, Run, and the
      // unique new User Message commit together. Mastra later saves the same
      // message id with ON CONFLICT semantics, so successful execution adds
      // only its Assistant/Tool output while pre-model failure still replays
      // the accepted input and recalls it on the next Turn.
      await client.query(`
        INSERT INTO agent."mastra_messages" (
          id,
          thread_id,
          content,
          "createdAt",
          "createdAtZ",
          role,
          type,
          "resourceId"
        ) VALUES ($1, $2, $3, $4, $5, 'user', 'v2', $6)
      `, [
        acceptedUserMessage.id,
        options.run.input.threadId,
        JSON.stringify(acceptedUserMessage.content),
        acceptedAtUtc,
        acceptedAtUtc,
        options.researcherId,
      ]);
      await client.query(`
        UPDATE agent."mastra_threads"
        SET "updatedAt" = $2,
            "updatedAtZ" = $3
        WHERE id = $1
      `, [options.run.input.threadId, acceptedAtUtc, acceptedAtUtc]);

      await client.query(`
        INSERT INTO agent.agent_run (
          id,
          thread_id,
          request_fingerprint,
          model_key,
          provider_model_id,
          reasoning_effort,
          agent_build_revision,
          status
        ) VALUES ($1::uuid, $2::uuid, $3, $4, $5, $6, $7, 'running')
      `, [
        options.run.input.runId,
        options.run.input.threadId,
        fingerprint,
        options.run.modelKey,
        options.providerModelId,
        options.run.reasoningEffort,
        options.agentBuildRevision,
      ]);
      await client.query("COMMIT");
      return { durableMessages, kind: "new", status: "running" };
    } catch (error) {
      await client.query("ROLLBACK").catch(() => undefined);
      throw error;
    } finally {
      client.release();
    }
  }

  async markCompleted(
    runId: string,
    usage: PersistedTokenUsage | undefined,
  ): Promise<void> {
    const result = await this.pool.query(`
      UPDATE agent.agent_run
      SET status = 'completed',
          token_usage = $2::jsonb,
          completed_at = pg_catalog.now()
      WHERE id = $1::uuid AND status = 'running'
    `, [runId, persistedUsage(usage)]);
    if (result.rowCount !== 1) throw new ChatRunConflictError();
  }

  async markFailed(
    runId: string,
    usage: PersistedTokenUsage | undefined,
  ): Promise<void> {
    await this.pool.query(`
      UPDATE agent.agent_run
      SET status = 'failed',
          token_usage = $2::jsonb,
          terminal_error_code = 'AGENT_RUN_FAILED',
          completed_at = pg_catalog.now()
      WHERE id = $1::uuid AND status = 'running'
    `, [runId, persistedUsage(usage)]);
  }

  async awaitFrameworkRunSettled(runId: string): Promise<void> {
    await waitForDurableCondition(async () => {
      const result = await this.pool.query<{ settled: boolean }>(`
        SELECT NOT EXISTS (
          SELECT 1
          FROM agent."mastra_workflow_snapshot"
          WHERE run_id = $1
        ) AS settled
      `, [runId]);
      return result.rows[0]?.settled === true;
    }, "MASTRA_RUN_CLEANUP_TIMEOUT");
  }

  async awaitDurableToolResult(
    threadId: string,
    researcherId: string,
    toolCallId: string,
  ): Promise<void> {
    await waitForDurableCondition(async () => {
      const messages = await loadDurableMessages(
        this.pool,
        threadId,
        researcherId,
      );
      return messages.some((message) => (
        message.role === "tool" && message.toolCallId === toolCallId
      ));
    }, "MASTRA_TOOL_RESULT_PERSISTENCE_TIMEOUT");
  }

  async durableMessages(
    threadId: string,
    researcherId: string,
  ): Promise<readonly Message[]> {
    const ownership = await this.ownership(threadId, researcherId);
    if (ownership === "foreign") throw new SessionNotFoundError();
    if (ownership === "absent") return [];
    return loadDurableMessages(this.pool, threadId, researcherId);
  }

  async latestRun(threadId: string, researcherId: string): Promise<TerminalRun | null> {
    const ownership = await this.ownership(threadId, researcherId);
    if (ownership !== "owned") return null;
    const result = await this.pool.query<{
      id: string;
      status: TerminalRun["status"];
      terminal_error_code: string | null;
    }>(`
      SELECT id::text, status, terminal_error_code
      FROM agent.agent_run
      WHERE thread_id = $1::uuid
      ORDER BY started_at DESC, id DESC
      LIMIT 1
    `, [threadId]);
    const row = result.rows[0];
    return row === undefined ? null : {
      id: row.id,
      status: row.status,
      terminalErrorCode: row.terminal_error_code,
    };
  }
}

function durableUserMessage(
  message: ValidatedChatRun["latestUserMessage"],
  threadId: string,
  researcherId: string,
  createdAt: Date,
): MastraDBMessage {
  try {
    const converted = convertMessages([message]).to("Mastra.V2");
    const durable = converted[0];
    if (
      converted.length !== 1
      || durable === undefined
      || durable.id !== message.id
      || durable.role !== "user"
    ) {
      throw new TranscriptConflictError();
    }
    return {
      ...durable,
      createdAt,
      resourceId: researcherId,
      threadId,
      type: "v2",
    };
  } catch {
    throw new TranscriptConflictError();
  }
}

function persistedUsage(usage: PersistedTokenUsage | undefined): string {
  return JSON.stringify(usage ?? { reported: false });
}

async function waitForDurableCondition(
  condition: () => Promise<boolean>,
  timeoutCode: string,
): Promise<void> {
  const deadline = Date.now() + 5_000;
  while (true) {
    if (await condition()) return;
    if (Date.now() >= deadline) throw new Error(timeoutCode);
    await new Promise<void>((resolve) => setTimeout(resolve, 10));
  }
}

async function loadDurableMessages(
  database: Pick<Pool | PoolClient, "query">,
  threadId: string,
  researcherId: string,
): Promise<readonly Message[]> {
  const thread = await database.query<{ resource_id: string }>(`
    SELECT "resourceId" AS resource_id
    FROM agent."mastra_threads"
    WHERE id = $1
  `, [threadId]);
  if (thread.rows[0] === undefined) {
    throw new TranscriptConflictError();
  }
  if (thread.rows[0].resource_id !== researcherId) {
    throw new SessionNotFoundError();
  }

  const result = await database.query<{
    content: string;
    created_at: Date | null;
    id: string;
    resource_id: string | null;
    role: MastraDBMessage["role"];
  }>(`
    SELECT
      id,
      content,
      role,
      "createdAtZ" AS created_at,
      "resourceId" AS resource_id
    FROM agent."mastra_messages"
    WHERE thread_id = $1
    ORDER BY "createdAtZ" ASC, id ASC
  `, [threadId]);
  const dbMessages = result.rows.map((row): MastraDBMessage => {
    if (row.resource_id !== null && row.resource_id !== researcherId) {
      throw new SessionNotFoundError();
    }
    let content: MastraDBMessage["content"];
    try {
      content = JSON.parse(row.content) as MastraDBMessage["content"];
    } catch {
      throw new TranscriptConflictError();
    }
    if (!(row.created_at instanceof Date) || Number.isNaN(row.created_at.getTime())) {
      throw new TranscriptConflictError();
    }
    return {
      content,
      createdAt: row.created_at,
      id: row.id,
      resourceId: row.resource_id ?? undefined,
      role: row.role,
      threadId,
    };
  });
  try {
    return projectDurableUiMessages(convertMessages(dbMessages).to("AIV4.UI"));
  } catch {
    throw new TranscriptConflictError();
  }
}

function assertOneNewUserMessage(
  submitted: readonly Message[],
  durable: readonly Message[],
): void {
  if (submitted.length !== durable.length + 1) throw new TranscriptConflictError();
  let safeSubmitted: readonly Message[];
  try {
    safeSubmitted = safeBrowserMessages(submitted.slice(0, -1));
  } catch {
    throw new TranscriptConflictError();
  }
  if (JSON.stringify(safeSubmitted) !== JSON.stringify(durable)) {
    throw new TranscriptConflictError();
  }
  const latest = submitted.at(-1);
  if (latest?.role !== "user" || typeof latest.content !== "string") {
    throw new TranscriptConflictError();
  }
}
