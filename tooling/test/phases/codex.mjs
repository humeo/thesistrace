import { readFileSync } from 'node:fs';
import { CommandError } from '../../process.mjs';
export async function codex(run) {
  await run.phase('codex-mcp-host-preflight', async () => {
    try { await run.exec('codex', ['--ask-for-approval', 'never', 'exec', '--help'], { quiet: true }); }
    catch (error) { throw new CommandError(error.code === 'ENOENT' ? 'real Codex acceptance requires the Codex CLI' : 'real Codex acceptance requires the supported noninteractive CLI contract', 1); }
  });
  await run.phase('codex-mcp-infrastructure', () => run.compose(['up', '--detach', '--wait', '--wait-timeout', '300', 'postgres', 'rustfs']));
  await run.updatePorts('postgres', 'rustfs');
  run.record({ postgres_port: run.postgres_port, s3_port: run.s3_port });
  await run.phase('codex-mcp-initialization', () => run.host(['uv', 'run', 'thesistrace-initialize']));
  const evidence = `${run.evidence_dir}/codex-stdio-acceptance.json`;
  await run.phase('codex-mcp-acceptance', () => run.host(['uv', 'run', 'pytest', '-c', `${run.repo_root}/apps/core/pyproject.toml`, '--rootdir', run.repo_root, '-q', 'apps/core/tests/acceptance/test_real_codex_research_agent_mcp.py', '-m', 'real_codex'], { env: { THESISTRACE_REAL_CODEX_EVIDENCE_PATH: evidence } }));
  await run.phase('codex-mcp-evidence', () => {
    if (JSON.parse(readFileSync(evidence, 'utf8')).status !== 'passed') throw new CommandError('Codex evidence did not pass', 1);
  });
}
