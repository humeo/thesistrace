import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { execFileSync, spawn } from "node:child_process";
import { writeFileSync } from "node:fs";
import { stripVTControlCharacters } from "node:util";

const origin = `http://127.0.0.1:${process.env.agent_port}`;
const headers = { "content-type": "application/json", origin: "https://thesistrace.test",
  cookie: "thesistrace.session_token=image-smoke-session" };
const container = execFileSync("docker", ["compose", "--env-file", "/dev/null", "--project-name", process.env.project_name,
  "--file", process.env.compose_file, "ps", "--quiet", "agent"], { encoding: "utf8" }).trim();
const samples = [];
let sampleBuffer = "";
let samplingFailed = false;
const monitor = spawn("docker", ["stats", "--format", "{{json .}}", container], { stdio: ["ignore", "pipe", "ignore"] });
const monitorClosed = new Promise(resolve => { monitor.once("close", resolve); monitor.once("error", resolve); });
monitor.stdout.on("data", chunk => {
  sampleBuffer += chunk.toString();
  let index;
  while ((index = sampleBuffer.indexOf("\n")) !== -1) {
    const line = stripVTControlCharacters(sampleBuffer.slice(0, index)).trim(); sampleBuffer = sampleBuffer.slice(index + 1);
    if (!line) continue;
    try {
      const value = JSON.parse(line);
      const sample = { cpu_percent: Number.parseFloat(value.CPUPerc), memory: value.MemUsage,
        memory_percent: Number.parseFloat(value.MemPerc), pids: value.PIDs };
      if (!Number.isFinite(sample.cpu_percent) || !Number.isFinite(sample.memory_percent)) samplingFailed = true;
      else samples.push(sample);
    } catch { samplingFailed = true; }
  }
});
try {
  const started = performance.now();
  const loops = Array.from({ length: 8 }, () => start("image-code-mode-loop"));
  const completed = Promise.all(loops.map(run => run.done));
  let concurrentProgramsSample;
  try {
    await until(() => loops.every(run => run.events.some(event => event.type === "CUSTOM"
      && JSON.stringify(event).includes('"name":"get_research_context"')
      && JSON.stringify(event).includes('"status":"complete"'))));
    const samplesBeforeLoaded = samples.length;
    await until(() => { assert.equal(samplingFailed, false, "Docker stats did not report valid metrics"); return samples.length > samplesBeforeLoaded; });
    concurrentProgramsSample = samples.at(-1);
    assert.equal((await fetch(`${origin}/health/ready`, { signal: AbortSignal.timeout(3_000) })).status, 200);
    const other = start("image-code-mode-text");
    await other.done;
    assert.equal(other.events.at(-1)?.type, "RUN_FINISHED");
    const overflow = start("image-code-mode-overflow");
    await overflow.done;
    assert.equal(overflow.events.at(-1)?.code, "AGENT_CAPACITY");
  } finally {
    await Promise.all(loops.map(async run => {
      const response = await fetch(`${origin}/api/agent/sessions/${run.threadId}/stop`, {
        method: "POST", headers, signal: AbortSignal.timeout(10_000),
        body: JSON.stringify({ commandId: randomUUID(), expectedTurnId: run.runId }),
      });
      assert.equal(response.status, 200);
    }));
    await completed;
  }
  for (const run of loops) {
    const response = await fetch(`${origin}/api/agent/sessions/${run.threadId}`, { headers });
    assert.equal(response.status, 200);
    assert.equal((await response.json()).latest_turn.status, "stopped");
  }
  for (const [prompt, code] of [["image-code-mode-heap", "AGENT_LIMIT"], ["image-code-mode-arguments", "AGENT_LIMIT"],
    ["image-code-mode-logs", undefined], ["image-code-mode-recovered", undefined]]) {
    const run = start(prompt);
    await run.done;
    assert.equal(run.events.at(-1)?.type, code ? "RUN_ERROR" : "RUN_FINISHED");
    if (code) assert.equal(run.events.at(-1)?.code, code);
  }
  assert.equal((await fetch(`${origin}/health/ready`)).status, 200);
  assert.equal(samplingFailed, false, "Docker stats did not report valid metrics");
  const evidence = {
    programs: 8, allocated_elements_per_program: 5_000_000, samples: samples.length,
    concurrent_programs_sample: concurrentProgramsSample,
    peak_memory_sample: [...samples].sort((a, b) => a.memory_percent - b.memory_percent).at(-1),
    peak_cpu_percent: Math.max(...samples.map(sample => sample.cpu_percent)),
    elapsed_ms: Math.round(performance.now() - started), stop: "passed", heap: "passed", arguments: "passed", logs: "passed", recovery: "passed",
  };
  writeFileSync(`${process.env.evidence_root}/code-mode-image.json`, JSON.stringify(evidence, null, 2));
  process.stdout.write(`${JSON.stringify({event: "code_mode_image_qualified", ...evidence})}\n`);
} finally {
  monitor.kill("SIGTERM");
  await monitorClosed;
}

function start(prompt) {
  const threadId = randomUUID(), runId = randomUUID();
  const events = [];
  const done = (async () => {
    const response = await fetch(`${origin}/api/agent/copilotkit/agent/research/run`, {
      method: "POST", headers, signal: AbortSignal.timeout(40_000), body: JSON.stringify({ threadId, runId,
        messages: [{ id: randomUUID(), role: "user", content: prompt }], state: {}, tools: [], context: [],
        forwardedProps: { thesistrace: { command: "prompt", selectionMode: "manual", modelKey: "gpt-6-luna", reasoningEffort: "max", sessionMode: "new" } },
      }),
    });
    assert.equal(response.status, 200);
    let buffer = "";
    const decoder = new TextDecoder();
    for await (const chunk of response.body) {
      buffer += decoder.decode(chunk, { stream: true });
      let index;
      while ((index = buffer.indexOf("\n")) !== -1) {
        const line = buffer.slice(0, index).trim(); buffer = buffer.slice(index + 1);
        if (!line.startsWith("data:")) continue;
        const data = line.slice(5).trim();
        if (data === "[DONE]") continue;
        const event = JSON.parse(data);
        assert.equal(data.includes("private-code-mode-image-canary"), false);
        if (event.type === "TOOL_CALL_ARGS") assert.equal(event.delta, "{}");
        events.push(event);
      }
    }
  })();
  return { threadId, runId, events, done };
}

async function until(condition) {
  const deadline = performance.now() + 15_000;
  while (!condition()) {
    assert.equal(performance.now() < deadline, true, "Eight native programs did not reach the authenticated read barrier");
    await new Promise(resolve => setTimeout(resolve, 20));
  }
}
