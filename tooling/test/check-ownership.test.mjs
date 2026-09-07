import { test } from 'node:test';
import assert from 'node:assert/strict';
import { checkFiles, owners } from './check-ownership.mjs';

test('new unit and integration tests have distinct owners', () => {
  assert.deepEqual(owners('apps/agent/src/new.integration.test.ts'), ['agent-integration']);
  assert.deepEqual(owners('apps/web/src/chat/new.test.tsx'), ['web-unit']);
  assert.deepEqual(owners('apps/core/tests/acceptance/test_real_codex_research_agent_mcp.py'), ['core-codex']);
});
test('unknown directories and overlapping suites fail closed', () => {
  assert.equal(checkFiles(['tests/unknown/test_new.py']).length, 1);
  assert.equal(checkFiles(['new-tests/test_new.py']).length, 1);
  assert.deepEqual(checkFiles(['apps/web/src/new.test.ts'], { a: ['apps/web/**'], b: ['apps/web/**'] }), ['apps/web/src/new.test.ts: expected one test suite, found a, b']);
  assert.deepEqual(checkFiles(['tests/e2e/support/prepare_data.py', 'tests/e2e/fixtures/page.tsx']), []);
});
