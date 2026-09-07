import { execFileSync } from 'node:child_process';
import { existsSync, readFileSync } from 'node:fs';
import { matchesGlob } from 'node:path';
import { fileURLToPath } from 'node:url';

export const suites = {
  'core-quick': ['tests/{kernel,architecture,adapters,data,entrypoints}/**/test_*.py'],
  'core-integration': ['tests/{integration,acceptance}/**/test_*.py'],
  'agent-unit': ['agent/src/**/*.test.ts'],
  'agent-integration': ['agent/src/**/*.integration.test.ts'],
  'agent-preflight': ['agent/scripts/*.test.mjs'],
  'auth-unit': ['auth/src/**/*.test.ts'],
  'auth-integration': ['auth/src/**/*.integration.test.ts'],
  'web-unit': ['web/src/**/*.test.{ts,tsx}'],
  'web-e2e': ['web/e2e-core/**/*.spec.ts'],
  'web-browser': ['web/browser/**/*.spec.ts'],
  'test-tooling': ['scripts/*.test.mjs'],
};

export function owners(path, rules = suites) {
  return Object.entries(rules).filter(([name, patterns]) =>
    !(name.endsWith('-unit') && path.endsWith('.integration.test.ts'))
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
    .split('\0').filter(path => ['tests', 'agent', 'auth', 'web', 'scripts'].includes(path.split('/')[0]) && existsSync(path));
  const failures = checkFiles([...new Set(paths)]);
  const root = JSON.parse(readFileSync('package.json', 'utf8'));
  for (const dir of ['kernel', 'architecture', 'adapters', 'data', 'entrypoints']) {
    if (!root.scripts.test.includes(`tests/${dir}`)) failures.push(`core-quick directory not invoked: ${dir}`);
  }
  if (failures.length) { console.error(failures.join('\n')); process.exitCode = 1; }
  else console.log('Every test file has one suite owner.');
}
