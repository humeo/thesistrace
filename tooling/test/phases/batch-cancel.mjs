export async function batchCancel(run) {
  await run.phase('integration-batch-cancel-infrastructure', () => run.compose(['up', '--detach', '--wait', '--wait-timeout', '300', 'postgres', 'rustfs']));
  await run.updatePorts('postgres', 'rustfs');
  run.record({ postgres_port: run.postgres_port, s3_port: run.s3_port });
  await run.phase('integration-batch-cancel-initialization', () => run.host(['uv', 'run', 'thesistrace-initialize']));
  const pytest = ['uv', 'run', 'pytest', '-c', `${run.repo_root}/apps/core/pyproject.toml`, '--rootdir', run.repo_root, '-q'];
  const test = 'apps/core/tests/acceptance/test_core_research_batch_cancel.py';
  await run.phase('integration-batch-cancel-pytest', () => run.host([...pytest, test, '-m', 'not database_restart and not dependency_restart', `--junitxml=${run.pytest_report}`]));
  for (const [phase, name, report] of [
    ['postgres-restart', 'test_cancel_check_fails_closed_during_postgres_outage_and_reconciles_after_restart', run.database_restart_report],
    ['rustfs-restart', 'test_cancel_is_terminal_while_object_cleanup_retries_after_rustfs_restart', run.dependency_restart_report],
  ]) {
    await run.updatePorts('postgres', 'rustfs');
    await run.phase(`integration-batch-cancel-${phase}`, () => run.host([...pytest, `${test}::${name}`, `--junitxml=${report}`], { env: { THESISTRACE_DATABASE_RESTART_PHASE: '1' } }));
  }
}
