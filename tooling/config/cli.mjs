import { writeFileSync } from 'node:fs';
import { CommandError, run } from '../process.mjs';
import { configurationFile, fail, initialize, loadConfiguration, report, root, template } from './configuration.mjs';
try {
  const [action, ...extra] = process.argv.slice(2);
  if (action === 'run') {
    const args = extra[0] === '--' ? extra.slice(1) : extra;
    if (!args.length) fail('CONFIG_USAGE_INVALID');
    await run(args[0], args.slice(1), { env: loadConfiguration() });
  } else if (extra.length) fail('CONFIG_USAGE_INVALID');
  else if (action === 'init') {
    initialize(configurationFile());
    console.log('Created private configuration. Fill external credentials, then run pnpm config:check.');
  } else if (action === 'check') loadConfiguration();
  else if (action === 'template') writeFileSync(`${root}/.env.example`, template());
  else fail('CONFIG_USAGE_INVALID');
} catch (error) {
  if (error instanceof CommandError) process.exitCode = error.status;
  else report(error);
}
