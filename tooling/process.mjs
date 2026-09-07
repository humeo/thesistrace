import { spawn } from 'node:child_process';
import { constants } from 'node:os';

export class CommandError extends Error {
  constructor(command, status) { super(`${command} failed (${status})`); this.status = status; }
}
// One process group per command: a signal reaches descendants before callers collect evidence.
export function run(command, args, { env = process.env, cwd, capture = false, timeoutMs = 0, signal: cancellation } = {}) {
  return new Promise((resolve, reject) => {
    if (cancellation?.aborted) { reject(new CommandError(command, 143)); return; }
    const child = spawn(command, args, { env, cwd, detached: true, stdio: ['inherit', capture ? 'pipe' : 'inherit', 'inherit'] });
    let output = '', failure, timeout, killDeadline;
    function kill(signal) {
      if (!child.pid) return;
      try { process.kill(-child.pid, signal); } catch (error) { if (error.code !== 'ESRCH') failure = error; }
    }
    function interrupt(signal) {
      failure = new CommandError(command, 128 + constants.signals[signal]);
      kill(signal);
      killDeadline ??= setTimeout(() => kill('SIGKILL'), 5000);
    }
    const onInt = () => interrupt('SIGINT'), onTerm = () => interrupt('SIGTERM');
    process.on('SIGINT', onInt); process.on('SIGTERM', onTerm);
    cancellation?.addEventListener('abort', onTerm, { once: true });
    if (timeoutMs) timeout = setTimeout(() => { failure = new CommandError(command, 124); kill('SIGTERM'); killDeadline = setTimeout(() => kill('SIGKILL'), 5000); }, timeoutMs);
    child.stdout?.on('data', chunk => {
      output += chunk;
      if (output.length > 16 * 1024 * 1024) { failure = new CommandError(command, 1); kill('SIGKILL'); }
    });
    function cleanup() {
      clearTimeout(timeout); clearTimeout(killDeadline);
      process.off('SIGINT', onInt); process.off('SIGTERM', onTerm);
      cancellation?.removeEventListener('abort', onTerm);
    }
    child.once('error', error => { cleanup(); reject(error); });
    child.once('close', (code, signal) => {
      cleanup();
      const status = code ?? (signal ? 128 + constants.signals[signal] : 1);
      if (failure || status) reject(failure ?? new CommandError(command, status));
      else resolve(output);
    });
  });
}
