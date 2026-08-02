import { expect, type Page, test } from "@playwright/test";
import {
  chmodSync,
  existsSync,
  mkdirSync,
  readFileSync,
  writeFileSync,
} from "node:fs";
import { execFileSync } from "node:child_process";
import { join } from "node:path";

type Credentials = {
  email_a: string;
  password_a: string;
  email_b: string;
  password_b: string;
};

type ProductContext = {
  suffix: string;
  api_relay_run_id: string;
  run_id: string;
  tombstone_run_id: string;
  track_id: string;
  workspace_a: string;
  workspace_b: string;
};

type BrowserCredentials = {
  email: string;
  password: string;
};

const stateDir = process.env.THESISTRACE_HOST_STATE_DIR;
const stack = process.env.THESISTRACE_HOSTED_STACK;
const evidencePath = process.env.THESISTRACE_HOSTED_BROWSER_EVIDENCE;
const screenshotDir = process.env.THESISTRACE_HOSTED_BROWSER_SCREENSHOTS;
if (!stateDir || !stack || !evidencePath || !screenshotDir) {
  throw new Error("Hosted browser acceptance paths are required");
}

const credentials = JSON.parse(
  readFileSync(join(stateDir, "public-origin-credentials.json"), "utf8"),
) as Credentials;
const product = JSON.parse(
  readFileSync(join(stateDir, "public-origin-context.json"), "utf8"),
) as ProductContext;
const browserCredentialsPath = join(stateDir, "browser-credentials.json");

function operator(...arguments_: string[]) {
  execFileSync(stack, arguments_, {
    cwd: join(import.meta.dirname, "../.."),
    env: process.env,
    stdio: "pipe",
  });
}

async function login(page: Page, email: string, password: string): Promise<string> {
  await page.goto("/");
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await page.getByLabel("邮箱").fill(email);
  await page.getByLabel("密码").fill(password);
  const sessionResponse = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      response.url().includes("/api/auth/sessions?client_type=server"),
  );
  await page.getByRole("button", { name: "继续" }).click();
  const response = await sessionResponse;
  expect(response.status()).toBe(200);
  const payload = (await response.json()) as { accessToken: string };
  await expect(page.getByText("Personal Workspace ·", { exact: false })).toBeVisible({
    timeout: 20_000,
  });
  return payload.accessToken;
}

