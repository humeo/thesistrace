import assert from 'node:assert/strict';
import { mkdtempSync, rmSync, writeFileSync, existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { test } from 'node:test';
import { TestRun } from './resources.mjs';
import { finish } from './cleanup.mjs';

for (const initial of [0, 6]) for (const failure of ['evidence-directory', 'metadata-write']) {
  test(`${failure} failure still cleans owned resources and preserves initial status ${initial}`, async () => {
    const directory = mkdtempSync(`${tmpdir()}/thesistrace-cleanup-`);
    try {
      const run = new TestRun('integration', { ambient: { THESISTRACE_TEST_STATE_ROOT: directory } });
      run.createMounts(); run.setOrigin(5180);
      writeFileSync(run.run_metadata, `project_name=${run.project_name}\ncaddy_port=5180\n`);
      run.port_acquired = true; run.compose_cleanup_required = true;
      let stopped = false, portReleased = false;
      run.compose = async args => { if (args[0] === 'down') stopped = true; return ''; };
      run.exec = async () => '';
      run.releasePort = async () => { portReleased = true; };
      if (failure === 'evidence-directory') rmSync(run.evidence_dir, { recursive: true });
      else run.record = () => { throw Object.assign(new Error('read-only metadata'), { code: 'EACCES' }); };
      assert.equal(await finish(run, initial), initial || 1);
      assert.ok(stopped); assert.ok(portReleased);
      assert.equal(existsSync(run.data_mount), false);
    } finally { rmSync(directory, { recursive: true, force: true }); }
  });
}
