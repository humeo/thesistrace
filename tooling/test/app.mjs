#!/usr/bin/env node
import assert from 'node:assert/strict';
import { randomBytes } from 'node:crypto';
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { root } from '../config/configuration.mjs';
import { CommandError } from '../process.mjs';
import { execute } from './commands.mjs';
import { deterministicEnvironment } from './environment.mjs';
import { runId } from './resources.mjs';
import { runPhase } from './phase.mjs';

const [app, command, ...args] = process.argv.slice(2);
let result = 0;
if (!['auth', 'agent'].includes(app) || !['integration', 'image-smoke', ...(app === 'agent' ? ['schema-generate'] : ['runner-contract-self-check'])].includes(command)) {
  console.error('usage: app.mjs {auth|agent} {integration|image-smoke|schema-generate}');
  process.exitCode = 2;
} else {
  const appRoot = `${root}/apps/${app}`, id = runId();
  const project = `thesistrace-${app}-test-${id}`, image = `thesistrace-${app}-test:${id}`;
  const evidence = mkdtempSync(`${tmpdir()}/thesistrace-${app}-test.`);
  const secret = randomBytes(32).toString('hex');
  const canary = `stale-image-canary-${id}.js`, canaryPath = `${appRoot}/dist/${canary}`;
  const controller = new AbortController();
  const environment = { ...deterministicEnvironment(process.env), COMPOSE_ANSI: 'never', COMPOSE_PROGRESS: 'plain',
    [`THESISTRACE_${app.toUpperCase()}_TEST_IMAGE`]: image,
    ...(app === 'auth' ? { THESISTRACE_AUTH_TEST_SECRET: secret } : {
      THESISTRACE_AGENT_TEST_OPENAI_SECRET: secret,
      THESISTRACE_AGENT_TEST_MODEL_REGISTRY: readFileSync(`${appRoot}/fixtures/image-model-registry.json`, 'utf8').trim(),
    }),
  };
  let cleaning = false, phaseSignal;
  const exec = (program, argv, options = {}) => execute(program, argv, { cwd: appRoot, env: environment, signal: cleaning ? undefined : phaseSignal ?? controller.signal, interruptible: !cleaning, ...options });
  const compose = (argv, options) => exec('docker', ['compose', '--env-file', '/dev/null', '--project-name', project, '--file', `${appRoot}/compose.test.yaml`, ...argv], options);
  const onInt = () => { if (!cleaning) { result = 130; controller.abort(); } };
  const onTerm = () => { if (!cleaning) { result = 143; controller.abort(); } };
  process.on('SIGINT', onInt); process.on('SIGTERM', onTerm);
  const phase = (name, operation) => runPhase(`${app}-${name}`, async signal => {
    phaseSignal = signal;
    try { await operation(); } finally { phaseSignal = undefined; }
  }, { signal: controller.signal, metadata: `${evidence}/run.txt` });
  const port = async (service, internal) => {
    const mapped = (await compose(['port', service, String(internal)], { capture: true })).trim().split(':').at(-1);
    if (!/^\d+$/.test(mapped) || +mapped < 1 || +mapped > 65535) throw new CommandError('could not resolve test service port', 1);
    return mapped;
  };
  const postgres = async () => {
    await compose(['up', '--detach', 'postgres']);
    const deadline = Date.now() + 20000;
    while (true) {
      try { await compose(['exec', '-T', 'postgres', 'test', '-e', `/tmp/thesistrace-${app}-test-initialization-held`], { quiet: true }); break; }
      catch (error) {
        if (controller.signal.aborted || phaseSignal?.aborted) throw error;
        if (Date.now() >= deadline) throw new CommandError('PostgreSQL did not enter the held initialization phase', 1);
        await new Promise(resolve => setTimeout(resolve, 50));
      }
    }
    const container = (await compose(['ps', '--quiet', 'postgres'], { capture: true })).trim();
    assert.notEqual((await exec('docker', ['inspect', '--format', '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}', container], { capture: true })).trim(), 'healthy');
    assert.notEqual((await compose(['exec', '-T', 'postgres', 'cat', '/proc/1/comm'], { capture: true })).trim(), 'postgres');
    await compose(['exec', '-T', 'postgres', 'touch', `/tmp/thesistrace-${app}-test-initialization-release`]);
    await compose(['up', '--detach', '--wait', '--wait-timeout', '120', 'postgres']);
  };
  const capture = async () => {
    for (const [name, argv] of [['compose-ps', ['ps', '--all']], ['compose-logs', ['logs', '--no-color']]]) {
      try { await compose(argv, { stdoutFile: `${evidence}/${name}.txt`, stderrFile: `${evidence}/${name}.stderr.txt` }); } catch { /* Best effort after the original failure. */ }
    }
  };
  try {
    if (command === 'runner-contract-self-check') {
      if (args.length !== 1 || !['success', 'int', 'term'].includes(args[0])) throw new CommandError('invalid runner self check', 2);
      if (args[0] === 'int') { onInt(); throw new CommandError('interrupted', 130); }
      if (args[0] === 'term') { onTerm(); throw new CommandError('terminated', 143); }
    } else {
      if (command !== 'integration' && args.length) throw new CommandError('unexpected application test arguments', 2);
      await compose(['config', '--quiet']);
      if (command === 'image-smoke') {
        mkdirSync(`${appRoot}/dist`, { recursive: true });
        writeFileSync(canaryPath, 'throw new Error("stale image canary executed")\n');
        await phase('image-build', () => compose(['build', app]));
        await phase('postgres', postgres);
        await phase('image-start', () => compose(['up', '--detach', '--no-build', '--wait', '--wait-timeout', '180', app]));
        const mapped = await port(app, app === 'auth' ? 8200 : 8400);
        await phase('image-contract', () => exec('sh', [`${appRoot}/test-fixtures/image-checks.sh`], { env: {
          ...environment, [`${app}_root`]: appRoot, [`${app}_port`]: mapped, project_name: project, compose_file: `${appRoot}/compose.test.yaml`,
          evidence_root: evidence, test_secret: secret, openai_secret: secret, stale_canary_name: canary,
        } }));
      } else {
        await phase('postgres', postgres);
        const mapped = await port('postgres', 5432);
        const env = { ...environment, [`THESISTRACE_${app.toUpperCase()}_TEST_OWNER_DATABASE_URL`]: `postgresql://thesistrace_owner:owner-test-password@127.0.0.1:${mapped}/thesistrace`, COPILOTKIT_TELEMETRY_DISABLED: 'true', TZ: 'Asia/Seoul' };
        if (command === 'schema-generate') {
          await phase('build', () => exec('pnpm', ['build']));
          await phase('schema-generate', () => exec('node', [`${appRoot}/scripts/generate-schema-contract.mjs`], { env: { ...env, THESISTRACE_AGENT_SCHEMA_GENERATION: 'isolated' } }));
        } else {
          if (app === 'auth') await phase('build', () => exec(`${appRoot}/node_modules/.bin/tsc`, ['--project', `${appRoot}/tsconfig.build.json`, '--pretty', 'false']));
          await phase('integration', () => exec(`${appRoot}/node_modules/.bin/vitest`, ['run', '--root', appRoot, '--config', `${appRoot}/vitest.integration.config.ts`, ...args], { env }));
        }
      }
    }
  } catch (error) { result ||= error.status ?? 1; console.error(error.message); }
  finally {
    cleaning = true;
    if (result) await capture();
    try {
      await compose(['down', '--volumes', '--remove-orphans'], { stdoutFile: `${evidence}/cleanup.stdout.log`, stderrFile: `${evidence}/cleanup.stderr.log` });
    } catch (error) { if (!result) await capture(); result ||= error.status ?? 1; console.error(`${app === 'auth' ? 'Auth' : 'Agent'} test cleanup failed`); }
    try { rmSync(canaryPath, { force: true }); } catch (error) { result ||= 1; console.error(error.message); }
    // A project owns its application image tag; retain it only if Docker still uses it.
    if (command === 'image-smoke') {
      try {
        const images = (await exec('docker', ['image', 'ls', '--format', '{{.Repository}}:{{.Tag}}', '--filter', `reference=${image}`], { capture: true })).trim().split('\n');
        if (images.includes(image)) await exec('docker', ['image', 'rm', image], { quiet: true });
      } catch (error) { result ||= error.status ?? 1; }
    }
    if (!result) { try { rmSync(evidence, { recursive: true }); } catch { result = 1; } }
    if (result) console.error(`${app === 'auth' ? 'Auth' : 'Agent'} test evidence: ${evidence}`);
    process.off('SIGINT', onInt); process.off('SIGTERM', onTerm);
    process.exitCode = result;
  }
}
