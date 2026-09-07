// Explicit Operator evaluation only. Never imported by the Agent Host or the
// deterministic gate. Private HTTP bodies stay in memory; only closed facts
// cross the report boundary. No model-generated text is printed on failure.
import { execFileSync, spawnSync } from "node:child_process";
import { createHash, randomUUID } from "node:crypto";
import { existsSync } from "node:fs";
import { readFile, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

const compiledEval = new URL("../dist/research-eval.js", import.meta.url);
let runtimeModules;
try {
  if (!existsSync(compiledEval)) {
    execFileSync(
      process.execPath,
      [
        fileURLToPath(new URL("../node_modules/typescript/bin/tsc", import.meta.url)),
        "-p",
        fileURLToPath(new URL("../tsconfig.build.json", import.meta.url)),
      ],
      { stdio: "ignore" },
    );
  }
  runtimeModules = await Promise.all([
    import("../dist/research-eval.js"),
    import("../dist/model-registry.js"),
    import("../dist/model-runtime.js"),
    import("../dist/guarded-language-model.js"),
    import("../dist/durable-agent-runner.js"),
    import("../dist/chat-request.js"),
    import("../dist/research-eval-stream.js"),
    import("../dist/research-eval-memory.js"),
  ]);
} catch {
  process.stderr.write("RESEARCH_EVAL_DEPENDENCY_UNAVAILABLE\n");
  process.exit(2);
}
const [
  evalRuntime,
  modelRegistryRuntime,
  modelRuntime,
  guardedRuntime,
  durableRuntime,
  chatRequestRuntime,
  evalStreamRuntime,
  evalMemoryRuntime,
] = runtimeModules;
const {
  ResearchEvalError, evalBatchWorkerFailure, evalFailureSource, evalRunSchema, evalStartupRegistry, evalToolCapabilities,
  maximumEvalTurnCostUsd, maximumTitleCostUsd, parseResearchEvalCandidates,
  parseResearchEvalCorpus, readResearchEvalControls, researchEvalPasses, researchEvalRepetitions, summarizeResearchEval,
  usageCostUsd, validateEvalObservation,
} = evalRuntime;
const { readModelRegistry } = modelRegistryRuntime;
const { RegisteredModelRuntime } = modelRuntime;
const { AGENT_LIMITS } = guardedRuntime;
const { MAX_ACTIVE_AGENT_RUNS } = durableRuntime;
const { MAX_CHAT_MESSAGE_BYTES } = chatRequestRuntime;
const {
  RESEARCH_EVAL_TURN_OBSERVATION_MS,
  requestResearchEvalTurn,
  researchEvalConversationMeetsOutcome,
  researchEvalToolRetryCount,
  unresolvedResearchEvalToolFailure,
} = evalStreamRuntime;
const { researchEvalMemoryFactsSchema } = evalMemoryRuntime;

const repo = new URL("../../../", import.meta.url);
const digest = (value) => createHash("sha256").update(value).digest("hex");
const paused = new Set();
let project;

try {
  const candidateBytes = await readFile(new URL("../evals/research-candidates.json", import.meta.url));
  const candidates = parseResearchEvalCandidates(JSON.parse(candidateBytes));
  const candidate = candidates.candidates.find((item) => item.key === required("THESISTRACE_AGENT_EVAL_MODEL_KEY"));
  const effort = required("THESISTRACE_AGENT_EVAL_REASONING_EFFORT");
  if (candidate === undefined) throw new ResearchEvalError("CONFIG_INVALID");
  const providerBaseUrl = candidate.provider_adapter === "openai" ? readOpenAIBaseUrl() : null;
  if (providerBaseUrl !== null) process.env.OPENAI_BASE_URL = providerBaseUrl;
  const registryValue = evalStartupRegistry(candidate, effort);
  const registry = readModelRegistry(JSON.stringify(registryValue), process.env);
  const selected = new RegisteredModelRuntime(registry).resolve(candidate.key, effort);
  const controls = readResearchEvalControls(candidate, process.env.THESISTRACE_AGENT_EVAL_PHASE, process.env.THESISTRACE_AGENT_EVAL_SPEND_LIMIT_USD);
  if (process.argv.length !== 3 || !["configure", "run"].includes(process.argv[2])) throw new ResearchEvalError("CONFIG_INVALID");
  if (process.argv[2] === "configure") {
    process.stdout.write(`${JSON.stringify(registryValue)}\n`);
  } else {
    await evaluate({
      candidate,
      candidateBytes,
      repetitions: researchEvalRepetitions(candidates, controls.phase),
      effort,
      registryValue,
      providerBaseUrl,
      providerOptions: selected.providerOptions,
      ...controls,
    });
  }
} catch (error) {
  process.stderr.write(`${error instanceof ResearchEvalError ? error.message : "RESEARCH_EVAL_DEPENDENCY_UNAVAILABLE"}\n`);
  process.exitCode = 2;
} finally {
  for (const worker of paused) {
    try { controlWorker("unpause", worker); }
    catch { process.stderr.write("RESEARCH_EVAL_DEPENDENCY_UNAVAILABLE\n"); process.exitCode = 2; }
  }
}

function readOpenAIBaseUrl() {
  const value = required("THESISTRACE_AGENT_OPENAI_BASE_URL");
  if (!URL.canParse(value)) throw new ResearchEvalError("CONFIG_INVALID");
  const url = new URL(value);
  const local = ["localhost", "127.0.0.1", "[::1]", "host.docker.internal"].includes(url.hostname);
  if (url.username || url.password || url.search || url.hash || url.href !== value
    || (url.protocol !== "https:" && !(local && url.protocol === "http:"))) {
    throw new ResearchEvalError("CONFIG_INVALID");
  }
  return value;
}

async function evaluate({ candidate, candidateBytes, repetitions, effort, registryValue, providerBaseUrl, providerOptions, phase, budget }) {
  const corpusBytes = await readFile(new URL("../evals/research-corpus.json", import.meta.url));
  const corpus = parseResearchEvalCorpus(JSON.parse(corpusBytes));
  project = required("THESISTRACE_TEST_PROJECT_NAME");
  if (!/^thesistrace-test-[0-9]{8}t[0-9]{6}z-[0-9]+-[0-9a-f]{8}$/.test(project)) throw new ResearchEvalError("CONFIG_INVALID");
  const origin = required("THESISTRACE_TEST_WEB_ORIGIN");
  if (!/^http:\/\/127\.0\.0\.1:[0-9]+$/.test(origin)) throw new ResearchEvalError("CONFIG_INVALID");
  const evidence = resolve(required("THESISTRACE_TEST_EVIDENCE_DIR"));
  if (!evidence.endsWith(`/${project.slice("thesistrace-test-".length)}/evidence`)) throw new ResearchEvalError("CONFIG_INVALID");
  const deployedRegistry = JSON.parse(required("THESISTRACE_AGENT_MODEL_REGISTRY"));
  if (JSON.stringify(deployedRegistry) !== JSON.stringify(registryValue)) throw new ResearchEvalError("CONFIG_INVALID");
  if (providerBaseUrl !== null) {
    const deployedEndpointHash = docker(["exec", `${project}-agent-1`, "node", "--input-type=module", "--eval",
      'import { createHash } from "node:crypto"; process.stdout.write(createHash("sha256").update(process.env.OPENAI_BASE_URL ?? "").digest("hex"));',
    ]);
    if (deployedEndpointHash !== digest(providerBaseUrl)) throw new ResearchEvalError("CONFIG_INVALID");
  }
  const inspect = JSON.parse(docker(["inspect", "--format", '{"memory":{{.HostConfig.Memory}},"nano_cpus":{{.HostConfig.NanoCpus}}}', `${project}-agent-1`]));
  if (inspect.memory !== 1073741824 || inspect.nano_cpus !== 1000000000) throw new ResearchEvalError("CONFIG_INVALID");
  const images = Object.fromEntries(["agent", "auth", "api", "research-worker", "batch-research-worker", "tracking-worker", "web"].map((service) => [service,
    docker(["inspect", "--format", "{{.Image}}", `${project}-${service}-1`]).trim(),
  ]));
  if (Object.values(images).some((id) => !/^sha256:[a-f0-9]{64}$/.test(id))) throw new ResearchEvalError("CONFIG_INVALID");
  const revision = command("git", ["rev-parse", "HEAD"]).trim();
  const sourceDigest = digest(command("git", ["diff", "HEAD", "--binary"]));
  const fixtureBytes = await readFile(new URL("tests/fixtures/tushare-financial-product-replay.json", repo));
  const setupDigest = digest(Buffer.concat(await Promise.all([
    "tests/e2e/support/prepare_current_data.py", "tests/fixtures/tushare-financial-capability.json",
    "tests/e2e/support/research_eval_formula.py", "apps/agent/scripts/eval-research.mjs", "pnpm-lock.yaml",
  ].map((path) => readFile(new URL(path, repo))))));
  const peer = await provision(origin, "peer");
  const data = await json(peer, "/api/data");
  if (data.data_through_session !== corpus.clock_window.head || data.market_research_readiness !== true
    || data.market_coverage?.start !== corpus.admission_window.requested_start) throw new ResearchEvalError("DEPENDENCY_UNAVAILABLE");
  const allowedTools = JSON.parse(required("THESISTRACE_MCP_DEPLOYMENT_TOOLS"));
  if (!Array.isArray(allowedTools) || allowedTools.some((name) => !/^[a-z][a-z0-9_]{0,127}$/.test(name))
    || !allowedTools.includes("refresh_daily_track")) throw new ResearchEvalError("CONFIG_INVALID");
  const observations = [];
  let spending = 0;
  let halted = null;
  const started = new Date().toISOString();
  outer: for (let repetition = 1; repetition <= repetitions; repetition++) {
    for (const testCase of corpus.cases) {
      // Reserve every possible step at the Provider input ceiling before a
      // paid turn. Unknown accounting halts the entire evaluation, never a
      // fake zero followed by additional paid work.
      if (spending + maximumEvalTurnCostUsd(candidate) * testCase.messages.length > budget) {
        halted = "budget";
        break outer;
      }
      let caseStarted = performance.now();
      let fixture = {};
      const threadId = randomUUID();
      const runs = [], streams = [], runIds = [];
      let transportFailed = false;
      let fixtureFailed = false;
      let artifact = { passed: false, ids: [] };
      let ownership = false;
      try {
        const researcher = await provision(origin, `${testCase.id}-${repetition}`);
        fixture = await prepareFixture(researcher, testCase, corpus);
        caseStarted = performance.now();
        let pendingInterrupt = null;
        let currentRunId = null;
        for (let turn = 0; turn < testCase.messages.length; turn++) {
          const text = testCase.messages[turn].replaceAll("{{run_id}}", fixture.runId ?? "").replaceAll("{{track_id}}", fixture.trackId ?? "");
          const answering = pendingInterrupt !== null;
          const runId = answering ? currentRunId : randomUUID();
          if (runId === null) throw new ResearchEvalError("PROTOCOL_INVALID");
          const inputId = randomUUID();
          const input = answering ? {
            threadId, runId, state: {}, context: [], tools: [], messages: [],
            resume: [{ interruptId: pendingInterrupt.id, payload: { selections: [], text }, status: "resolved" }],
            forwardedProps: { thesistrace: { command: "answer", inputId, interruptId: pendingInterrupt.id } },
          } : {
            threadId, runId, state: {}, context: [], tools: [],
            messages: [{ id: inputId, role: "user", content: text }],
            forwardedProps: { thesistrace: { command: "prompt", modelKey: candidate.key, reasoningEffort: effort, sessionMode: turn === 0 ? "new" : "existing" } },
          };
          if (!answering) {
            currentRunId = runId;
            runIds.push(runId);
          }
          const stream = await requestResearchEvalTurn((timeout) => request(researcher, "/api/agent/copilotkit/agent/research/run", {
            method: "POST", body: JSON.stringify(input),
          }, timeout), (call) => {
            if (call.name === "get_research_run" && call.outcome?.outcome === "completed"
              && ["queued", "running"].includes(call.outcome.resource?.status)
              && testCase.fixture === "paused-research" && paused.has("research-worker")) controlWorker("unpause", "research-worker");
          });
          streams.push(stream);
          pendingInterrupt = stream.interrupt;
          if (pendingInterrupt === null) {
            runs.push(await terminalObservation(runId, candidate, effort));
            currentRunId = null;
          }
          if (runs.length > 0 && usageCostUsd(runs.at(-1).token_usage, candidate.pricing) === null) {
            // Stop paid work, but retain the independently observed failure.
            // Missing accounting is not itself a transport failure.
            break;
          }
          if (stream.failure !== null) break;
          if (pendingInterrupt !== null && turn + 1 >= testCase.messages.length) break;
        }
        artifact = await checkArtifact(researcher, testCase, fixture, corpus, threadId);
        fixtureFailed = artifact.workerFailure === true;
        ownership = await artifactsArePrivate(peer, artifact.ids);
        const foreignChat = await request(peer, `/api/agent/sessions/${threadId}`);
        await foreignChat.body?.cancel();
        ownership &&= foreignChat.status === 404;
      } catch {
        transportFailed = true;
      } finally {
        for (const worker of [...paused]) controlWorker("unpause", worker);
      }
      let metadata = [];
      try { metadata = logEvents().filter((item) => runIds.includes(item.run_id)); }
      catch { transportFailed = true; }
      const toolEvents = metadata.filter((item) => item.event === "agent_tool_finished");
      const namedCalls = streams.flatMap((item) => item.calls);
      const observedToolEvents = streams.flatMap((item) => item.toolEvents);
      const names = namedCalls.map((call) => call.name);
      const toolErrors = Math.max(toolEvents.filter((item) => item.status === "failed").length, namedCalls.filter((item) => item.failure !== null).length);
      const duration = Math.floor(performance.now() - caseStarted);
      const costs = runs.map((run) => usageCostUsd(run.token_usage, candidate.pricing));
      const usageComplete = runs.length === runIds.length && runs.length > 0 && costs.every((cost) => cost !== null);
      const cost = usageComplete ? costs.reduce((total, value) => total + value, 0) : null;
      const titleReserve = maximumTitleCostUsd(candidate) * runIds.length;
      const conversation = researchEvalConversationMeetsOutcome(testCase, streams, fixture);
      const { invalid, forbidden } = evalToolCapabilities(names, allowedTools, testCase.forbidden_tools);
      const checks = {
        artifact: artifact.passed, required_tools: testCase.required_tools.every((name) => namedCalls.some((call) => call.name === name && call.outcome?.outcome === "completed")),
        forbidden_tools: forbidden === 0 && invalid === 0, ownership, conversation,
        terminal: !transportFailed && pendingInterrupt === null
          && runs.length === runIds.length && runs.length > 0
          && runs.every((run) => run.status === "completed"),
        within_time: duration <= testCase.max_duration_ms,
        within_cost: cost !== null && cost + titleReserve <= testCase.max_cost_usd,
        usage_complete: usageComplete,
      };
      const succeeded = Object.values(checks).every(Boolean);
      const terminalCode = runs.find((run) => run.error_category !== null)?.error_category
        ?? (artifact.unresolvedAdmissionRejection ? "TOOL_REJECTION" : null)
        ?? unresolvedResearchEvalToolFailure(observedToolEvents);
      const observation = validateEvalObservation({
        case_id: testCase.id, repetition, succeeded, checks,
        failure_source: succeeded ? null : evalFailureSource(terminalCode, { workerFailure: fixtureFailed, transportFailed, usageComplete }),
        duration_ms: duration, estimated_cost_usd: cost, title_cost_upper_bound_usd: titleReserve, runs,
        tool_calls: Math.max(namedCalls.length, toolEvents.length), invalid_tool_calls: invalid, forbidden_tool_calls: forbidden,
        tool_errors: toolErrors, tool_retries: researchEvalToolRetryCount(observedToolEvents),
        admission_correction: testCase.outcome === "admission-repaired-factor" ? artifact.admissionCorrection === true : null,
        artifact_ids: artifact.ids,
      });
      observations.push(observation);
      process.stdout.write(`${JSON.stringify({ event: "research_eval_case", case_id: testCase.id, repetition, succeeded, failure_source: observation.failure_source, checks, duration_ms: duration, estimated_cost_usd: cost })}\n`);
      await persistReport();
      if (cost === null || transportFailed) { halted = "incomplete-accounting-or-transport"; break outer; }
      spending += cost + titleReserve;
    }
  }
  await persistReport();

  async function persistReport() {
    if (observations.length === 0) throw new ResearchEvalError("BUDGET_EXHAUSTED");
    const summary = summarizeResearchEval(corpus, repetitions, observations);
    const reasoningProven = effort === "none" || (summary.reasoning_tokens !== null && summary.reasoning_tokens > 0);
    const qualified = phase === "qualification" && halted === null && reasoningProven && researchEvalPasses(summary, candidate);
    const report = {
      kind: "research-agent-eval", phase, qualified, halted, started_at: started,
      corpus_version: corpus.version, corpus_sha256: digest(corpusBytes), candidates_sha256: digest(candidateBytes),
      dataset: corpus.dataset, dataset_fixture_sha256: digest(fixtureBytes), evaluation_setup_sha256: setupDigest, clock_window: corpus.clock_window,
      git_revision: revision, tracked_source_diff_sha256: sourceDigest, images,
      model_key: candidate.key, provider_adapter: candidate.provider_adapter, provider_model_id: candidate.provider_model_id,
      provider_endpoint_sha256: providerBaseUrl === null ? null : digest(providerBaseUrl),
      reasoning_effort: effort, reasoning_mapping: providerOptions, reasoning_mapping_proven: reasoningProven,
      startup_registry_sha256: digest(JSON.stringify(registryValue)), capability_inventory_sha256: digest(JSON.stringify(allowedTools)),
      pricing: candidate.pricing, repetitions, thresholds: candidate.thresholds, spend_limit_usd: budget,
      envelope: { ...AGENT_LIMITS, messageBytes: MAX_CHAT_MESSAGE_BYTES, activeRuns: MAX_ACTIVE_AGENT_RUNS,
        cpuCount: 1, memoryBytes: 1073741824, runWallSeconds: 600, mcpTokenLifetimeSeconds: 660, mcpClockSkewSeconds: 30,
        evalTurnObservationMs: RESEARCH_EVAL_TURN_OBSERVATION_MS },
      summary, observations,
    };
    // Every observation is validated again immediately before persistence;
    // the rest is fixed profile/config metadata, never a raw dependency object.
    report.observations = observations.map(validateEvalObservation);
    await writeFile(resolve(evidence, "research-agent-eval.json"), `${JSON.stringify(report, null, 2)}\n`, { mode: 0o600 });
    const rows = summary.case_rates.map((item) => `| ${item.case_id} | ${item.attempts}/${repetitions} | ${(item.success_rate * 100).toFixed(1)}% |`).join("\n");
    await writeFile(resolve(evidence, "research-agent-eval.md"), `# Research Agent real-model evaluation\n\n${phase}; ${candidate.key} / ${effort}; qualified: ${qualified}.\n\nCorpus ${corpus.version}, ${summary.observed_cases}/${summary.expected_cases} cases.\n\nSuccess ${(summary.task_success_rate * 100).toFixed(1)}%; P95 ${summary.duration_p95_ms} ms; primary cost upper bound ${summary.estimated_primary_cost_usd === null ? "unreported" : `$${summary.estimated_primary_cost_usd.toFixed(6)}`}; separate title cost upper bound $${summary.title_cost_upper_bound_usd.toFixed(6)}.\n\nCosts use published Standard reference upper bounds, not verified local proxy charges.\n\n| Case | Attempts | Success |\n| --- | --- | --- |\n${rows}\n\nThe fixed small replay dataset measures workflow correctness, not investment efficacy. Missing accounting and infrastructure failures are not removed from the denominator. No generated text, formulas or tool payloads are retained in this report.\n`, { mode: 0o600 });
    if (phase === "qualification") process.exitCode = qualified ? 0 : 1;
    else process.exitCode = summary.complete && halted === null ? 0 : 1;
  }
}

function docker(args, input) { return command("docker", args, input); }
function command(program, args, input) {
  try { return execFileSync(program, args, { input, encoding: "utf8", stdio: [input === undefined ? "ignore" : "pipe", "pipe", "pipe"], timeout: 60000, maxBuffer: 32 * 1024 * 1024, cwd: repo }); }
  catch { throw new ResearchEvalError("DEPENDENCY_UNAVAILABLE"); }
}
function required(name) { const value = process.env[name]; if (!value) throw new ResearchEvalError("CONFIG_INVALID"); return value; }
async function provision(origin, suffix) {
  const output = JSON.parse(docker(["exec", `${project}-auth-1`, "node", "/test-fixtures/provision-image-smoke-session.mjs",
    `agent-eval-${suffix}@example.test`, "Agent-eval-isolated-password-2026", `198.51.100.${Number.parseInt(digest(suffix).slice(0, 2), 16) || 1}`]));
  if (typeof output.cookie !== "string" || !/^[a-f0-9-]{36}$/.test(output.researcher_id)) throw new ResearchEvalError("DEPENDENCY_UNAVAILABLE");
  const researcher = { origin, cookie: output.cookie, id: output.researcher_id };
  await json(researcher, "/api/researcher/bootstrap", { method: "POST", body: "{}" });
  return researcher;
}
function request(researcher, path, init = {}, timeout = 90000) {
  if (timeout <= 0) throw new ResearchEvalError("DEPENDENCY_UNAVAILABLE");
  return fetch(new URL(path, researcher.origin), { ...init, redirect: "error", signal: AbortSignal.timeout(Math.ceil(timeout)),
    headers: { "content-type": "application/json", origin: researcher.origin, "sec-fetch-site": "same-origin", cookie: researcher.cookie } });
}
async function json(researcher, path, init = {}) {
  const response = await request(researcher, path, init);
  if (!response.ok) throw new ResearchEvalError("DEPENDENCY_UNAVAILABLE");
  return response.json();
}
async function poll(read, ready, timeout = 90000) {
  const deadline = performance.now() + timeout;
  while (performance.now() < deadline) {
    const value = await read();
    if (ready(value)) return value;
    await new Promise((done) => setTimeout(done, 100));
  }
  throw new ResearchEvalError("DEPENDENCY_UNAVAILABLE");
}
function controlWorker(action, worker) {
  if (!["pause", "unpause"].includes(action) || !["research-worker", "tracking-worker"].includes(worker)) throw new ResearchEvalError("CONFIG_INVALID");
  docker([action, `${project}-${worker}-1`]);
  if (action === "pause") paused.add(worker); else paused.delete(worker);
}
async function prepareFixture(researcher, testCase, corpus) {
  const fixture = {};
  if (testCase.fixture === "paused-research") { controlWorker("pause", "research-worker"); return fixture; }
  if (testCase.fixture === "empty") return fixture;
  const run = await json(researcher, "/api/research-runs", { method: "POST", body: JSON.stringify({
    request_id: `eval-fixture-${randomUUID()}`, folder_id: "folder_default", name: "Isolated evaluation fixture",
    formula: "rank(close)", hypothesis: null, start_date: corpus.clock_window.start, end_date: corpus.clock_window.end,
    universe: "top300", neutralization: "none", research_kind: testCase.fixture === "factor" ? "factor_evaluation" : "strategy_backtest",
    ...(testCase.fixture === "factor" ? {} : { holdings_count: 10, rebalance_every_sessions: 1 }),
  }) });
  fixture.runId = run.id;
  await poll(() => json(researcher, `/api/research-runs/${run.id}`), (value) => value.status === "succeeded");
  if (testCase.fixture === "strategy" || testCase.fixture === "factor") return fixture;
  if (testCase.fixture === "blocked-track") controlWorker("pause", "tracking-worker");
  const track = await json(researcher, `/api/research-runs/${run.id}/daily-tracks`, { method: "POST", body: JSON.stringify({ request_id: `eval-start-${randomUUID()}` }) });
  fixture.trackId = track.id;
  if (testCase.fixture === "blocked-track") {
    await json(researcher, `/api/daily-tracks/${track.id}/refresh`, {
      method: "POST", body: JSON.stringify({ request_id: `eval-refresh-${randomUUID()}` }),
    });
    docker(["exec", "--env", "THESISTRACE_TRACKING_WORKER_EXECUTION_MEMORY_BYTES=1", `${project}-api-1`, "thesistrace-core-worker", "--role", "tracking", "--once"]);
    const blocked = await json(researcher, `/api/daily-tracks/${track.id}`);
    if (blocked.status !== "blocked") throw new ResearchEvalError("DEPENDENCY_UNAVAILABLE");
    controlWorker("unpause", "tracking-worker");
  }
  return fixture;
}

function logEvents() {
  const result = [];
  const logs = spawnSync("docker", ["logs", `${project}-agent-1`], { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"], timeout: 10000, maxBuffer: 32 * 1024 * 1024 });
  if (logs.status !== 0) throw new ResearchEvalError("DEPENDENCY_UNAVAILABLE");
  // Docker sends container stderr to CLI stderr. Neither channel is printed.
  for (const line of `${logs.stdout}\n${logs.stderr}`.split("\n")) {
    if (!line.startsWith("{")) continue;
    try { const event = JSON.parse(line); if (event.component === "agent") result.push(event); } catch { /* unrelated safe infrastructure line */ }
  }
  return result;
}
async function terminalObservation(runId, candidate, effort) {
  const event = await poll(() => Promise.resolve(logEvents().find((item) => item.event === "agent_run_finished" && item.run_id === runId)), (item) => item !== undefined, 5000);
  if (event.model_key !== candidate.key || event.provider_model_id !== candidate.provider_model_id || event.reasoning_effort !== effort) throw new ResearchEvalError("REPORT_INVALID");
  const parsed = evalRunSchema.safeParse({ run_id: event.run_id, thread_id: event.thread_id, status: event.status,
    error_category: event.error_category, step_count: event.step_count, duration_ms: event.duration_ms, token_usage: event.token_usage });
  if (!parsed.success) throw new ResearchEvalError("REPORT_INVALID");
  return parsed.data;
}
async function checkArtifact(researcher, testCase, fixture, corpus, threadId) {
  const [runList, batchList, trackList] = await Promise.all(["research-runs", "research-batches", "daily-tracks"].map((resource) => json(researcher, `/api/${resource}`)));
  if (![runList, batchList, trackList].every((value) => Array.isArray(value.items) && value.next_cursor === null)) throw new ResearchEvalError("REPORT_INVALID");
  const ids = [...runList.items, ...batchList.items, ...trackList.items].map((item) => item.id);
  const facts = memoryFacts(researcher, threadId, null);
  const result = (passed, workerFailure = false) => ({ passed, ids, workerFailure, unresolvedAdmissionRejection: facts.unresolved_admission_rejection });
  if (testCase.outcome === "batch") {
    if (batchList.items.length !== 1 || runList.items.length !== 2 || trackList.items.length !== 0) return result(false);
    const batch = await json(researcher, `/api/research-batches/${batchList.items[0].id}`);
    if (batch.items.length !== 2 || batch.batch_kind !== "factor_evaluation") return result(false);
    const children = await Promise.all(batch.items.map((item) => json(researcher, `/api/research-runs/${item.research_run_id}`)));
    const inspected = memoryFacts(researcher, threadId, { kind: "batch-results", run_ids: batch.items.map((item) => item.research_run_id) });
    return result(batch.status === "succeeded" && batch.items.every((item, index) => item.ordinal === index + 1)
      && children.every((run) => validRun(run, "factor_evaluation", corpus))
      && inspected.batch_results_inspected
      && formulaMatches(children[0].input.formula, "price-rank") && formulaMatches(children[1].input.formula, "negative-price-rank"),
    evalBatchWorkerFailure(batch.status));
  }
  if (["track-started", "track-refreshed", "track-recovered"].includes(testCase.outcome)) {
    if (runList.items.length !== 1 || trackList.items.length !== 1 || batchList.items.length !== 0) return result(false);
    const track = await json(researcher, `/api/daily-tracks/${trackList.items[0].id}`);
    return result(track.status === "active" && track.origin.seed_run_id === fixture.runId
      && (!["track-refreshed", "track-recovered"].includes(testCase.outcome)
        || track.strategy_session === corpus.clock_window.head), track.status === "blocked");
  }
  if (runList.items.length !== 1 || trackList.items.length !== 0 || batchList.items.length !== 0) return result(false);
  const run = await json(researcher, `/api/research-runs/${runList.items[0].id}`);
  const kind = testCase.outcome === "strategy" ? "strategy_backtest" : "factor_evaluation";
  const admissionCase = testCase.outcome === "admission-repaired-factor";
  let passed = validRun(run, kind, corpus, admissionCase ? corpus.admission_window.corrected_start : corpus.clock_window.start);
  passed &&= formulaMatches(run.input.formula, ["factor", "clarified-factor"].includes(testCase.outcome) ? "momentum" : admissionCase ? "two-session-mean" : "price-rank");
  if (kind === "strategy_backtest") passed &&= run.input.holdings_count === 10 && run.input.rebalance_every_sessions === 1;
  let admissionCorrection = false;
  if (passed && (testCase.outcome === "repaired-factor" || admissionCase)) {
    const expectedRun = Object.fromEntries(["formula", "start_date", "end_date", "universe", "neutralization", "research_kind"].map((key) => [key, run.input[key]]));
    expectedRun.id = run.id;
    const expectation = admissionCase
      ? { kind: "admission", requested_start: corpus.admission_window.requested_start, run: expectedRun }
      : { kind: "formula", original_formula: "rank(not_a_market_field)", run: expectedRun };
    const correction = memoryFacts(researcher, threadId, expectation);
    admissionCorrection = admissionCase && correction.admission_corrected;
    passed &&= admissionCase ? admissionCorrection : correction.formula_corrected;
  }
  if (testCase.outcome === "explained-result") passed &&= run.id === fixture.runId;
  return { ...result(passed, run.status === "failed"), admissionCorrection };
}
function validRun(run, kind, corpus, startDate = corpus.clock_window.start) {
  return run.status === "succeeded" && run.input.research_kind === kind
    && run.input.universe === "top300" && run.input.neutralization === "none"
    && run.input.start_date === startDate && run.input.end_date === corpus.clock_window.end
    && run.result?.provenance?.research_run_id === run.id
    && (kind === "factor_evaluation" ? run.result.factor !== undefined : run.result.strategy !== undefined);
}
function memoryFacts(researcher, threadId, expectation) {
  const output = docker(["exec", "--interactive", "--env", "THESISTRACE_AGENT_EVAL_ORACLE=isolated", `${project}-agent-1`,
    "node", "--input-type=module", "--eval", "import { runResearchEvalMemoryOracle } from './dist/research-eval-memory.js'; await runResearchEvalMemoryOracle();"],
  JSON.stringify({ thread_id: threadId, researcher_id: researcher.id, expectation }));
  const parsed = researchEvalMemoryFactsSchema.safeParse(JSON.parse(output));
  if (!parsed.success) throw new ResearchEvalError("REPORT_INVALID");
  return parsed.data;
}
async function artifactsArePrivate(peer, ids) {
  // Missing artifacts fail the outcome, not the cross-owner isolation check.
  for (const id of ids) {
    if (!/^(run|batch|track)_[a-f0-9]{20}$/.test(id)) throw new ResearchEvalError("REPORT_INVALID");
    const resource = id.startsWith("run_") ? "research-runs" : id.startsWith("batch_") ? "research-batches" : "daily-tracks";
    const response = await request(peer, `/api/${resource}/${id}`);
    await response.body?.cancel();
    if (response.status !== 404) return false;
  }
  return true;
}
function formulaMatches(formula, outcome) {
  let output;
  try {
    output = execFileSync("uv", ["run", "python", "tests/e2e/support/research_eval_formula.py"], {
      input: JSON.stringify({ formula, outcome }), encoding: "utf8", stdio: ["pipe", "pipe", "pipe"], timeout: 10000, cwd: repo,
    });
  } catch { throw new ResearchEvalError("DEPENDENCY_UNAVAILABLE"); }
  const parsed = JSON.parse(output);
  if (typeof parsed.matches !== "boolean" || Object.keys(parsed).length !== 1) throw new ResearchEvalError("REPORT_INVALID");
  return parsed.matches;
}
