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

// Fast checks own no Docker resources. Dependency and user-flow suites have separate entrypoints.
export const quickCommands = [
  ['node', ['tooling/test/check-ownership.mjs']],
  ['node', ['--test', 'tooling/**/*.test.mjs']],
  ['uv', ['run', '--project', 'apps/core', 'ruff', 'check', '--config', 'apps/core/pyproject.toml', 'apps/core/src', 'apps/core/tests', 'tooling/test/tests', 'tests']],
  ['uv', ['run', '--project', 'apps/core', 'pytest', '-c', 'apps/core/pyproject.toml', '--rootdir', '.', '-q', '-n', '4', ...['kernel', 'architecture', 'adapters', 'data', 'entrypoints'].map(name => 'apps/core/tests/' + name), 'tooling/test/tests']],
  ...['typecheck', 'test', 'test:eval-preflight'].map(name => ['pnpm', ['--dir', 'apps/agent', name]]),
  ...['typecheck', 'test'].map(name => ['pnpm', ['--dir', 'apps/auth', name]]),
  ['pnpm', ['exec', 'tsc', '-p', 'tests/tsconfig.json']],
  ...['typecheck', 'test:shell'].map(name => ['pnpm', ['--dir', 'apps/web', name]]),
];
