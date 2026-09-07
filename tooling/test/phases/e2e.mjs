export async function e2e(run) {
  await run.phase('e2e-images', () => run.buildImages());
  await run.phase('e2e-infrastructure', () => run.compose(['up', '--detach', '--no-build', '--wait', '--wait-timeout', '300', 'postgres', 'rustfs']));
  await run.updatePorts('rustfs');
  await run.phase('e2e-rustfs-s3-ready', () => run.waitForS3());
  await run.phase('e2e-initializers', () => run.compose(['up', '--detach', '--no-build', 'initialize', 'auth-initialize']));
  await run.phase('e2e-initialization', () => run.compose(['wait', 'initialize', 'auth-initialize']));
  await run.updatePorts('postgres', 'rustfs');
  await run.phase('e2e-operator-bootstrap', () => run.host(['uv', 'run', 'thesistrace-data-operator', 'bootstrap', '--idempotency-key', 'financial-release-bootstrap', '--as-of', '2026-08-05T18:00:00+08:00', '--start-date', '2010-01-04', '--replay', 'tests/fixtures/tushare-financial-product-replay.json']));
  await run.phase('e2e-prepare-data', () => run.host(['uv', 'run', 'python', 'tests/e2e/support/prepare_current_data.py']));
  await run.phase('e2e-application', () => run.compose(['up', '--detach', '--no-build', '--wait', '--wait-timeout', '300', 'auth', 'auth-fixture-control', 'agent', 'api', 'research-worker', 'batch-research-worker', 'tracking-worker', 'data-operator-worker', 'web']));
  await run.phase('e2e-tushare-secret-scope', () => run.check('verify_tushare_secret_scope'));
  await run.updatePorts('resend-fake', 'auth-fixture-control', 'auth-exchange-proxy', 'mcp-fault-proxy');
  for (const [origin, port] of [['resend_test_origin', 'resend_port'], ['auth_fixture_origin', 'auth_fixture_port'], ['auth_proxy_origin', 'auth_proxy_port'], ['mcp_proxy_origin', 'mcp_proxy_port']]) run[origin] = `http://127.0.0.1:${run[port]}`;
  run.record(Object.fromEntries(['postgres_port', 's3_port', 'resend_port', 'auth_fixture_port', 'auth_proxy_port', 'mcp_proxy_port'].map(key => [key, run[key]])));
  await run.phase('e2e-auth-fixture-ready', () => run.waitForAuthFixture());
  await run.phase('e2e-caddy-single-origin', () => run.check('verify_caddy_single_origin', [run.mcp_resource_url]));
  if (run.command === 'agent-eval') await run.phase('agent-eval-real-provider', () => run.host(['node', `${run.repo_root}/apps/agent/scripts/eval-research.mjs`, 'run']));
  else await run.phase('e2e-playwright', () => run.host(['pnpm', 'exec', 'playwright', 'test', '--config', 'tests/playwright.config.ts', ...(run.playwright_grep ? ['--grep', run.playwright_grep] : [])]));
}
