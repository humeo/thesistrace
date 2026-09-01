import { expect, test as base, type Page } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";

export type AuthenticatedResearcher = Readonly<{
  cookie: string;
  email: string;
  id: string;
}>;

export const browserPassword = "Browser-acceptance-password-2026";
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
    await page.goto("/data");
    await expect(page.getByRole("heading", { name: "Data overview" })).toBeVisible();
    await use(researcher);
  }, { auto: true }],
});

export { expect };

export async function issueInvitation(email: string): Promise<string> {
  const resendOrigin = requiredEnvironment("THESISTRACE_TEST_RESEND_ORIGIN");
  const cleared = await fetch(`${resendOrigin}/__test/emails`, { method: "DELETE" });
  if (!cleared.ok) throw new Error("Could not reset the local Resend acceptance fixture");
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
  const resendOrigin = requiredEnvironment("THESISTRACE_TEST_RESEND_ORIGIN");
  const deadline = Date.now() + 5_000;
  let lastEmailCount = 0;
  while (Date.now() < deadline) {
    const response = await fetch(`${resendOrigin}/__test/emails`);
    if (!response.ok) throw new Error("Could not read the local Resend acceptance fixture");
    const payload = await response.json() as unknown;
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

export function runAuthOperator(...args: string[]): unknown {
  return authFixtureRequest("/__test/operator", { args });
}

export function expireInvitation(token: string): void {
  const result = authFixtureRequest("/__test/expire-invitation", { token });
  if (!isRecord(result) || result.status !== "expired") {
    throw new Error("Private Auth expiry fixture returned an invalid result");
  }
}

function resetAuthRateLimits(): void {
  const result = authFixtureRequest("/__test/reset-rate-limits", {});
  if (!isRecord(result) || result.status !== "reset") {
    throw new Error("Private Auth rate-limit fixture returned an invalid result");
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
