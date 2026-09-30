import { CommandError } from '../process.mjs';

const coreServices = ['api', 'research-worker', 'batch-research-worker', 'tracking-worker', 'publication-maintenance-worker', 'data-operator-worker'];
const imageServices = [...coreServices, 'initialize', 'agent', 'auth', 'web'];
const projectPattern = /^thesistrace-test-\d{8}t\d{6}z-\d+-[a-f0-9]{8}$/;

export function validateTestProject(project) {
  if (typeof project !== 'string' || !projectPattern.test(project)) throw new CommandError(`refusing non-canonical Test project: ${project}`, 2);
  return project;
}

// The allocating child reports ownership separately from human-readable logs.
export async function announceTestProject(project) {
  validateTestProject(project);
  if (!process.send) return;
  await new Promise((resolve, reject) => process.send({ type: 'test-run-allocated', project }, error => error ? reject(error) : resolve()));
  process.disconnect();
}

export class TestImages {
  constructor(project, execute) {
    this.project = validateTestProject(project);
    this.execute = execute;
  }
  async build(compose, sourceProject) {
    if (sourceProject) {
      validateTestProject(sourceProject);
      for (const service of imageServices) await this.execute('docker', ['image', 'tag', `${sourceProject}-${service}`, `${this.project}-${service}`]);
      return;
    }
    await compose(['build', 'initialize', 'auth-initialize', 'agent', 'web']);
    for (const service of coreServices) await this.execute('docker', ['image', 'tag', `${this.project}-initialize`, `${this.project}-${service}`]);
  }
  async release() {
    const results = [];
    let existing;
    try {
      existing = (await this.execute('docker', ['image', 'ls', '--format', '{{.Repository}}', '--filter', `reference=${this.project}-*`], { capture: true })).trim().split('\n');
    } catch (error) {
      return [{ operation: 'image-list', status: error.status ?? 1 }];
    }
    for (const service of imageServices) {
      const image = `${this.project}-${service}`;
      if (!existing.includes(image)) continue;
      try {
        await this.execute('docker', ['image', 'rm', image], { quiet: true });
        results.push({ image, status: 0 });
      } catch (error) {
        results.push({ image, status: error.status ?? 1 });
      }
    }
    return results;
  }
}
