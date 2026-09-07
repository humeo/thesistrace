import type { Page } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { expect, test, testProjectName } from "./auth-fixture";
import { revealToolActivity, selectModel, submitChatPrompt } from "../fixtures/chat-ui";

for (const mode of ["normal", "recovery", "recovery-fails"] as const) {
  test(`Session context ${mode} preserves its checkpoint and audit across browser reload`, async ({ page, researcher }) => {
    test.setTimeout(90_000);
    await page.goto("/chat");
    await finishPrompt(page, "Prepare a research conversation.");
    await expect(page.locator("[data-chat-status]")).toHaveText("Run complete");
    const threadId = new URL(page.url()).searchParams.get("session")!;
    seedHistory(threadId, researcher.id, mode === "normal" ? 22000 : 11000);
    await finishPrompt(page, `[scripted-context-${mode}] Continue the research.`, mode === "recovery-fails" ? "failed" : "completed");
    await expect(page.locator("[data-chat-status]")).toHaveText(mode === "recovery-fails" ? "Run failed" : "Run complete", { timeout: 60_000 });
    const before = facts(threadId, researcher.id);
    expect(before.revision).toBe(1);
    expect(before.raw_characters).toBeGreaterThan(500000);
    if (mode === "normal") {
      await expect(page.getByText("I continued after compaction and read the current Core research context.", { exact: true })).toBeVisible();
      await expect((await revealToolActivity(page, "get_research_context", "complete")).first()).toBeVisible();
      expect(before.recoveries).toHaveLength(0);
    } else {
      expect(before.recoveries).toHaveLength(1);
      const recovery = before.recoveries[0]!;
      expect(recovery.attempts).toBe(1);
      expect(recovery.status).toBe(mode === "recovery" ? "succeeded" : "failed");
      expect(recovery.original_id).not.toBe(recovery.replacement_id);
      await expect(page.locator(`[data-entry-id="assistant:${recovery.original_id}"]`)).toBeVisible();
      await expect(page.locator(`[data-entry-id="assistant:${recovery.replacement_id}"]`)).toBeVisible();
      await expect(page.getByText("This is the retained partial answer.", { exact: true }).first()).toBeVisible();
      await expect(page.locator('[data-tool-name="get_research_context"]')).toHaveCount(0);
      if (mode === "recovery") await expect(page.getByText("The complete replacement answer uses the compacted Session.", { exact: true })).toBeVisible();
      else await expect(page.getByText("Partial response · recovery failed", { exact: true })).toBeVisible();
    }
    await expect(page.getByText("Scripted context checkpoint.", { exact: true })).toHaveCount(0);
    await page.reload();
    await expect(page.locator("[data-chat-status]")).toHaveText(mode === "recovery-fails" ? "Run failed" : "Run complete");
    expect(facts(threadId, researcher.id)).toEqual(before);
    if (mode === "normal") await expect(page.getByText("I continued after compaction and read the current Core research context.", { exact: true })).toBeVisible();
    else await expect(page.getByText("This is the retained partial answer.", { exact: true }).first()).toBeVisible();
  });
}

test("Session context small-window selection preserves a checkpoint without compression", async ({ page, researcher }) => {
  test.setTimeout(120_000);
  await page.goto("/chat");
  await finishPrompt(page, "Prepare research.");
  await expect(page.locator("[data-chat-status]")).toHaveText("Run complete");
  const threadId = new URL(page.url()).searchParams.get("session")!;
  seedHistory(threadId, researcher.id, 22000);
  await finishPrompt(page, "[scripted-context-normal] Continue.");
  await expect(page.locator("[data-chat-status]")).toHaveText("Run complete", { timeout: 60_000 });
  const checkpoint = facts(threadId, researcher.id);
  expect(checkpoint.revision).toBe(1);
  seedHistory(threadId, researcher.id, 22000, true);
  await selectModel(page, "Scripted Small Window");
  await page.keyboard.press("Escape");
  await finishPrompt(page, "[scripted-context-normal] Continue after model change.", "failed");
  await expect(page.locator("[data-chat-status]")).toHaveText("Run failed");
  const rejected = facts(threadId, researcher.id);
  expect(rejected.revision).toBe(checkpoint.revision);
  expect(rejected.summary_hash).toBe(checkpoint.summary_hash);
  expect(rejected.raw_characters).toBeGreaterThan(checkpoint.raw_characters);
  expect(rejected.selected_model).toBe("scripted-small-window");
  expect(rejected.latest_steps).toBe(0);
  expect(rejected.recoveries.every(recovery => recovery.attempts === 0)).toBe(true);
  await page.reload();
  expect(facts(threadId, researcher.id)).toEqual(rejected);
  await expect(page.getByRole("button", { name: "Model Scripted Small Window, reasoning Medium" })).toBeVisible();
  await selectModel(page, "Scripted Research");
  await page.keyboard.press("Escape");
  await finishPrompt(page, "[scripted-context-normal] Continue on the larger model.");
  await expect(page.locator("[data-chat-status]")).toHaveText("Run complete", { timeout: 60_000 });
  expect(facts(threadId, researcher.id).revision).toBe(2);
});

