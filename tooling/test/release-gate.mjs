#!/usr/bin/env node
import { root } from '../config/configuration.mjs';
import { execute } from './commands.mjs';
import { deterministicEnvironment } from './environment.mjs';

function fail(code) { console.error(JSON.stringify({ code, event: 'release_gate_failed' })); process.exit(2); }
if (process.argv.length !== 2) fail('RELEASE_GATE_USAGE_INVALID');
let revision, state;
try {
  revision = (await execute('git', ['-C', root, 'rev-parse', '--verify', 'HEAD^{commit}'], { capture: true, quiet: true })).trim();
  state = await execute('git', ['-C', root, 'status', '--porcelain=v1', '--untracked-files=normal'], { capture: true, quiet: true });
} catch { fail('RELEASE_GIT_STATE_INVALID'); }
if (!/^[0-9a-f]{40,64}$/.test(revision)) fail('RELEASE_GIT_STATE_INVALID');
if (state.trim()) fail('RELEASE_WORKTREE_DIRTY');
const report = event => console.log(JSON.stringify({ event, git_revision: revision, real_model_eval: 'not_run', model_qualification: 'pending' }));
try {
  report('release_gate_started');
  for (const command of ['check', 'test:image:qualification']) await execute('pnpm', [command], { cwd: root, env: deterministicEnvironment(process.env) });
  report('release_gate_completed');
} catch (error) { process.exitCode = error.status ?? 1; }
