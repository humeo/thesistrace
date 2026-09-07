import { execFileSync } from "node:child_process";
import type { Page } from "@playwright/test";

import { expect, restoreResearcherSession, sameOriginHeaders, test, testProjectName } from "./auth-fixture";
import { revealToolActivity, submitChatPrompt, waitForChatTurn } from "./chat-ui";
import { proxyState, setProxyMode } from "./fault-proxy";
import { controlWorker } from "./research-run-control";

const toolPrompt = "[scripted-tool-turn] Inspect the available research context.";
const factorPrompt = "Evaluate a low-volatility Alpha idea as a Factor Evaluation using reliable ThesisTrace defaults.";
const resumePrompt = "Resume the accepted ResearchRun from this Chat and explain its authoritative Result when available.";
const runtimePath = "/api/agent/copilotkit/agent/research";
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

test("Chat shared Session binds two contexts to one Run while another Session runs independently", async ({ browser, page, researcher }, testInfo) => {
  test.setTimeout(100_000);
  const identities = observeRunRequests(page);
  const otherContext = await browser.newContext({ baseURL: process.env.THESISTRACE_TEST_WEB_ORIGIN });
  const other = await otherContext.newPage();
  const parallel = await otherContext.newPage();
  try {
    await page.goto("/chat");
    await send(page, "Keep this research conversation available on my other device.");
    await expect(status(page)).toHaveText("Run complete", { timeout: 30_000 });
    await expect(page.getByRole("textbox", { name: "Message", exact: true })).toBeEnabled();
    const sessionUrl = page.url();
    const threadId = sessionId(page);
    await restoreResearcherSession(other, researcher);
    await other.goto(sessionUrl);
    await expect(other.locator(".chat-message-user")).toHaveCount(1);
    await expect(other.getByRole("textbox", { name: "Message", exact: true })).toBeEnabled();

    setProxyMode("mcp-fault-proxy", 8150, "tool-call", "hold");
    await send(page, toolPrompt);
    await expect.poll(
      () => proxyState("mcp-fault-proxy", 8150).pending_held_tool_responses,
      { timeout: 30_000 },
    ).toBe(1);
    await expect.poll(() => identities.length).toBe(2);
    const runId = identities[1]!.runId;
    for (const client of [page, other]) {
      await expect(status(client)).toHaveText("Research Agent is working", { timeout: 10_000 });
      await expect(client.locator(".chat-main")).toHaveAttribute("data-agent-run-id", runId);
      await expect(client.getByRole("textbox", { name: "Message", exact: true })).toBeEnabled();
      await expect(client.getByRole("button", { name: "Stop", exact: true })).toBeEnabled();
      await expect(client.locator(".chat-message-user")).toHaveCount(2);
    }
    const rejected = await other.request.post(`${runtimePath}/run`, {
      data: requestInput(threadId), headers: sameOriginHeaders(),
    });
    expect(rejected.status()).toBe(200);
    const rejectionEvents = sseEvents(await rejected.text());
    expect(rejectionEvents).toMatchObject([{ type: "RUN_ERROR", code: "AGENT_RUN_CONFLICT" }]);
    expect(rejectionEvents).toHaveLength(1);
    const deletion = await other.request.delete(`/api/agent/sessions/${threadId}`, { headers: sameOriginHeaders() });
    expect(deletion.status()).toBe(409);
    expect(await deletion.json()).toEqual({ code: "CHAT_SESSION_RUN_ACTIVE" });

    await parallel.goto("/chat");
    await send(parallel, toolPrompt);
    await expect.poll(
      () => proxyState("mcp-fault-proxy", 8150).pending_held_tool_responses,
      { timeout: 30_000 },
    ).toBe(2);
    await expect(parallel).toHaveURL((url) => uuid.test(url.searchParams.get("session") ?? ""));
    expect(sessionId(parallel)).not.toBe(threadId);
    await expect(parallel.locator(".chat-main")).toHaveAttribute("data-agent-run-id", uuid);
    const parallelRunId = await parallel.locator(".chat-main").getAttribute("data-agent-run-id");
    if (!parallelRunId || !uuid.test(parallelRunId)) throw new Error("Parallel Run identity missing");
    expect(databaseFacts(researcher.id)).toMatchObject({ active_runs: 2, agent_runs: 3, user_messages: 3 });

    // Reload tears down the HTTP stream, not the accepted model invocation.
    await page.reload();
    await expect(page.locator(".chat-main")).toHaveAttribute("data-agent-run-id", runId);
    await expect(status(page)).toHaveText("Research Agent is working");
    await expect(page.locator(".chat-message-user")).toHaveCount(2);
    expect(identities).toHaveLength(2);
    expect(databaseFacts(researcher.id).user_messages).toBe(3);
    await testInfo.attach("shared-session-running", { body: await other.screenshot(), contentType: "image/png" });

    setProxyMode("mcp-fault-proxy", 8150, "tool-call", "pass");
    for (const client of [page, other, parallel]) {
      // A completed Tool and an enabled composer do not mean the Run has finished.
      await waitForChatTurn(client, client === parallel ? parallelRunId : runId);
      await expect(status(client)).toHaveText("Run complete", { timeout: 30_000 });
      await expect(client.getByRole("textbox", { name: "Message", exact: true })).toBeEnabled({ timeout: 15_000 });
      await expect((await revealToolActivity(client, "get_research_context", "complete")).last()).toBeVisible();
    }
    for (const client of [page, other]) {
      await expect(client.locator(".chat-main")).toHaveAttribute("data-agent-run-id", runId);
      await expect(client.locator(".chat-message-user")).toHaveCount(2);
    }
    const facts = databaseFacts(researcher.id);
    expect(facts).toMatchObject({ active_runs: 0, agent_runs: 3, user_messages: 3 });
    expect(facts.user_order[threadId]).toEqual(identities.map((identity) => identity.messageId));
    await testInfo.attach("shared-session-metadata", {
      body: Buffer.from(JSON.stringify({ facts, run_id: runId, thread_id: threadId })), contentType: "application/json",
    });
  } finally {
    setProxyMode("mcp-fault-proxy", 8150, "tool-call", "pass");
    await otherContext.close();
  }
});

