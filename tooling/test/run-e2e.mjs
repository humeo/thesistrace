import { spawn, execFileSync } from 'node:child_process';
import { mkdirSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { groupsFromReport } from './e2e-groups.mjs';

if (process.argv.length > 2) throw new Error('Use THESISTRACE_TEST_PLAYWRIGHT_GREP to select E2E cases');
const filter = process.env.THESISTRACE_TEST_PLAYWRIGHT_GREP;
const groupOrder = process.env.THESISTRACE_TEST_E2E_GROUP_ORDER;
if (groupOrder !== undefined && groupOrder !== 'reverse') throw new Error('Unsupported E2E group order');
const evidence = resolve('.local/e2e-runs', `${Date.now()}-${process.pid}`);
mkdirSync(evidence, { recursive: true });
const report = JSON.parse(execFileSync('pnpm', ['exec', 'playwright', 'test', '--config', 'tests/playwright.config.ts', '--list', '--reporter=json', ...(filter ? ['--grep', filter] : [])], {
  encoding: 'utf8', maxBuffer: 10 * 1024 * 1024,
  env: { ...process.env, THESISTRACE_TEST_WEB_ORIGIN: 'http://127.0.0.1', THESISTRACE_TEST_EVIDENCE_DIR: evidence },
}));
if (report.errors?.length) throw new Error('E2E collection failed');
const groups = groupsFromReport(report);
if (groupOrder === 'reverse') groups.reverse();
if (!groups.length) throw new Error('E2E selection matched no tests');
for (const group of groups) {
  const selected = JSON.parse(execFileSync('pnpm', ['exec', 'playwright', 'test', '--config', 'tests/playwright.config.ts', '--list', '--reporter=json', '--grep', group.grep], {
    encoding: 'utf8', maxBuffer: 10 * 1024 * 1024,
    env: { ...process.env, THESISTRACE_TEST_WEB_ORIGIN: 'http://127.0.0.1', THESISTRACE_TEST_EVIDENCE_DIR: evidence },
  }));
  const actual = groupsFromReport(selected).flatMap(item => item.ids).sort();
  if (JSON.stringify(actual) !== JSON.stringify([...group.ids].sort())) throw new Error(`Ambiguous E2E selection: ${group.name}`);
}
let sourceProject;
let child;
let cancelled = false;
for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => { cancelled = true; child?.kill(signal); });
const results = [];
let cleanupFailed = false;
try {
  for (const group of groups) {
    if (cancelled) break;
    const started = Date.now();
    let project;
    let pending = '';
    const status = await new Promise((resolveStatus, reject) => {
      child = spawn('./tooling/test/runtime', ['e2e'], {
        env: { ...process.env, THESISTRACE_TEST_PLAYWRIGHT_GREP: group.grep,
          THESISTRACE_TEST_IMAGE_SOURCE_PROJECT: sourceProject ?? '',
          THESISTRACE_TEST_KEEP_IMAGES: sourceProject ? '0' : '1' },
        stdio: ['inherit', 'pipe', 'inherit'],
      });
      child.stdout.on('data', data => {
        process.stdout.write(data);
        pending += data.toString();
        const lines = pending.split('\n'); pending = lines.pop();
        for (const line of lines) {
          const match = /^Compose project: (thesistrace-test-\d{8}t\d{6}z-\d+-[a-f0-9]{8})$/.exec(line);
          if (match) project = match[1];
        }
      });
      child.on('error', reject);
      child.on('exit', code => resolveStatus(code ?? 130));
    });
    sourceProject ??= project;
    results.push({ name: group.name, project, status, elapsed_ms: Date.now() - started });
    writeFileSync(`${evidence}/results.json`, JSON.stringify(results, null, 2));
    if (!project) break;
  }
} finally {
  if (sourceProject) {
    const cleanup = [];
    try {
      const existing = execFileSync('docker', ['image', 'ls', '--format', '{{.Repository}}', '--filter', `reference=${sourceProject}-*`], { encoding: 'utf8' }).trim().split('\n');
      for (const service of ['initialize', 'api', 'research-worker', 'batch-research-worker', 'tracking-worker', 'data-operator-worker', 'auth', 'agent', 'web']) {
        const image = `${sourceProject}-${service}`;
        if (!existing.includes(image)) continue;
        try {
          execFileSync('docker', ['image', 'rm', image], { stdio: 'ignore' });
          cleanup.push({ image, status: 0 });
        } catch {
          cleanupFailed = true;
          cleanup.push({ image, status: 1 });
        }
      }
    } catch {
      cleanupFailed = true;
      cleanup.push({ operation: 'image-list', status: 1 });
    }
    writeFileSync(`${evidence}/cleanup.json`, JSON.stringify(cleanup, null, 2));
  }
}
console.log(`E2E group results: ${evidence}/results.json`);
process.exitCode = cancelled ? 130 : cleanupFailed || results.length !== groups.length || results.some(result => result.status !== 0) ? 1 : 0;
