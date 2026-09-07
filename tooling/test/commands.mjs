import { openSync, closeSync } from 'node:fs';
import { run } from '../process.mjs';

// Keep original stdout/stderr separate so later sanitization cannot conceal a failed check.
export async function execute(command, args, { stdoutFile, stderrFile, stdout, stderr, quiet = false, ...options } = {}) {
  const descriptors = [];
  const output = file => {
    if (!file) return quiet ? 'ignore' : 'inherit';
    const fd = openSync(file, 'w', 0o600);
    descriptors.push(fd);
    return fd;
  };
  try {
    return await run(command, args, { stdin: 'ignore', ...options, stdout: stdout ?? output(stdoutFile), stderr: stderr ?? output(stderrFile) });
  } finally {
    for (const fd of descriptors) closeSync(fd);
  }
}
