import { mkdirSync } from 'node:fs';
export async function performance(run) {
  await run.phase('performance-images', () => run.buildImages());
  await run.phase('performance-infrastructure', () => run.compose(['up', '--detach', '--no-build', '--wait', '--wait-timeout', '300', 'postgres', 'rustfs', 'initialize']));
  await run.phase('performance-initialization', () => run.compose(['wait', 'initialize']));
  mkdirSync(`${run.evidence_dir}/long-research`, { recursive: true });
  const script = '/qualification/long_research_qualification.py';
  await run.phase('performance-prepare', () => run.composeRun(['initialize', 'python', script, 'prepare', '--output', '/smoke-evidence/long-research/preparation.json']));
  const kinds = ['factor_evaluation', 'strategy_backtest'];
  for (const phase of ['cold', 'warm']) {
    if (phase === 'warm') {
      await run.phase('performance-warm-preload-product-state-reset', () => run.resetProductState());
      await run.phase('performance-warm-preload', () => run.composeRun(['research-worker', 'python', script, 'preload', '--output', '/qualification-evidence/long-research/preload.json']));
    }
    for (const kind of kinds) for (let index = 0; index < 5; index++) {
      const name = `${kind}-${phase}-${index}`;
      await run.phase(`performance-${name}-product-state-reset`, () => run.resetProductState());
      await run.phase(`performance-${name}-api`, () => run.prepareBenchmarkApi());
      await run.phase(`performance-${name}`, () => run.composeRun(['-e', 'THESISTRACE_TEST_API_ORIGIN=http://api:8100', 'research-worker', 'python', script, 'sample', '--research-kind', kind, '--phase', phase, '--index', String(index), '--require-fresh-product-state', '--log', `/qualification-evidence/long-research/${name}.log`, '--output', `/qualification-evidence/long-research/${name}.json`]), { timeoutMs: 60 * 60 * 1000 });
    }
  }
  for (const kind of kinds) {
    await run.phase(`performance-${kind}-cancellation-product-state-reset`, () => run.resetProductState());
    await run.phase(`performance-${kind}-cancellation-api`, () => run.prepareBenchmarkApi());
    await run.phase(`performance-${kind}-cancellation`, () => run.composeRun(['-e', 'THESISTRACE_TEST_API_ORIGIN=http://api:8100', 'research-worker', 'python', script, 'cancel', '--research-kind', kind, '--log', `/qualification-evidence/long-research/${kind}-cancellation.log`, '--output', `/qualification-evidence/long-research/${kind}-cancellation.json`]));
  }
  const image = (await run.exec('docker', ['image', 'inspect', `${run.project_name}-initialize`, '--format', '{{.Id}}'], { capture: true })).trim();
  await run.phase('performance-qualification', () => run.composeRun(['initialize', 'python', script, 'assemble', '--samples', '/smoke-evidence/long-research', '--image-revision', image, '--output', '/smoke-evidence/long-research-qualification.json']));
  for (const [file, args] of [['api.log', ['logs', '--no-color', 'api']], ['compose-ps.txt', ['ps', '--all']], ['images.jsonl', ['images', '--format', 'json']]]) await run.compose(args, { stdoutFile: `${run.evidence_dir}/long-research/${file}` });
}
