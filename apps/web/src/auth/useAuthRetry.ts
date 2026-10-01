import { useEffect, useState } from "react";

/** Display an Auth recovery deadline without automatically retrying credentials. */
export function useAuthRetry(retryAt: number): number {
  const [now, setNow] = useState(Date.now);
  const waiting = retryAt > now;
  useEffect(() => {
    setNow(Date.now());
    if (!waiting) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1_000);
    return () => window.clearInterval(timer);
  }, [retryAt, waiting]);
  return Math.max(0, Math.ceil((retryAt - now) / 1_000));
}
