import { spawn } from 'node:child_process';
import { constants } from 'node:os';

export class CommandError extends Error {
  constructor(command, status) { super(`${command} failed (${status})`); this.status = status; }
}
// One process group per command: a signal reaches descendants before callers collect evidence.
export function run(command, args, { env = process.env, cwd, capture = false, timeoutMs = 0, signal: cancellation,
  stdin = 'inherit', stdout = 'inherit', stderr = 'inherit', interruptible = true } = {}) {
  return new Promise((resolve, reject) => {
    if (cancellation?.aborted) { reject(new CommandError(command, 143)); return; }
    const child = spawn(command, args, { env, cwd, detached: true, stdio: [stdin, capture ? 'pipe' : stdout, stderr] });
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
    if (interruptible) { process.on('SIGINT', onInt); process.on('SIGTERM', onTerm); }
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
    child.once('close', async (code, signal) => {
      if (failure && child.pid) {
        // A shell can exit before its children. Reap the remaining process group
        // before callers capture evidence or remove resources used by descendants.
        kill('SIGKILL');
        const deadline = Date.now() + 5000;
        while (Date.now() < deadline) {
          try { process.kill(-child.pid, 0); }
          catch (error) { if (error.code === 'ESRCH') break; }
          await new Promise(resolve => setTimeout(resolve, 10));
        }
      }
      cleanup();
      const status = code ?? (signal ? 128 + constants.signals[signal] : 1);
      if (failure || status) reject(failure ?? new CommandError(command, status));
      else resolve(output);
    });
  });
}