for (const variant of ["single", "batch"] as const) {
  test(`Session context compresses after the real Core ${variant} Tool results`, async ({ page, researcher }) => {
    test.setTimeout(90_000);
    await page.goto("/chat");
    await finishPrompt(page, "Prepare research.");
    const threadId = new URL(page.url()).searchParams.get("session")!;
    seedHistory(threadId, researcher.id, 18400);
    sql(`INSERT INTO research_folders.folders (researcher_id, id, name, is_default)
      SELECT session.researcher_id, 'folder_context_' || ordinal, repeat('研', 118) || lpad(ordinal::text, 2, '0'), false
      FROM agent.chat_session session CROSS JOIN generate_series(1, 24) ordinal
      WHERE session.id = '${threadId}'::uuid AND session.researcher_id = '${researcher.id}'::uuid;`);
    const runId = await finishPrompt(page, `[scripted-context-${variant === "single" ? "normal" : "tool-batch"}] Read the real Core folders and continue.`);
    const checkpoint = facts(threadId, researcher.id);
    expect(checkpoint.revision).toBe(1);
    expect(checkpoint.recoveries).toHaveLength(0);
    expect(hasFrozenTool(threadId, "get_research_context")).toBe(true);
    const activities = sql(`SELECT count(*) FROM agent.chat_timeline_entry
      WHERE thread_id = '${threadId}'::uuid AND turn_id = '${runId}'::uuid AND kind = 'tool_activity';`).trim();
    expect(activities).toBe(variant === "single" ? "1" : "4");
    if (variant === "batch") expect(hasFrozenTool(threadId, "get_alpha_catalog")).toBe(true);
    await expect((await revealToolActivity(page, "get_research_context", "complete")).first()).toBeVisible();
    await expect(page.getByText(variant === "single" ? "I continued after compaction and read the current Core research context." : "I read bounded Core folder and catalog pages, continued their cursors after compaction, and retained any further-page indicators.", { exact: true })).toBeVisible();
    await page.reload();
    expect(facts(threadId, researcher.id)).toEqual(checkpoint);
  });

}

