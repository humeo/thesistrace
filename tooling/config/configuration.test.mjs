import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { resolve } from 'node:path';
import { test } from 'node:test';
import { parseEnv } from 'node:util';

const root = resolve(import.meta.dirname, '../..');
const cli = resolve(root, 'tooling/config/cli.mjs');
function fixture(t) {
  const dir = mkdtempSync(resolve(tmpdir(), 'thesistrace-config-'));
  t.after(() => rmSync(dir, { recursive: true, force: true }));
  const file = resolve(dir, 'runtime.env');
  const env = { ...process.env, THESISTRACE_ENV_FILE: file };
  const init = spawnSync(process.execPath, [cli, 'init'], { env, encoding: 'utf8' });
  assert.equal(init.status, 0, init.stderr);
  const values = {
    ...parseEnv(readFileSync(file, 'utf8')),
    RESEND_API_KEY: 're_fixture-configuration-only-12345',
    RESEND_FROM_EMAIL: 'Fixture <fixture@thesistrace.local>',
    THESISTRACE_TUSHARE_TOKEN: 'fixture-configuration-only-12345',
    THESISTRACE_AGENT_OPENAI_API_KEY: 'fixture-model-configuration-only-12345'
  };
  const save = () => writeFileSync(file, Object.entries(values).map(([k, v]) => `${k}=${v}`).join('\n') + '\n');
  save();
  return { dir, file, env, values, save };
}
function run(env, ...args) {
  return spawnSync(process.execPath, [cli, ...args], { env, encoding: 'utf8' });
}

test('private CLI accepts file worker capacity and discards ambient capacity', t => {
  const f = fixture(t);
  f.values.THESISTRACE_RESEARCH_WORKER_CPU_COUNT = '4'; f.save();
  const result = run({ ...f.env, THESISTRACE_RESEARCH_WORKER_CPU_COUNT: '9', THESISTRACE_TRACKING_WORKER_CPU_COUNT: '9' },
    'run', process.execPath, '-e', 'console.log(JSON.stringify([process.env.THESISTRACE_RESEARCH_WORKER_CPU_COUNT,process.env.THESISTRACE_TRACKING_WORKER_CPU_COUNT]))');
  assert.equal(result.status, 0, result.stderr);
  assert.deepEqual(JSON.parse(result.stdout), ['4', '2']);
});

test('one public origin determines browser port and every MCP address', t => {
  const f = fixture(t); f.values.THESISTRACE_PUBLIC_ORIGIN = 'http://127.0.0.1:5180'; f.save();
  const result = run(f.env, 'run', process.execPath, '-e', `console.log(JSON.stringify(Object.fromEntries(['THESISTRACE_DEV_WEB_PORT','THESISTRACE_MCP_ISSUER_URL','THESISTRACE_MCP_RESOURCE_URL','THESISTRACE_MCP_ALLOWED_HOSTS','THESISTRACE_MCP_ALLOWED_ORIGINS'].map(k=>[k,process.env[k]]))))`);
  assert.equal(result.status, 0, result.stderr);
  assert.deepEqual(JSON.parse(result.stdout), {
    THESISTRACE_DEV_WEB_PORT: '5180', THESISTRACE_MCP_ISSUER_URL: 'http://127.0.0.1:5180/api/auth',
    THESISTRACE_MCP_RESOURCE_URL: 'http://127.0.0.1:5180/mcp', THESISTRACE_MCP_ALLOWED_HOSTS: '["api:8100","127.0.0.1:5180"]',
    THESISTRACE_MCP_ALLOWED_ORIGINS: '["http://127.0.0.1:5180"]'
});
  for (const name of ['THESISTRACE_DEV_WEB_PORT', 'THESISTRACE_MCP_ISSUER_URL', 'THESISTRACE_MCP_RESOURCE_URL', 'THESISTRACE_MCP_ALLOWED_HOSTS', 'THESISTRACE_MCP_ALLOWED_ORIGINS']) assert.equal(name in f.values, false);
});

test('development stop operates on the existing project without a configuration file', t => {
  const f = fixture(t); rmSync(f.file);
  const log = resolve(f.dir, 'docker.jsonl');
  writeFileSync(resolve(f.dir, 'docker'), `#!${process.execPath}\nconst fs=require('node:fs');const args=process.argv.slice(2);fs.appendFileSync(${JSON.stringify(log)},JSON.stringify(args)+'\\n');if(args[0]==='ps')console.log('existing-container');\n`, { mode: 0o755 });
  const result = spawnSync(process.execPath, [resolve(root, 'tooling/dev/runtime.mjs'), 'development', 'stop'], { env: { ...f.env, PATH: `${f.dir}:${process.env.PATH}` }, encoding: 'utf8' });
  assert.equal(result.status, 0, result.stderr);
  const calls = readFileSync(log, 'utf8').trim().split('\n').map(JSON.parse);
  assert.ok(calls.some(args => args.includes('label=com.docker.compose.project=thesistrace-dev')));
  assert.ok(calls.some(args => args[0] === 'stop' && args.includes('existing-container')));
  assert.ok(calls.every(args => !args.includes('compose')));
});

