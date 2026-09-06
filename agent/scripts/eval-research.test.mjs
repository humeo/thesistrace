import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { test } from "node:test";

const environment = {
  PATH: process.env.PATH,
  COPILOTKIT_TELEMETRY_DISABLED: "true",
  THESISTRACE_AGENT_OPENAI_API_KEY: "offline-provider-key-canary",
  THESISTRACE_AGENT_OPENAI_BASE_URL: "http://host.docker.internal:8317/v1",
  THESISTRACE_AGENT_EVAL_MODEL_KEY: "gpt-5.6-luna",
  THESISTRACE_AGENT_EVAL_REASONING_EFFORT: "high",
  THESISTRACE_AGENT_EVAL_PHASE: "baseline",
  THESISTRACE_AGENT_EVAL_SPEND_LIMIT_USD: "20",
};
// No inherited credentials and no network, even if a preflight regresses.
const networkGuard = 'data:text/javascript,globalThis.fetch=()=>{throw new Error("OFFLINE_NETWORK_FORBIDDEN")}';
const offlinePreflightTimeoutMs = 30_000;

function invoke(command, overrides = {}) {
  const result = spawnSync(process.execPath, ["--import", networkGuard, "scripts/eval-research.mjs", command], {
    cwd: new URL("../", import.meta.url), env: { ...environment, ...overrides },
    encoding: "utf8", timeout: offlinePreflightTimeoutMs,
  });
  assert.equal(result.error, undefined);
  assert.ok(!result.stdout.includes(environment.THESISTRACE_AGENT_OPENAI_API_KEY));
  assert.ok(!result.stderr.includes(environment.THESISTRACE_AGENT_OPENAI_API_KEY));
  return result;
}

test("offline preflight rejects a finite reserve without a model-call bound", () => {
  const result = invoke("configure");
  assert.equal(result.status, 2);
  assert.equal(result.stdout, "");
  assert.equal(result.stderr.trim(), "RESEARCH_EVAL_CONFIG_INVALID");
});

for (const [label, command, overrides] of [
  ["unsupported effort", "configure", { THESISTRACE_AGENT_EVAL_REASONING_EFFORT: "minimal" }],
  ["superseded model", "configure", { THESISTRACE_AGENT_EVAL_MODEL_KEY: "gpt-5.4-mini" }],
  ["missing spending authorization", "configure", { THESISTRACE_AGENT_EVAL_SPEND_LIMIT_USD: "" }],
  ["missing provider credential", "configure", { THESISTRACE_AGENT_OPENAI_API_KEY: "" }],
  ["missing explicit provider endpoint", "configure", { THESISTRACE_AGENT_OPENAI_BASE_URL: "", OPENAI_BASE_URL: "https://unapproved.example/v1" }],
  ["credential-bearing endpoint", "configure", { THESISTRACE_AGENT_OPENAI_BASE_URL: "https://offline-provider-key-canary@provider.example/v1" }],
  ["endpoint with query credentials", "configure", { THESISTRACE_AGENT_OPENAI_BASE_URL: "https://provider.example/v1?key=offline-provider-key-canary" }],
  ["remote plain HTTP endpoint", "configure", { THESISTRACE_AGENT_OPENAI_BASE_URL: "http://provider.example/v1" }],
  ["malformed endpoint", "configure", { THESISTRACE_AGENT_OPENAI_BASE_URL: "not-a-url" }],
  ["non-isolated project", "run", { THESISTRACE_TEST_PROJECT_NAME: "not-an-isolated-project" }],
]) {
  test(`offline preflight rejects ${label} without content or dependency access`, () => {
    const result = invoke(command, overrides);
    assert.equal(result.status, 2);
    assert.equal(result.stdout, "");
    assert.match(result.stderr, /^RESEARCH_EVAL_(CONFIG_INVALID|DEPENDENCY_UNAVAILABLE)\n$/);
  });
}
