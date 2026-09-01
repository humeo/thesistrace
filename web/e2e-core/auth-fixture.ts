import { expect, test as base, type Locator, type Page } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";

export type AuthenticatedResearcher = Readonly<{
  cookie: string;
  email: string;
  id: string;
}>;

export const browserPassword = "Browser-acceptance-password-2026";

// Playwright renders locator.fill(value) arguments into HTML report step titles.
// Drive the password control without putting the private value in that title.
export async function fillPasswordInput(
  passwordInput: Locator,
  password = browserPassword,
): Promise<void> {
  await passwordInput.evaluate((element, password) => {
    if (!(element instanceof HTMLInputElement) || element.type !== "password") {
      throw new Error("Browser password helper requires an input[type=password]");
    }
    const valueSetter = Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )?.set;
    if (!valueSetter) {
      throw new Error("Browser password input has no native value setter");
    }
    element.focus();
    valueSetter.call(element, password);
    element.dispatchEvent(new Event("input", { bubbles: true, composed: true }));
  }, password);
}

export const securityTest = base.extend<{ cspGuard: void }>({
  cspGuard: [async ({ page }, use) => {
    resetAuthRateLimits();
    const violations: Array<Readonly<{
      blockedResource: string;
      columnNumber: number;
      directive: string;
      lineNumber: number;
      sourcePath: string;
    }>> = [];
    await page.exposeFunction(
      "__thesistraceRecordCspViolation",
      (violation: unknown) => {
        if (
          typeof violation === "object"
          && violation !== null
          && "directive" in violation
        ) {
          violations.push(violation as (typeof violations)[number]);
          return;
        }
        violations.push({
          blockedResource: "invalid",
          columnNumber: 0,
          directive: "invalid",
          lineNumber: 0,
          sourcePath: "invalid",
        });
      },
    );
    await page.addInitScript(() => {
      window.addEventListener("securitypolicyviolation", (event) => {
        const record = (window as unknown as {
          __thesistraceRecordCspViolation: (violation: {
            blockedResource: string;
            columnNumber: number;
            directive: string;
            lineNumber: number;
            sourcePath: string;
          }) => Promise<void>;
        }).__thesistraceRecordCspViolation;
        const resourcePath = (value: string): string => {
          if (!value || !value.includes(":")) return value;
          try {
            return new URL(value, window.location.href).pathname;
          } catch {
            return "invalid";
          }
        };
        void record({
          blockedResource: resourcePath(event.blockedURI),
          columnNumber: event.columnNumber,
          directive: event.effectiveDirective,
          lineNumber: event.lineNumber,
          sourcePath: resourcePath(event.sourceFile),
        });
      });
    });
    await use();
    expect(violations).toEqual([]);
  }, { auto: true }],
});

export const test = securityTest.extend<{ researcher: AuthenticatedResearcher }>({
  researcher: [async ({ page }, use, testInfo) => {
    const suffix = createHash("sha256").update(testInfo.testId).digest("hex").slice(0, 16);
    const researcher = await createResearcher(page, `browser-core-${suffix}@example.test`);
    const bootstrap = await page.request.post("/api/researcher/bootstrap", {
      data: {},
      headers: sameOriginHeaders(),
    });
    expect(bootstrap.status()).toBe(200);
    expect(await bootstrap.json()).toMatchObject({ researcher_id: researcher.id });
    await openDataOverview(page);
    await use(researcher);
  }, { auto: true }],
});

export { expect };

export async function openDataOverview(page: Page): Promise<void> {
  // Cold navigation includes Auth, capability, and Researcher bootstrap before
  // these requests start. Wait for network readiness before the short UI check.
  const [overview, catalog] = await Promise.all([
    page.waitForResponse((response) => (
      new URL(response.url()).pathname === "/api/data"
      && response.request().method() === "GET"
    )),
    page.waitForResponse((response) => (
      new URL(response.url()).pathname === "/api/alpha/catalog"
      && response.request().method() === "GET"
    )),
    page.goto("/data"),
  ]);
  expect(overview.status(), "Data overview request").toBe(200);
  expect(catalog.status(), "Alpha catalog request").toBe(200);
  await Promise.all([overview.finished(), catalog.finished()]);
  await expect(page.getByRole("heading", { name: "Data overview" })).toBeVisible();
}

