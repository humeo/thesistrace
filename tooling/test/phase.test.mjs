import assert from 'node:assert/strict';
import { existsSync, mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { test } from 'node:test';
import { runPhase } from './phase.mjs';
import { run } from '../process.mjs';

async function timeoutReadyProcess(name, args, pidFile, options = {}) {
  const controller = new AbortController();
  const running = run(process.execPath, args, { signal: controller.signal });
  // Attach a rejection handler immediately, including failures before readiness.
  const settled = running.catch(() => {});
  try {
    const deadline = Date.now() + 10000;
    while (!existsSync(pidFile)) {
      assert.ok(Date.now() < deadline, 'fixture process did not become ready');
      await new Promise(resolve => setTimeout(resolve, 10));
    }
    await assert.rejects(runPhase(name, signal => {
      signal.addEventListener('abort', () => controller.abort(), { once: true });
      return running;
    }, { ...options, timeoutMs: 20 }), { status: 124 });
    const pid = Number(readFileSync(pidFile, 'utf8'));
    assert.throws(() => process.kill(pid, 0), { code: 'ESRCH' });
  } finally {
    controller.abort();
    await settled;
  }
}

test('phase failure preserves its exit status and records bounded evidence', async () => {
  const directory = mkdtempSync(join(tmpdir(), 'thesistrace-phase-'));
  try {
    const metadata = join(directory, 'run.txt');
    await assert.rejects(runPhase('fixture', signal => run(process.execPath, ['-e', 'process.exit(6)'], { signal }), { metadata }), { status: 6 });
    assert.match(readFileSync(metadata, 'utf8'), /^phase=fixture seconds=\d+ status=6\n$/);
  } finally { rmSync(directory, { recursive: true, force: true }); }
});

test('phase timeout terminates and waits for its process before returning', async () => {
  const directory = mkdtempSync(join(tmpdir(), 'thesistrace-phase-'));
  try {
    const metadata = join(directory, 'run.txt');
    const pidFile = join(directory, 'pid');
    await timeoutReadyProcess('timeout', ['-e', 'require("node:fs").writeFileSync(process.argv[1], String(process.pid)); setInterval(() => {}, 1000)', pidFile], pidFile, { metadata });
    assert.match(readFileSync(metadata, 'utf8'), /status=124\n$/);
  } finally { rmSync(directory, { recursive: true, force: true }); }
});

test('phase timeout reaps a descendant that ignores termination after its parent exits', async () => {
  const directory = mkdtempSync(join(tmpdir(), 'thesistrace-phase-descendant-'));
  const pidFile = join(directory, 'pid');
  let descendant;
  try {
    const script = `const {spawn} = require('node:child_process');
      const child = spawn(process.execPath, ['-e', 'process.on("SIGTERM", () => {}); require("node:fs").writeFileSync(process.argv[1], String(process.pid)); setInterval(() => {}, 1000)', process.argv[1]], {stdio: 'ignore'});
      setInterval(() => {}, 1000);`;
    await timeoutReadyProcess('descendant-timeout', ['-e', script, pidFile], pidFile);
    descendant = Number(readFileSync(pidFile, 'utf8'));
  } finally {
    if (descendant) { try { process.kill(descendant, 'SIGKILL'); } catch {} }
    rmSync(directory, { recursive: true, force: true });
  }
});
