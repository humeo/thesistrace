#!/usr/bin/env node
import { CommandError, run } from '../process.mjs';

try {
  const [command, project, ...extra] = process.argv.slice(2);
  if (project !== 'thesistrace-dev' && !/^thesistrace-test-\d{8}t\d{6}z-\d+-[a-f0-9]{8}(?:-lifecycle)?$/.test(project ?? '')) throw new CommandError(`refusing Product State volume project: ${project || '<empty>'}`, 2);
  if (extra.length || !['reset', 'erase'].includes(command)) throw new CommandError('usage: product-state-volumes.mjs {reset|erase} project-name', 2);
  const names = ['batch-attempt-control', 'postgres-data', 'rustfs-data', ...(command === 'erase' ? ['canonical-data', 'benchmark-data'] : [])];
  for (const name of names) {
    const volume = `${project}_${name}`;
    try { await run('docker', ['volume', 'inspect', volume], { stdout: 'ignore', stderr: 'ignore' }); }
    catch (error) { if (error.status === 1) continue; throw error; }
    await run('docker', ['volume', 'rm', volume]);
  }
} catch (error) { console.error(error.message); process.exitCode = error.status ?? 1; }
