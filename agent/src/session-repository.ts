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
  canonicalSubmittedBrowserMessages,
  projectDurableUiMessages,
} from "./browser-message-safety.js";
import {
  chatRunFingerprint,
  type ValidatedChatRun,
} from "./chat-request.js";
import {
  SESSION_HISTORY_PAGE_SIZE,
  UNTITLED_SESSION_TITLE,
  encodeSessionCursor,
  normalizeReplacementSessionTitle,
  normalizeSessionTitle,
  type SessionCursor,
} from "./session-management.js";
import type { PersistedTokenUsage } from "./usage-capture.js";

export type SessionOwnership = "absent" | "foreign" | "owned";
export type PreparedRun = Readonly<{
  durableMessages: readonly Message[];
  generateTitle: boolean;
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
export type SessionSummary = Readonly<{
  activeRun: boolean;
  activityAt: string;
  createdAt: string;
  id: string;
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
  providerModelId: string;
  researcherId: string;
  run: ValidatedChatRun;
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
            updated_at = pg_catalog.now()
        FROM agent.agent_run AS run
        WHERE activity.run_id = run.id
          AND activity.lifecycle_status = 'loading'
          AND run.status = 'running'
      `, [JSON.stringify(safeResearchA2UIErrorContent())]);
      const result = await client.query(`
        UPDATE agent.agent_run
        SET status = 'failed',
            token_usage = '{"reported":false}'::jsonb,
            terminal_error_code = 'AGENT_RUN_INTERRUPTED',
            completed_at = pg_catalog.now()
        WHERE status = 'running'
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
      active_run: boolean;
      activity_at: string;
      created_at: string;
      id: string;
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
        EXISTS (
          SELECT 1
          FROM agent.agent_run AS run
          WHERE run.thread_id = session.id
            AND run.status = 'running'
        ) AS active_run
      FROM agent.chat_session AS session
      JOIN agent."mastra_threads" AS thread
        ON thread.id = session.id::text
       AND thread."resourceId" = session.researcher_id::text
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
        EXISTS (
          SELECT 1
          FROM agent.agent_run AS run
          WHERE run.thread_id = session.id
            AND run.status = 'running'
        ) AS active_run
      FROM agent.chat_session AS session
      JOIN agent."mastra_threads" AS thread
        ON thread.id = session.id::text
       AND thread."resourceId" = session.researcher_id::text
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
        WHERE thread_id = $1::uuid AND status = 'running'
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
          generateTitle: false,
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
      if (
        (existingOwner === undefined && options.run.sessionMode !== "new")
        || (existingOwner !== undefined && options.run.sessionMode !== "existing")
      ) {
        throw new SessionNotFoundError();
      }

      if (existingOwner !== undefined) {
        const active = await client.query(`
          SELECT 1
          FROM agent.agent_run
          WHERE thread_id = $1::uuid AND status = 'running'
          LIMIT 1
        `, [options.run.input.threadId]);
        if (active.rowCount !== 0) throw new SessionActiveRunError();
      }

      const durableMessages = existingOwner === undefined
        ? []
        : await loadDurableMessages(
            client,
            options.run.input.threadId,
            options.researcherId,
          );
      let generateTitle = existingOwner === undefined;
      let existingThreadVersion: Date | null = null;
      if (existingOwner !== undefined) {
        const thread = await loadOwnedThreadForUpdate(
          client,
          options.run.input.threadId,
          options.researcherId,
        );
        existingThreadVersion = thread.version;
        generateTitle = thread.title === UNTITLED_SESSION_TITLE;
      }
      assertOneNewUserMessage(options.run.input.messages, durableMessages);
      const acceptedAt = new Date();
      const acceptedAtUtc = acceptedAt.toISOString();
      const acceptedThreadVersion = existingThreadVersion === null
        ? acceptedAt
        : nextThreadVersion(existingThreadVersion);
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
          UNTITLED_SESSION_TITLE,
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
      return {
        durableMessages,
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
    const result = await this.pool.query(`
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
          updated_at = pg_catalog.now()
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
  }

  async durableBrowserMessages(
    threadId: string,
    researcherId: string,
  ): Promise<readonly Message[]> {
    const client = await this.pool.connect();
    try {
      // Messages and surfaces must come from one database snapshot. Separate
      // read-committed queries can straddle an owner/surface commit and make a
      // valid FK-backed surface appear orphaned to a reconnecting client.
      await client.query("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY");
      await client.query("SET LOCAL search_path = pg_catalog");
      const owner = await client.query<{ researcher_id: string }>(`
        SELECT researcher_id::text FROM agent.chat_session WHERE id = $1::uuid
      `, [threadId]);
      if (owner.rows[0] === undefined) {
        await client.query("COMMIT");
        return [];
      }
      if (owner.rows[0].researcher_id !== researcherId) throw new SessionNotFoundError();
      const messages = await loadDurableMessages(client, threadId, researcherId);
      const activities = await loadA2UIActivities(client, threadId, researcherId);
      const merged = mergeA2UIActivities(messages, activities);
      await client.query("COMMIT");
      return merged;
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
  active_run: boolean;
  activity_at: string;
  created_at: string;
  id: string;
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
    activeRun: row.active_run,
    activityAt: row.activity_at,
    createdAt: row.created_at,
    id: row.id,
    title,
    version: exactDate(row.version).toISOString(),
  };
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

function assertOneNewUserMessage(
  submitted: readonly Message[],
  durable: readonly Message[],
): void {
  let safeSubmitted: readonly Message[];
  try {
    safeSubmitted = canonicalSubmittedBrowserMessages(submitted.slice(0, -1));
  } catch {
    throw new TranscriptConflictError();
  }
  if (
    safeSubmitted.length !== durable.length
    || JSON.stringify(safeSubmitted) !== JSON.stringify(durable)
  ) {
    throw new TranscriptConflictError();
  }
  const latest = submitted.at(-1);
  if (latest?.role !== "user" || typeof latest.content !== "string") {
    throw new TranscriptConflictError();
  }
}
