import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { test } from 'node:test';
import { runPhase } from './phase.mjs';
import { run } from '../process.mjs';

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
    await assert.rejects(runPhase('timeout', signal => run(process.execPath, ['-e', 'require("node:fs").writeFileSync(process.argv[1], String(process.pid)); setInterval(() => {}, 1000)', pidFile], { signal }), { metadata, timeoutMs: 500 }), { status: 124 });
    const pid = Number(readFileSync(pidFile, 'utf8'));
    assert.throws(() => process.kill(pid, 0), { code: 'ESRCH' });
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
    await assert.rejects(runPhase('descendant-timeout', signal => run(process.execPath, ['-e', script, pidFile], { signal }), { timeoutMs: 500 }), { status: 124 });
    descendant = Number(readFileSync(pidFile, 'utf8'));
    assert.throws(() => process.kill(descendant, 0), { code: 'ESRCH' });
  } finally {
    if (descendant) { try { process.kill(descendant, 'SIGKILL'); } catch {} }
    rmSync(directory, { recursive: true, force: true });
  }
});
