import { expect, test as base, type Page } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";

export type AuthenticatedResearcher = Readonly<{
  cookie: string;
  email: string;
  id: string;
}>;

export const browserPassword = "Browser-acceptance-password-2026";
export const test = base.extend<{ researcher: AuthenticatedResearcher }>({
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
  const output = execFileSync(
    "docker",
    [
      "exec",
      `${testProjectName()}-auth-1`,
      "node",
      "/test-fixtures/provision-image-smoke-session.mjs",
      email,
      password,
      `198.51.100.${ipSuffix}`,
    ],
    { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] },
  );
  const provisioned = JSON.parse(output) as unknown;
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
    for (const candidate of payload.emails) {
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
  const output = execFileSync(
    "docker",
    ["exec", `${testProjectName()}-auth-1`, "node", "dist/operator.js", ...args],
    { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] },
  );
  return JSON.parse(output) as unknown;
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
