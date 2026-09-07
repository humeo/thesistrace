import { writeFileSync } from 'node:fs';

const inspectFormat = 'id={{.Id}} name={{.Name}} image={{.Image}} status={{.State.Status}} running={{.State.Running}} exit_code={{.State.ExitCode}} oom_killed={{.State.OOMKilled}} health={{with index .State "Health"}}{{.Status}}{{else}}none{{end}} log_driver={{.HostConfig.LogConfig.Type}} log_max_size={{index .HostConfig.LogConfig.Config "max-size"}} log_max_file={{index .HostConfig.LogConfig.Config "max-file"}}';
export const logFiles = { 'worker-events.jsonl': ['research-worker', 'batch-research-worker', 'tracking-worker', 'data-operator-worker'], 'api-events.jsonl': ['api'], 'caddy-events.jsonl': ['web'], 'auth-events.jsonl': ['auth'], 'agent-events.jsonl': ['agent'] };
export async function captureEvidence(run) {
  for (const [file, args] of [['compose-ps.txt', ['ps', '--all']], ['compose-logs.txt', ['logs', '--no-color', '--timestamps']]]) {
    try { await run.compose(args, { stdoutFile: `${run.evidence_dir}/${file}`, stderrFile: `${run.evidence_dir}/${file}.stderr` }); } catch {}
  }
  let inspection = '';
  try {
    const ids = (await run.compose(['ps', '--all', '--quiet'], { capture: true, quiet: true })).trim().split('\n').filter(Boolean);
    for (const id of ids) inspection += await run.exec('docker', ['inspect', '--format', inspectFormat, id], { capture: true, quiet: true });
  } catch {}
  writeFileSync(`${run.evidence_dir}/container-inspect.txt`, inspection);
}
export async function captureLogs(run, files = Object.keys(logFiles)) {
  for (const file of files) await run.compose(['logs', '--no-color', ...logFiles[file]], { stdoutFile: `${run.evidence_dir}/${file}`, stderrFile: `${run.evidence_dir}/${file}.stderr` });
}
export function sanitize(run, action, options = {}) {
  return run.exec('uv', ['run', 'python', `${run.repo_root}/tests/sanitize_production_mcp_evidence.py`, action, run.evidence_dir], options);
}
export async function scanCanaries(run) {
  try { await sanitize(run, 'verify'); writeFileSync(`${run.evidence_dir}/secret-canary-scan.txt`, 'passed\n'); }
  catch (error) { writeFileSync(`${run.evidence_dir}/secret-canary-scan.txt`, 'failed\n'); throw error; }
}
