import { convertMessages, type MastraDBMessage } from "@mastra/core/agent";
import type { Message } from "@ag-ui/core";
import type { Pool, PoolClient } from "pg";

import {
  isResearchA2UIMessageId,
  projectResearchA2UIContent,
  safeResearchA2UIErrorContent,
  RESEARCH_A2UI_ACTIVITY_TYPE,
  RESEARCH_A2UI_CATALOG_ID,
  RESEARCH_A2UI_PROTOCOL_VERSION,
} from "../../contracts/research-a2ui.mjs";

import {
  projectDurableUiMessages,
} from "./browser-message-safety.js";
import {
  chatRunFingerprint,
  type ValidatedAnswerRun,
  type ValidatedChatRun,
  type ValidatedPromptRun,
} from "./chat-request.js";
import {
  ChatControlError,
  encodeTimelineCursor,
  validateAnswerForQuestion,
  type ChatTimelineEntry,
  type CommandKind,
  type CommandReceipt,
  type PendingQuestion,
  type PublicTurn,
  type TimelineCursor,
  type TimelinePage,
  type TurnKind,
  type TurnStatus,
} from "./chat-control.js";
import {
  SESSION_HISTORY_PAGE_SIZE,
  UNTITLED_SESSION_TITLE,
  encodeSessionCursor,
  normalizeReplacementSessionTitle,
  normalizeSessionTitle,
  type SessionCursor,
} from "./session-management.js";
import type { PersistedTokenUsage } from "./usage-capture.js";
import type { AgentFailureCode } from "../../contracts/agent-failure.mjs";
import type { RunSelection } from "../../contracts/agent-run-selection.mjs";

export type SessionOwnership = "absent" | "foreign" | "owned";
export type PreparedRun = Readonly<{
  durableMessages: readonly Message[];
  generateTitle: boolean;
}> & (Readonly<{
  execution: "start" | "resume";
  kind: "new";
  status: "running";
}> | Readonly<{
  kind: "duplicate";
  question: PendingQuestion | null;
  status: TurnStatus;
  terminalErrorCode: string | null;
  selection: RunSelection;
}>);
export type TerminalRun = Readonly<{
  id: string;
  kind: TurnKind;
  startedAt: string;
  status: TurnStatus;
  terminalErrorCode: string | null;
  selection: RunSelection;
  question: PendingQuestion | null;
}>;
export type ThreadPreference = Readonly<{
  modelKey: string;
  reasoningEffort: import("./model-registry.js").ReasoningEffort;
}>;
export type SessionSummary = Readonly<{
  activityAt: string;
  createdAt: string;
  currentTurn: PublicTurn | null;
  id: string;
  latestTurn: PublicTurn | null;
  title: string;
  version: string;
}>;
export type SessionPage = Readonly<{
  nextCursor: string | null;
  sessions: readonly SessionSummary[];
}>;
export type RenamedSession = Readonly<{
  id: string;
  title: string;
  version: string;
}>;
export type PersistedA2UIActivity = Readonly<{
  content: Record<string, unknown>;
  lifecycle: "error" | "loading" | "ready";
  messageId: string;
  ownerMessageId: string;
  runId: string;
  sequence: number;
  threadId: string;
}>;