test("Chat Host restart retains completed Tools and Core work without replaying admission", async ({ page, researcher }, testInfo) => {
  test.setTimeout(120_000);
  const identities = observeRunRequests(page);
  let workerPaused = false;
  let agentStopped = false;
  const agentContainer = `${testProjectName()}-agent-1`;
  try {
    controlWorker("pause");
    workerPaused = true;
    setProxyMode("mcp-fault-proxy", 8150, "tool-call", "hold-detail");
    await page.goto("/chat");
    await send(page, factorPrompt);
    await expect.poll(() => proxyState("mcp-fault-proxy", 8150).pending_held_tool_responses, { timeout: 30_000 }).toBe(1);
    await expect((await revealToolActivity(page, "submit_research_run", "complete")).last()).toBeVisible();
    const threadId = sessionId(page);
    const runId = identities[0]!.runId;
    const before = databaseFacts(researcher.id);
    expect(before).toMatchObject({ active_runs: 1, admissions: 1, agent_runs: 1, core_runs: 1, user_messages: 1 });
    const coreRunId = before.core_run_ids[0]!;

    docker(["stop", "--time", "15", agentContainer], 25_000);
    agentStopped = true;
    await testInfo.attach("stopped-agent-database-metadata", {
      body: Buffer.from(JSON.stringify(databaseFacts(researcher.id))), contentType: "application/json",
    });
    // exit-hook preserves SIGTERM's 128 + 15 status even after graceful drain.
    expect(docker(["inspect", "--format", "{{.State.ExitCode}}", agentContainer]).trim()).toBe("143");
    expect(docker(["logs", agentContainer])).toContain('"event":"agent_shutdown_completed"');
    docker(["start", agentContainer]);
    agentStopped = false;
    await expect.poll(async () => (await page.request.get("/api/agent/models", { headers: sameOriginHeaders() })).status(), { timeout: 30_000 }).toBe(200);
    await page.reload();
    await expect(page.locator(".chat-main")).toHaveAttribute("data-agent-run-id", runId);
    await expect(status(page)).toHaveText("Run failed", { timeout: 15_000 });
    await expect(page.getByRole("textbox", { name: "Message", exact: true })).toBeEnabled();
    await expect((await revealToolActivity(page, "submit_research_run", "complete")).last()).toBeVisible();
    await expect(page.locator(".chat-message-user")).toHaveCount(1);
    expect(identities).toHaveLength(1);
    expect(databaseFacts(researcher.id)).toMatchObject({ active_runs: 0, admissions: 1, agent_runs: 1, core_runs: 1, user_messages: 1 });

    // No Agent is polling Core while the real Research Worker finishes.
    controlWorker("unpause");
    workerPaused = false;
    await expect.poll(async () => {
      const response = await page.request.get(`/api/research-runs/${coreRunId}`);
      expect(response.status()).toBe(200);
      return (await response.json()).status;
    }, { timeout: 45_000 }).toBe("succeeded");
    setProxyMode("mcp-fault-proxy", 8150, "tool-call", "pass");
    await send(page, resumePrompt);
    await expect(page.getByRole("region", { name: "Factor Evaluation result", exact: true }).last()).toBeVisible({ timeout: 30_000 });
    await expect(page.getByRole("textbox", { name: "Message", exact: true })).toBeEnabled();
    const after = databaseFacts(researcher.id);
    expect(after).toMatchObject({ active_runs: 0, admissions: 1, agent_runs: 2, core_runs: 1, user_messages: 2 });
    expect(after.core_run_ids).toEqual(before.core_run_ids);
    expect(after.user_order[threadId]).toEqual(identities.map((identity) => identity.messageId));
    await testInfo.attach("host-restart-metadata", {
      body: Buffer.from(JSON.stringify({ after, before, graceful_exit_code: 143, run_id: runId, thread_id: threadId })), contentType: "application/json",
    });
  } finally {
    setProxyMode("mcp-fault-proxy", 8150, "tool-call", "pass");
    if (agentStopped) docker(["start", agentContainer]);
    if (workerPaused) controlWorker("unpause");
  }
});

