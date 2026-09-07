import { execFileSync } from "node:child_process";

type FaultProxyService = "auth-exchange-proxy" | "mcp-fault-proxy";
type FaultProxyResource = "exchange" | "metadata" | "readiness" | "tool-call";
type FaultProxyMode = "canary" | "disconnect" | "disconnect-submit" | "hold" | "hold-detail" | "pass" | "timeout";

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
  const expectedPort = service === "auth-exchange-proxy" ? 8250 : 8150;
  if (port !== expectedPort) throw new Error("Fault proxy port does not match its service");
  const environmentName = service === "auth-exchange-proxy"
    ? "THESISTRACE_TEST_AUTH_PROXY_ORIGIN"
    : "THESISTRACE_TEST_MCP_PROXY_ORIGIN";
  const origin = process.env[environmentName];
  if (origin === undefined || origin === "") {
    throw new Error(`Missing ${environmentName}`);
  }
  const args = [
    "--fail",
    "--silent",
    "--show-error",
    "--connect-timeout",
    "2",
    "--max-time",
    "5",
  ];
  if (body !== undefined) {
    args.push(
      "--header",
      "content-type: application/json",
      "--request",
      "PUT",
      "--data-binary",
      "@-",
    );
  }
  args.push(`${origin}${path}`);
  try {
    return execFileSync("curl", args, {
      encoding: "utf8",
      input: body,
      killSignal: "SIGKILL",
      stdio: [body === undefined ? "ignore" : "pipe", "pipe", "pipe"],
      timeout: 8_000,
    });
  } catch {
    throw new Error("Fault proxy control request failed");
  }
}
