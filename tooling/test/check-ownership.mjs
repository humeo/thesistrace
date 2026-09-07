import { execFileSync } from 'node:child_process';
import { existsSync, readFileSync } from 'node:fs';
import { matchesGlob, relative } from 'node:path';
import { fileURLToPath } from 'node:url';

export const suites = {
  'core-quick': ['apps/core/tests/{kernel,architecture,adapters,data,entrypoints}/**/test_*.py'],
  'core-integration': ['apps/core/tests/{integration,acceptance}/**/test_*.py'],
  'core-codex': ['apps/core/tests/acceptance/test_real_codex_research_agent_mcp.py'],
  'agent-unit': ['apps/agent/src/**/*.test.ts'],
  'agent-integration': ['apps/agent/src/**/*.integration.test.ts'],
  'agent-preflight': ['apps/agent/scripts/*.test.mjs'],
  'auth-unit': ['apps/auth/src/**/*.test.ts'],
  'auth-integration': ['apps/auth/src/**/*.integration.test.ts'],
  'web-unit': ['apps/web/src/**/*.test.{ts,tsx}'],
  'web-e2e': ['tests/e2e/**/*.spec.ts'],
  'web-browser': ['apps/web/browser/**/*.spec.ts'],
  'test-tooling': ['tooling/**/*.test.mjs', 'tooling/test/tests/test_*.py'],
};

export function owners(path, rules = suites) {
  return Object.entries(rules).filter(([name, patterns]) =>
    !(name === 'core-integration' && path === 'apps/core/tests/acceptance/test_real_codex_research_agent_mcp.py')
    && !(name.endsWith('-unit') && path.endsWith('.integration.test.ts'))
    && patterns.some(pattern => matchesGlob(path, pattern))).map(([name]) => name);
}

export function checkFiles(paths, rules = suites) {
  return paths.filter(path => /(?:^|\/)test_[^/]+\.py$|\.(?:test|spec)\.(?:ts|tsx|mjs)$/.test(path))
    .flatMap(path => {
      const found = owners(path, rules);
      return found.length === 1 ? [] : [`${path}: expected one test suite, found ${found.join(', ') || 'none'}`];
    });
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const paths = execFileSync('git', ['ls-files', '-z', '--cached', '--others', '--exclude-standard'], { encoding: 'utf8' })
    .split('\0').filter(path => !path.startsWith('.scratch/') && existsSync(path));
  const failures = checkFiles([...new Set(paths)]);
  const root = JSON.parse(readFileSync('package.json', 'utf8'));
  for (const dir of ['kernel', 'architecture', 'adapters', 'data', 'entrypoints']) {
    if (!root.scripts.test.includes(`tests/${dir}`)) failures.push(`core-quick directory not invoked: ${dir}`);
  }
  for (const [directory, suite, config] of [
    ['apps/agent', 'agent-unit', 'vitest.config.ts'],
    ['apps/agent', 'agent-integration', 'vitest.integration.config.ts'],
    ['apps/auth', 'auth-unit', 'vitest.config.ts'],
    ['apps/auth', 'auth-integration', 'vitest.integration.config.ts'],
    ['apps/web', 'web-unit', 'vitest.config.ts'],
  ]) {
    const collected = JSON.parse(execFileSync('pnpm', ['--dir', directory, 'exec', 'vitest', 'list', '--filesOnly', '--json', '--config', config], {
      encoding: 'utf8', maxBuffer: 4 * 1024 * 1024,
    })).map(item => relative(process.cwd(), item.file));
    const expected = paths.filter(path => owners(path).includes(suite));
    for (const path of expected) if (!collected.includes(path)) failures.push(`${suite} does not collect ${path}`);
    for (const path of collected) if (!expected.includes(path)) failures.push(`${suite} unexpectedly collects ${path}`);
  }
  if (failures.length) { console.error(failures.join('\n')); process.exitCode = 1; }
  else console.log('Every test file has one suite owner.');
}
