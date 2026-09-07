import { test } from 'node:test';
import assert from 'node:assert/strict';
import { checkFiles, owners } from './check-test-ownership.mjs';

test('new unit and integration tests have distinct owners', () => {
  assert.deepEqual(owners('agent/src/new.integration.test.ts'), ['agent-integration']);
  assert.deepEqual(owners('web/src/chat/new.test.tsx'), ['web-unit']);
});
test('unknown directories and overlapping suites fail closed', () => {
  assert.equal(checkFiles(['tests/unknown/test_new.py']).length, 1);
  assert.equal(checkFiles(['web/src/new.test.ts'], { a: ['web/**'], b: ['web/**'] }).length, 1);
  assert.deepEqual(checkFiles(['tests/browser/prepare_data.py', 'web/e2e-core/fixtures/page.tsx']), []);
});
