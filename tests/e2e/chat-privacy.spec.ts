import { execFileSync, spawnSync } from "node:child_process";
import { createHash, randomUUID } from "node:crypto";
import { readFileSync } from "node:fs";
import { expect, test, testProjectName } from "./auth-fixture";
import { proxyState, setProxyMode } from "./fault-proxy";

const canaries: Record<string, string> = JSON.parse(readFileSync(new URL("../../apps/agent/fixtures/agent-privacy-canaries.json", import.meta.url), "utf8"));
const logKeys = ["component", "context_compaction", "duration_ms", "error_category", "event", "input_token_estimate", "level", "model_call", "model_key", "provider_model_id", "reasoning_effort", "recovery_attempts", "researcher_correlation", "retry_classification", "run_id", "status", "step_count", "thread_id", "timestamp", "token_usage", "tool_result_bytes", "trace_id"].sort();

test("Chat content-free telemetry survives success faults restart and deletion in final images", async ({ researcher }, testInfo) => {
  test.setTimeout(180_000);
  const origin = process.env.THESISTRACE_TEST_WEB_ORIGIN!;
  const headers = {
    "content-type": "application/json", origin, "sec-fetch-site": "same-origin",
    cookie: `${researcher.cookie}; privacy=${canaries.cookie}`,
  };
  // Node fetch deliberately keeps private test requests out of Playwright's
  // browser trace. Assertions and attachments below expose metadata only.
  async function request(path: string, init: RequestInit = {}) {
    try { return await fetch(new URL(path, origin), { ...init, headers: { ...headers, ...init.headers }, signal: AbortSignal.timeout(75_000) }); }
    catch { throw new Error("PRIVACY_HTTP_DEPENDENCY_UNAVAILABLE"); }
  }
  async function run(prompt: string) {
    const threadId = randomUUID(), runId = randomUUID();
    const response = await request("/api/agent/copilotkit/agent/research/run", {
      method: "POST", body: JSON.stringify({ threadId, runId,
        messages: [{ id: randomUUID(), role: "user", content: prompt }], state: {}, context: [], tools: [],
        forwardedProps: { thesistrace: { command: "prompt", modelKey: "scripted-research", reasoningEffort: "medium", sessionMode: "new" } },
      }),
    });
    expect(response.status).toBe(200);
    const body = await response.text();
    let events: Array<Record<string, any>>;
    try { events = body.split("\n\n").filter((frame) => frame.startsWith("data: ")).map((frame) => JSON.parse(frame.slice(6))); }
    catch { throw new Error("PRIVACY_STREAM_PROTOCOL_INVALID"); }
    return { threadId, runId, events, body };
  }

  const cases: Array<{ runId: string; threadId: string; status: string; code: string | null }> = [];
  let coreRunId: string | undefined;
  try {
    setProxyMode("mcp-fault-proxy", 8150, "tool-call", "canary");
    const successful = await run(canaries.user!);
    expect(successful.events.at(-1)?.type).toBe("RUN_FINISHED");
    expect(successful.body.includes(canaries.assistant!), "assistant canary did not reach its content boundary").toBe(true);
    expect(successful.body.includes(canaries.a2ui!), "validated A2UI canary did not reach its content boundary").toBe(true);
    expect(Number(proxyState("mcp-fault-proxy", 8150).canary_tool_responses)).toBeGreaterThan(0);
    const ids = successful.body.match(/run_[a-f0-9]{20}/g) ?? [];
    coreRunId = ids[0];
    expect(coreRunId !== undefined, "privacy fixture did not admit Core Research").toBe(true);
    const original = await request(`/api/research-runs/${coreRunId}`);
    expect(original.status).toBe(200);
    const coreBody = await original.text();
    expect(JSON.parse(coreBody).status).toBe("succeeded");
    expect(["formula", "hypothesis", "mcp_argument"].every((key) => coreBody.includes(canaries[key]!)), "private research values did not reach Core").toBe(true);
    const fingerprint = digest(coreBody);
    cases.push({ ...successful, status: "completed", code: null });
    setProxyMode("mcp-fault-proxy", 8150, "tool-call", "pass");

    for (const [prompt, code] of [
      ["[scripted-provider-unexpected] Test an unexpected provider error.", "INTERNAL_FAILURE"],
      ["[scripted-provider-output-limit] Test a bounded provider output.", "OUTPUT_LIMIT"],
    ]) {
      const failed = await run(prompt!);
      expect(failed.events.at(-1)?.type).toBe("RUN_ERROR");
      expect(failed.events.at(-1)?.code).toBe(code);
      cases.push({ ...failed, status: "failed", code: code! });
    }
    setProxyMode("mcp-fault-proxy", 8150, "tool-call", "disconnect");
    const failedTool = await run("[scripted-tool-turn] Inspect the available research context.");
    expect(failedTool.events.at(-1)?.code).toBe("MCP_TRANSIENT");
    cases.push({ ...failedTool, status: "failed", code: "MCP_TRANSIENT" });
    setProxyMode("mcp-fault-proxy", 8150, "tool-call", "pass");
    const invalidA2ui = await run("[scripted-invalid-a2ui] Attempt one unsafe research surface.");
    expect(invalidA2ui.events.at(-1)?.type).toBe("RUN_FINISHED");
    cases.push({ ...invalidA2ui, status: "completed", code: null });

    const denied = await request("/api/agent/models", { headers: { cookie: `privacy=${canaries.cookie}` } });
    expect(denied.status).toBe(401);
    const deniedToken = await request("/mcp", { method: "POST", headers: {
      authorization: `Bearer ${canaries.access_token}`,
    }, body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "tools/list" }) });
    expect(deniedToken.status).toBe(401);

    const container = `${testProjectName()}-agent-1`;
    const inspect = JSON.parse(docker(["inspect", container]))[0];
    const env = Object.fromEntries((inspect.Config.Env as string[]).map((item) => { const i = item.indexOf("="); return [item.slice(0, i), item.slice(i + 1)]; }));
    expect(env.THESISTRACE_AGENT_SCRIPTED_MODEL_SECRET === canaries.provider_key, "configured Provider Key canary is missing").toBe(true);
    expect(Object.keys(env).some((key) => /^(?:THESISTRACE_(?:DATABASE_URL|AUTH_DATABASE_URL|OWNER_DATABASE_URL|S3_|DATA_MOUNT|BENCHMARK_MOUNT|MCP_SIGNING)|BETTER_AUTH_SECRET)|QUEUE|WORKER/.test(key))).toBe(false);
    expect(new URL(env.THESISTRACE_AGENT_DATABASE_URL).username).toBe("agent_runtime");
    expect(inspect.Mounts.length).toBe(0);
    for (const endpoint of ["live", "ready"]) {
      const health = docker(["exec", container, "node", "--input-type=module", "--eval", `const r=await fetch('http://127.0.0.1:8400/health/${endpoint}');process.stdout.write(await r.text());`]);
      expect(Object.values(canaries).some((value) => health.includes(value))).toBe(false);
      expect(JSON.parse(health).status).toBe(endpoint === "live" ? "ok" : "ready");
    }
    const invalid = spawnSync("docker", ["exec", "--env", "THESISTRACE_AGENT_SCRIPTED_MODEL_SECRET=", container, "node", "dist/server.js"], { encoding: "utf8", timeout: 10_000 });
    expect(invalid.status).toBe(1);
    const startup = `${invalid.stdout}${invalid.stderr}`;
    expect(Object.values(canaries).some((value) => startup.includes(value))).toBe(false);
    expect(startup.trim()).toBe('{"code":"AGENT_STARTUP_INVALID","event":"agent_startup_failed"}');

    docker(["restart", "--time", "20", container]);
    await expect.poll(async () => { try { return (await request("/api/agent/models")).status; } catch { return 0; } }, { timeout: 20_000 }).toBe(200);
    for (const item of cases) {
      const retained = await request(`/api/agent/sessions/${item.threadId}`);
      expect(retained.status).toBe(200);
      const removed = await request(`/api/agent/sessions/${item.threadId}`, { method: "DELETE" });
      expect(removed.status).toBe(204);
      expect((await request(`/api/agent/sessions/${item.threadId}`)).status).toBe(404);
    }
    const afterDelete = await request(`/api/research-runs/${coreRunId}`);
    expect(afterDelete.status).toBe(200);
    expect(digest(await afterDelete.text())).toBe(fingerprint);
    const remaining = docker(["exec", "--env", "PGPASSWORD=owner-test-password", `${testProjectName()}-postgres-1`, "psql", "--username", "thesistrace_owner", "--dbname", "thesistrace", "--tuples-only", "--no-align", "--command",
      `SELECT count(*) FROM agent.mastra_messages WHERE "resourceId" = '${researcher.id}'`]);
    expect(remaining.trim()).toBe("0");

    const logs = docker(["logs", container]);
    expect(Object.values(canaries).some((value) => logs.includes(value)), "Agent logs contain a private value").toBe(false);
    const observations = logs.split("\n").filter((line) => line.startsWith("{")).map((line) => JSON.parse(line)).filter((item) => item.component === "agent");
    for (const item of cases) {
      const finished = observations.filter((event) => event.event === "agent_run_finished" && event.run_id === item.runId);
      expect(finished.length).toBe(1);
      const metric = finished[0];
      expect(Object.keys(metric).sort()).toEqual(logKeys);
      expect(metric).toMatchObject({ context_compaction: null, model_call: null, recovery_attempts: 0, tool_result_bytes: null });
      expect(metric).toMatchObject({ status: item.status, error_category: item.code, model_key: "scripted-research", provider_model_id: "scripted-v1", reasoning_effort: "medium" });
      expect(metric.researcher_correlation).toMatch(/^[a-f0-9]{64}$/);
      expect(metric.trace_id).toMatch(/^[a-f0-9-]{36}$/);
      expect(Number.isSafeInteger(metric.duration_ms) && metric.duration_ms >= 0).toBe(true);
      expect(Number.isSafeInteger(metric.step_count) && metric.step_count > 0).toBe(true);
    }
    const successMetric = observations.find((event) => event.event === "agent_run_finished" && event.run_id === successful.runId);
    expect(successMetric.token_usage.inputTokens.total).toBe(successMetric.step_count * 11);
    expect(successMetric.token_usage.outputTokens.total).toBe(successMetric.step_count * 12);
    expect(observations.some((event) => event.run_id === invalidA2ui.runId && event.event === "agent_tool_finished" && event.error_category === "TOOL_REJECTION")).toBe(true);

    const assets = docker(["exec", `${testProjectName()}-web-1`, "find", "/srv/assets", "-maxdepth", "1", "-type", "f"])
      .trim().split("\n");
    expect(assets.length).toBeGreaterThan(0);
    expect(assets.every((asset) => /^\/srv\/assets\/[A-Za-z0-9._-]+$/.test(asset))).toBe(true);
    for (const asset of assets) {
      const source = await (await request(asset.slice(4))).text();
      expect([canaries.provider_key!, canaries.access_token!, researcher.cookie].some((value) => source.includes(value))).toBe(false);
    }
    await testInfo.attach("content-free-privacy-metadata", { contentType: "application/json", body: Buffer.from(JSON.stringify({
      status: "passed", seed: 0, scenarios: ["success", "provider_failure", "auth_failure", "mcp_error", "invalid_a2ui", "agent_limit", "restart", "delete"],
      canary_categories: Object.keys(canaries), runs: cases.map(({ runId, threadId, status, code }) => ({ run_id: runId, thread_id: threadId, status, error_category: code })),
      core_resource_retained: true, content_remaining: 0, runtime_mounts: 0, image_digest: inspect.Image,
    })) });
  } finally { setProxyMode("mcp-fault-proxy", 8150, "tool-call", "pass"); }
});

function docker(args: string[]): string {
  try {
    // docker logs writes application stderr to command stderr. Keep both in
    // memory for scanning, never echo a failed command's diagnostic payload.
    if (args[0] === "logs") {
      const result = spawnSync("docker", args, { encoding: "utf8", timeout: 10_000, maxBuffer: 8 * 1024 * 1024 });
      if (result.status !== 0) throw new Error();
      return `${result.stdout}${result.stderr}`;
    }
    return execFileSync("docker", args, { encoding: "utf8", timeout: 35_000, maxBuffer: 8 * 1024 * 1024, stdio: ["ignore", "pipe", "pipe"] });
  } catch { throw new Error("PRIVACY_CONTAINER_DEPENDENCY_UNAVAILABLE"); }
}
function digest(value: string) { return createHash("sha256").update(value).digest("hex"); }
