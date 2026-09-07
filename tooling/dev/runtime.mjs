import { fail, report, root } from '../config/configuration.mjs';
import { CommandError, run } from '../process.mjs';
import { existing } from './existing.mjs';
import { deployment } from './compose.mjs';

try {
  const [mode, action, ...args] = process.argv.slice(2);
  if (!['development', 'production'].includes(mode)) fail('RUNTIME_USAGE_INVALID');
  const project = mode === 'production' ? 'thesistrace' : 'thesistrace-dev';
  if (mode === 'development' && process.env.THESISTRACE_DEV_PROJECT_NAME !== undefined && process.env.THESISTRACE_DEV_PROJECT_NAME !== project) fail('RUNTIME_PROJECT_INVALID');
  if (['stop', 'down', 'status', 'logs'].includes(action)) {
    if ((args.length && action !== 'logs') || (mode === 'development' && action === 'down') || (mode === 'production' && action === 'stop')) fail('RUNTIME_USAGE_INVALID');
    await existing(project, action, args);
  } else {
    if (!['validate', 'bootstrap', 'up', 'watch', 'reset', 'erase', 'run'].includes(action) || (args.length && action !== 'run')
      || (action === 'run' && !args.length) || (mode === 'production' && !['validate', 'up', 'run'].includes(action))) fail('RUNTIME_USAGE_INVALID');
    if (action === 'bootstrap') {
      await run('mise', ['install'], { cwd: root });
      await run('uv', ['sync', '--project', 'apps/core', '--frozen'], { cwd: root });
      await run('mise', ['exec', '--', 'pnpm', 'install', '--frozen-lockfile'], { cwd: root });
    }
    const compose = deployment(mode);
    await compose('config', '--quiet');
    const start = () => compose('up', '--detach', '--build', '--wait', '--wait-timeout', '300');
    if (action === 'up') await start();
    else if (action === 'bootstrap') { await compose('pull', 'postgres', 'rustfs'); await compose('build'); }
    else if (action === 'run') await compose('run', '--rm', '--no-deps', '-T', ...args);
    else if (action === 'reset' || action === 'erase') {
      await compose('down', '--remove-orphans');
      await run(`${root}/tooling/dev/product-state-volumes.mjs`, [action, project]);
      if (action === 'reset') await start();
    } else if (action === 'watch') {
      try { await compose('up', '--watch'); }
      catch (error) {
        if (!(error instanceof CommandError) || ![130, 143].includes(error.status)) throw error;
        await existing(project, 'stop');
      }
    }
  }
} catch (error) {
  if (error instanceof CommandError) process.exitCode = error.status;
  else report(error);
}
