import { globSync } from 'node:fs';
import { root } from '../config/configuration.mjs';
import { run } from '../process.mjs';
import { quickCommands } from './suites.mjs';

try {
  for (const [command, args] of quickCommands) {
    const expanded = args.flatMap(arg => arg === 'tooling/**/*.test.mjs' ? [...globSync(arg, { cwd: root })].sort() : [arg]);
    await run(command, expanded, { cwd: root });
  }
} catch (error) {
  console.error(error.message);
  process.exitCode = error.status ?? 1;
}