type StoredA2UIActivity = Readonly<{
  message: Extract<Message, { role: "activity" }>;
  ownerMessageId: string;
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

export class SessionVersionConflictError extends Error {
  constructor() {
    super("CHAT_SESSION_VERSION_CONFLICT");
    this.name = "SessionVersionConflictError";
  }
}

export class SessionActiveRunError extends Error {
  constructor() {
    super("CHAT_SESSION_RUN_ACTIVE");
    this.name = "SessionActiveRunError";
  }
}

type PrepareRunOptions = Readonly<{
  agentBuildRevision: string;
  providerModelId?: string;
  researcherId: string;
  run: ValidatedChatRun;
}>;

export type RunExecution = Readonly<{
  generatedBytes: number;
  selection: RunSelection;
  stepCount: number;
  usage: PersistedTokenUsage | undefined;
}>;

export class ResearchSessionRepository {
  constructor(private readonly pool: Pool) {}

  async failInterruptedRunsAfterHostRestart(): Promise<number> {
    const client = await this.pool.connect();
    try {
      await client.query("BEGIN");
      await client.query("SET LOCAL search_path = pg_catalog");
      await client.query(`
        UPDATE agent.a2ui_message AS activity
        SET lifecycle_status = 'error',
            content = $1::jsonb,
            updated_at = pg_catalog.clock_timestamp()
        FROM agent.agent_run AS run
        WHERE activity.run_id = run.id
          AND activity.lifecycle_status = 'loading'
          AND run.status = ANY (ARRAY['running', 'stopping'])
      `, [JSON.stringify(safeResearchA2UIErrorContent())]);
      await client.query(`
        UPDATE agent.chat_timeline_entry AS entry
        SET payload = pg_catalog.jsonb_set(
              entry.payload,
              '{status}',
              pg_catalog.to_jsonb(
                CASE
                  WHEN run.status = 'stopping' THEN 'stopped'
                  WHEN entry.kind = 'assistant_message' THEN 'failed'
                  ELSE 'failed'
                END::text
              )
            ),
            updated_at = pg_catalog.clock_timestamp()
        FROM agent.agent_run AS run
        WHERE entry.turn_id = run.id
          AND run.status = ANY (ARRAY['running', 'stopping'])
          AND (
            (entry.kind = 'assistant_message' AND entry.payload->>'status' = 'streaming')
            OR (entry.kind = 'tool_activity' AND entry.payload->>'status' = 'running')
          )
      `);
      await client.query(`
        UPDATE agent.chat_interrupt AS interrupt
        SET status = 'stopped', answered_at = pg_catalog.clock_timestamp()
        FROM agent.agent_run AS run
        WHERE interrupt.turn_id = run.id
          AND run.status = 'stopping'
          AND interrupt.status = 'pending'
      `);
      const result = await client.query<{ id: string; status: "failed" | "stopped"; thread_id: string }>(`
        UPDATE agent.agent_run
        SET status = CASE WHEN status = 'stopping' THEN 'stopped' ELSE 'failed' END,
            token_usage = COALESCE(token_usage, '{"reported":false}'::jsonb),
            terminal_error_code = CASE
              WHEN status = 'running' THEN 'AGENT_RUN_INTERRUPTED'
              ELSE NULL
            END,
            completed_at = pg_catalog.clock_timestamp()
        WHERE status = ANY (ARRAY['running', 'stopping'])
        RETURNING id::text, thread_id::text, status
      `);
      for (const run of result.rows) {
        await insertTimelineEntry(client, {
          entryId: `outcome:${run.id}`,
          kind: "turn_outcome",
          payload: run.status === "failed"
            ? { errorCode: "AGENT_RUN_INTERRUPTED", status: "failed" }
            : { status: "stopped" },
          threadId: run.thread_id,
          turnId: run.id,
        });
      }
      await client.query(`
        UPDATE agent.chat_command AS command
        SET status = 'accepted', updated_at = pg_catalog.clock_timestamp()
        FROM agent.agent_run AS run
        WHERE command.turn_id = run.id
          AND command.kind = 'stop'
          AND command.status = 'pending'
          AND run.status = 'stopped'
      `);
      await client.query(`
        UPDATE agent.chat_command
        SET status = 'rejected',
            error_code = 'CHAT_CAPABILITY_UNAVAILABLE',
            updated_at = pg_catalog.clock_timestamp()
        WHERE kind = 'steer' AND status = 'pending'
      `);
      await client.query("COMMIT");
      return result.rowCount ?? 0;
    } catch (error) {
      await client.query("ROLLBACK").catch(() => undefined);
      throw error;
    } finally {
      client.release();
    }
  }

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

  async listSessions(
    researcherId: string,
    cursor?: SessionCursor,
  ): Promise<SessionPage> {
    const parameters: unknown[] = [researcherId];
    const cursorClause = cursor === undefined
      ? ""
      : `
        AND (session.updated_at, session.id)
          < ($2::timestamp with time zone, $3::uuid)
      `;
    if (cursor !== undefined) {
      parameters.push(cursor.activityAt, cursor.id);
    }
    parameters.push(SESSION_HISTORY_PAGE_SIZE + 1);
    const limitParameter = parameters.length;
    const result = await this.pool.query<{
      activity_at: string;
      created_at: string;
      current_turn: unknown;
      id: string;
      latest_turn: unknown;
      title: string;
      version: Date;
    }>(`
      SELECT
        session.id::text,
        pg_catalog.to_char(
          session.created_at AT TIME ZONE 'UTC',
          'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'
        ) AS created_at,
        pg_catalog.to_char(
          session.updated_at AT TIME ZONE 'UTC',
          'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'
        ) AS activity_at,
        thread.title,
        thread."updatedAtZ" AS version,
        CASE
          WHEN latest_run.status = ANY (ARRAY['running', 'waiting_for_user', 'stopping'])
          THEN latest_run.turn
          ELSE NULL
        END AS current_turn,
        latest_run.turn AS latest_turn
      FROM agent.chat_session AS session
      JOIN agent."mastra_threads" AS thread
        ON thread.id = session.id::text
       AND thread."resourceId" = session.researcher_id::text
      LEFT JOIN LATERAL (
        SELECT
          run.status,
          pg_catalog.jsonb_build_object(
            'id', run.id::text,
            'kind', run.kind,
            'status', run.status,
            'started_at', pg_catalog.to_char(
              run.started_at AT TIME ZONE 'UTC',
              'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'
            ),
            'model_key', run.model_key,
            'reasoning_effort', run.reasoning_effort,
            'terminal_error_code', run.terminal_error_code,
            'question', CASE WHEN interrupt.id IS NULL THEN NULL ELSE
              pg_catalog.jsonb_build_object(
                'interrupt_id', interrupt.id,
                'tool_call_id', interrupt.tool_call_id,
                'question', interrupt.question,
                'options', interrupt.options,
                'selection_mode', interrupt.selection_mode
              )
            END
          ) AS turn
        FROM agent.agent_run AS run
        LEFT JOIN agent.chat_interrupt AS interrupt
          ON interrupt.thread_id = run.thread_id
         AND interrupt.turn_id = run.id
         AND interrupt.status = 'pending'
        WHERE run.thread_id = session.id
        ORDER BY run.started_at DESC, run.id DESC
        LIMIT 1
      ) AS latest_run ON TRUE
      WHERE session.researcher_id = $1::uuid
      ${cursorClause}
      ORDER BY session.updated_at DESC, session.id DESC
      LIMIT $${limitParameter}
    `, parameters);
    const hasMore = result.rows.length > SESSION_HISTORY_PAGE_SIZE;
    const rows = result.rows.slice(0, SESSION_HISTORY_PAGE_SIZE);
    const sessions = rows.map(sessionSummaryFromRow);
    const last = rows.at(-1);
    return {
      nextCursor: !hasMore || last === undefined
        ? null
        : encodeSessionCursor({ activityAt: last.activity_at, id: last.id }),
      sessions,
    };
  }

  async session(threadId: string, researcherId: string): Promise<SessionSummary> {
    const result = await this.pool.query<SessionSummaryRow>(`
      SELECT
        session.id::text,
        pg_catalog.to_char(
          session.created_at AT TIME ZONE 'UTC',
          'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'
        ) AS created_at,
        pg_catalog.to_char(
          session.updated_at AT TIME ZONE 'UTC',
          'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'
        ) AS activity_at,
        thread.title,
        thread."updatedAtZ" AS version,
        CASE
          WHEN latest_run.status = ANY (ARRAY['running', 'waiting_for_user', 'stopping'])
          THEN latest_run.turn
          ELSE NULL
        END AS current_turn,
        latest_run.turn AS latest_turn
      FROM agent.chat_session AS session
      JOIN agent."mastra_threads" AS thread
        ON thread.id = session.id::text
       AND thread."resourceId" = session.researcher_id::text
      LEFT JOIN LATERAL (
        SELECT
          run.status,
          pg_catalog.jsonb_build_object(
            'id', run.id::text,
            'kind', run.kind,
            'status', run.status,
            'started_at', pg_catalog.to_char(
              run.started_at AT TIME ZONE 'UTC',
              'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'
            ),
            'model_key', run.model_key,
            'reasoning_effort', run.reasoning_effort,
            'terminal_error_code', run.terminal_error_code,
            'question', CASE WHEN interrupt.id IS NULL THEN NULL ELSE
              pg_catalog.jsonb_build_object(
                'interrupt_id', interrupt.id,
                'tool_call_id', interrupt.tool_call_id,
                'question', interrupt.question,
                'options', interrupt.options,
                'selection_mode', interrupt.selection_mode
              )
            END
          ) AS turn
        FROM agent.agent_run AS run
        LEFT JOIN agent.chat_interrupt AS interrupt
          ON interrupt.thread_id = run.thread_id
         AND interrupt.turn_id = run.id
         AND interrupt.status = 'pending'
        WHERE run.thread_id = session.id
        ORDER BY run.started_at DESC, run.id DESC
        LIMIT 1
      ) AS latest_run ON TRUE
      WHERE session.id = $1::uuid
        AND session.researcher_id = $2::uuid
    `, [threadId, researcherId]);
    const row = result.rows[0];
    if (result.rowCount !== 1 || row === undefined) throw new SessionNotFoundError();
    return sessionSummaryFromRow(row);
  }

  async renameSession(
    threadId: string,
    researcherId: string,
    titleInput: unknown,
    expectedVersion: Date,
  ): Promise<RenamedSession> {
    const title = normalizeReplacementSessionTitle(titleInput);
    const client = await this.pool.connect();
    try {
      await beginSessionMutation(client, threadId);
      const existing = await loadOwnedThreadForUpdate(client, threadId, researcherId);
      if (existing.version.getTime() !== expectedVersion.getTime()) {
        throw new SessionVersionConflictError();
      }
      const version = nextThreadVersion(existing.version);
      const result = await client.query<{ id: string; title: string; version: Date }>(`
        UPDATE agent."mastra_threads"
        SET title = $2,
            "updatedAt" = $3::timestamp without time zone,
            "updatedAtZ" = $4::timestamp with time zone
        WHERE id = $1
        RETURNING id, title, "updatedAtZ" AS version
      `, [
        threadId,
        title,
        version.toISOString().replace("Z", ""),
        version,
      ]);
      const renamed = result.rows[0];
      if (result.rowCount !== 1 || renamed === undefined) {
        throw new TranscriptConflictError();
      }
      await client.query("COMMIT");
      return {
        id: renamed.id,
        title: renamed.title,
        version: exactDate(renamed.version).toISOString(),
      };
    } catch (error) {
      await client.query("ROLLBACK").catch(() => undefined);
      throw error;
    } finally {
      client.release();
    }
  }

  async storeGeneratedTitle(
    threadId: string,
    researcherId: string,
    titleInput: unknown,
  ): Promise<boolean> {
    const title = normalizeReplacementSessionTitle(titleInput);
    const client = await this.pool.connect();
    try {
      await beginSessionMutation(client, threadId);
      const existing = await loadOwnedThreadForUpdate(
        client,
        threadId,
        researcherId,
        false,
      );
      if (existing === null || existing.title !== UNTITLED_SESSION_TITLE) {
        await client.query("COMMIT");
        return false;
      }
      const version = nextThreadVersion(existing.version);
      const result = await client.query(`
        UPDATE agent."mastra_threads"
        SET title = $2,
            "updatedAt" = $3::timestamp without time zone,
            "updatedAtZ" = $4::timestamp with time zone
        WHERE id = $1 AND title = $5
      `, [
        threadId,
        title,
        version.toISOString().replace("Z", ""),
        version,
        UNTITLED_SESSION_TITLE,
      ]);
      if (result.rowCount !== 1) throw new SessionVersionConflictError();
      await client.query("COMMIT");
      return true;
    } catch (error) {
      await client.query("ROLLBACK").catch(() => undefined);
      throw error;
    } finally {
      client.release();
    }
  }

  async deleteSession(threadId: string, researcherId: string): Promise<void> {
    const client = await this.pool.connect();
    try {
      await beginSessionMutation(client, threadId);
      await loadOwnedThreadForUpdate(client, threadId, researcherId);
      const active = await client.query(`
        SELECT 1
        FROM agent.agent_run
        WHERE thread_id = $1::uuid
          AND status = ANY (ARRAY['running', 'waiting_for_user', 'stopping'])
        LIMIT 1
      `, [threadId]);
      if (active.rowCount !== 0) throw new SessionActiveRunError();

      await client.query(`
        DELETE FROM agent."mastra_workflow_snapshot"
        WHERE run_id IN (
          SELECT id::text
          FROM agent.agent_run
          WHERE thread_id = $1::uuid
        )
      `, [threadId]);
      await client.query(`
        DELETE FROM agent."mastra_observational_memory"
        WHERE "threadId" = $1
      `, [threadId]);
      await client.query(`
        DELETE FROM agent."mastra_messages"
        WHERE thread_id = $1
      `, [threadId]);
      const thread = await client.query(`
        DELETE FROM agent."mastra_threads"
        WHERE id = $1
      `, [threadId]);
      const session = await client.query(`
        DELETE FROM agent.chat_session
        WHERE id = $1::uuid AND researcher_id = $2::uuid
      `, [threadId, researcherId]);
      if (thread.rowCount !== 1 || session.rowCount !== 1) {
        throw new TranscriptConflictError();
      }
      await client.query("COMMIT");
    } catch (error) {
      await client.query("ROLLBACK").catch(() => undefined);
      throw error;
    } finally {
      client.release();
    }
  }

  async prepareRun(options: PrepareRunOptions): Promise<PreparedRun> {
    const client = await this.pool.connect();
    try {
      await beginSessionMutation(client, options.run.input.threadId);
      if (options.run.command === "answer") {
        const prepared = await prepareAnswerRun(client, { ...options, run: options.run });
        await client.query("COMMIT");
        return prepared;
      }

      const fingerprint = chatRunFingerprint(options.run);
      const duplicate = await loadRunForUpdate(client, options.run.input.runId);
      if (duplicate !== null) {
        assertOwnedRun(duplicate, options.run.input.threadId, options.researcherId);
        if (!duplicate.requestFingerprint.equals(fingerprint)) throw new ChatRunConflictError();
        const durableMessages = await loadDurableMessages(
          client,
          options.run.input.threadId,
          options.researcherId,
        );
        await client.query("COMMIT");
        return duplicatePreparedRun(duplicate, durableMessages);
      }

      const reusedCommand = await loadCommand(client, options.run.input.threadId, options.run.commandId);
      if (reusedCommand !== null) throw new ChatControlError("CHAT_COMMAND_CONFLICT", 409);

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
      if ((existingOwner === undefined && options.run.sessionMode !== "new")
        || (existingOwner !== undefined && options.run.sessionMode !== "existing")) {
        throw new SessionNotFoundError();
      }

      if (existingOwner !== undefined) {
        const active = await client.query(`
          SELECT 1
          FROM agent.agent_run
          WHERE thread_id = $1::uuid
            AND status = ANY (ARRAY['running', 'waiting_for_user', 'stopping'])
          LIMIT 1
        `, [options.run.input.threadId]);
        if (active.rowCount !== 0) throw new SessionActiveRunError();
      }

      if (options.run.command === "continue") {
        const latest = await client.query<{ status: TurnStatus }>(`
          SELECT status
          FROM agent.agent_run
          WHERE thread_id = $1::uuid
          ORDER BY started_at DESC, id DESC
          LIMIT 1
          FOR UPDATE
        `, [options.run.input.threadId]);
        if (latest.rows[0]?.status !== "stopped") {
          throw new ChatControlError("CHAT_CAPABILITY_UNAVAILABLE", 409);
        }
      }

      const durableMessages = existingOwner === undefined
        ? []
        : await loadDurableMessages(
            client,
            options.run.input.threadId,
            options.researcherId,
          );
      let generateTitle = options.run.command === "prompt" && existingOwner === undefined;
      let existingThreadVersion: Date | null = null;
      if (existingOwner !== undefined) {
        const thread = await loadOwnedThreadForUpdate(
          client,
          options.run.input.threadId,
          options.researcherId,
        );
        existingThreadVersion = thread.version;
        generateTitle = options.run.command === "prompt"
          && thread.title === UNTITLED_SESSION_TITLE;
      }
      const acceptedAt = new Date();
      const acceptedAtUtc = acceptedAt.toISOString();
      const acceptedThreadVersion = existingThreadVersion === null
        ? acceptedAt
        : nextThreadVersion(existingThreadVersion);
      const acceptedUserMessage = options.run.command === "prompt"
        ? durableUserMessage(
            options.run.userMessage,
            options.run.input.threadId,
            options.researcherId,
            acceptedAt,
          )
        : null;

      if (existingOwner === undefined) {
        if (options.run.command !== "prompt") throw new SessionNotFoundError();
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
          UNTITLED_SESSION_TITLE,
          acceptedAtUtc,
        ]);
      } else {
        await client.query(`
          UPDATE agent.chat_session
          SET selected_model_key = $2,
              selected_reasoning_effort = $3,
              updated_at = pg_catalog.clock_timestamp()
          WHERE id = $1::uuid
        `, [
          options.run.input.threadId,
          options.run.modelKey,
          options.run.reasoningEffort,
        ]);
      }

      if (acceptedUserMessage !== null) {
        // The accepted Prompt is durable before any provider call. Mastra
        // later writes the same message id with its conflict-safe adapter.
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
      }
      await client.query(`
        UPDATE agent."mastra_threads"
        SET "updatedAt" = $2::timestamp without time zone,
            "updatedAtZ" = $3::timestamp with time zone
        WHERE id = $1
      `, [
        options.run.input.threadId,
        acceptedThreadVersion.toISOString().replace("Z", ""),
        acceptedThreadVersion,
      ]);

      await client.query(`
        INSERT INTO agent.agent_run (
          id,
          thread_id,
          kind,
          request_fingerprint,
          model_key,
          provider_model_id,
          reasoning_effort,
          agent_build_revision,
          status
        ) VALUES ($1::uuid, $2::uuid, $3, $4, $5, $6, $7, $8, 'running')
      `, [
        options.run.input.runId,
        options.run.input.threadId,
        options.run.command,
        fingerprint,
        options.run.modelKey,
        requireProviderModelId(options.providerModelId),
        options.run.reasoningEffort,
        options.agentBuildRevision,
      ]);
      await insertCommand(client, {
        fingerprint,
        id: options.run.commandId,
        kind: options.run.command,
        status: "accepted",
        threadId: options.run.input.threadId,
        turnId: options.run.input.runId,
      });
      if (options.run.command === "prompt") {
        await insertTimelineEntry(client, {
          entryId: `user:${options.run.commandId}`,
          kind: "user_input",
          payload: {
            content: options.run.userMessage.content,
            inputId: options.run.commandId,
            source: "prompt",
          },
          threadId: options.run.input.threadId,
          turnId: options.run.input.runId,
        });
      }
      await client.query("COMMIT");
      return {
        durableMessages,
        execution: "start",
        generateTitle,
        kind: "new",
        status: "running",
      };
    } catch (error) {
      await client.query("ROLLBACK").catch(() => undefined);
      throw error;
    } finally {
      client.release();
    }
  }

  async runExecution(
    run: ValidatedAnswerRun,
    researcherId: string,
  ): Promise<RunExecution> {
    const result = await this.pool.query<{
      answer_fingerprint: Buffer | null;
      answer_kind: CommandKind | null;
      answer_status: "accepted" | "pending" | "rejected" | null;
      generated_bytes: number;
      model_key: string;
      provider_model_id: string;
      reasoning_effort: RunSelection["reasoningEffort"];
      status: TurnStatus;
      step_count: number;
      token_usage: unknown;
    }>(`
      SELECT
        run.generated_bytes,
        run.model_key,
        run.provider_model_id,
        run.reasoning_effort,
        run.status,
        run.step_count,
        run.token_usage,
        answer.kind AS answer_kind,
        answer.status AS answer_status,
        answer.request_fingerprint AS answer_fingerprint
      FROM agent.agent_run AS run
      JOIN agent.chat_session AS session ON session.id = run.thread_id
      LEFT JOIN agent.chat_command AS answer
        ON answer.thread_id = run.thread_id
       AND answer.id = $4::uuid
      WHERE run.thread_id = $1::uuid
        AND run.id = $2::uuid
        AND session.researcher_id = $3::uuid
    `, [run.input.threadId, run.input.runId, researcherId, run.commandId]);
    const row = result.rows[0];
    if (row === undefined) throw new SessionNotFoundError();
    const duplicateAcceptedAnswer = row.answer_kind === "answer"
      && row.answer_status === "accepted"
      && row.answer_fingerprint?.equals(chatRunFingerprint(run)) === true;
    if (row.status !== "waiting_for_user" && row.answer_kind !== null && !duplicateAcceptedAnswer) {
      throw new ChatControlError("CHAT_COMMAND_CONFLICT", 409);
    }
    if (row.status !== "waiting_for_user" && !duplicateAcceptedAnswer) {
      throw new ChatControlError("CHAT_QUESTION_NOT_FOUND", 409);
    }
    return {
      generatedBytes: row.generated_bytes,
      selection: {
        modelKey: row.model_key,
        providerModelId: row.provider_model_id,
        reasoningEffort: row.reasoning_effort,
      },
      stepCount: row.step_count,
      usage: parsePersistedUsage(row.token_usage),
    };
  }

  async prepareSteer(
    threadId: string,
    researcherId: string,
    input: import("./chat-control.js").SteerInput,
  ): Promise<Readonly<{ duplicate: boolean; receipt: CommandReceipt }>> {
    const client = await this.pool.connect();
    try {
      await beginSessionMutation(client, threadId);
      await loadOwnedThreadForUpdate(client, threadId, researcherId);
      const existing = await loadCommand(client, threadId, input.inputId);
      if (existing !== null) {
        assertMatchingCommand(existing, "steer", input.expectedTurnId, input.fingerprint);
        await client.query("COMMIT");
        return { duplicate: true, receipt: existing.receipt };
      }
      const current = await loadCurrentRunForUpdate(client, threadId);
      if (current === null || current.id !== input.expectedTurnId) {
        throw new ChatControlError("STALE_CHAT_TURN", 409);
      }
      if (current.status !== "running" || !isSteerableTurn(current.kind)) {
        throw new ChatControlError("CHAT_TURN_NOT_STEERABLE", 409);
      }
      await insertCommand(client, {
        fingerprint: input.fingerprint,
        id: input.inputId,
        kind: "steer",
        status: "pending",
        threadId,
        turnId: input.expectedTurnId,
      });
      await client.query("COMMIT");
      return {
        duplicate: false,
        receipt: {
          commandId: input.inputId,
          errorCode: null,
          kind: "steer",
          status: "pending",
          turnId: input.expectedTurnId,
        },
      };
    } catch (error) {
      await client.query("ROLLBACK").catch(() => undefined);
      throw error;
    } finally {
      client.release();
    }
  }

  async acceptSteer(
    threadId: string,
    researcherId: string,
    input: import("./chat-control.js").SteerInput,
  ): Promise<CommandReceipt> {
    const client = await this.pool.connect();
    try {
      await beginSessionMutation(client, threadId);
      await loadOwnedThreadForUpdate(client, threadId, researcherId);
      const command = await loadCommand(client, threadId, input.inputId);
      if (command === null) throw new ChatControlError("CHAT_COMMAND_CONFLICT", 409);
      assertMatchingCommand(command, "steer", input.expectedTurnId, input.fingerprint);
      if (command.receipt.status === "rejected") {
        throw new ChatControlError("CHAT_COMMAND_CONFLICT", 409);
      }
      if (command.receipt.status === "pending") {
        await client.query(`
          UPDATE agent.chat_command
          SET status = 'accepted', updated_at = pg_catalog.clock_timestamp()
          WHERE thread_id = $1::uuid AND id = $2::uuid AND status = 'pending'
        `, [threadId, input.inputId]);
        await insertTimelineEntry(client, {
          entryId: `user:${input.inputId}`,
          kind: "user_input",
          payload: { content: input.content, inputId: input.inputId, source: "steer" },
          threadId,
          turnId: input.expectedTurnId,
        });
        await touchSession(client, threadId);
      }
      await client.query("COMMIT");
      return {
        commandId: input.inputId,
        errorCode: null,
        kind: "steer",
        status: "accepted",
        turnId: input.expectedTurnId,
      };
    } catch (error) {
      await client.query("ROLLBACK").catch(() => undefined);
      throw error;
    } finally {
      client.release();
    }
  }

  async rejectPendingCommand(
    threadId: string,
    commandId: string,
    code: string,
  ): Promise<void> {
    await this.pool.query(`
      UPDATE agent.chat_command
      SET status = 'rejected', error_code = $3, updated_at = pg_catalog.clock_timestamp()
      WHERE thread_id = $1::uuid AND id = $2::uuid AND status = 'pending'
    `, [threadId, commandId, code]);
  }

  async prepareStop(
    threadId: string,
    researcherId: string,
    input: import("./chat-control.js").StopInput,
  ): Promise<Readonly<{ duplicate: boolean; previousStatus: "running" | "waiting_for_user"; receipt: CommandReceipt }>> {
    const client = await this.pool.connect();
    try {
      await beginSessionMutation(client, threadId);
      await loadOwnedThreadForUpdate(client, threadId, researcherId);
      const existing = await loadCommand(client, threadId, input.commandId);
      if (existing !== null) {
        assertMatchingCommand(existing, "stop", input.expectedTurnId, input.fingerprint);
        const turn = await loadRunForUpdate(client, input.expectedTurnId);
        if (turn === null) throw new ChatControlError("STALE_CHAT_TURN", 409);
        await client.query("COMMIT");
        return {
          duplicate: true,
          previousStatus: turn.status === "waiting_for_user" ? "waiting_for_user" : "running",
          receipt: existing.receipt,
        };
      }
      const current = await loadCurrentRunForUpdate(client, threadId);
      if (current === null || current.id !== input.expectedTurnId) {
        throw new ChatControlError("STALE_CHAT_TURN", 409);
      }
      if (current.status !== "running" && current.status !== "waiting_for_user") {
        throw new ChatControlError("STALE_CHAT_TURN", 409);
      }
      await insertCommand(client, {
        fingerprint: input.fingerprint,
        id: input.commandId,
        kind: "stop",
        status: "pending",
        threadId,
        turnId: input.expectedTurnId,
      });
      const changed = await client.query(`
        UPDATE agent.agent_run
        SET status = 'stopping'
        WHERE thread_id = $1::uuid AND id = $2::uuid AND status = $3
      `, [threadId, input.expectedTurnId, current.status]);
      if (changed.rowCount !== 1) throw new ChatControlError("STALE_CHAT_TURN", 409);
      await client.query("COMMIT");
      return { duplicate: false, previousStatus: current.status, receipt: {
        commandId: input.commandId,
        errorCode: null,
        kind: "stop",
        status: "pending",
        turnId: input.expectedTurnId,
      } };
    } catch (error) {
      await client.query("ROLLBACK").catch(() => undefined);
      throw error;
    } finally {
      client.release();
    }
  }

  async finishStop(
    threadId: string,
    researcherId: string,
    commandId: string,
    turnId: string,
    usage?: PersistedTokenUsage,
  ): Promise<CommandReceipt> {
    const client = await this.pool.connect();
    try {
      await beginSessionMutation(client, threadId);
      await loadOwnedThreadForUpdate(client, threadId, researcherId);
      const command = await loadCommand(client, threadId, commandId);
      if (command === null || command.receipt.kind !== "stop" || command.receipt.turnId !== turnId) {
        throw new ChatControlError("CHAT_COMMAND_CONFLICT", 409);
      }
      if (command.receipt.status === "accepted") {
        await client.query("COMMIT");
        return command.receipt;
      }
      if (command.receipt.status === "rejected") {
        throw new ChatControlError("CHAT_COMMAND_CONFLICT", 409);
      }
      const stopped = await client.query(`
        UPDATE agent.agent_run
        SET status = 'stopped',
            token_usage = COALESCE(token_usage, $3::jsonb),
            completed_at = pg_catalog.clock_timestamp()
        WHERE thread_id = $1::uuid AND id = $2::uuid AND status = 'stopping'
      `, [threadId, turnId, persistedUsage(usage)]);
      if (stopped.rowCount !== 1) {
        const terminal = await client.query<{ status: TurnStatus }>(`
          SELECT status
          FROM agent.agent_run
          WHERE thread_id = $1::uuid AND id = $2::uuid
        `, [threadId, turnId]);
        if (terminal.rows[0]?.status !== "stopped") {
          throw new ChatControlError("STALE_CHAT_TURN", 409);
        }
      }
      await client.query(`
        UPDATE agent.chat_command
        SET status = 'accepted', updated_at = pg_catalog.clock_timestamp()
        WHERE thread_id = $1::uuid AND id = $2::uuid AND status = 'pending'
      `, [threadId, commandId]);
      await finishTimeline(client, threadId, turnId, "stopped");
      await client.query(`
        UPDATE agent.chat_interrupt
        SET status = 'stopped', answered_at = pg_catalog.clock_timestamp()
        WHERE thread_id = $1::uuid AND turn_id = $2::uuid AND status = 'pending'
      `, [threadId, turnId]);
      await client.query(`
        UPDATE agent.chat_timeline_entry
        SET payload = pg_catalog.jsonb_set(payload, '{status}', '"stopped"'::jsonb),
            updated_at = pg_catalog.clock_timestamp()
        WHERE thread_id = $1::uuid AND turn_id = $2::uuid AND kind = 'question'
          AND payload->>'status' = 'pending'
      `, [threadId, turnId]);
      await touchSession(client, threadId);
      await client.query("COMMIT");
      return { commandId, errorCode: null, kind: "stop", status: "accepted", turnId };
    } catch (error) {
      await client.query("ROLLBACK").catch(() => undefined);
      throw error;
    } finally {
      client.release();
    }
  }

  async discardSuspendedRun(runId: string): Promise<void> {
    await this.pool.query(`
      DELETE FROM agent."mastra_workflow_snapshot"
      WHERE run_id = $1
    `, [runId]);
  }

  async commandReceipt(
    threadId: string,
    researcherId: string,
    commandId: string,
  ): Promise<CommandReceipt> {
    const ownership = await this.ownership(threadId, researcherId);
    if (ownership !== "owned") throw new SessionNotFoundError();
    const command = await loadCommand(this.pool, threadId, commandId);
    if (command === null) throw new SessionNotFoundError();
    return command.receipt;
  }

  async timeline(
    threadId: string,
    researcherId: string,
    before: TimelineCursor | undefined,
    limit: number,
  ): Promise<TimelinePage> {
    if (await this.ownership(threadId, researcherId) !== "owned") {
      throw new SessionNotFoundError();
    }
    const parameters: unknown[] = [threadId];
    const beforeClause = before === undefined
      ? ""
      : "AND (run.started_at, run.id) < ($2::timestamptz, $3::uuid)";
    if (before !== undefined) parameters.push(before.startedAt, before.turnId);
    parameters.push(limit + 1, limit);
    const candidateLimitParameter = parameters.length - 1;
    const pageLimitParameter = parameters.length;
    const result = await this.pool.query<TimelineRow>(`
      WITH candidate_turns AS (
        SELECT
          run.id,
          run.status,
          run.started_at,
          run.completed_at,
          pg_catalog.row_number() OVER (
            ORDER BY run.started_at DESC, run.id DESC
          ) AS page_rank
        FROM agent.agent_run AS run
        WHERE run.thread_id = $1::uuid ${beforeClause}
        ORDER BY run.started_at DESC, run.id DESC
        LIMIT $${candidateLimitParameter}
      ), selected_turns AS (
        SELECT *
        FROM candidate_turns
        WHERE page_rank <= $${pageLimitParameter}
      )
      SELECT
        turn.id::text AS turn_id,
        turn.status AS turn_status,
        pg_catalog.to_char(
          turn.started_at AT TIME ZONE 'UTC',
          'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'
        ) AS turn_started_at,
        CASE WHEN turn.completed_at IS NULL THEN NULL ELSE pg_catalog.to_char(
          turn.completed_at AT TIME ZONE 'UTC',
          'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'
        ) END AS turn_completed_at,
        entry.entry_id,
        entry.sequence::text,
        entry.kind,
        entry.payload,
        CASE WHEN entry.created_at IS NULL THEN NULL ELSE pg_catalog.to_char(
          entry.created_at AT TIME ZONE 'UTC',
          'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'
        ) END AS created_at,
        EXISTS(
          SELECT 1 FROM candidate_turns WHERE page_rank > $${pageLimitParameter}
        ) AS has_more
      FROM selected_turns AS turn
      LEFT JOIN agent.chat_timeline_entry AS entry
        ON entry.thread_id = $1::uuid
       AND entry.turn_id = turn.id
      ORDER BY turn.started_at ASC, turn.id ASC, entry.sequence ASC NULLS FIRST
    `, parameters);
    const turns: Array<{
      completedAt: string | null;
      entries: ChatTimelineEntry[];
      id: string;
      startedAt: string;
      status: TurnStatus;
    }> = [];
    for (const row of result.rows) {
      let turn = turns.at(-1);
      if (turn?.id !== row.turn_id) {
        turn = {
          completedAt: row.turn_completed_at,
          entries: [],
          id: row.turn_id,
          startedAt: row.turn_started_at,
          status: row.turn_status,
        };
        turns.push(turn);
      }
      if (row.entry_id !== null) turn.entries.push(timelineEntryFromRow(row));
    }
    const oldest = turns[0];
    return {
      nextCursor: result.rows[0]?.has_more === true && oldest !== undefined
        ? encodeTimelineCursor({ startedAt: oldest.startedAt, turnId: oldest.id })
        : null,
      turns,
    };
  }

  async persistAssistantMessage(
    threadId: string,
    runId: string,
    messageId: string,
    content: string,
  ): Promise<void> {
    await withSessionMutation(this.pool, threadId, async (client) => {
      await client.query(`
      INSERT INTO agent.chat_timeline_entry (
        thread_id, entry_id, turn_id, kind, payload
      )
      SELECT
        run.thread_id,
        $3,
        run.id,
        'assistant_message',
        pg_catalog.jsonb_build_object(
          'content', $4::text,
          'status', CASE
            WHEN run.status = 'failed' THEN 'failed'
            WHEN run.status = ANY (ARRAY['stopping', 'stopped']) THEN 'stopped'
            WHEN run.status = ANY (ARRAY['waiting_for_user', 'completed']) THEN 'complete'
            ELSE 'streaming'
          END
        )
      FROM agent.agent_run AS run
      WHERE run.thread_id = $1::uuid AND run.id = $2::uuid
      ON CONFLICT (thread_id, entry_id) DO UPDATE
      SET payload = EXCLUDED.payload, updated_at = pg_catalog.clock_timestamp()
      WHERE agent.chat_timeline_entry.turn_id = EXCLUDED.turn_id
        AND agent.chat_timeline_entry.kind = 'assistant_message'
      `, [threadId, runId, `assistant:${messageId}`, content]);
    });
  }

  async persistToolActivity(
    threadId: string,
    runId: string,
    toolCallId: string,
    name: string,
    status: "running" | "complete" | "failed",
  ): Promise<void> {
    await withSessionMutation(this.pool, threadId, async (client) => {
      await client.query(`
      INSERT INTO agent.chat_timeline_entry (
        thread_id, entry_id, turn_id, kind, payload
      )
      SELECT
        run.thread_id,
        $3,
        run.id,
        'tool_activity',
        pg_catalog.jsonb_build_object(
          'name', $4::text,
          'status', CASE
            WHEN $5::text != 'running' THEN $5::text
            WHEN run.status = 'failed' THEN 'failed'
            WHEN run.status = ANY (ARRAY['stopping', 'stopped']) THEN 'stopped'
            WHEN run.status = ANY (ARRAY['waiting_for_user', 'completed']) THEN 'complete'
            ELSE $5::text
          END
        )
      FROM agent.agent_run AS run
      WHERE run.thread_id = $1::uuid AND run.id = $2::uuid
      ON CONFLICT (thread_id, entry_id) DO UPDATE
      SET payload = EXCLUDED.payload, updated_at = pg_catalog.clock_timestamp()
      WHERE agent.chat_timeline_entry.turn_id = EXCLUDED.turn_id
        AND agent.chat_timeline_entry.kind = 'tool_activity'
      `, [threadId, runId, `tool:${toolCallId}`, name, status]);
    });
  }

  async markWaiting(
    runId: string,
    usage: PersistedTokenUsage | undefined,
    stepCount: number,
    generatedBytes: number,
    question: PendingQuestion,
  ): Promise<void> {
    const threadId = await threadIdForRun(this.pool, runId);
    const client = await this.pool.connect();
    try {
      await beginSessionMutation(client, threadId);
      const run = await loadRunForUpdate(client, runId);
      if (run === null || run.status !== "running") throw new ChatRunConflictError();
      const result = await client.query(`
        UPDATE agent.agent_run
        SET status = 'waiting_for_user',
            token_usage = $2::jsonb,
            step_count = $3,
            generated_bytes = $4
        WHERE id = $1::uuid AND status = 'running'
      `, [runId, persistedUsage(usage), stepCount, generatedBytes]);
      if (result.rowCount !== 1) throw new ChatRunConflictError();
      await client.query(`
        INSERT INTO agent.chat_interrupt (
          thread_id, id, turn_id, tool_call_id, question, options, selection_mode, status
        ) VALUES ($1::uuid, $2, $3::uuid, $4, $5, $6::jsonb, $7, 'pending')
      `, [
        run.threadId,
        question.interruptId,
        runId,
        question.toolCallId,
        question.question,
        question.options === null ? null : JSON.stringify(question.options),
        question.selectionMode,
      ]);
      await insertTimelineEntry(client, {
        entryId: `question:${question.interruptId}`,
        kind: "question",
        payload: { ...question, status: "pending" },
        threadId: run.threadId,
        turnId: runId,
      });
      await finalizeOpenTimelineItems(client, run.threadId, runId, "complete");
      await touchSession(client, run.threadId);
      await client.query("COMMIT");
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
    stepCount = 0,
    generatedBytes = 0,
  ): Promise<"completed" | "stopped"> {
    const threadId = await threadIdForRun(this.pool, runId);
    const client = await this.pool.connect();
    try {
      await beginSessionMutation(client, threadId);
      const run = await loadRunForUpdate(client, runId);
      if (run === null) throw new ChatRunConflictError();
      if (run.status === "stopping" || run.status === "stopped") {
        await client.query("ROLLBACK");
        return "stopped";
      }
      if (run.status === "completed") {
        await client.query("ROLLBACK");
        return "completed";
      }
      const result = await client.query(`
        UPDATE agent.agent_run
        SET status = 'completed',
            token_usage = $2::jsonb,
            step_count = $3,
            generated_bytes = $4,
            completed_at = pg_catalog.clock_timestamp()
        WHERE id = $1::uuid AND status = 'running'
      `, [runId, persistedUsage(usage), stepCount, generatedBytes]);
      if (result.rowCount !== 1) throw new ChatRunConflictError();
      await finishTimeline(client, run.threadId, runId, "completed");
      await touchSession(client, run.threadId);
      await client.query("COMMIT");
      return "completed";
    } catch (error) {
      await client.query("ROLLBACK").catch(() => undefined);
      throw error;
    } finally {
      client.release();
    }
  }

  async markFailed(
    runId: string,
    usage: PersistedTokenUsage | undefined,
    code: AgentFailureCode = "INTERNAL_FAILURE",
    stepCount = 0,
    generatedBytes = 0,
  ): Promise<"failed" | "stopped"> {
    const threadId = await threadIdForRun(this.pool, runId);
    const client = await this.pool.connect();
    try {
      await beginSessionMutation(client, threadId);
      const run = await loadRunForUpdate(client, runId);
      if (run === null) throw new ChatRunConflictError();
      if (run.status === "stopped" || run.status === "failed") {
        await client.query("ROLLBACK");
        return run.status;
      }
      const terminalStatus = run.status === "stopping" ? "stopped" : "failed";
      const result = await client.query(`
        UPDATE agent.agent_run
        SET status = $2,
            token_usage = COALESCE(token_usage, $3::jsonb),
            step_count = GREATEST(step_count, $4),
            generated_bytes = GREATEST(generated_bytes, $5),
            terminal_error_code = CASE WHEN $2 = 'failed' THEN $6 ELSE NULL END,
            completed_at = pg_catalog.clock_timestamp()
        WHERE id = $1::uuid
          AND status = ANY (ARRAY['running', 'stopping'])
      `, [runId, terminalStatus, persistedUsage(usage), stepCount, generatedBytes, code]);
      if (result.rowCount === 1) {
        await finishTimeline(client, run.threadId, runId, terminalStatus, code);
        await touchSession(client, run.threadId);
      } else {
        throw new ChatRunConflictError();
      }
      await client.query("COMMIT");
      return terminalStatus;
    } catch (error) {
      await client.query("ROLLBACK").catch(() => undefined);
      throw error;
    } finally {
      client.release();
    }
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

  async persistA2UIActivity(activity: PersistedA2UIActivity): Promise<void> {
    if (
      !isResearchA2UIMessageId(activity.messageId)
      || activity.ownerMessageId.length === 0
      || activity.ownerMessageId.length > 220
      || /[\u0000-\u001f\u007f]/.test(activity.ownerMessageId)
      || !Number.isInteger(activity.sequence)
      || activity.sequence < 1
      || activity.sequence > 1_000_000
    ) {
      throw new TranscriptConflictError();
    }
    const projected = projectResearchA2UIContent(activity.content);
    if (
      canonicalJson(projected.content) !== canonicalJson(activity.content)
      || projected.kind !== activity.lifecycle
    ) {
      throw new TranscriptConflictError();
    }
    // Mastra emits Tool results before its owning Assistant message is always
    // committed. This bounded persistence barrier keeps reconnect/restart from
    // ever seeing an orphaned surface. The FK also enforces the invariant for
    // every writer, while the join below enforces the owning Thread and role.
    await waitForDurableCondition(async () => {
      const owner = await this.pool.query<{
        owner_role: string | null;
        owner_thread_id: string | null;
        status: string;
      }>(`
        SELECT message.role AS owner_role,
               message.thread_id AS owner_thread_id,
               run.status
        FROM agent.agent_run AS run
        LEFT JOIN agent."mastra_messages" AS message ON message.id = $3
        WHERE run.id = $1::uuid AND run.thread_id = $2::uuid
      `, [activity.runId, activity.threadId, activity.ownerMessageId]);
      const row = owner.rows[0];
      if (row === undefined) throw new TranscriptConflictError();
      if (row.owner_thread_id !== null) {
        if (row.owner_thread_id !== activity.threadId || row.owner_role !== "assistant") {
          throw new TranscriptConflictError();
        }
        return true;
      }
      if (row.status !== "running") throw new TranscriptConflictError();
      return false;
    }, "A2UI_OWNER_PERSISTENCE_TIMEOUT");
    await withSessionMutation(this.pool, activity.threadId, async (client) => {
      const result = await client.query(`
        INSERT INTO agent.a2ui_message (
        thread_id,
        id,
        run_id,
        owner_message_id,
        activity_type,
        protocol_version,
        catalog_id,
        lifecycle_status,
        sequence,
        content
      )
      SELECT
        run.thread_id,
        $3,
        run.id,
        $4,
        $5,
        $6,
        $7,
        $8,
        $9,
        $10::jsonb
      FROM agent.agent_run AS run
      JOIN agent."mastra_messages" AS message
        ON message.id = $4
       AND message.thread_id = run.thread_id::text
       AND message.role = 'assistant'
      WHERE run.id = $1::uuid AND run.thread_id = $2::uuid
        ON CONFLICT (thread_id, id) DO UPDATE
        SET lifecycle_status = EXCLUDED.lifecycle_status,
            content = EXCLUDED.content,
            updated_at = pg_catalog.clock_timestamp()
        WHERE agent.a2ui_message.run_id = EXCLUDED.run_id
          AND agent.a2ui_message.owner_message_id = EXCLUDED.owner_message_id
          AND agent.a2ui_message.activity_type = EXCLUDED.activity_type
          AND agent.a2ui_message.protocol_version = EXCLUDED.protocol_version
          AND agent.a2ui_message.catalog_id = EXCLUDED.catalog_id
          AND agent.a2ui_message.sequence = EXCLUDED.sequence
        RETURNING id
      `, [
        activity.runId,
        activity.threadId,
        activity.messageId,
        activity.ownerMessageId,
        RESEARCH_A2UI_ACTIVITY_TYPE,
        RESEARCH_A2UI_PROTOCOL_VERSION,
        RESEARCH_A2UI_CATALOG_ID,
        activity.lifecycle,
        activity.sequence,
        JSON.stringify(activity.content),
      ]);
      if (result.rowCount !== 1) throw new TranscriptConflictError();
      await client.query(`
        INSERT INTO agent.chat_timeline_entry (
          thread_id, entry_id, turn_id, kind, payload
        ) VALUES ($1::uuid, $2, $3::uuid, 'a2ui', $4::jsonb)
        ON CONFLICT (thread_id, entry_id) DO UPDATE
        SET payload = EXCLUDED.payload, updated_at = pg_catalog.clock_timestamp()
        WHERE agent.chat_timeline_entry.turn_id = EXCLUDED.turn_id
          AND agent.chat_timeline_entry.kind = 'a2ui'
      `, [
        activity.threadId,
        `a2ui:${activity.messageId}`,
        activity.runId,
        JSON.stringify({
          activityType: RESEARCH_A2UI_ACTIVITY_TYPE,
          content: activity.content,
          status: activity.lifecycle,
        }),
      ]);
    });
  }

  async durableBrowserMessages(
    threadId: string,
    researcherId: string,
  ): Promise<readonly Message[]> {
    return (await this.connectionSnapshot(threadId, researcherId)).messages;
  }

  async connectionSnapshot(
    threadId: string,
    researcherId: string,
  ): Promise<Readonly<{ latestRun: TerminalRun | null; messages: readonly Message[] }>> {
    const client = await this.pool.connect();
    try {
      // Run identity, Messages and surfaces must come from one snapshot. Separate
      // read-committed queries can straddle an owner/surface commit and make a
      // valid FK-backed surface appear orphaned to a reconnecting client.
      await client.query("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY");
      await client.query("SET LOCAL search_path = pg_catalog");
      const owner = await client.query<{ researcher_id: string }>(`
        SELECT researcher_id::text FROM agent.chat_session WHERE id = $1::uuid
      `, [threadId]);
      if (owner.rows[0] === undefined) {
        await client.query("COMMIT");
        return { latestRun: null, messages: [] };
      }
      if (owner.rows[0].researcher_id !== researcherId) throw new SessionNotFoundError();
      const messages = await loadDurableMessages(client, threadId, researcherId);
      const activities = await loadA2UIActivities(client, threadId, researcherId);
      const merged = mergeA2UIActivities(messages, activities);
      const latestRun = await loadLatestRun(client, threadId);
      await client.query("COMMIT");
      return { latestRun, messages: merged };
    } catch (error) {
      await client.query("ROLLBACK").catch(() => undefined);
      throw error;
    } finally {
      client.release();
    }
  }

  async durableBrowserMessagesForThread(threadId: string): Promise<readonly Message[]> {
    const owner = await this.pool.query<{ researcher_id: string }>(`
      SELECT researcher_id::text
      FROM agent.chat_session
      WHERE id = $1::uuid
    `, [threadId]);
    const researcherId = owner.rows[0]?.researcher_id;
    if (researcherId === undefined) throw new SessionNotFoundError();
    return this.durableBrowserMessages(threadId, researcherId);
  }

  async latestRun(threadId: string, researcherId: string): Promise<TerminalRun | null> {
    const ownership = await this.ownership(threadId, researcherId);
    if (ownership !== "owned") return null;
    return loadLatestRun(this.pool, threadId);
  }
}

type StoredRun = Readonly<{
  generatedBytes: number;
  id: string;
  kind: TurnKind;
  modelKey: string;
  providerModelId: string;
  question: PendingQuestion | null;
  reasoningEffort: RunSelection["reasoningEffort"];
  requestFingerprint: Buffer;
  researcherId: string;
  startedAt: Date;
  status: TurnStatus;
  stepCount: number;
  terminalErrorCode: string | null;
  threadId: string;
  tokenUsage: unknown;
}>;

type StoredCommand = Readonly<{
  fingerprint: Buffer;
  receipt: CommandReceipt;
}>;

type TimelineRow = Readonly<{
  created_at: string | null;
  entry_id: string | null;
  has_more: boolean;
  kind: ChatTimelineEntry["kind"] | null;
  payload: unknown;
  sequence: string | null;
  turn_completed_at: string | null;
  turn_id: string;
  turn_started_at: string;
  turn_status: TurnStatus;
}>;

async function prepareAnswerRun(
  client: PoolClient,
  options: PrepareRunOptions & Readonly<{ run: ValidatedAnswerRun }>,
): Promise<PreparedRun> {
  const run = await loadRunForUpdate(client, options.run.input.runId);
  if (run === null) throw new SessionNotFoundError();
  assertOwnedRun(run, options.run.input.threadId, options.researcherId);
  const fingerprint = chatRunFingerprint(options.run);
  const existing = await loadCommand(client, options.run.input.threadId, options.run.commandId);
  if (existing !== null) {
    assertMatchingCommand(existing, "answer", run.id, fingerprint);
    const durableMessages = await loadDurableMessages(client, run.threadId, options.researcherId);
    return duplicatePreparedRun(run, durableMessages);
  }
  if (run.status !== "waiting_for_user") {
    throw new ChatControlError("CHAT_QUESTION_NOT_FOUND", 409);
  }
  const questionResult = await client.query<{
    id: string;
    options: unknown;
    question: string;
    selection_mode: PendingQuestion["selectionMode"];
    tool_call_id: string;
  }>(`
    SELECT id, tool_call_id, question, options, selection_mode
    FROM agent.chat_interrupt
    WHERE thread_id = $1::uuid
      AND turn_id = $2::uuid
      AND id = $3
      AND status = 'pending'
    FOR UPDATE
  `, [run.threadId, run.id, options.run.interruptId]);
  const questionRow = questionResult.rows[0];
  if (questionRow === undefined) throw new ChatControlError("CHAT_QUESTION_NOT_FOUND", 409);
  const question = pendingQuestionFromRow(questionRow);
  validateAnswerForQuestion(options.run.answer, question);
  const durableMessages = await loadDurableMessages(client, run.threadId, options.researcherId);
  await insertCommand(client, {
    fingerprint,
    id: options.run.commandId,
    kind: "answer",
    status: "accepted",
    threadId: run.threadId,
    turnId: run.id,
  });
  await client.query(`
    UPDATE agent.chat_interrupt
    SET status = 'answered', answer_command_id = $4::uuid, answered_at = pg_catalog.clock_timestamp()
    WHERE thread_id = $1::uuid AND turn_id = $2::uuid AND id = $3 AND status = 'pending'
  `, [run.threadId, run.id, question.interruptId, options.run.commandId]);
  await client.query(`
    UPDATE agent.chat_timeline_entry
    SET payload = pg_catalog.jsonb_set(payload, '{status}', '"answered"'::jsonb),
        updated_at = pg_catalog.clock_timestamp()
    WHERE thread_id = $1::uuid AND entry_id = $2 AND kind = 'question'
  `, [run.threadId, `question:${question.interruptId}`]);
  await insertTimelineEntry(client, {
    entryId: `user:${options.run.commandId}`,
    kind: "user_input",
    payload: {
      content: typeof options.run.answer === "string"
        ? options.run.answer
        : options.run.answer.join(", "),
      inputId: options.run.commandId,
      source: "answer",
    },
    threadId: run.threadId,
    turnId: run.id,
  });
  const resumed = await client.query(`
    UPDATE agent.agent_run
    SET status = 'running', token_usage = NULL
    WHERE thread_id = $1::uuid AND id = $2::uuid AND status = 'waiting_for_user'
  `, [run.threadId, run.id]);
  if (resumed.rowCount !== 1) throw new ChatControlError("CHAT_QUESTION_NOT_FOUND", 409);
  await touchSession(client, run.threadId);
  return {
    durableMessages,
    execution: "resume",
    generateTitle: false,
    kind: "new",
    status: "running",
  };
}

async function loadRunForUpdate(client: PoolClient, runId: string): Promise<StoredRun | null> {
  const result = await client.query<{
    generated_bytes: number;
    id: string;
    kind: TurnKind;
    model_key: string;
    provider_model_id: string;
    interrupt_id: string | null;
    options: unknown;
    question: string | null;
    reasoning_effort: RunSelection["reasoningEffort"];
    request_fingerprint: Buffer;
    researcher_id: string;
    started_at: Date;
    status: TurnStatus;
    step_count: number;
    selection_mode: PendingQuestion["selectionMode"] | null;
    terminal_error_code: string | null;
    thread_id: string;
    token_usage: unknown;
    tool_call_id: string | null;
  }>(`
    SELECT
      run.id::text,
      run.thread_id::text,
      session.researcher_id::text,
      run.kind,
      run.request_fingerprint,
      run.model_key,
      run.provider_model_id,
      interrupt.id AS interrupt_id,
      interrupt.tool_call_id,
      interrupt.question,
      interrupt.options,
      interrupt.selection_mode,
      run.reasoning_effort,
      run.status,
      run.token_usage,
      run.step_count,
      run.generated_bytes,
      run.terminal_error_code,
      run.started_at
    FROM agent.agent_run AS run
    JOIN agent.chat_session AS session ON session.id = run.thread_id
    LEFT JOIN agent.chat_interrupt AS interrupt
      ON interrupt.thread_id = run.thread_id
     AND interrupt.turn_id = run.id
     AND interrupt.status = 'pending'
    WHERE run.id = $1::uuid
    FOR UPDATE OF run, session
  `, [runId]);
  const row = result.rows[0];
  if (row === undefined) return null;
  return {
    generatedBytes: row.generated_bytes,
    id: row.id,
    kind: row.kind,
    modelKey: row.model_key,
    providerModelId: row.provider_model_id,
    question: row.interrupt_id === null ? null : pendingQuestionFromRow({
      id: row.interrupt_id,
      options: row.options,
      question: row.question ?? "",
      selection_mode: row.selection_mode ?? "free_text",
      tool_call_id: row.tool_call_id ?? "",
    }),
    reasoningEffort: row.reasoning_effort,
    requestFingerprint: row.request_fingerprint,
    researcherId: row.researcher_id,
    startedAt: exactDate(row.started_at),
    status: row.status,
    stepCount: row.step_count,
    terminalErrorCode: row.terminal_error_code,
    threadId: row.thread_id,
    tokenUsage: row.token_usage,
  };
}

async function threadIdForRun(database: Pool, runId: string): Promise<string> {
  const result = await database.query<{ thread_id: string }>(`
    SELECT thread_id::text
    FROM agent.agent_run
    WHERE id = $1::uuid
  `, [runId]);
  const threadId = result.rows[0]?.thread_id;
  if (threadId === undefined) throw new ChatRunConflictError();
  return threadId;
}

async function loadCurrentRunForUpdate(client: PoolClient, threadId: string): Promise<StoredRun | null> {
  const result = await client.query<{ id: string }>(`
    SELECT id::text
    FROM agent.agent_run
    WHERE thread_id = $1::uuid
      AND status = ANY (ARRAY['running', 'waiting_for_user', 'stopping'])
    ORDER BY started_at DESC, id DESC
    LIMIT 1
    FOR UPDATE
  `, [threadId]);
  const id = result.rows[0]?.id;
  return id === undefined ? null : loadRunForUpdate(client, id);
}

function duplicatePreparedRun(
  run: StoredRun,
  durableMessages: readonly Message[],
): PreparedRun {
  return {
    durableMessages,
    generateTitle: false,
    kind: "duplicate",
    question: run.question,
    selection: {
      modelKey: run.modelKey,
      providerModelId: run.providerModelId,
      reasoningEffort: run.reasoningEffort,
    },
    status: run.status,
    terminalErrorCode: run.terminalErrorCode,
  };
}

function assertOwnedRun(run: StoredRun, threadId: string, researcherId: string): void {
  if (run.threadId !== threadId || run.researcherId !== researcherId) {
    throw new SessionNotFoundError();
  }
}

async function loadCommand(
  database: Pick<Pool | PoolClient, "query">,
  threadId: string,
  commandId: string,
): Promise<StoredCommand | null> {
  const result = await database.query<{
    error_code: string | null;
    id: string;
    kind: CommandKind;
    request_fingerprint: Buffer;
    status: CommandReceipt["status"];
    turn_id: string;
  }>(`
    SELECT id::text, turn_id::text, kind, request_fingerprint, status, error_code
    FROM agent.chat_command
    WHERE thread_id = $1::uuid AND id = $2::uuid
  `, [threadId, commandId]);
  const row = result.rows[0];
  return row === undefined ? null : {
    fingerprint: row.request_fingerprint,
    receipt: {
      commandId: row.id,
      errorCode: row.error_code,
      kind: row.kind,
      status: row.status,
      turnId: row.turn_id,
    },
  };
}

function assertMatchingCommand(
  command: StoredCommand,
  kind: CommandKind,
  turnId: string,
  fingerprint: Buffer,
): void {
  if (
    command.receipt.kind !== kind
    || command.receipt.turnId !== turnId
    || !command.fingerprint.equals(fingerprint)
  ) {
    throw new ChatControlError("CHAT_COMMAND_CONFLICT", 409);
  }
}

async function insertCommand(
  client: PoolClient,
  command: Readonly<{
    fingerprint: Buffer;
    id: string;
    kind: CommandKind;
    status: "pending" | "accepted";
    threadId: string;
    turnId: string;
  }>,
): Promise<void> {
  await client.query(`
    INSERT INTO agent.chat_command (
      thread_id, id, turn_id, kind, request_fingerprint, status
    ) VALUES ($1::uuid, $2::uuid, $3::uuid, $4, $5, $6)
  `, [command.threadId, command.id, command.turnId, command.kind, command.fingerprint, command.status]);
}

async function insertTimelineEntry(
  client: PoolClient,
  entry: Readonly<{
    entryId: string;
    kind: ChatTimelineEntry["kind"];
    payload: object;
    threadId: string;
    turnId: string;
  }>,
): Promise<void> {
  await client.query(`
    INSERT INTO agent.chat_timeline_entry (
      thread_id, entry_id, turn_id, kind, payload
    ) VALUES ($1::uuid, $2, $3::uuid, $4, $5::jsonb)
    ON CONFLICT (thread_id, entry_id) DO NOTHING
  `, [entry.threadId, entry.entryId, entry.turnId, entry.kind, JSON.stringify(entry.payload)]);
}

async function touchSession(client: PoolClient, threadId: string): Promise<void> {
  await client.query(`
    UPDATE agent.chat_session
    SET updated_at = pg_catalog.clock_timestamp()
    WHERE id = $1::uuid
  `, [threadId]);
}

async function finalizeOpenTimelineItems(
  client: PoolClient,
  threadId: string,
  runId: string,
  assistantStatus: "complete" | "stopped" | "failed",
): Promise<void> {
  await client.query(`
    UPDATE agent.chat_timeline_entry
    SET payload = pg_catalog.jsonb_set(payload, '{status}', $3::jsonb),
        updated_at = pg_catalog.clock_timestamp()
    WHERE thread_id = $1::uuid AND turn_id = $2::uuid
      AND kind = 'assistant_message' AND payload->>'status' = 'streaming'
  `, [threadId, runId, JSON.stringify(assistantStatus)]);
  const toolStatus = assistantStatus === "complete" ? "complete" : assistantStatus;
  await client.query(`
    UPDATE agent.chat_timeline_entry
    SET payload = pg_catalog.jsonb_set(payload, '{status}', $3::jsonb),
        updated_at = pg_catalog.clock_timestamp()
    WHERE thread_id = $1::uuid AND turn_id = $2::uuid
      AND kind = 'tool_activity' AND payload->>'status' = 'running'
  `, [threadId, runId, JSON.stringify(toolStatus)]);
}

async function finishTimeline(
  client: PoolClient,
  threadId: string,
  runId: string,
  status: "completed" | "stopped" | "failed",
  errorCode?: string,
): Promise<void> {
  await finalizeOpenTimelineItems(
    client,
    threadId,
    runId,
    status === "completed" ? "complete" : status,
  );
  await insertTimelineEntry(client, {
    entryId: `outcome:${runId}`,
    kind: "turn_outcome",
    payload: errorCode === undefined ? { status } : { errorCode, status },
    threadId,
    turnId: runId,
  });
}

function pendingQuestionFromRow(row: Readonly<{
  id: string;
  options: unknown;
  question: string;
  selection_mode: PendingQuestion["selectionMode"];
  tool_call_id: string;
}>): PendingQuestion {
  const options = row.options === null ? null : readQuestionOptions(row.options);
  if (
    typeof row.id !== "string"
    || typeof row.tool_call_id !== "string"
    || typeof row.question !== "string"
    || !["free_text", "single_select", "multi_select"].includes(row.selection_mode)
  ) {
    throw new TranscriptConflictError();
  }
  return {
    interruptId: row.id,
    options,
    question: row.question,
    selectionMode: row.selection_mode,
    toolCallId: row.tool_call_id,
  };
}

function readQuestionOptions(value: unknown): readonly import("./chat-control.js").QuestionOption[] {
  if (!Array.isArray(value)) throw new TranscriptConflictError();
  return value.map((entry) => {
    if (!isRecord(entry) || typeof entry.label !== "string") throw new TranscriptConflictError();
    if (entry.description !== undefined && typeof entry.description !== "string") {
      throw new TranscriptConflictError();
    }
    return entry.description === undefined
      ? { label: entry.label }
      : { description: entry.description, label: entry.label };
  });
}

function requireProviderModelId(value: string | undefined): string {
  if (value === undefined) throw new TranscriptConflictError();
  return value;
}

function isSteerableTurn(kind: unknown): kind is TurnKind {
  return kind === "prompt" || kind === "continue";
}

function parsePersistedUsage(value: unknown): PersistedTokenUsage | undefined {
  if (!isRecord(value) || value.reported !== true) return undefined;
  return value as PersistedTokenUsage;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function timelineEntryFromRow(row: TimelineRow): ChatTimelineEntry {
  if (!isCanonicalTimelineEntry(row) || !isRecord(row.payload)) {
    throw new TranscriptConflictError();
  }
  return {
    createdAt: row.created_at,
    entryId: row.entry_id,
    kind: row.kind,
    payload: row.payload,
    turnId: row.turn_id,
  } as ChatTimelineEntry;
}

function isCanonicalTimelineEntry(row: TimelineRow): row is TimelineRow & Readonly<{
  created_at: string;
  entry_id: string;
  kind: ChatTimelineEntry["kind"];
  sequence: string;
}> {
  return typeof row.entry_id === "string"
    && typeof row.created_at === "string"
    && typeof row.turn_id === "string"
    && Number.isSafeInteger(Number(row.sequence))
    && typeof row.kind === "string"
    && [
      "user_input",
      "assistant_message",
      "tool_activity",
      "a2ui",
      "question",
      "turn_outcome",
    ].includes(row.kind);
}

async function loadLatestRun(client: Pool | PoolClient, threadId: string): Promise<TerminalRun | null> {
  const result = await client.query<{
    id: string;
    interrupt_id: string | null;
    kind: TurnKind;
    status: TerminalRun["status"];
    started_at: string;
    terminal_error_code: string | null;
    model_key: string;
    options: unknown;
    provider_model_id: string;
    question: string | null;
    reasoning_effort: RunSelection["reasoningEffort"];
    selection_mode: PendingQuestion["selectionMode"] | null;
    tool_call_id: string | null;
  }>(`
    SELECT
      run.id::text,
      run.kind,
      run.status,
      run.terminal_error_code,
      run.model_key,
      run.provider_model_id,
      run.reasoning_effort,
      pg_catalog.to_char(
        run.started_at AT TIME ZONE 'UTC',
        'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'
      ) AS started_at,
      interrupt.id AS interrupt_id,
      interrupt.tool_call_id,
      interrupt.question,
      interrupt.options,
      interrupt.selection_mode
    FROM agent.agent_run AS run
    LEFT JOIN agent.chat_interrupt AS interrupt
      ON interrupt.thread_id = run.thread_id
     AND interrupt.turn_id = run.id
     AND interrupt.status = 'pending'
    WHERE run.thread_id = $1::uuid
    ORDER BY run.started_at DESC, run.id DESC
    LIMIT 1
  `, [threadId]);
  const row = result.rows[0];
  return row === undefined ? null : {
    id: row.id,
    kind: row.kind,
    question: row.interrupt_id === null ? null : pendingQuestionFromRow({
      id: row.interrupt_id,
      options: row.options,
      question: row.question ?? "",
      selection_mode: row.selection_mode ?? "free_text",
      tool_call_id: row.tool_call_id ?? "",
    }),
    startedAt: row.started_at,
    status: row.status,
    terminalErrorCode: row.terminal_error_code,
    selection: { modelKey: row.model_key, providerModelId: row.provider_model_id, reasoningEffort: row.reasoning_effort },
  };
}

export function mergeA2UIActivities(
  messages: readonly Message[],
  activities: readonly StoredA2UIActivity[],
): readonly Message[] {
  const merged = [...messages];
  const insertedAfterOwner = new Map<string, number>();
  for (const activity of activities) {
    const ownerIndex = merged.findIndex((message) => message.id === activity.ownerMessageId);
    if (ownerIndex < 0) {
      throw new TranscriptConflictError();
    }
    const previousCount = insertedAfterOwner.get(activity.ownerMessageId) ?? 0;
    let insertionIndex = ownerIndex + 1 + previousCount;
    const owner = merged[ownerIndex];
    if (owner?.role === "assistant" && previousCount === 0) {
      const ownedToolCalls = new Set(owner.toolCalls?.map((call) => call.id) ?? []);
      while (insertionIndex < merged.length) {
        const candidate = merged[insertionIndex];
        if (candidate?.role !== "tool" || !ownedToolCalls.has(candidate.toolCallId)) break;
        insertionIndex += 1;
      }
    }
    merged.splice(insertionIndex, 0, activity.message);
    insertedAfterOwner.set(
      activity.ownerMessageId,
      previousCount + 1 + (insertionIndex - ownerIndex - 1 - previousCount),
    );
  }
  return merged;
}

type SessionSummaryRow = Readonly<{
  activity_at: string;
  created_at: string;
  current_turn: unknown;
  id: string;
  latest_turn: unknown;
  title: string;
  version: Date;
}>;

type OwnedThreadRow = Readonly<{
  title: string;
  version: Date;
}>;

function sessionSummaryFromRow(row: SessionSummaryRow): SessionSummary {
  let title: string;
  try {
    title = normalizeSessionTitle(row.title);
  } catch {
    throw new TranscriptConflictError();
  }
  if (title !== row.title) throw new TranscriptConflictError();
  return {
    activityAt: row.activity_at,
    createdAt: row.created_at,
    currentTurn: publicTurnFromValue(row.current_turn),
    id: row.id,
    latestTurn: publicTurnFromValue(row.latest_turn),
    title,
    version: exactDate(row.version).toISOString(),
  };
}

function publicTurnFromValue(value: unknown): PublicTurn | null {
  if (value === null) return null;
  if (!isRecord(value)) throw new TranscriptConflictError();
  const id = value.id;
  const kind = value.kind;
  const status = value.status;
  const startedAt = value.started_at;
  const modelKey = value.model_key;
  const reasoningEffort = value.reasoning_effort;
  const terminalErrorCode = value.terminal_error_code;
  if (
    typeof id !== "string"
    || !isSteerableTurn(kind)
    || !isTurnStatus(status)
    || typeof startedAt !== "string"
    || typeof modelKey !== "string"
    || typeof reasoningEffort !== "string"
    || (terminalErrorCode !== null && typeof terminalErrorCode !== "string")
  ) {
    throw new TranscriptConflictError();
  }
  let question: PendingQuestion | null = null;
  if (value.question !== null) {
    if (!isRecord(value.question)) throw new TranscriptConflictError();
    question = pendingQuestionFromRow({
      id: typeof value.question.interrupt_id === "string" ? value.question.interrupt_id : "",
      options: value.question.options,
      question: typeof value.question.question === "string" ? value.question.question : "",
      selection_mode: typeof value.question.selection_mode === "string"
        ? value.question.selection_mode as PendingQuestion["selectionMode"]
        : "free_text",
      tool_call_id: typeof value.question.tool_call_id === "string" ? value.question.tool_call_id : "",
    });
  }
  return {
    id,
    kind,
    modelKey,
    question,
    reasoningEffort,
    startedAt,
    status,
    terminalErrorCode,
  };
}

function isTurnStatus(value: unknown): value is TurnStatus {
  return typeof value === "string" && [
    "running",
    "waiting_for_user",
    "stopping",
    "completed",
    "stopped",
    "failed",
  ].includes(value);
}

async function beginSessionMutation(client: PoolClient, threadId: string): Promise<void> {
  await client.query("BEGIN");
  await client.query("SET LOCAL search_path = pg_catalog");
  await client.query("SET LOCAL statement_timeout = '10000ms'");
  await client.query(
    "SELECT pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended($1, 0))",
    [`thesistrace:agent-thread:${threadId}`],
  );
}

async function withSessionMutation<T>(
  pool: Pool,
  threadId: string,
  operation: (client: PoolClient) => Promise<T>,
): Promise<T> {
  const client = await pool.connect();
  try {
    await beginSessionMutation(client, threadId);
    const result = await operation(client);
    await client.query("COMMIT");
    return result;
  } catch (error) {
    await client.query("ROLLBACK").catch(() => undefined);
    throw error;
  } finally {
    client.release();
  }
}

async function loadOwnedThreadForUpdate(
  client: PoolClient,
  threadId: string,
  researcherId: string,
): Promise<OwnedThreadRow>;
async function loadOwnedThreadForUpdate(
  client: PoolClient,
  threadId: string,
  researcherId: string,
  required: false,
): Promise<OwnedThreadRow | null>;
async function loadOwnedThreadForUpdate(
  client: PoolClient,
  threadId: string,
  researcherId: string,
  required = true,
): Promise<OwnedThreadRow | null> {
  const result = await client.query<{
    title: string;
    version: Date;
  }>(`
    SELECT thread.title, thread."updatedAtZ" AS version
    FROM agent.chat_session AS session
    JOIN agent."mastra_threads" AS thread
      ON thread.id = session.id::text
     AND thread."resourceId" = session.researcher_id::text
    WHERE session.id = $1::uuid
      AND session.researcher_id = $2::uuid
    FOR UPDATE OF session, thread
  `, [threadId, researcherId]);
  const row = result.rows[0];
  if (result.rowCount !== 1 || row === undefined) {
    if (required) throw new SessionNotFoundError();
    return null;
  }
  return {
    title: row.title,
    version: exactDate(row.version),
  };
}

function exactDate(value: Date): Date {
  if (!(value instanceof Date) || Number.isNaN(value.getTime())) {
    throw new TranscriptConflictError();
  }
  return value;
}

function nextThreadVersion(current: Date): Date {
  return new Date(Math.max(Date.now(), exactDate(current).getTime() + 1));
}

function durableUserMessage(
  message: ValidatedPromptRun["userMessage"],
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

async function loadA2UIActivities(
  database: Pick<Pool | PoolClient, "query">,
  threadId: string,
  researcherId: string,
): Promise<readonly StoredA2UIActivity[]> {
  const result = await database.query<{
    activity_type: string;
    catalog_id: string;
    content: unknown;
    id: string;
    lifecycle_status: "error" | "loading" | "ready";
    owner_message_id: string;
    protocol_version: string;
    sequence: number;
  }>(`
    SELECT
      activity.id,
      activity.owner_message_id,
      activity.activity_type,
      activity.protocol_version,
      activity.catalog_id,
      activity.lifecycle_status,
      activity.sequence,
      activity.content
    FROM agent.a2ui_message AS activity
    JOIN agent.chat_session AS session
      ON session.id = activity.thread_id
    JOIN agent.agent_run AS run ON run.id = activity.run_id
    WHERE activity.thread_id = $1::uuid
      AND session.researcher_id = $2::uuid
    ORDER BY run.started_at ASC, run.id ASC, activity.sequence ASC
  `, [threadId, researcherId]);
  return result.rows.map((row): StoredA2UIActivity => {
    if (
      row.activity_type !== RESEARCH_A2UI_ACTIVITY_TYPE
      || row.catalog_id !== RESEARCH_A2UI_CATALOG_ID
      || row.protocol_version !== RESEARCH_A2UI_PROTOCOL_VERSION
      || !isResearchA2UIMessageId(row.id)
      || row.owner_message_id.length === 0
      || row.owner_message_id.length > 220
      || /[\u0000-\u001f\u007f]/.test(row.owner_message_id)
      || !Number.isInteger(row.sequence)
      || row.sequence < 1
      || row.sequence > 1_000_000
    ) {
      throw new TranscriptConflictError();
    }
    const projected = projectResearchA2UIContent(row.content);
    if (
      projected.kind !== row.lifecycle_status
      || canonicalJson(projected.content) !== canonicalJson(row.content)
    ) {
      throw new TranscriptConflictError();
    }
    return {
      message: {
        activityType: RESEARCH_A2UI_ACTIVITY_TYPE,
        content: projected.content,
        id: row.id,
        role: "activity",
      },
      ownerMessageId: row.owner_message_id,
    };
  });
}

function canonicalJson(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  if (value !== null && typeof value === "object") {
    return `{${Object.entries(value)
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([key, entry]) => `${JSON.stringify(key)}:${canonicalJson(entry)}`)
      .join(",")}}`;
  }
  return JSON.stringify(value);
}
