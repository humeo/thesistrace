import { run } from '../process.mjs';
import { fail } from '../config/configuration.mjs';

export async function existing(project, action, services = []) {
  if (!['thesistrace-dev', 'thesistrace'].includes(project)) fail('RUNTIME_PROJECT_INVALID');
  if (services.some(name => !/^[a-z][a-z0-9-]*$/.test(name))) fail('RUNTIME_SERVICE_INVALID');
  const filter = ['--filter', `label=com.docker.compose.project=${project}`];
  if (action === 'status') { await run('docker', ['ps', '--all', ...filter]); return; }
  // Query Docker's exact Compose labels; neither YAML interpolation nor credentials are needed.
  const list = async service => (await run('docker', ['ps', '--all', ...filter,
    ...(service ? ['--filter', `label=com.docker.compose.service=${service}`] : []), '--format', '{{.ID}}'], { capture: true })).trim().split(/\s+/).filter(Boolean);
  const ids = [...new Set((await Promise.all((services.length ? services : [null]).map(list))).flat())];
  if (action === 'logs') {
    const cancellation = new AbortController();
    let failure;
    await Promise.allSettled(ids.map(id => run('docker', ['logs', '--follow', '--timestamps', id], {
      signal: cancellation.signal,
    }).catch(error => {
      failure ??= error;
      cancellation.abort();
    })));
    if (failure) throw failure;
  }
  else if (action === 'stop' && ids.length) await run('docker', ['stop', ...ids]);
  else if (action === 'down') {
    if (ids.length) {
      await run('docker', ['stop', ...ids]);
      await run('docker', ['rm', ...ids]);
    }
    const networks = (await run('docker', ['network', 'ls', ...filter, '--format', '{{.ID}}'], { capture: true })).trim().split(/\s+/).filter(Boolean);
    if (networks.length) await run('docker', ['network', 'rm', ...networks]);
  }
}
