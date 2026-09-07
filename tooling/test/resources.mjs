import { randomBytes } from 'node:crypto';
import { appendFileSync, mkdirSync, mkdtempSync, readFileSync, writeFileSync, chmodSync, rmSync } from 'node:fs';
import { resolve } from 'node:path';
import { tmpdir } from 'node:os';
import { root } from '../config/configuration.mjs';
import { CommandError } from '../process.mjs';
import { execute } from './commands.mjs';
import { fixtureValues, composeEnvironment, deterministicEnvironment, hostEnvironment } from './environment.mjs';
import { runPhase } from './phase.mjs';

export const imageServices = ['api', 'research-worker', 'batch-research-worker', 'tracking-worker', 'data-operator-worker', 'initialize', 'agent', 'auth', 'web'];
export const projectPattern = /^thesistrace-test-\d{8}t\d{6}z-\d+-[a-f0-9]{8}$/;
export function runId() {
  return `${new Date().toISOString().replace(/[-:]/g, '').replace(/\.\d{3}Z$/, 'z').replace('T', 't')}-${process.pid}-${randomBytes(4).toString('hex')}`;
}

export class TestRun {
  constructor(command, options = {}) {
    const ambient = options.ambient ?? process.env;
    Object.assign(this, fixtureValues);
    this.command = command;
    this.repo_root = root;
    this.base_file = `${root}/deploy/compose.yaml`;
    this.test_file = `${root}/deploy/compose.test-run.yaml`;
    this.image_smoke_file = `${root}/deploy/compose.image-smoke.yaml`;
    this.project_name = options.project ?? `thesistrace-test-${runId()}`;
    this.validateProject();
    this.run_id = this.project_name.slice('thesistrace-test-'.length);
    this.bucket_name = this.project_name;
    this.state_root = resolve(ambient.THESISTRACE_TEST_STATE_ROOT ?? `${root}/.local/test-runs`);
    this.port_lock_root = ambient.THESISTRACE_TEST_PORT_LOCK_ROOT ?? `${ambient.XDG_RUNTIME_DIR ?? ambient.TMPDIR ?? tmpdir()}/thesistrace-${process.getuid()}/caddy-port-locks`;
    this.run_root = `${this.state_root}/${this.run_id}`;
    this.setMounts(this.run_root);
    this.evidence_dir = `${this.run_root}/evidence`;
    this.run_metadata = `${this.run_root}/run.txt`;
    this.pytest_report = `${this.evidence_dir}/pytest.xml`;
    this.database_restart_report = `${this.evidence_dir}/pytest-database-restart.xml`;
    this.dependency_restart_report = `${this.evidence_dir}/pytest-dependency-restart.xml`;
    this.secret_dir = this.auth_session_file = this.operator_sessions_file = '';
    this.use_image_overlay = ['performance', 'image-smoke'].includes(command);
    this.compose_cleanup_required = false;
    this.port_acquired = false;
    this.keep_environment = options.keepEnvironment ?? false;
    this.keep_images = ambient.THESISTRACE_TEST_KEEP_IMAGES === '1';
    this.source_project = ambient.THESISTRACE_TEST_IMAGE_SOURCE_PROJECT;
    this.playwright_grep = ambient.THESISTRACE_TEST_PLAYWRIGHT_GREP;
    this.ambient = deterministicEnvironment(ambient);
    this.controller = new AbortController();
    this.interrupted_status = 0;
  }
  validateProject() {
    if (!projectPattern.test(this.project_name)) throw new CommandError(`refusing non-canonical Test project: ${this.project_name}`, 2);
  }
  setMounts(base) {
    this.data_mount = `${base}/canonical-data`;
    this.benchmark_mount = `${base}/benchmark-data`;
    this.batch_attempt_control_directory = `${base}/batch-attempt-control/.batch-attempts`;
  }
  createMounts() {
    for (const path of [this.evidence_dir, this.data_mount, this.benchmark_mount, this.batch_attempt_control_directory]) mkdirSync(path, { recursive: true });
  }
  record(values) {
    appendFileSync(this.run_metadata, Object.entries(values).map(([name, value]) => `${name}=${value}\n`).join(''));
  }
  exec(command, args, options = {}) {
    return execute(command, args, { cwd: root, env: composeEnvironment(this), signal: this.phaseSignal ?? this.controller.signal, interruptible: !this.cleaning, ...options });
  }
  compose(args, { base = false, ...options } = {}) {
    this.validateProject();
    const files = [this.base_file, ...(!base ? [this.test_file, ...(this.use_image_overlay ? [this.image_smoke_file] : [])] : [])];
    return this.exec('docker', ['compose', '--env-file', '/dev/null', '--project-name', this.project_name, ...files.flatMap(file => ['--file', file]), ...args], options);
  }
  composeRun(args, options) { return this.compose(['run', '--rm', '--no-deps', '-T', '--interactive=false', ...args], options); }
  host(args, options = {}) { return this.exec(args[0], args.slice(1), { ...options, env: { ...hostEnvironment(this), ...options.env } }); }
  async phase(name, operation, options = {}) {
    return runPhase(name, async signal => {
      this.phaseSignal = signal;
      try { return await operation(); } finally { this.phaseSignal = undefined; }
    }, { metadata: this.run_metadata, signal: this.controller.signal, ...options });
  }
  check(name, args = [], options = {}) {
    const variables = Object.fromEntries(Object.entries(this).filter(([, value]) => ['string', 'number', 'boolean'].includes(typeof value)).map(([key, value]) => [key, String(value)]));
    return this.exec('sh', [`${root}/tests/image-checks.sh`, name, ...args], { ...options, env: { ...composeEnvironment(this), ...variables } });
  }
  async mappedPort(service, port) {
    const address = (await this.compose(['port', service, String(port)], { capture: true })).trim();
    const mapped = address.split(':').at(-1);
    if (!/^\d+$/.test(mapped) || +mapped < 1 || +mapped > 65535) throw new CommandError(`could not resolve ${service} port`, 1);
    return mapped;
  }
  async updatePorts(...services) {
    const names = { postgres: ['postgres_port', 5432], rustfs: ['s3_port', 9000], auth: ['auth_port', 8200], 'resend-fake': ['resend_port', 8300], 'auth-fixture-control': ['auth_fixture_port', 8260], 'auth-exchange-proxy': ['auth_proxy_port', 8250], 'mcp-fault-proxy': ['mcp_proxy_port', 8150] };
    for (const service of services) {
      const [key, port] = names[service];
      this[key] = await this.mappedPort(service, port);
    }
  }
  setOrigin(port) {
    if (!/^\d+$/.test(String(port)) || +port < 1 || +port > 65535) throw new CommandError('invalid Test Caddy port', 2);
    this.caddy_port = String(port);
    this.public_origin = `http://127.0.0.1:${port}`;
    this.mcp_issuer_url = `${this.public_origin}/api/auth`;
    this.mcp_resource_url = `${this.public_origin}/mcp`;
    this.auth_secret = `test-only-${this.run_id}-auth-secret-with-at-least-32-characters`;
    this.mcp_allowed_hosts = JSON.stringify(['api:8100', `127.0.0.1:${port}`]);
    this.mcp_allowed_origins = JSON.stringify([this.public_origin]);
  }
  async allocate() {
    this.createMounts();
    if (this.use_image_overlay) {
      const secretRoot = `${this.state_root}/.runtime-secrets`;
      mkdirSync(secretRoot, { recursive: true, mode: 0o700 });
      chmodSync(secretRoot, 0o700);
      this.secret_dir = mkdtempSync(`${secretRoot}/${this.run_id}.`);
      this.auth_session_file = `${this.secret_dir}/auth-session.json`;
      if (this.command === 'image-smoke') this.operator_sessions_file = `${this.secret_dir}/operator-sessions.json`;
    }
    const revision = (await this.exec('git', ['-C', root, 'rev-parse', 'HEAD'], { capture: true, quiet: true })).trim();
    const dirty = (await this.exec('git', ['-C', root, 'status', '--short'], { capture: true, quiet: true })).trim().length > 0;
    writeFileSync(this.run_metadata, '', { mode: 0o600 });
    this.record({ run_id: this.run_id, project_name: this.project_name, git_revision: revision, git_worktree_dirty: dirty, test_kind: this.command });
    const port = (await this.exec('uv', ['run', 'python', `${root}/tooling/test/locked-loopback-port`, 'acquire', '--lock-root', this.port_lock_root, '--owner', this.project_name], { capture: true })).trim();
    this.setOrigin(port);
    this.port_acquired = true;
    this.record({ caddy_port: this.caddy_port, public_origin: this.public_origin });
    console.log(`Test run: ${this.run_id}\nCompose project: ${this.project_name}`);
  }
  loadExisting() {
    this.validateProject();
    let metadata;
    try { metadata = readFileSync(this.run_metadata, 'utf8'); } catch { throw new CommandError(`refusing Test cleanup without matching run metadata: ${this.project_name}`, 2); }
    if (!metadata.split('\n').includes(`project_name=${this.project_name}`)) throw new CommandError(`refusing Test cleanup without matching run metadata: ${this.project_name}`, 2);
    this.setOrigin(metadata.match(/^caddy_port=(\d+)$/m)?.[1] ?? '');
    this.port_acquired = true;
  }
  async releasePort() {
    if (!this.port_acquired) return;
    await this.exec('uv', ['run', 'python', `${root}/tooling/test/locked-loopback-port`, 'release', '--lock-root', this.port_lock_root, '--owner', this.project_name, '--port', this.caddy_port]);
    this.port_acquired = false;
  }
  async buildImages() {
    if (this.source_project) {
      if (!projectPattern.test(this.source_project)) throw new CommandError('invalid source Test project', 2);
      this.record({ image_source_project: this.source_project });
      for (const service of imageServices) await this.exec('docker', ['image', 'tag', `${this.source_project}-${service}`, `${this.project_name}-${service}`]);
      return;
    }
    await this.compose(['build', 'initialize', 'auth-initialize', 'agent', 'web']);
    for (const service of ['api', 'research-worker', 'batch-research-worker', 'tracking-worker', 'data-operator-worker']) await this.exec('docker', ['image', 'tag', `${this.project_name}-initialize`, `${this.project_name}-${service}`]);
  }
  async provisionAuth() {
    if (!this.auth_session_file) throw new CommandError('missing private Auth session path', 2);
    rmSync(this.auth_session_file, { force: true });
    await this.host(['uv', 'run', 'python', 'apps/core/tests/acceptance/provision_image_smoke_auth.py', this.auth_session_file]);
  }
  async prepareBenchmarkApi() {
    await this.compose(['up', '--detach', '--no-build', '--wait', '--wait-timeout', '120', 'auth', 'api']);
    await this.updatePorts('postgres', 'rustfs');
    await this.provisionAuth();
  }
  async resetProductState() {
    const services = ['auth', 'auth-fixture-control', 'api', 'research-worker', 'batch-research-worker', 'tracking-worker', 'data-operator-worker', 'postgres', 'rustfs'];
    await this.compose(['stop', ...services], { quiet: true });
    await this.compose(['rm', '--force', ...services, 'auth-initialize', 'initialize'], { quiet: true });
    await this.exec(`${root}/tooling/dev/product-state-volumes.mjs`, ['reset', this.project_name]);
    await this.compose(['up', '--detach', '--no-build', '--wait', '--wait-timeout', '300', 'postgres', 'rustfs']);
    await this.compose(['up', '--detach', '--no-build', 'initialize', 'auth-initialize']);
    await this.compose(['wait', 'initialize', 'auth-initialize']);
  }
  async waitForS3(image = false) {
    const deadline = Date.now() + 180000;
    while (true) {
      try {
        if (image) await this.composeRun(['initialize', 'python', '/smoke/tooling/test/probe-rustfs-ready', '--ensure-bucket', this.bucket_name], { quiet: true });
        else await this.host(['uv', 'run', 'python', `${root}/tooling/test/probe-rustfs-ready`, '--ensure-bucket', this.bucket_name], { quiet: true });
        return;
      } catch (error) {
        if (error.status !== 75) throw error;
        if (Date.now() >= deadline) throw new CommandError('RustFS S3 API did not become writable', 1);
        await new Promise(resolve => setTimeout(resolve, 250));
      }
    }
  }
  async waitForAuthFixture() {
    const deadline = Date.now() + 30000;
    while (true) {
      try { await this.exec('curl', ['--fail', '--silent', '--show-error', '--connect-timeout', '2', '--max-time', '5', `${this.auth_fixture_origin}/health/ready`], { quiet: true }); return; }
      catch (error) {
        if (this.controller.signal.aborted || this.phaseSignal?.aborted) throw error;
        if (Date.now() >= deadline) throw new CommandError('Auth fixture control did not become ready', 1);
        await new Promise(resolve => setTimeout(resolve, 250));
      }
    }
  }
}
