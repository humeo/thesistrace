export async function imageSmoke(run) {
  // The image overlay supplies a deterministic OAuth identity for MCP checks.
  const mcpResource = 'https://core.test/mcp';
  run.smoke_state = "/smoke-evidence/image-smoke-state.json";
  run.bootstrap_replay = "/smoke-evidence/tushare-financial-product-full-replay.json";
  await run.phase("image-smoke-images", () => run.buildImages());
  await run.phase("image-smoke-infrastructure", () => run.compose(["up", "--detach", "--no-build", "--wait", "--wait-timeout", "300", "postgres", "rustfs"]));
  await run.phase("image-smoke-rustfs-s3-ready", () => run.waitForS3(true));
  await run.phase("image-smoke-initializers", () => run.compose(["up", "--detach", "--no-build", "initialize", "auth-initialize"]));
  await run.phase("image-smoke-initialization", () => run.compose(["wait", "initialize", "auth-initialize"]));
  await run.phase("image-smoke-bootstrap-replay", () => run.composeRun(["initialize", "python", "/smoke/tests/e2e/support/prepare_image_smoke_bootstrap_replay.py", "--input", "/smoke/tests/fixtures/tushare-financial-product-replay.json", "--output", run.bootstrap_replay]));
  await run.phase("image-smoke-operator-bootstrap", () => run.composeRun(["initialize", "thesistrace-data-operator", "bootstrap", "--idempotency-key", "financial-release-bootstrap", "--as-of", "2026-08-05T18:00:00+08:00", "--start-date", "2010-01-04", "--replay", run.bootstrap_replay]));
  await run.phase("image-smoke-prepare-data", () => run.composeRun(["initialize", "python", "/smoke/tests/e2e/support/prepare_image_smoke_data.py"]));
  await run.phase("image-smoke-application", () => run.compose(["up", "--detach", "--no-build", "--wait", "--wait-timeout", "300", "auth", "agent", "api", "web", "research-worker", "batch-research-worker", "tracking-worker", "publication-maintenance-worker", "data-operator-worker"]));
  run.postgres_port = await run.mappedPort("postgres", "5432");
  run.s3_port = await run.mappedPort("rustfs", "9000");
  await run.phase("image-smoke-auth-session", () => run.provisionAuth());
  await run.phase("image-smoke-health", () => run.check("verify_image_health", ["initial"]));
  await run.phase("image-smoke-caddy-single-origin", () => run.check("verify_caddy_single_origin", [mcpResource]));
  await run.phase("image-smoke-startup", () => run.composeRun([
    "-e", "THESISTRACE_TEST_API_ORIGIN=http://api:8100",
    "-e", "THESISTRACE_TEST_WEB_ORIGIN=http://web:" + run.caddy_port,
    "-e", "THESISTRACE_TEST_SMOKE_STATE=" + run.smoke_state,
    "initialize", "python", "/smoke/tests/production_image_smoke.py", "startup",
  ], {stdoutFile: run.evidence_dir + "/startup.json", stderrFile: run.evidence_dir + "/startup.stderr.log"}));
}