export async function issueInvitation(email: string): Promise<string> {
  const cleared = requestResendFixture("DELETE");
  if (!isRecord(cleared) || cleared.status !== true) {
    throw new Error("Could not reset the local Resend acceptance fixture");
  }
  runAuthOperator("invite", "--email", email);
  return emailToken(email, "/accept-invitation#token=");
}

export async function createResearcher(
  page: Page,
  email: string,
  password = browserPassword,
): Promise<AuthenticatedResearcher> {
  const ipSuffix = Number.parseInt(
    createHash("sha256").update(email).digest("hex").slice(0, 2),
    16,
  ) || 1;
  const provisioned = authFixtureRequest("/__test/provision-session", {
    client_ip: `198.51.100.${ipSuffix}`,
    email,
    password,
  });
  if (
    !isRecord(provisioned)
    || typeof provisioned.cookie !== "string"
    || typeof provisioned.researcher_id !== "string"
  ) throw new Error("Private Auth test provisioning returned an invalid result");
  await restoreResearcherSession(page, {
    cookie: provisioned.cookie,
    email,
    id: provisioned.researcher_id,
  });
  return { cookie: provisioned.cookie, email, id: provisioned.researcher_id };
}

export async function restoreResearcherSession(
  page: Page,
  researcher: AuthenticatedResearcher,
): Promise<void> {
  const cookies = researcher.cookie.split("; ").map((pair) => {
    const separator = pair.indexOf("=");
    if (separator <= 0) throw new Error("Private Auth test provisioning returned an invalid Cookie");
    return {
      name: pair.slice(0, separator),
      value: pair.slice(separator + 1),
      url: requiredEnvironment("THESISTRACE_TEST_WEB_ORIGIN"),
    };
  });
  await page.context().addCookies(cookies);
}

