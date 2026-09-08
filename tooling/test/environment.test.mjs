import assert from 'node:assert/strict';
import { test } from 'node:test';
import { hostEnvironment } from './environment.mjs';
import { TestRun } from './resources.mjs';

test('host S3 clients use the credentials of their selected test deployment', () => {
  for (const command of ['integration', 'e2e', 'image-smoke', 'image-qualification', 'performance']) {
    const environment = hostEnvironment(new TestRun(command, { ambient: {} }));
    const image = command === 'image-smoke' || command === 'image-qualification' || command === 'performance';
    assert.equal(environment.THESISTRACE_S3_ACCESS_KEY_ID,
      image ? 'observability-access-canary' : 'rustfsadmin', command);
    assert.equal(environment.THESISTRACE_S3_SECRET_ACCESS_KEY,
      image ? 'observability-secret-canary' : 'rustfsadmin', command);
  }
});
