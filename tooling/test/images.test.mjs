import { test } from 'node:test';
import assert from 'node:assert/strict';
import { TestImages } from './images.mjs';

const project = 'thesistrace-test-20260930t000000z-1-aaaaaaaa';
const source = 'thesistrace-test-20260930t000000z-2-bbbbbbbb';

test('image reuse and release cover every isolated runtime role, preserving other owners', async () => {
  const commands = [];
  const owned = ['initialize', 'api', 'research-worker', 'batch-research-worker', 'tracking-worker', 'publication-maintenance-worker', 'data-operator-worker', 'auth', 'agent', 'web'].map(role => `${project}-${role}`);
  const images = new TestImages(project, async (_, args) => {
    commands.push(args);
    return args[1] === 'ls' ? [...owned, `${source}-api`, `${project}-unrelated`].join('\n') : '';
  });
  await images.build(() => assert.fail('reuse must not rebuild'), source);
  assert.deepEqual(commands.map(args => args.at(-1)).sort(), [...owned].sort());
  commands.length = 0;
  const results = await images.release();
  assert.deepEqual(results.map(result => result.image).sort(), [...owned].sort());
  assert.ok(results.every(result => result.status === 0));
  assert.equal(commands.some(args => args[1] === 'rm' && !owned.includes(args[2])), false);
});

test('release retains per-image failure evidence and continues cleaning other roles', async () => {
  const removed = [];
  const images = new TestImages(project, async (_, args) => {
    if (args[1] === 'ls') return `${project}-api\n${project}-publication-maintenance-worker\n${project}-web`;
    removed.push(args[2]);
    if (args[2] === `${project}-api`) throw Object.assign(new Error('busy'), { status: 6 });
    return '';
  });
  assert.deepEqual(await images.release(), [
    { image: `${project}-api`, status: 6 },
    { image: `${project}-publication-maintenance-worker`, status: 0 },
    { image: `${project}-web`, status: 0 },
  ]);
  assert.equal(removed.length, 3);
});

test('non-test destination and source identities are refused before Docker commands', async () => {
  const execute = () => assert.fail('invalid identity must not reach Docker');
  assert.throws(() => new TestImages('thesistrace-dev', execute));
  await assert.rejects(new TestImages(project, execute).build(execute, 'thesistrace-dev'));
});
