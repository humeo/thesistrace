export async function integration(run) {
  await run.phase('integration-infrastructure', () => run.compose(['up', '--detach', '--wait', '--wait-timeout', '300', 'postgres', 'rustfs', 'resend-fake']));
  await run.updatePorts('rustfs');
  await run.phase('integration-rustfs-s3-ready', () => run.waitForS3());
  await run.phase('integration-auth-initialization', () => run.compose(['up', '--detach', 'auth-initialize']));
  await run.phase('integration-auth-initializer-exit', () => run.compose(['wait', 'auth-initialize']));
  await run.phase('integration-auth', () => run.compose(['up', '--detach', '--wait', '--wait-timeout', '120', 'auth']));
  await run.updatePorts('postgres', 'rustfs', 'auth', 'resend-fake');
  run.auth_internal_origin = `http://127.0.0.1:${run.auth_port}`;
  run.resend_test_origin = `http://127.0.0.1:${run.resend_port}`;
  run.record(Object.fromEntries(['postgres_port', 's3_port', 'auth_port', 'resend_port'].map(key => [key, run[key]])));
  await run.phase('integration-initialization', () => run.host(['uv', 'run', 'thesistrace-initialize']));
  const pytest = ['uv', 'run', 'pytest', '-c', `${run.repo_root}/apps/core/pyproject.toml`, '--rootdir', run.repo_root, '-q'];
  await run.phase('integration-pytest', () => run.host([...pytest, 'apps/core/tests/integration', 'apps/core/tests/acceptance', '-m', 'not database_restart and not dependency_restart and not real_codex', `--junitxml=${run.pytest_report}`]));
  for (const [phase, target, marker, report] of [
    ['database-restart', 'test_core_direct_research_run_admission.py', 'database_restart', run.database_restart_report],
    ['rustfs-restart', 'test_core_research_batch_factor_recovery.py::test_real_rustfs_loss_retries_the_complete_factor_task', '', run.dependency_restart_report],
    ['rustfs-strategy-restart', 'test_core_research_batch_strategy_execution.py::test_real_rustfs_loss_retries_shared_strategy_prerequisite', '', `${run.evidence_dir}/pytest-rustfs-strategy-restart.xml`],
    ['rustfs-batch-cancel-restart', 'test_core_research_batch_cancel.py::test_cancel_is_terminal_while_object_cleanup_retries_after_rustfs_restart', '', `${run.evidence_dir}/pytest-rustfs-batch-cancel-restart.xml`],
    ['postgres-batch-restart', 'test_core_research_batch_factor_recovery.py::test_real_postgres_loss_recovers_after_child_exit', '', `${run.evidence_dir}/pytest-postgres-batch-restart.xml`],
    ['postgres-strategy-restart', 'test_core_research_batch_strategy_execution.py::test_real_postgres_loss_reuses_acknowledged_private_artifact', '', `${run.evidence_dir}/pytest-postgres-strategy-restart.xml`],
  ]) {
    await run.updatePorts('postgres', 'rustfs');
    await run.phase(`integration-${phase}`, () => run.host([...pytest, `apps/core/tests/acceptance/${target}`, ...(marker ? ['-m', marker] : []), `--junitxml=${report}`], { env: { THESISTRACE_DATABASE_RESTART_PHASE: '1' } }));
  }
}
