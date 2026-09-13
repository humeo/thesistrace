import { TestRun } from '../../tooling/test/resources.mjs';
import { finish } from '../../tooling/test/cleanup.mjs';

// Reuse isolated PostgreSQL provisioning/cleanup. This is real-source preparation,
// explicitly distinct from deterministic regression/qualification test results.
const run = new TestRun('integration');
let result = 0;
try {
  await run.allocate();
  await run.compose(['config', '--quiet']);
  run.compose_cleanup_required = true;
  run.record({ purpose: 'Ticket07 authorized real financial indicator history collection' });
  await run.phase('indicator-history-database', () => run.compose([
    'up', '--detach', '--wait', '--wait-timeout', '300', 'postgres',
  ]));
  await run.updatePorts('postgres');
  await run.phase('indicator-history-schema', () => run.host(['uv', 'run', 'thesistrace-initialize']));
  await run.phase('indicator-history-source', () => run.host([
    'uv', 'run', 'python', '.scratch/data-field-expansion-20260912/collect_indicator_history.py',
    '--root', '.local/field-expansion-226-candidate/candidate-data',
    '--source-scope', '.scratch/data-field-expansion-20260912/issue07-collection-scope.json',
    '--output', '.scratch/data-field-expansion-20260912/issue07-indicator-history.json',
  ]), { timeoutMs: 6 * 60 * 60 * 1000 });
} catch (error) {
  result = error.status || 1;
  console.error(error);
} finally {
  process.exitCode = await finish(run, result);
}
