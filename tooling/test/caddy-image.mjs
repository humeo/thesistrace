#!/usr/bin/env node
import assert from 'node:assert/strict';
import { mkdtempSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { root } from '../config/configuration.mjs';
import { execute } from './commands.mjs';
import { runId } from './resources.mjs';
import { runPhase } from './phase.mjs';
import { deterministicEnvironment } from './environment.mjs';
import { CommandError } from '../process.mjs';

const id = runId(), prefix = `thesistrace-caddy-smoke-${id}`;
const evidence = mkdtempSync(`${tmpdir()}/thesistrace-caddy-smoke.`);
const names = { image_name: prefix, container_name: `${prefix}-web`, auth_container_name: `${prefix}-auth`, client_one_name: `${prefix}-client-one`, client_two_name: `${prefix}-client-two`, network_name: `${prefix}-network`, volume_name: `${prefix}-data` };
const { image_name: image, container_name: web, auth_container_name: auth, network_name: network, volume_name: volume } = names;
const environment = { ...deterministicEnvironment(process.env), ...names, repo_root: root, evidence_root: evidence };
const controller = new AbortController();
let result = 0, cleaning = false, phaseSignal;
const exec = (command, args, options = {}) => execute(command, args, { cwd: root, env: environment, signal: cleaning ? undefined : phaseSignal ?? controller.signal, interruptible: !cleaning, ...options });
const docker = (args, options) => exec('docker', args, options);
const phase = (name, operation) => runPhase(`caddy-${name}`, async signal => {
  phaseSignal = signal;
  try { await operation(); } finally { phaseSignal = undefined; }
}, { signal: controller.signal, metadata: `${evidence}/phases.txt` });
const onInt = () => { if (!cleaning) { result = 130; controller.abort(); } };
const onTerm = () => { if (!cleaning) { result = 143; controller.abort(); } };
process.on('SIGINT', onInt); process.on('SIGTERM', onTerm);
const start = async () => {
  const proxyIp = (await docker(['inspect', '--format', '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}', names.client_one_name], { capture: true })).trim();
  await docker(['run', '--detach', '--name', web, '--hostname', 'thesistrace.test', '--network', network, '--network-alias', 'thesistrace.test',
    '--env', 'THESISTRACE_PUBLIC_ORIGIN=https://thesistrace.test', '--env', 'THESISTRACE_CADDY_TLS_DIRECTIVE=tls internal',
    '--env', `THESISTRACE_CADDY_TRUSTED_PROXIES_DIRECTIVE=trusted_proxies static ${proxyIp}`,
    '--env', 'THESISTRACE_CADDY_HSTS_DIRECTIVE=header >Strict-Transport-Security "max-age=31536000"', '--volume', `${volume}:/data`, image], { stdoutFile: `${evidence}/container-id.txt` });
  const deadline = Date.now() + 20000;
  while (true) {
    try { await docker(['exec', web, 'wget', '--quiet', '--no-check-certificate', '--output-document', '/dev/null', 'https://thesistrace.test/data'], { quiet: true }); return; }
    catch (error) {
      if (controller.signal.aborted || phaseSignal?.aborted) throw error;
      if (Date.now() >= deadline) throw new CommandError('Caddy HTTPS listener did not become ready', 1);
      await new Promise(resolve => setTimeout(resolve, 100));
    }
  }
};
const certificates = async () => (await docker(['exec', web, 'find', '/data/caddy/certificates/local', '-type', 'f', '-name', '*.crt', '-exec', 'sha256sum', '{}', ';'], { capture: true })).trim().split('\n').sort().join('\n');
try {
  if (process.argv.length !== 2) throw new CommandError('Caddy image check accepts no arguments', 2);
  await phase('build', () => docker(['build', '--file', `${root}/apps/web/Dockerfile`, '--tag', image, root]));
  await phase('infrastructure', async () => {
    await docker(['network', 'create', network], { stdoutFile: `${evidence}/network-id.txt` });
    await docker(['volume', 'create', volume], { stdoutFile: `${evidence}/volume-name.txt` });
    await docker(['run', '--detach', '--name', auth, '--network', network, '--network-alias', 'auth', '--volume', `${root}/deploy/caddy/Caddyfile.header-echo.test:/etc/caddy/Caddyfile:ro`, '--entrypoint', 'caddy', image, 'run', '--config', '/etc/caddy/Caddyfile'], { stdoutFile: `${evidence}/auth-container-id.txt` });
    for (const client of [names.client_one_name, names.client_two_name]) await docker(['run', '--detach', '--name', client, '--network', network, '--entrypoint', '/bin/sh', image, '-c', 'exec sleep 300'], { stdoutFile: `${evidence}/${client}.id` });
    await start();
  });
  await phase('routing', () => exec('sh', ['tests/caddy-image-checks.sh', 'routing']));
  await phase('certificate-reuse', async () => {
    const certificates_before = await certificates();
    assert.ok(certificates_before);
    await docker(['rm', '--force', web], { quiet: true });
    await start();
    const certificates_after = await certificates();
    assert.equal(certificates_after, certificates_before);
  });
  await phase('security', () => exec('sh', ['tests/caddy-image-checks.sh', 'security']));
  await phase('idle-close-race', async () => {
    await docker(['logs', auth], { stdoutFile: `${evidence}/auth-header-echo.log`, stderrFile: `${evidence}/auth-header-echo.stderr.log` });
    await docker(['rm', '--force', auth], { quiet: true });
    await docker(['run', '--detach', '--name', auth, '--network', network, '--network-alias', 'auth', '--network-alias', 'api', '--volume', `${root}/tests/fixtures/caddy-keepalive-upstream.mjs:/keepalive-probe.mjs:ro`, 'node:24.14.0-bookworm-slim@sha256:d3d197c99e937af98e07c7830622c243d836a7485e6131495418232e787308fe', 'node', '/keepalive-probe.mjs', 'serve'], { stdoutFile: `${evidence}/keepalive-container-id.txt` });
    await docker(['exec', auth, 'node', '/keepalive-probe.mjs', 'probe'], { stdoutFile: `${evidence}/keepalive.json`, stderrFile: `${evidence}/keepalive.stderr.log` });
  });
} catch (error) { result ||= error.status ?? 1; console.error(error.message); }
finally {
  cleaning = true;
  writeFileSync(`${evidence}/run.txt`, Object.entries({ run_id: id, ...names, initial_status: result }).map(([key, value]) => `${key}=${value}\n`).join(''));
  for (const [file, args] of [
    ['docker-version.txt', ['version']], ['caddy.log', ['logs', web]], ['auth-echo.log', ['logs', auth]],
    ['container-inspect.json', ['container', 'inspect', web]], ['image-inspect.json', ['image', 'inspect', image]], ['network-inspect.json', ['network', 'inspect', network]], ['volume-inspect.json', ['volume', 'inspect', volume]],
  ]) { try { await docker(args, { stdoutFile: `${evidence}/${file}`, stderrFile: `${evidence}/${file}.stderr` }); } catch { /* Capture what is available before cleanup. */ } }
  let cleanup = 0;
  for (const [kind, name] of [['container', web], ['container', auth], ['container', names.client_one_name], ['container', names.client_two_name], ['network', network], ['volume', volume], ['image', image]]) {
    try { await docker([kind, 'inspect', name], { quiet: true }); }
    catch (error) { if (error.status !== 1) cleanup ||= error.status ?? 1; continue; }
    try { await docker(kind === 'container' ? ['rm', '--force', name] : [kind, 'rm', name], { quiet: true }); }
    catch (error) { cleanup ||= error.status ?? 1; }
  }
  result ||= cleanup;
  writeFileSync(`${evidence}/cleanup-status.txt`, `${cleanup}\n`);
  writeFileSync(`${evidence}/final-status.txt`, `${result}\n`);
  if (!result) { try { rmSync(evidence, { recursive: true }); } catch { result = 1; } }
  if (result) console.error(`Caddy Production image-smoke evidence: ${evidence}`);
  process.off('SIGINT', onInt); process.off('SIGTERM', onTerm);
  process.exitCode = result;
}
