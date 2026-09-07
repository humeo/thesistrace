import { test } from 'node:test';
import assert from 'node:assert/strict';
import { groupsFromReport } from './e2e-groups.mjs';

test('ordinary cases share a group and each mutation has its own exact selection', () => {
  const report = { suites: [{ title: 'file.spec.ts', specs: [
    { title: 'read (one)', tags: [] }, { title: 'write A', tags: ['isolated'] },
    { title: 'write B', tags: ['isolated'] },
  ] }] };
  const groups = groupsFromReport(report);
  assert.equal(groups.length, 3);
  assert.ok(new RegExp(groups[0].grep).test('file.spec.ts read (one)'));
  assert.equal(groupsFromReport(report, 'write B').length, 1);
  assert.deepEqual(groupsFromReport(report, 'absent'), []);
});