export async function emailToken(email: string, path: string): Promise<string> {
  const deadline = Date.now() + 5_000;
  let lastEmailCount = 0;
  while (Date.now() < deadline) {
    const payload = requestResendFixture("GET");
    if (!isRecord(payload) || !Array.isArray(payload.emails)) {
      throw new Error("Local Resend acceptance fixture response is invalid");
    }
    lastEmailCount = payload.emails.length;
    for (const candidate of [...payload.emails].reverse()) {
      if (!isRecord(candidate) || !Array.isArray(candidate.to) || !candidate.to.includes(email)) {
        continue;
      }
      if (typeof candidate.html !== "string") break;
      const marker = candidate.html.indexOf(path);
      if (marker === -1) continue;
      const match = candidate.html.slice(marker + path.length).match(/^([^"'<\s]+)/);
      if (match?.[1] !== undefined) return decodeURIComponent(match[1]);
    }
    await new Promise<void>((resolve) => setTimeout(resolve, 50));
  }
  throw new Error(`Invitation email was not delivered; observed ${lastEmailCount} email(s)`);
}

function requestResendFixture(method: "DELETE" | "GET"): unknown {
  return authFixtureRequest("/__test/resend-emails", { method });
}

export function runAuthOperator(...args: string[]): unknown {
  return authFixtureRequest("/__test/operator", { args });
}

export function expireInvitation(token: string): void {
  const result = authFixtureRequest("/__test/expire-invitation", { token });
  if (!isRecord(result) || result.status !== "expired") {
    throw new Error("Private Auth expiry fixture returned an invalid result");
  }
}

export function seedOperatorDirectory(): void {
  const result = authFixtureRequest("/__test/seed-operator-directory", {});
  if (
    !isRecord(result)
    || result.invitations !== 55
    || result.researchers !== 55
    || result.status !== "seeded"
  ) {
    throw new Error("Private Auth Operator directory fixture returned an invalid result");
  }
}

export function resetAuthRateLimits(): void {
  const result = authFixtureRequest("/__test/reset-rate-limits", {});
  if (!isRecord(result) || result.status !== "reset") {
    throw new Error("Private Auth rate-limit fixture returned an invalid result");
  }
}

export function stopDataOperatorWorker(): void {
  execFileSync(
    "docker",
    ["stop", "--time", "10", `${testProjectName()}-data-operator-worker-1`],
    { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] },
  );
}

export function startDataOperatorWorker(): void {
  execFileSync(
    "docker",
    ["start", `${testProjectName()}-data-operator-worker-1`],
    { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] },
  );
}

export async function ensureOperatorDataBaseline(page: Page): Promise<void> {
  const overviewResponse = await page.request.get("/api/data");
  if (!overviewResponse.ok()) {
    throw new Error(`Could not inspect the Operator browser Dataset: ${overviewResponse.status()}`);
  }
  const overview = await overviewResponse.json() as unknown;
  if (!isRecord(overview) || typeof overview.data_through_session !== "string") {
    throw new Error("Operator browser Dataset response is invalid");
  }
  const financialCoverage = overview.financial_coverage;
  const financialComplete = isRecord(financialCoverage)
    && typeof financialCoverage.discovery_complete_through_session === "string"
    ? financialCoverage.discovery_complete_through_session
    : null;
  if (
    overview.data_through_session === "2026-08-11"
    && financialComplete === "2026-08-11"
  ) return;
  if (
    overview.data_through_session !== "2026-08-05"
    || financialComplete !== "2026-08-05"
  ) {
    throw new Error(
      "Operator browser Dataset has an unexpected baseline: "
        + `${overview.data_through_session}/${financialComplete ?? "unavailable"}`,
    );
  }

  const idempotencyKey = "browser-operator-baseline-market-refresh";
  const accepted = runDataOperator(
    "refresh",
    "--idempotency-key",
    idempotencyKey,
    "--as-of",
    "2026-08-11T18:00:00+08:00",
  );
  if (!isRecord(accepted) || accepted.status !== "accepted") {
    throw new Error("Operator browser market baseline was not accepted");
  }

  const deadline = Date.now() + 30_000;
  while (Date.now() < deadline) {
    const receipt = runDataOperator("inspect-refresh", "--idempotency-key", idempotencyKey);
    if (!isRecord(receipt) || typeof receipt.status !== "string") {
      throw new Error("Operator browser market baseline receipt is invalid");
    }
    if (receipt.status === "succeeded") {
      if (receipt.data_through_session !== "2026-08-11") {
        throw new Error("Operator browser market baseline published the wrong Research Session");
      }
      publishOperatorFinancialBaseline();
      const readyResponse = await page.request.get("/api/data");
      const ready = await readyResponse.json() as unknown;
      const readyFinancial = isRecord(ready) ? ready.financial_coverage : null;
      if (
        !readyResponse.ok()
        || !isRecord(ready)
        || ready.data_through_session !== "2026-08-11"
        || !isRecord(readyFinancial)
        || readyFinancial.discovery_complete_through_session !== "2026-08-11"
      ) {
        throw new Error("Operator browser Financial baseline was not published");
      }
      return;
    }
    if (receipt.status === "failed" || receipt.status === "cancelled") {
      throw new Error(
        `Operator browser market baseline ${receipt.status}: ${String(receipt.failure_code)}`,
      );
    }
    await new Promise<void>((resolve) => setTimeout(resolve, 100));
  }
  throw new Error("Operator browser market baseline did not reach a terminal state");
}

export function assertDataOperatorWorkerLeaseReleased(): void {
  const result = runDataStateCommand(`
    SELECT CASE
      WHEN owner_token IS NULL AND lease_expires_at IS NULL THEN 1
      ELSE 0
    END
    FROM data.refresh_worker_leases
    WHERE singleton = 1
  `);
  if (result !== "1") {
    throw new Error(`Data Operator Worker lease was not released: ${result || "no row"}`);
  }
}

export function markDataRefreshRunning(idempotencyKey: string): void {
  assertDataRefreshKey(idempotencyKey);
  const result = runDataStateCommand(`WITH claimed AS (
        UPDATE data.refresh_operations
        SET status = 'running', owner_token = 'browser-worker-claim',
            lease_expires_at = clock_timestamp() + interval '10 minutes',
            attempt_count = attempt_count + 1, phase = 'claim',
            last_heartbeat_at = clock_timestamp(), started_at = clock_timestamp(),
            updated_at = clock_timestamp()
        WHERE idempotency_key = '${idempotencyKey}' AND status = 'accepted'
        RETURNING status
      ) SELECT status FROM claimed`);
  if (result !== "running") {
    throw new Error(`Could not mark Data Refresh running: ${result || "no row"}`);
  }
}

export function expireDataRefreshClaim(idempotencyKey: string): void {
  assertDataRefreshKey(idempotencyKey);
  const result = runDataStateCommand(`
    WITH expired AS (
      UPDATE data.refresh_operations
      SET lease_expires_at = clock_timestamp() - interval '1 second'
      WHERE idempotency_key = '${idempotencyKey}' AND status = 'running'
      RETURNING status
    ) SELECT status FROM expired
  `);
  if (result !== "running") {
    throw new Error(`Could not expire Data Refresh claim: ${result || "no row"}`);
  }
}

export function exhaustDataRefresh(idempotencyKey: string): void {
  assertDataRefreshKey(idempotencyKey);
  const result = runDataStateCommand(`
    WITH exhausted AS (
      UPDATE data.refresh_operations
      SET status = 'failed', owner_token = NULL, lease_expires_at = NULL,
          attempt_count = 3, phase = 'claim',
          last_heartbeat_at = clock_timestamp(),
          failure_code = 'RETRY_EXHAUSTED',
          last_failure_code = 'WORKER_LEASE_EXPIRED',
          started_at = clock_timestamp(), finished_at = clock_timestamp(),
          updated_at = clock_timestamp()
      WHERE idempotency_key = '${idempotencyKey}'
        AND status = 'running'
        AND attempt_count >= 1
        AND lease_expires_at <= clock_timestamp()
      RETURNING status
    ) SELECT status FROM exhausted
  `);
  if (result !== "failed") {
    throw new Error(`Could not exhaust Data Refresh: ${result || "no row"}`);
  }
}

function runDataStateCommand(statement: string): string {
  return execFileSync(
    "docker",
    [
      "exec",
      `${testProjectName()}-postgres-1`,
      "psql",
      "--username",
      "thesistrace_owner",
      "--dbname",
      "thesistrace",
      "--set",
      "ON_ERROR_STOP=1",
      "--tuples-only",
      "--no-align",
      "--command",
      statement,
    ],
    { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] },
  ).trim();
}