test("Session context shows durable recovery in progress and stops without publishing", async ({ page, researcher }) => {
  test.setTimeout(90_000);
  await page.goto("/chat");
  await finishPrompt(page, "Prepare research.");
  const threadId = new URL(page.url()).searchParams.get("session")!;
  seedHistory(threadId, researcher.id, 11000);
  sql(`UPDATE agent.mastra_messages SET content = jsonb_set(content::jsonb, '{parts,0,text}',
    to_jsonb('[scripted-observer-await-cancel] ' || (content::jsonb #>> '{parts,0,text}')))::text
    WHERE thread_id = '${threadId}' AND id LIKE 'context-browser-${threadId}-%';`);
  const runId = await submitChatPrompt(page, "[scripted-context-recovery] Continue and preserve the audit.");
  await expect(page.getByText("Partial response · preparing a replacement", { exact: true })).toBeVisible();
  await expect(page.getByText("This is the retained partial answer.", { exact: true })).toBeVisible();
  const pending = facts(threadId, researcher.id);
  expect(pending.revision ?? 0).toBe(0);
  expect(pending.summary_hash).toBeNull();
  expect(pending.recoveries).toHaveLength(1);
  expect(pending.recoveries[0]).toMatchObject({ attempts: 1, status: "recovering" });
  await page.reload();
  await expect(page.getByText("Partial response · preparing a replacement", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Stop", exact: true }).click();
  await expect.poll(() => sql(`SELECT status FROM agent.agent_run WHERE id = '${runId}'::uuid;`).trim(), { timeout: 10000 }).toBe("stopped");
  await expect(page.locator("[data-chat-status]")).toHaveText("Turn stopped");
  const stopped = facts(threadId, researcher.id);
  expect(stopped.revision ?? 0).toBe(0);
  expect(stopped.summary_hash).toBeNull();
  expect(stopped.recoveries[0]).toMatchObject({ attempts: 1, status: "failed" });
  await expect(page.locator('[data-tool-name="get_research_context"]')).toHaveCount(0);
  await page.reload();
  await expect(page.locator("[data-chat-status]")).toHaveText("Turn stopped");
  await expect(page.getByText("This is the retained partial answer.", { exact: true })).toBeVisible();
  expect(facts(threadId, researcher.id)).toEqual(stopped);
});

function ownedIdentity(threadId: string, researcherId: string) {
  const uuid = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/;
  if (!uuid.test(threadId) || !uuid.test(researcherId)) throw new Error("Context fixture requires canonical identities");
}

function seedHistory(threadId: string, researcherId: string, repetitions: number, append = false) {
  ownedIdentity(threadId, researcherId);
  if (repetitions !== 11000 && repetitions !== 18400 && repetitions !== 22000) throw new Error("Unknown context fixture size");
  sql(`INSERT INTO agent.mastra_messages (id, thread_id, content, role, type, "createdAt", "createdAtZ", "resourceId")
    SELECT 'context-browser-${threadId}-${append ? 'appended' : 'initial'}-' || ordinal, session.id::text,
      jsonb_build_object('format', 2, 'parts', jsonb_build_array(jsonb_build_object('type', 'text', 'text', repeat('archived context evidence ', ${repetitions}))))::text,
      'assistant', (SELECT type FROM agent.mastra_messages WHERE thread_id = session.id::text LIMIT 1),
      (${append ? 'statement_timestamp()' : "statement_timestamp() - interval '1 hour'"} + ordinal * interval '1 millisecond') AT TIME ZONE 'UTC',
      ${append ? 'statement_timestamp()' : "statement_timestamp() - interval '1 hour'"} + ordinal * interval '1 millisecond', session.researcher_id::text
    FROM agent.chat_session session CROSS JOIN generate_series(1, 2) ordinal
    WHERE session.id = '${threadId}'::uuid AND session.researcher_id = '${researcherId}'::uuid;`);
}

type Facts = { selected_model: string; latest_steps: number; revision: number | null; raw_characters: number; summary_hash: string | null; recoveries: Array<{ attempts: number; status: string; original_id: string; replacement_id: string }> };
function facts(threadId: string, researcherId: string): Facts {
  ownedIdentity(threadId, researcherId);
  return JSON.parse(sql(`SELECT json_build_object(
    'selected_model', session.selected_model_key,
    'latest_steps', (SELECT run.step_count FROM agent.agent_run run WHERE run.thread_id = session.id ORDER BY run.started_at DESC LIMIT 1),
    'revision', (SELECT revision FROM agent.session_context_checkpoint WHERE thread_id = session.id),
    'summary_hash', (SELECT md5(snapshot->>'renderedSummary') FROM agent.session_context_checkpoint WHERE thread_id = session.id),
    'raw_characters', (SELECT sum(length(content)) FROM agent.mastra_messages WHERE thread_id = session.id::text),
    'recoveries', (SELECT coalesce(json_agg(json_build_object('attempts', attempts, 'status', status, 'original_id', original_message_id,
      'replacement_id', replacement_message_id) ORDER BY created_at), '[]'::json) FROM agent.model_step_recovery WHERE thread_id = session.id)
  ) FROM agent.chat_session session WHERE id = '${threadId}'::uuid AND researcher_id = '${researcherId}'::uuid;`));
}

function sql(input: string) {
  return execFileSync("docker", ["exec", "--interactive", "--env", "PGPASSWORD=owner-test-password", `${testProjectName()}-postgres-1`,
    "psql", "--username", "thesistrace_owner", "--dbname", "thesistrace", "--set", "ON_ERROR_STOP=1", "--tuples-only", "--no-align", "--quiet"],
  { input, encoding: "utf8", timeout: 10000 });
}

async function finishPrompt(page: Page, prompt: string, status = "completed") {
  const runId = await submitChatPrompt(page, prompt);
  await expect.poll(() => sql(`SELECT status FROM agent.agent_run WHERE id = '${runId}'::uuid;`).trim(),
    { timeout: 60_000, message: "The newly accepted Run reaches its terminal state" }).toBe(status);
  return runId;
}

function hasFrozenTool(threadId: string, name: "get_research_context" | "get_alpha_catalog") {
  return sql(`SELECT EXISTS (
    SELECT 1 FROM agent.session_context_checkpoint checkpoint,
      jsonb_array_elements(checkpoint.snapshot->'sourceWatermark') stamp
    JOIN agent.mastra_messages message ON message.id = stamp->>'messageId'
    WHERE checkpoint.thread_id = '${threadId}'::uuid AND message.thread_id = '${threadId}'
      AND message.content LIKE '%${name}%'
  );`).trim() === "t";
}