for (const [mode, action] of [['development', 'status'], ['development', 'logs'], ['production', 'status'], ['production', 'logs'], ['production', 'down']]) {
  test(`${mode} ${action} tolerates invalid configuration and selects only its project`, t => {
    const f = fixture(t); writeFileSync(f.file, 'INVALID_CONTENT');
    const log = resolve(f.dir, 'calls.jsonl');
    writeFileSync(resolve(f.dir, 'docker'), `#!${process.execPath}\nconst fs=require('node:fs');const a=process.argv.slice(2);fs.appendFileSync(${JSON.stringify(log)},JSON.stringify(a)+'\\n');if(a[0]==='ps' && a.includes('--format'))console.log('owned-container');if(a[0]==='network' && a[1]==='ls')console.log('owned-network');`, { mode: 0o755 });
    const result = spawnSync(process.execPath, [resolve(root, 'tooling/dev/runtime.mjs'), mode, action], { env: { ...f.env, PATH: `${f.dir}:${process.env.PATH}` }, encoding: 'utf8' });
    assert.equal(result.status, 0, result.stderr);
    const calls = readFileSync(log, 'utf8').trim().split('\n').map(JSON.parse);
    assert.ok(calls.filter(a => a[0] === 'ps' || a[1] === 'ls').every(a => a.includes(`label=com.docker.compose.project=${mode === 'production' ? 'thesistrace' : 'thesistrace-dev'}`)));
    assert.ok(calls.every(a => !a.includes('compose') && !a.includes('volume')));
    if (action === 'down') assert.deepEqual(calls.filter(a => a[0] === 'stop' || a[0] === 'rm' || a[1] === 'rm'), [['stop', 'owned-container'], ['rm', 'owned-container'], ['network', 'rm', 'owned-network']]);
  });
}

test('invalid worker budgets fail without exposing configuration values', t => {
  const f = fixture(t);
  for (const [name, value] of [['THESISTRACE_RESEARCH_WORKER_CPU_COUNT', '0'], ['THESISTRACE_RESEARCH_WORKER_CALCULATION_THREADS', '3'], ['THESISTRACE_BATCH_RESEARCH_WORKER_EXECUTION_MEMORY_BYTES', '2147483648'], ['THESISTRACE_MCP_ACCESS_TOKEN_TTL_SECONDS', '630'], ['THESISTRACE_TRACKING_WORKER_MEMORY_BYTES', 'unsafe-private-value']]) {
    const original = f.values[name]; f.values[name] = value; f.save();
    const result = run(f.env, 'check'); assert.equal(result.status, 2); assert.ok(JSON.parse(result.stderr).variables.includes(name));
    assert.ok(!result.stderr.includes('unsafe-private-value')); f.values[name] = original;
  }
});

test('checked-in template is generated by the same field definitions as init', async () => {
  const { template } = await import('./configuration.mjs');
  assert.equal(readFileSync(resolve(root, '.env.example'), 'utf8'), template());
});

test('development rejects an IPv6 origin that the published topology cannot serve', t => {
  const f = fixture(t); f.values.THESISTRACE_PUBLIC_ORIGIN = 'http://[::1]:5180'; f.save();
  const result = run(f.env, 'check');
  assert.equal(result.status, 2);
  assert.deepEqual(JSON.parse(result.stderr).variables, ['THESISTRACE_PUBLIC_ORIGIN']);
});

test('failed log attachment terminates and waits for other log processes', t => {
  const f = fixture(t), ready = resolve(f.dir, 'ready'), stopped = resolve(f.dir, 'stopped');
  writeFileSync(resolve(f.dir, 'docker'), `#!${process.execPath}
const fs=require('node:fs'); const args=process.argv.slice(2);
if(args[0]==='ps'){console.log('live-container\\ngone-container');process.exit(0);}
if(args.at(-1)==='live-container'){
  fs.writeFileSync(${JSON.stringify(ready)},'ready');
  process.on('SIGTERM',()=>{fs.writeFileSync(${JSON.stringify(stopped)},'stopped');process.exit(0);});
  setInterval(()=>{},100);
}else{
  const deadline=Date.now()+3000;
  const check=()=>{if(fs.existsSync(${JSON.stringify(ready)}))process.exit(19);if(Date.now()>deadline)process.exit(20);setTimeout(check,10);};check();
}
`, { mode: 0o755 });
  const result = spawnSync(process.execPath, [resolve(root, 'tooling/dev/runtime.mjs'), 'development', 'logs'], {
    env: { ...f.env, PATH: `${f.dir}:${process.env.PATH}` }, encoding: 'utf8', timeout: 6000,
  });
  assert.equal(result.error, undefined, result.error?.message);
  assert.equal(result.status, 19, result.stderr);
  assert.equal(readFileSync(stopped, 'utf8'), 'stopped');
});

test('oversized model configuration is rejected before spawning private commands', async t => {
  const { cpSync } = await import('node:fs');
  const f = fixture(t);
  cpSync(resolve(root, 'tooling'), resolve(f.dir, 'tooling'), { recursive: true });
  cpSync(resolve(root, 'apps/agent/config'), resolve(f.dir, 'apps/agent/config'), { recursive: true });
  const registryPath = resolve(f.dir, 'apps/agent/config/model-registry.json');
  const registry = JSON.parse(readFileSync(registryPath, 'utf8'));
  registry.padding = 'private-model-configuration'.repeat(3000);
  writeFileSync(registryPath, JSON.stringify(registry));
  const result = spawnSync(process.execPath, [resolve(f.dir, 'tooling/config/cli.mjs'), 'run', process.execPath, '-e', 'console.log("unexpected-command")'], { env: f.env, encoding: 'utf8' });
  assert.equal(result.status, 2, result.stderr);
  assert.equal(JSON.parse(result.stderr).code, 'CONFIG_MODEL_REGISTRY_INVALID');
  assert.equal(result.stdout, '');
  assert.ok(!result.stderr.includes('private-model-configuration'));
});
