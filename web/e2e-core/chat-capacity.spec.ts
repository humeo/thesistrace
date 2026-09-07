import { execFileSync } from "node:child_process";
import { randomUUID } from "node:crypto";

import { expect, test, testProjectName } from "./auth-fixture";
import { revealToolActivity, submitChatPrompt, waitForChatTurn } from "./chat-ui";
import { proxyState, setProxyMode } from "./fault-proxy";

test("Chat saturation rejects an unaccepted Session and preserves an explicit browser retry", async ({ page, researcher }, testInfo) => {
  test.setTimeout(120_000);
  const origin = process.env.THESISTRACE_TEST_WEB_ORIGIN!;
  const prompt = "[scripted-tool-turn] Inspect the available research context.";
  const pending: Promise<{ ok: boolean; finished: boolean }>[] = [];
  setProxyMode("mcp-fault-proxy", 8150, "tool-call", "hold");
  try {
    for (let index = 0; index < 4; index++) {
      pending.push((async () => {
        try {
          const response = await fetch(new URL("/api/agent/copilotkit/agent/research/run", origin), {
            method: "POST", headers: { origin, cookie: researcher.cookie, "content-type": "application/json", "sec-fetch-site": "same-origin" },
            signal: AbortSignal.timeout(90_000), body: JSON.stringify({
              threadId: randomUUID(), runId: randomUUID(), state: {}, context: [], tools: [],
              messages: [{ id: randomUUID(), role: "user", content: prompt }],
              forwardedProps: { thesistrace: { command: "prompt", modelKey: "scripted-research", reasoningEffort: "medium", sessionMode: "new" } },
            }),
          });
          const body = await response.text();
          return { ok: response.ok, finished: body.includes('"type":"RUN_FINISHED"') && !body.includes('"type":"RUN_ERROR"') };
        } catch { return { ok: false, finished: false }; }
      })());
    }
    await expect.poll(() => proxyState("mcp-fault-proxy", 8150).pending_held_tool_responses, { timeout: 20_000 }).toBe(4);
    await page.goto("/chat");
    await page.getByRole("textbox", { name: "Message", exact: true }).fill(prompt);
    await page.getByRole("button", { name: "Send" }).click();
    await expect(page.getByRole("alert")).toHaveAttribute("data-failure-code", "AGENT_CAPACITY");
    await expect(page.getByRole("alert")).toContainText("Agent at capacity");
    await expect(page.getByRole("textbox", { name: "Message", exact: true })).toHaveValue(prompt);
    await expect(page).toHaveURL(/\/chat$/);
    expect(databaseCounts(researcher.id)).toEqual({ sessions: 4, runs: 4, running: 4 });

    const resource = JSON.parse(docker(["exec", `${testProjectName()}-agent-1`, "node", "--input-type=module", "--eval", `
      import { readFileSync } from 'node:fs';
      process.stdout.write(JSON.stringify({
        memory_bytes: Number(readFileSync('/sys/fs/cgroup/memory.current', 'utf8')),
        peak_bytes: Number(readFileSync('/sys/fs/cgroup/memory.peak', 'utf8')),
        limit_bytes: Number(readFileSync('/sys/fs/cgroup/memory.max', 'utf8')),
        cpu_max: readFileSync('/sys/fs/cgroup/cpu.max', 'utf8').trim()
      }));
    `]));
    expect(resource.limit_bytes).toBe(1073741824);
    expect(resource.memory_bytes).toBeGreaterThan(0);
    expect(resource.peak_bytes).toBeLessThan(resource.limit_bytes);
    expect(resource.cpu_max).toBe("100000 100000");
    await testInfo.attach("agent-capacity-engineering-envelope", { body: JSON.stringify({
      kind: "deterministic-engineering-evidence", model_quality_evidence: false,
      active_runs: 4, ...resource,
    }), contentType: "application/json" });

    setProxyMode("mcp-fault-proxy", 8150, "tool-call", "pass");
    expect(await Promise.all(pending)).toEqual(Array.from({ length: 4 }, () => ({ ok: true, finished: true })));
    const acceptedTurn = await submitChatPrompt(page, prompt);
    await waitForChatTurn(page, acceptedTurn);
    await expect(page.locator("[data-chat-status]")).toHaveText("Run complete", { timeout: 30_000 });
    await expect(page.locator(".chat-message-user .chat-message-content")).toHaveText(prompt);
    await expect((await revealToolActivity(page, "get_research_context", "complete")).last()).toBeVisible();
    await expect(page).toHaveURL(/\/chat\?session=[a-f0-9-]{36}$/);
    expect(databaseCounts(researcher.id)).toEqual({ sessions: 5, runs: 5, running: 0 });
  } finally {
    setProxyMode("mcp-fault-proxy", 8150, "tool-call", "pass");
    await Promise.allSettled(pending);
  }
});

function docker(args: string[]): string {
  try { return execFileSync("docker", args, { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"], timeout: 10_000 }); }
  catch { throw new Error("CAPACITY_TEST_DEPENDENCY_UNAVAILABLE"); }
}
function databaseCounts(researcherId: string): { sessions: number; runs: number; running: number } {
  if (!/^[a-f0-9-]{36}$/.test(researcherId)) throw new Error("CAPACITY_TEST_IDENTITY_INVALID");
  return JSON.parse(docker(["exec", "--env", "PGPASSWORD=owner-test-password", `${testProjectName()}-postgres-1`,
    "psql", "--username", "thesistrace_owner", "--dbname", "thesistrace", "--tuples-only", "--no-align", "--set", "ON_ERROR_STOP=1", "--command", `
      SELECT json_build_object(
        'sessions', (SELECT count(*) FROM agent.chat_session WHERE researcher_id = '${researcherId}'::uuid),
        'runs', count(*), 'running', count(*) FILTER (WHERE run.status = 'running')
      ) FROM agent.agent_run AS run
      JOIN agent.chat_session AS session ON session.id = run.thread_id
      WHERE session.researcher_id = '${researcherId}'::uuid
    `]));
}