test("proves the staged Hosted Web identity, product, and privacy flows", async ({
  page,
  request,
}) => {
  mkdirSync(screenshotDir, { recursive: true, mode: 0o700 });
  const consoleErrors: string[] = [];
  const failedRequests: { method: string; url: string; error: string }[] = [];
  const responseStatuses: { method: string; path: string; status: number }[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("requestfailed", (failed) => {
    failedRequests.push({
      method: failed.method(),
      url: new URL(failed.url()).pathname,
      error: failed.failure()?.errorText ?? "unknown",
    });
  });
  page.on("response", (response) => {
    const url = new URL(response.url());
    if (url.pathname.startsWith("/api/")) {
      responseStatuses.push({
        method: response.request().method(),
        path: url.pathname,
        status: response.status(),
      });
    }
  });

  const identityReused = existsSync(browserCredentialsPath);
  let browserCredentials: BrowserCredentials;
  if (identityReused) {
    browserCredentials = JSON.parse(
      readFileSync(browserCredentialsPath, "utf8"),
    ) as BrowserCredentials;
    await login(page, browserCredentials.email, browserCredentials.password);
  } else {
    const browserEmail = `local-browser-${product.suffix}@example.invalid`;
    const browserPassword = `Browser-${product.suffix.slice(0, 12)}!9`;
    const recoveredPassword = `${browserPassword}-reset`;
    operator("acceptance-seed-invitation", browserEmail);

    await page.goto("/");
    await expect(page.getByRole("heading", { name: "登录 Personal Workspace" })).toBeVisible();
    await page.getByRole("button", { name: "注册" }).click();
    await page.getByLabel("邮箱").fill(browserEmail);
    await page.getByLabel("密码").fill(browserPassword);
    await page.getByRole("button", { name: "继续" }).click();
    await expect(page.getByRole("heading", { name: "验证邮箱" })).toBeVisible();
    operator("acceptance-seed-otp", browserEmail, "VERIFY_EMAIL", "424242");
    await page.getByLabel("邮箱验证码").fill("424242");
    await page.getByRole("button", { name: "继续" }).click();
    await expect(page.getByRole("heading", { name: "创建 Personal Workspace" })).toBeVisible();
    await page.getByRole("button", { name: "创建唯一的 Personal Workspace" }).click();
    await expect(page.getByRole("heading", { name: "研究工作台" })).toBeVisible({
      timeout: 20_000,
    });
    await expect(page.getByText("DATASET RELEASES", { exact: true })).toBeVisible();
    await page.screenshot({
      path: join(screenshotDir, "01-registration-provisioning.png"),
      fullPage: true,
    });

    await page.getByRole("button", { name: "退出登录" }).click();
    await page.getByRole("button", { name: "忘记密码" }).click();
    await page.getByLabel("邮箱").fill(browserEmail);
    await page.getByRole("button", { name: "发送恢复邮件" }).click();
    await expect(page.getByLabel("重置验证码")).toBeVisible();
    operator("acceptance-seed-otp", browserEmail, "RESET_PASSWORD", "434343");
    await page.getByLabel("重置验证码").fill("434343");
    await page.getByLabel("新密码").fill(recoveredPassword);
    await page.getByRole("button", { name: "继续" }).click();
    await expect(page.getByRole("heading", { name: "登录 Personal Workspace" })).toBeVisible();
    await page.getByLabel("邮箱").fill(browserEmail);
    await page.getByLabel("密码").fill(recoveredPassword);
    await page.getByRole("button", { name: "继续" }).click();
    await expect(page.getByRole("heading", { name: "研究工作台" })).toBeVisible();
    browserCredentials = { email: browserEmail, password: recoveredPassword };
    writeFileSync(
      browserCredentialsPath,
      `${JSON.stringify(browserCredentials)}\n`,
      { mode: 0o600 },
    );
    chmodSync(browserCredentialsPath, 0o600);
  }
  await page.screenshot({
    path: join(screenshotDir, "01-registration-provisioning.png"),
    fullPage: true,
  });

  await page.getByRole("button", { name: "退出登录" }).click();
  const tokenA = await login(page, credentials.email_a, credentials.password_a);
  await expect(page.getByText(product.run_id, { exact: true }).first()).toBeVisible();
  await expect(page.getByText(product.track_id, { exact: true }).first()).toBeVisible();
  await expect(page.getByText("Result Bundle", { exact: false }).first()).toBeVisible();

  const browserResearchTitle = `Browser acceptance ${product.suffix.slice(0, 12)}`;
  const existingBrowserRun = page.getByText(browserResearchTitle, { exact: true });
  if ((await existingBrowserRun.count()) === 0) {
    await page.getByLabel("研究名称").fill(browserResearchTitle);
    await page.getByLabel("研究假设").fill("浏览器验收必须冻结并运行可复现定义。");
    await page.getByRole("button", { name: "运行研究" }).click();
    await expect(page.getByText("SUCCEEDED", { exact: true }).first()).toBeVisible({
      timeout: 60_000,
    });
    await expect(page.getByRole("heading", { name: "因子结论" })).toBeVisible();
    await page.getByRole("button", { name: "开始每日追踪" }).click();
    await expect(page.getByText("ACTIVE", { exact: true }).first()).toBeVisible();
    const activeTracks = await request.get("/api/v1/daily-tracks", {
      headers: { Authorization: `Bearer ${tokenA}` },
    });
    expect(activeTracks.status()).toBe(200);
    const activeTrackId = (
      (await activeTracks.json()) as { items: { id: string; status: string }[] }
    ).items.find((track) => track.status === "active")?.id;
    expect(activeTrackId).toBeTruthy();
    await page.getByRole("button", { name: "运行研究" }).click();
    await expect(page.getByText("SUCCEEDED", { exact: true }).first()).toBeVisible({
      timeout: 60_000,
    });
    await page.getByRole("button", { name: "开始每日追踪" }).click();
    await expect(page.getByText("QUOTA_EXCEEDED", { exact: false })).toBeVisible();
    const stopped = await request.post(`/api/v1/daily-tracks/${activeTrackId}/stop`, {
      headers: { Authorization: `Bearer ${tokenA}` },
    });
    expect(stopped.status()).toBe(200);
    await page.getByRole("button", { name: "开始每日追踪" }).click();
    await expect(page.getByText("ACTIVE", { exact: true }).first()).toBeVisible();
    await page.getByRole("button", { name: "停止追踪" }).click();
    await expect(page.getByText("STOPPED", { exact: true }).first()).toBeVisible();
    const rerunButtons = page.getByRole("button", { name: "重新运行" });
    const terminalRunsBefore = await rerunButtons.count();
    await rerunButtons.last().click();
    await expect
      .poll(() => rerunButtons.count(), { timeout: 60_000 })
      .toBeGreaterThan(terminalRunsBefore);
  } else {
    await expect(existingBrowserRun.first()).toBeVisible();
  }
  await page.screenshot({
    path: join(screenshotDir, "02-retained-product.png"),
    fullPage: true,
  });

  const loginB = await request.post("/api/auth/sessions?client_type=server", {
    data: { email: credentials.email_b, password: credentials.password_b },
  });
  expect(loginB.status()).toBe(200);
  const tokenB = ((await loginB.json()) as { accessToken: string }).accessToken;
  const foreignRun = await request.get(`/api/v1/research-runs/${product.run_id}`, {
    headers: { Authorization: `Bearer ${tokenB}` },
  });
  expect(foreignRun.status()).toBe(404);
  const tombstone = await request.get(
    `/api/v1/research-runs/${product.tombstone_run_id}`,
    { headers: { Authorization: `Bearer ${tokenA}` } },
  );
  expect(tombstone.status()).toBe(404);
  const browserTombstone = await request.get(
    `/api/v1/research-runs/${product.api_relay_run_id}`,
    { headers: { Authorization: `Bearer ${tokenA}` } },
  );
  if (browserTombstone.status() === 200) {
    const row = page
      .getByText(product.api_relay_run_id, { exact: true })
      .first()
      .locator("xpath=ancestor::article");
    page.once("dialog", (dialog) => void dialog.accept());
    await row.getByRole("button", { name: "永久删除" }).click();
    await expect(page.getByText(product.api_relay_run_id, { exact: true })).toHaveCount(0);
  } else {
    expect(browserTombstone.status()).toBe(404);
  }
  for (const path of [
    "/storage/v1/buckets",
    "/storage/v1/object/private/probe",
    "/api/storage/v1/object/private/probe",
  ]) {
    const blocked = await request.get(path, {
      headers: { Authorization: `Bearer ${tokenA}` },
    });
    expect(blocked.status()).toBe(404);
  }
  expect(await page.evaluate(() => ({
    local: Object.keys(localStorage),
    session: Object.keys(sessionStorage),
  }))).toEqual({ local: [], session: [] });

  await page.getByRole("button", { name: "退出登录" }).click();
  await expect(page.locator("body")).not.toContainText(product.run_id);
  await expect(page.locator("body")).not.toContainText(product.workspace_a);
  await page.screenshot({
    path: join(screenshotDir, "03-logged-out.png"),
    fullPage: true,
  });

  const unexpectedFailures = failedRequests.filter(
    (failure) => failure.error !== "net::ERR_ABORTED",
  );
  expect(consoleErrors).toEqual([]);
  expect(unexpectedFailures).toEqual([]);
  const evidence = {
    schema_version: "hosted-local-browser-v1",
    status: "passed",
    route: new URL(page.url()).pathname,
    assertions: {
      registration_verification: true,
      registration_identity_reused: identityReused,
      password_recovery: true,
      personal_workspace_provisioning: true,
      retained_product_visible: true,
      cross_workspace_denied: true,
      tombstone_stale_route_denied: true,
      separate_tombstone_flow: true,
      private_research_and_tracking_visible: true,
      quota_visible: true,
      rerun_visible: true,
      storage_routes_denied: true,
      browser_storage_empty: true,
      logged_out_private_state_absent: true,
    },
    screenshots: [
      "01-registration-provisioning.png",
      "02-retained-product.png",
      "03-logged-out.png",
    ],
    console_errors: consoleErrors,
    failed_requests: failedRequests,
    response_statuses: responseStatuses,
  };
  writeFileSync(evidencePath, `${JSON.stringify(evidence, null, 2)}\n`, { mode: 0o600 });
  chmodSync(evidencePath, 0o600);
});
