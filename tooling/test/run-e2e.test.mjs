import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, copyFileSync, writeFileSync, readFileSync, readdirSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { resolve, join } from 'node:path';
import { spawnSync } from 'node:child_process';

for (const mode of ['success', 'test-failure', 'cleanup-failure', 'reverse']) test(`E2E groups preserve lifecycle evidence after ${mode}`, () => {
  const failing = mode === 'test-failure';
  const cwd = mkdtempSync(join(tmpdir(), 'e2e-runner-'));
  try {
    mkdirSync(join(cwd, 'tooling/test'), {recursive:true}); mkdirSync(join(cwd, 'bin'));
    for (const file of ['run-e2e.mjs', 'e2e-groups.mjs']) copyFileSync(resolve('tooling/test', file), join(cwd, 'tooling/test', file));
    const executable = (path, body) => writeFileSync(join(cwd, path), `#!${process.execPath}\n${body}`, { mode: 0o755 });
    executable('bin/pnpm', `
      const specs = ['read', 'write A', 'write B'].map((title, i) => ({ title, id: String(i), tags: i ? ['isolated'] : [] }));
      const idx = process.argv.indexOf('--grep');
      const selected = idx < 0 ? specs : specs.filter(s => new RegExp(process.argv[idx + 1]).test('case.spec.ts ' + s.title));
      console.log(JSON.stringify({ suites: [{ title: 'case.spec.ts', specs: selected }] }));
    `);
    executable('bin/docker', `
      if (${mode === 'cleanup-failure'} && process.argv[3] === 'ls') process.exit(1);
      if (process.argv[3] === 'ls') console.log(['initialize','api','research-worker','batch-research-worker','tracking-worker','data-operator-worker','auth','agent','web'].map(name => 'thesistrace-test-20260907t000000z-1-aaaaaaaa-' + name).join('\\n'));
      require('node:fs').appendFileSync('docker.log', process.argv.slice(2).join(' ') + '\\n');
    `);
    executable('tooling/test/cli.mjs', `
      const fs = await import('node:fs');
      const previous = fs.existsSync('runs.json') ? JSON.parse(fs.readFileSync('runs.json')) : [];
      const project = 'thesistrace-test-20260907t000000z-' + (previous.length + 1) + '-aaaaaaaa';
      previous.push({ project, source: process.env.THESISTRACE_TEST_IMAGE_SOURCE_PROJECT, keep: process.env.THESISTRACE_TEST_KEEP_IMAGES });
      fs.writeFileSync('runs.json', JSON.stringify(previous));
      console.log('Compose project: ' + project);
      process.exit(${failing} && previous.length === 1 ? 1 : 0);
    `);
    const result = spawnSync(process.execPath, ['tooling/test/run-e2e.mjs'], { cwd, env: { ...process.env, PATH: `${cwd}/bin:${process.env.PATH}`, THESISTRACE_TEST_PLAYWRIGHT_GREP: '', THESISTRACE_TEST_E2E_GROUP_ORDER: mode === 'reverse' ? 'reverse' : undefined }, encoding: 'utf8', timeout: 15_000 });
    assert.equal(result.status, ["success", "reverse"].includes(mode) ? 0 : 1, result.stderr);
    const runs = JSON.parse(readFileSync(join(cwd, 'runs.json')));
    assert.equal(runs.length, 3);
    assert.equal(new Set(runs.map(run => run.project)).size, 3);
    assert.deepEqual(runs.map(run => run.source), ['', runs[0].project, runs[0].project]);
    assert.deepEqual(runs.map(run => run.keep), ['1', '0', '0']);
    const evidence = readdirSync(join(cwd, '.local/e2e-runs'))[0];
    const results = JSON.parse(readFileSync(join(cwd, '.local/e2e-runs', evidence, 'results.json')));
    assert.deepEqual(results.map(result => result.status), [failing ? 1 : 0, 0, 0]);
    assert.deepEqual(results.map(result => result.name), mode === 'reverse'
      ? ['case.spec.ts write B', 'case.spec.ts write A', 'ordinary']
      : ['ordinary', 'case.spec.ts write A', 'case.spec.ts write B']);
    const cleanup = JSON.parse(readFileSync(join(cwd, '.local/e2e-runs', evidence, 'cleanup.json')));
    if (mode === 'cleanup-failure') assert.deepEqual(cleanup, [{ operation: 'image-list', status: 1 }]);
    else assert.match(readFileSync(join(cwd, 'docker.log'), 'utf8'), new RegExp(`image rm ${runs[0].project}-agent`));
  } finally { rmSync(cwd, { recursive: true, force: true }); }
});
