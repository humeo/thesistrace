import { fail, report } from '../config/configuration.mjs';
import { CommandError } from '../process.mjs';
import { deployment } from './compose.mjs';

try {
  const [flag, value, ...extra] = process.argv.slice(2);
  if (!['--email', '--researcher-id'].includes(flag) || !value || extra.length) fail('DEACTIVATION_USAGE_INVALID');
  const compose = deployment('production');
  await compose('config', '--quiet');
  const execute = async (...args) => JSON.parse(await compose('run', '--rm', '--no-deps', '-T', ...args, { capture: true }));
  const resolved = await execute('auth', 'node', 'dist/operator.js', 'resolve', flag, value);
  const id = resolved.researcher_id;
  if (resolved.command !== 'resolve' || resolved.status !== 'resolved' || !/^[0-9a-f-]{36}$/.test(id)) fail('RESEARCHER_RESOLUTION_INVALID');
  const inspection = await execute('api', 'thesistrace-core-access-inspect', 'active-daily-tracks', '--researcher-id', id);
  if (inspection.status !== 'inspected' || inspection.researcher_id !== id || !Number.isSafeInteger(inspection.active_daily_track_count) || inspection.active_daily_track_count < 0) fail('RESEARCHER_INSPECTION_INVALID');
  const mutation = await execute('auth', 'node', 'dist/operator.js', 'deactivate', '--researcher-id', id);
  if (mutation.command !== 'deactivate' || mutation.researcher_id !== id || !['updated', 'no_change'].includes(mutation.status)) fail('RESEARCHER_DEACTIVATION_INVALID');
  console.log(JSON.stringify({ active_daily_track_count: inspection.active_daily_track_count, command: 'deactivate', researcher_id: id, status: mutation.status }));
} catch (error) {
  if (error instanceof CommandError) process.exitCode = error.status;
  else report(error);
}
