import { existsSync, rmSync, rmdirSync } from 'node:fs';
import { imageServices } from './resources.mjs';
import { captureEvidence, captureLogs, sanitize, scanCanaries } from './evidence.mjs';

export async function cleanupImages(run) {
  if (run.keep_images) return;
  const names = (await run.exec('docker', ['image', 'ls', '--format', '{{.Repository}}', '--filter', `reference=${run.project_name}-*`], { capture: true })).trim().split('\n');
  let failure;
  for (const service of imageServices) {
    const name = `${run.project_name}-${service}`;
    if (!names.includes(name)) continue;
    try { await run.exec('docker', ['image', 'rm', name], { quiet: true }); } catch (error) { failure ??= error; }
  }
  if (failure) throw failure;
}
export async function cleanupProject(run) {
  // Existing-project commands validate persisted metadata at the CLI boundary.
  // An active run already owns this identity even if its evidence disk failed.
  run.validateProject();
  let failure, composeFailed = false;
  const attempt = async operation => { try { await operation(); } catch (error) { failure ??= error; } };
  if (run.compose_cleanup_required) {
    try { await run.compose(['down', '--volumes', '--remove-orphans']); }
    catch (error) { composeFailed = true; failure = error; }
    await attempt(() => run.exec(`${run.repo_root}/tooling/dev/product-state-volumes.mjs`, ['erase', run.project_name]));
    if (!composeFailed) await attempt(() => cleanupImages(run));
  }
  for (const path of ['canonical-data', 'benchmark-data', 'batch-attempt-control', 'operator-browser-state']) await attempt(() => rmSync(`${run.run_root}/${path}`, { recursive: true, force: true }));
  if (!composeFailed) await attempt(() => run.releasePort());
  if (failure) throw failure;
}
export async function finish(run, initialStatus) {
  let status = initialStatus;
  run.cleaning = true;
  run.controller = new AbortController();
  run.phaseSignal = undefined;
  const attempt = async operation => { try { await operation(); return 0; } catch (error) { return error.status ?? 1; } };
  const record = values => {
    try { run.record(values); }
    catch { status ||= 1; console.error('could not write Test run metadata'); }
  };
  const secrets = await attempt(() => {
    if (!run.secret_dir) return;
    for (const path of [run.auth_session_file, run.operator_sessions_file].filter(Boolean)) rmSync(path, { force: true });
    rmdirSync(run.secret_dir);
  });
  if (!existsSync(run.run_metadata) && !run.port_acquired && !run.compose_cleanup_required) return status || secrets;
  record({ runtime_secret_cleanup_status: secrets });
  if (secrets) { console.error('runtime secret cleanup failed'); status ||= secrets; }
  // Scan originals before sanitization: redaction must not make a leak pass.
  const diagnostics = await attempt(() => captureEvidence(run));
  const logs = await attempt(() => captureLogs(run));
  record({ diagnostic_capture_status: diagnostics, log_capture_status: logs });
  status ||= diagnostics || logs;
  const scan = await attempt(() => sanitize(run, 'scan', { stdoutFile: `${run.evidence_dir}/raw-canary-scan.json` }));
  record({ raw_canary_scan_status: scan });
  if (scan) { console.error('content canary detected in original diagnostics; see sanitized categories'); status ||= 1; }
  if (status) {
    const sanitized = await attempt(() => sanitize(run, 'sanitize'));
    if (sanitized) {
      console.error('failed to sanitize MCP failure evidence');
      const discarded = await attempt(() => sanitize(run, 'discard'));
      record({ failure_evidence_discard_status: discarded });
      if (discarded) console.error('failed to discard unsanitized MCP evidence');
    }
    record({ failure_evidence_sanitization_status: sanitized, failure_canary_scan_status: await attempt(() => scanCanaries(run)) });
  }
  if (status && run.keep_environment && run.compose_cleanup_required) {
    console.error(`preserved failing Test project ${run.project_name}`);
    record({ cleanup_status: 'kept' });
  } else {
    const started = Date.now();
    const cleanup = await attempt(() => cleanupProject(run));
    record({ cleanup_seconds: Math.floor((Date.now() - started) / 1000), cleanup_status: cleanup });
    if (cleanup) console.error(`cleanup failed for Test project ${run.project_name} (status ${cleanup})`);
    status ||= cleanup;
  }
  record({ status });
  return status;
}
