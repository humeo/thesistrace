import { execFileSync } from "node:child_process";

import { testProjectName } from "./auth-fixture";

type FaultProxyService = "auth-exchange-proxy" | "mcp-fault-proxy";
type FaultProxyResource = "exchange" | "metadata" | "readiness" | "tool-call";
type FaultProxyMode = "disconnect" | "disconnect-submit" | "hold" | "hold-detail" | "pass" | "timeout";

export function setProxyMode(
  service: FaultProxyService,
  port: 8250 | 8150,
  resource: FaultProxyResource,
  mode: FaultProxyMode,
): void {
  proxyRequest(
    service,
    port,
    `/__test/${resource}-mode`,
    JSON.stringify({ mode, reset: true }),
  );
}

export function proxyState(
  service: FaultProxyService,
  port: 8250 | 8150,
): Record<string, unknown> {
  const parsed = JSON.parse(proxyRequest(service, port, "/__test/state")) as unknown;
  if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("Fault proxy returned an invalid state document");
  }
  return parsed as Record<string, unknown>;
}

function proxyRequest(
  service: FaultProxyService,
  port: 8250 | 8150,
  path: string,
  body?: string,
): string {
  return execFileSync(
    "docker",
    [
      "exec",
      `${testProjectName()}-${service}-1`,
      "node",
      "--input-type=module",
      "--eval",
      `
        const [url, body] = process.argv.slice(1);
        const response = await fetch(url, {
          ...(body === undefined ? {} : {
            body,
            headers: { "content-type": "application/json" },
            method: "PUT",
          }),
          signal: AbortSignal.timeout(5_000),
        });
        if (!response.ok) process.exit(1);
        process.stdout.write(await response.text());
      `,
      `http://127.0.0.1:${port}${path}`,
      ...(body === undefined ? [] : [body]),
    ],
    {
      encoding: "utf8",
      killSignal: "SIGKILL",
      stdio: ["ignore", "pipe", "pipe"],
      timeout: 10_000,
    },
  );
}
