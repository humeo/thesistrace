import { randomUUID } from "node:crypto";
import { performance } from "node:perf_hooks";

const trustedRequestId =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

const exactRoutes = new Set([
  "/api/auth/get-session",
  "/api/auth/ok",
  "/api/auth/oauth2/authorize",
  "/api/auth/oauth2/token",
  "/api/auth/oauth2/register",
  "/api/auth/oauth2/consent",
  "/api/auth/oauth2/continue",
  "/api/auth/oauth2/public-client",
  "/api/auth/oauth2/revoke",
  "/api/auth/oauth2/introspect",
  "/api/auth/sign-in/email-otp",
  "/api/auth/email-otp/send-verification-otp",
  "/api/auth/operator/proofs/send-code",
  "/api/auth/sign-out",
  "/health/live",
  "/health/ready",
  "/internal/session/verify",
]);

export type AuthHttpEvent = Readonly<{
  component: "auth_http";
  duration_ms: number;
  event: "http_request_completed";
  http_request_id: string;
  level: "INFO";
  method: string;
  route: string;
  status_code: number;
  retry_after_seconds?: number;
  timestamp: string;
}>;

type AuthHttpObservation = Readonly<{
  requestId: string;
  startedAt: number;
}>;

export type AuthHttpObserver = Readonly<{
  complete: (
    observation: AuthHttpObservation,
    request: Readonly<{ method: string; path: string; status: number; retryAfter?: string | null }>,
  ) => void;
  start: (headers: Headers) => AuthHttpObservation;
}>;

type AuthHttpObserverOptions = Readonly<{
  clock?: () => Date;
  monotonicMilliseconds?: () => number;
  requestIdFactory?: () => string;
  write?: (event: AuthHttpEvent) => void;
}>;

export function createAuthHttpObserver(
  options: AuthHttpObserverOptions = {},
): AuthHttpObserver {
  const clock = options.clock ?? (() => new Date());
  const monotonicMilliseconds =
    options.monotonicMilliseconds ?? (() => performance.now());
  const requestIdFactory = options.requestIdFactory ?? randomUUID;
  const write = options.write ?? writeAuthHttpEvent;

  return {
    complete(observation, request) {
      const retry = request.retryAfter;
      const retrySeconds = retry && /^[1-9][0-9]*$/.test(retry) ? Number(retry) : NaN;
      write({
        component: "auth_http",
        duration_ms: Math.max(
          0,
          Math.floor(monotonicMilliseconds() - observation.startedAt),
        ),
        event: "http_request_completed",
        http_request_id: observation.requestId,
        level: "INFO",
        method: normalizeMethod(request.method),
        route: normalizeAuthRoute(request.path),
        status_code: normalizeStatus(request.status),
        ...(request.status === 429 && Number.isSafeInteger(retrySeconds) && retrySeconds <= 60 ? {retry_after_seconds: retrySeconds} : {}),
        timestamp: clock().toISOString(),
      });
    },
    start(headers) {
      const candidate = headers.get("x-request-id")?.toLowerCase();
      return {
        requestId:
          candidate !== undefined && trustedRequestId.test(candidate)
            ? candidate
            : requestIdFactory(),
        startedAt: monotonicMilliseconds(),
      };
    },
  };
}

export function normalizeAuthRoute(path: string): string {
  if (exactRoutes.has(path)) {
    return path;
  }
  if (path.startsWith("/api/auth/")) {
    return "/api/auth/*";
  }
  if (path.startsWith("/internal/")) {
    return "/internal/*";
  }
  return "/unmatched";
}

function normalizeMethod(method: string): string {
  return /^[A-Z]{3,16}$/.test(method) ? method : "UNKNOWN";
}

function normalizeStatus(status: number): number {
  return Number.isInteger(status) && status >= 100 && status <= 599 ? status : 500;
}

function writeAuthHttpEvent(event: AuthHttpEvent): void {
  process.stderr.write(`${JSON.stringify(event)}\n`);
}