async function send(page: Page, prompt: string): Promise<void> {
  await submitChatPrompt(page, prompt);
}

function status(page: Page) { return page.locator("[data-chat-status]"); }
function sessionId(page: Page): string {
  const id = new URL(page.url()).searchParams.get("session");
  if (id === null || !uuid.test(id)) throw new Error("A durable Session identity is required");
  return id;
}

function observeRunRequests(page: Page): Array<{ messageId: string; runId: string }> {
  const identities: Array<{ messageId: string; runId: string }> = [];
  page.on("request", (request) => {
    if (request.method() !== "POST" || new URL(request.url()).pathname !== `${runtimePath}/run`) return;
    const input = request.postDataJSON() as { messages: Array<{ id: string }>; runId: string };
    identities.push({ messageId: input.messages.at(-1)!.id, runId: input.runId });
  });
  return identities;
}

function requestInput(threadId: string) {
  return {
    context: [],
    forwardedProps: { thesistrace: { command: "prompt", modelKey: "scripted-research", reasoningEffort: "medium", sessionMode: "existing" } },
    messages: [{ content: "Competing turn must not be admitted.", id: "00000000-0000-4000-8000-000000009411", role: "user" }],
    runId: "00000000-0000-4000-8000-000000009412", state: {}, threadId, tools: [],
  };
}

function sseEvents(body: string): Array<Record<string, unknown>> {
  return body.split("\n\n").filter((frame) => frame.startsWith("data: ")).map((frame) => JSON.parse(frame.slice(6)));
}

type DatabaseFacts = Readonly<{
  active_runs: number;
  admissions: number;
  agent_runs: number;
  core_run_ids: string[];
  core_runs: number;
  user_messages: number;
  user_order: Record<string, string[]>;
}>;

function databaseFacts(researcherId: string): DatabaseFacts {
  if (!uuid.test(researcherId)) throw new Error("Database inspection requires a safe Researcher identity");
  return JSON.parse(docker([
    "exec", "--env", "PGPASSWORD=owner-test-password", `${testProjectName()}-postgres-1`,
    "psql", "--username", "thesistrace_owner", "--dbname", "thesistrace", "--tuples-only", "--no-align", "--set", "ON_ERROR_STOP=1", "--command", `
      WITH owned_runs AS (
        SELECT run.* FROM agent.agent_run AS run JOIN agent.chat_session AS session ON session.id = run.thread_id
        WHERE session.researcher_id = '${researcherId}'::uuid
      ), owned_users AS (
        SELECT message.* FROM agent.mastra_messages AS message JOIN agent.chat_session AS session ON session.id::text = message.thread_id
        WHERE session.researcher_id = '${researcherId}'::uuid AND message.role = 'user'
      ), ordered_users AS (
        SELECT thread_id, json_agg(id ORDER BY "createdAtZ", id) AS ids FROM owned_users GROUP BY thread_id
      ) SELECT json_build_object(
        'active_runs', (SELECT count(*) FROM owned_runs WHERE status = 'running'),
        'agent_runs', (SELECT count(*) FROM owned_runs),
        'user_messages', (SELECT count(*) FROM owned_users),
        'user_order', (SELECT json_object_agg(thread_id, ids) FROM ordered_users),
        'core_runs', (SELECT count(*) FROM research_runs.runs WHERE researcher_id = '${researcherId}'::uuid),
        'core_run_ids', (SELECT coalesce(json_agg(id ORDER BY id), '[]') FROM research_runs.runs WHERE researcher_id = '${researcherId}'::uuid),
        'admissions', (SELECT count(*) FROM research_runs.admission_requests WHERE researcher_id = '${researcherId}'::uuid)
      )
    `,
  ]).trim()) as DatabaseFacts;
}

function docker(arguments_: string[], timeout = 10_000): string {
  testProjectName();
  return execFileSync("docker", arguments_, { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"], timeout });
}
