import { appendFileSync } from 'node:fs';
import { CommandError } from '../process.mjs';

export async function runPhase(name, operation, { metadata, timeoutMs = 30 * 60 * 1000, signal } = {}) {
  const started = Date.now();
  const controller = new AbortController();
  const cancel = () => controller.abort();
  signal?.addEventListener('abort', cancel, { once: true });
  if (signal?.aborted) cancel();
  let timedOut = false, status = 0;
  const timer = setTimeout(() => { timedOut = true; controller.abort(); }, timeoutMs);
  try {
    const result = await operation(controller.signal);
    if (timedOut) throw new CommandError(name, 124);
    if (signal?.aborted) throw new CommandError(name, 143);
    return result;
  } catch (error) {
    status = timedOut ? 124 : error.status ?? 1;
    if (timedOut) throw new CommandError(name, status);
    throw error;
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener('abort', cancel);
    if (metadata) {
      try { appendFileSync(metadata, `phase=${name} seconds=${Math.floor((Date.now() - started) / 1000)} status=${status}\n`); }
      catch (error) { if (!status) throw error; console.error('could not write Test phase metadata'); }
    }
  }
}
