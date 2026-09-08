#!/usr/bin/env node
import { CommandError } from '../process.mjs';
import { TestRun, runId } from './resources.mjs';
import { cleanupProject, finish } from './cleanup.mjs';

const phases = { integration: 'integration', e2e: 'e2e', 'agent-eval': 'e2e', 'image-smoke': 'image-smoke', 'image-qualification': 'image-qualification', performance: 'performance', 'codex-mcp': 'codex', 'integration-batch-cancel': 'batch-cancel' };
let run;
try {
  const [command, ...args] = process.argv.slice(2);
  if (command === 'identity') {
    if (args.length) throw new CommandError('Test identity accepts no arguments', 2);
    console.log(`thesistrace-test-${runId()}`);
  } else if (['cleanup', 'stop-postgres', 'restart-postgres', 'stop-rustfs', 'restart-rustfs'].includes(command)) {
    if (args.length) throw new CommandError('Test resource commands accept no arguments', 2);
    run = new TestRun(command, { project: process.env.THESISTRACE_TEST_PROJECT_NAME ?? '' });
    run.loadExisting();
    run.compose_cleanup_required = true;
    if (command === 'cleanup') await cleanupProject(run);
    else {
      const service = command.endsWith('postgres') ? 'postgres' : 'rustfs';
      await run.compose([command.startsWith('stop-') ? 'stop' : 'restart', service], { stdout: 2 });
      if (command.startsWith('restart-')) {
        const deadline = Date.now() + 60000;
        while (true) {
          try {
            await run.compose(['exec', '-T', service, ...(service === 'postgres' ? ['pg_isready', '-U', 'thesistrace_owner', '-d', 'thesistrace'] : ['sh', '-c', 'curl -fsS http://127.0.0.1:9000/health'])], { quiet: true });
            break;
          } catch (error) {
            if (error.status >= 128) throw error;
            if (Date.now() >= deadline) throw new CommandError(`${service} did not become ready after restart`, 1);
            await new Promise(resolve => setTimeout(resolve, 250));
          }
        }
        const port = await run.mappedPort(service, service === 'postgres' ? 5432 : 9000);
        if (service === 'rustfs') {
          run.s3_port = port;
          try { await run.waitForS3(); } catch (error) { console.error('RustFS S3 API did not become ready after restart'); throw error; }
        }
        console.log(port);
      }
    }
  } else {
    if (!Object.hasOwn(phases, command) || args.length > 1 || (args.length && args[0] !== '--keep-environment')) throw new CommandError('invalid Test command or options', 2);
    run = new TestRun(command, { keepEnvironment: args.length === 1 });
    if (command === 'agent-eval') {
      if (run.keep_environment) throw new CommandError('agent-eval cannot retain a credential-bearing environment', 2);
      await run.exec('pnpm', ['--dir', `${run.repo_root}/apps/agent`, 'build']);
      run.agent_openai_api_key = process.env.THESISTRACE_AGENT_OPENAI_API_KEY ?? '';
      run.agent_openai_base_url = process.env.THESISTRACE_AGENT_OPENAI_BASE_URL ?? '';
      run.agent_anthropic_api_key = process.env.THESISTRACE_AGENT_ANTHROPIC_API_KEY ?? '';
      run.agent_google_api_key = process.env.THESISTRACE_AGENT_GOOGLE_API_KEY ?? '';
      run.eval_controls = Object.fromEntries(['MODEL_KEY', 'REASONING_EFFORT', 'PHASE', 'SPEND_LIMIT_USD']
        .map(key => `THESISTRACE_AGENT_EVAL_${key}`).filter(key => process.env[key] !== undefined)
        .map(key => [key, process.env[key]]));
      run.agent_model_registry = (await run.exec('node', [`${run.repo_root}/apps/agent/scripts/eval-research.mjs`, 'configure'], { capture: true })).trim();
      run.agent_scripted_model_secret = '';
      run.agent_build_revision = (await run.exec('git', ['-C', run.repo_root, 'rev-parse', 'HEAD'], { capture: true })).trim();
    }
    const signal = name => {
      if (run.cleaning) return;
      run.interrupted_status = name === 'SIGINT' ? 130 : 143;
      run.controller.abort();
    };
    const onInt = () => signal('SIGINT'), onTerm = () => signal('SIGTERM');
    process.on('SIGINT', onInt); process.on('SIGTERM', onTerm);
    let result = 0;
    try {
      await run.allocate();
      await run.compose(['config', '--quiet']);
      run.compose_cleanup_required = true;
      const module = await import(`./phases/${phases[command]}.mjs`);
      await module[phases[command].replace(/-([a-z])/g, (_, letter) => letter.toUpperCase())](run);
    } catch (error) {
      result = run.interrupted_status || error.status || 1;
      console.error(error.message);
    } finally {
      process.exitCode = await finish(run, result);
      process.off('SIGINT', onInt); process.off('SIGTERM', onTerm);
    }
  }
} catch (error) {
  console.error(error.message);
  process.exitCode = error.status ?? 1;
}