function runDataOperator(...args: string[]): unknown {
  const output = execFileSync(
    "docker",
    [
      "exec",
      `${testProjectName()}-data-operator-worker-1`,
      "thesistrace-data-operator",
      ...args,
    ],
    { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] },
  );
  return JSON.parse(output) as unknown;
}

function publishOperatorFinancialBaseline(): void {
  execFileSync(
    "uv",
    [
      "run",
      "python",
      "../tests/browser/publish_financial_track_head.py",
      "recovered",
    ],
    { cwd: process.cwd(), env: process.env, stdio: ["ignore", "pipe", "pipe"] },
  );
}

function assertDataRefreshKey(idempotencyKey: string): void {
  if (!/^[a-z0-9-]+$/.test(idempotencyKey)) {
    throw new Error("Browser acceptance Data Refresh key is invalid");
  }
}

function authFixtureRequest(path: string, body: Record<string, unknown>): unknown {
  const origin = requiredEnvironment("THESISTRACE_TEST_AUTH_FIXTURE_ORIGIN");
  let output: string;
  try {
    output = execFileSync(
      "curl",
      [
        "--fail",
        "--silent",
        "--show-error",
        "--connect-timeout",
        "2",
        "--max-time",
        "30",
        "--header",
        "content-type: application/json",
        "--request",
        "POST",
        "--data-binary",
        "@-",
        `${origin}${path}`,
      ],
      {
        encoding: "utf8",
        input: JSON.stringify(body),
        killSignal: "SIGKILL",
        maxBuffer: 8 * 1024 * 1024,
        stdio: ["pipe", "pipe", "pipe"],
        timeout: 35_000,
      },
    );
  } catch {
    throw new Error("Private Auth test control request failed");
  }
  try {
    return JSON.parse(output) as unknown;
  } catch {
    throw new Error("Private Auth test control returned invalid JSON");
  }
}

export function sameOriginHeaders(): Record<string, string> {
  return { origin: requiredEnvironment("THESISTRACE_TEST_WEB_ORIGIN") };
}

export function testProjectName(): string {
  const project = requiredEnvironment("THESISTRACE_TEST_PROJECT_NAME");
  if (!/^thesistrace-test-[0-9]{8}t[0-9]{6}z-[0-9]+-[0-9a-f]{8}$/.test(project)) {
    throw new Error("Browser acceptance requires an isolated ThesisTrace Test project");
  }
  return project;
}

function requiredEnvironment(name: string): string {
  const value = process.env[name];
  if (value === undefined || value === "") throw new Error(`Missing ${name}`);
  return value;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
