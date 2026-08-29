import type { Locator, Page } from "@playwright/test";

import {
  browserPassword,
  createResearcher,
  emailToken,
  expect,
  expireInvitation,
  issueInvitation,
  restoreResearcherSession,
  runAuthOperator,
  sameOriginHeaders,
  securityTest as test,
} from "./auth-fixture";

test("Invitation, login, account password, reset, refresh, and access lifecycle stay invite-only", async ({ page }) => {
  test.setTimeout(90_000);
  await page.setViewportSize({ width: 375, height: 812 });
  const email = "browser-auth-flow@example.test";
  const invitationToken = await issueInvitation(email);

  await page.goto(`/accept-invitation#token=${encodeURIComponent(invitationToken)}`);
  await expect(page).toHaveURL(/\/accept-invitation$/);
  await expect(page.getByLabel("Email")).toHaveValue(email);
  await expect(page.getByLabel("Email")).toHaveAttribute("readonly", "");
  await expect(page.getByLabel(/name/i)).toHaveCount(0);
  const invitationPassword = page.getByLabel("Password", { exact: true });
  const invitationConfirmation = page.getByLabel("Confirm password");
  const acceptInvitation = page.getByRole("button", { name: "Accept invitation" });
  await expectTouchTargets(invitationPassword, invitationConfirmation, acceptInvitation);
  await expect(invitationPassword).toHaveAttribute("autocomplete", "new-password");
  await invitationPassword.focus();
  await page.keyboard.press("Tab");
  await expect(invitationConfirmation).toBeFocused();
  await invitationPassword.fill(browserPassword);
  await invitationConfirmation.fill(browserPassword);
  await acceptInvitation.click();

  await expect(page).toHaveURL(/\/data$/);
  await expect(page.getByRole("heading", { name: "Data overview" })).toBeVisible();
  await expect(page.locator("body")).not.toContainText(invitationToken);
  expect(await localStorageContains(page, invitationToken)).toBe(false);
  expect(await localStorageContains(page, "session_token")).toBe(false);

  await openAccountMenu(page);
  const accountMenu = page.getByLabel("Account menu");
  const changePasswordAction = page.getByRole("button", {
    name: "Change password",
    exact: true,
  });
  const logOutAction = page.getByRole("button", { name: "Log out" });
  await expectTouchTargets(accountMenu, changePasswordAction, logOutAction);
  await expect(accountMenu).not.toHaveAttribute("aria-haspopup");
  await expect(page.getByText(email, { exact: true })).toBeVisible();
  await accountMenu.focus();
  await page.keyboard.press("Shift+Tab");
  await expect(logOutAction).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(accountMenu).toBeFocused();
  await logOutAction.focus();
  await page.keyboard.press("Escape");
  await expect(accountMenu.locator("xpath=..")).not.toHaveAttribute("open", "");
  await expect(accountMenu).toBeFocused();

  await openAccountMenu(page);
  await changePasswordAction.click();
  const changedPassword = "Browser-changed-password-2026";
  const currentPassword = page.getByLabel("Current password");
  const newPassword = page.getByLabel("New password", { exact: true });
  const passwordConfirmation = page.getByLabel("Confirm password");
  const submitPassword = page.getByRole("button", {
    name: "Change password",
    exact: true,
  }).last();
  await expectTouchTargets(
    currentPassword,
    newPassword,
    passwordConfirmation,
    submitPassword,
    logOutAction,
  );
  await currentPassword.fill(browserPassword);
  await newPassword.fill(changedPassword);
  await passwordConfirmation.fill(changedPassword);
  await submitPassword.click();
  await expect(page.getByText("Password changed. Other sessions were logged out.")).toBeVisible();
  await page.getByRole("button", { name: "Log out" }).click();
  await expect(page).toHaveURL(/\/login\?returnTo=/);

  await page.goto("/research?folder=folder_default#formula");
  await expect(page).toHaveURL(/\/login\?returnTo=/);
  const returnTo = new URL(page.url()).searchParams.get("returnTo");
  expect(returnTo).toBe("/research?folder=folder_default#formula");
  await loginThroughUi(page, email, browserPassword);
  await expect(page.getByRole("alert")).toContainText("Email or password is incorrect.");
  await page.getByLabel("Password").fill(changedPassword);
  await page.getByRole("button", { name: "Log in" }).click();
  await expect(page).toHaveURL(/\/research\?folder=folder_default#formula$/);

  let sessionRefreshCount = 0;
  page.on("response", (response) => {
    if (new URL(response.url()).pathname === "/api/auth/get-session") sessionRefreshCount += 1;
  });
  const beforeFocus = sessionRefreshCount;
  await page.evaluate(() => window.dispatchEvent(new Event("focus")));
  await expect.poll(() => sessionRefreshCount).toBeGreaterThan(beforeFocus);
  const beforeOnline = sessionRefreshCount;
  await page.evaluate(() => window.dispatchEvent(new Event("online")));
  await expect.poll(() => sessionRefreshCount).toBeGreaterThan(beforeOnline);

  await openAccountMenu(page);
  await page.getByRole("button", { name: "Log out" }).click();
  await expect(page.getByRole("heading", { name: "Log in to ThesisTrace" })).toBeVisible();
  const forgotPassword = page.getByRole("button", { name: "Forgot password?" });
  await expectTouchTargets(forgotPassword);
  await forgotPassword.click();
  const forgotEmail = page.getByLabel("Email");
  const sendResetLink = page.getByRole("button", { name: "Send reset link" });
  await expectTouchTargets(forgotEmail, sendResetLink);
  await forgotEmail.fill(email);
  await sendResetLink.click();
  await expect(page.getByText("If the account exists, a reset link has been sent.")).toBeVisible();
  const resetToken = await emailToken(email, "/reset-password#token=");
  await page.goto(`/reset-password#token=${encodeURIComponent(resetToken)}`);
  await expect(page).toHaveURL(/\/reset-password$/);
  const resetPassword = "Browser-reset-password-2026";
  const resetPasswordInput = page.locator("#reset-password");
  const resetConfirmation = page.getByLabel("Confirm password");
  const resetPasswordAction = page.getByRole("button", { name: "Reset password" });
  await expectTouchTargets(resetPasswordInput, resetConfirmation, resetPasswordAction);
  await resetPasswordInput.fill(resetPassword);
  await resetConfirmation.fill(resetPassword);
  await resetPasswordAction.click();
  await expect(page).toHaveURL(/\/login\?reset=complete$/);
  await expect(page.getByText("Password reset. Log in with your new password.")).toBeVisible();
  expect(await localStorageContains(page, resetToken)).toBe(false);
  await loginThroughUi(page, email, resetPassword);
  await expect(page).toHaveURL(/\/data$/);

  expect(runAuthOperator("deactivate", "--email", email)).toMatchObject({
    command: "deactivate",
    status: "updated",
  });
  await page.evaluate(() => window.dispatchEvent(new Event("focus")));
  await expect(page.getByRole("heading", { name: "Log in to ThesisTrace" })).toBeVisible();
  expect(runAuthOperator("reactivate", "--email", email)).toMatchObject({
    command: "reactivate",
    status: "updated",
  });
  await loginThroughUi(page, email, resetPassword);
  await expect(page).toHaveURL(/\/data$/);

  expect(runAuthOperator("revoke-sessions", "--email", email)).toMatchObject({
    command: "revoke-sessions",
    status: "updated",
  });
  await page.evaluate(() => window.dispatchEvent(new Event("focus")));
  await expect(page.getByRole("heading", { name: "Log in to ThesisTrace" })).toBeVisible();
});

test("Invitation expiry, reissue, and lost-response replay converge safely", async ({ page }) => {
  const email = "browser-invitation-reissue@example.test";
  const expiredToken = await issueInvitation(email);
  expireInvitation(expiredToken);

  await page.goto(`/accept-invitation#token=${encodeURIComponent(expiredToken)}`);
  await expect(page).toHaveURL(/\/accept-invitation$/);
  await expect(page.getByRole("alert")).toContainText(
    "This invitation is invalid or has expired.",
  );

  expect(runAuthOperator("reissue", "--email", email)).toMatchObject({
    command: "reissue",
    status: "delivered",
  });
  const replacementToken = await emailToken(email, "/accept-invitation#token=");
  expect(replacementToken).not.toBe(expiredToken);
  await page.goto(`/accept-invitation#token=${encodeURIComponent(replacementToken)}`);
  await expect(page.getByLabel("Email")).toHaveValue(email);
  await page.getByLabel("Password", { exact: true }).fill(browserPassword);
  await page.getByLabel("Confirm password").fill(browserPassword);
  await page.getByRole("button", { name: "Accept invitation" }).click();
  await expect(page).toHaveURL(/\/data$/);

  const replay = await page.request.post(
    "/api/auth/researcher-invitation/accept",
    {
      data: { password: browserPassword, token: replacementToken },
      headers: sameOriginHeaders(),
    },
  );
  expect(replay.status()).toBe(200);
  const wrongPassword = await page.request.post(
    "/api/auth/researcher-invitation/accept",
    {
      data: {
        password: "Browser-wrong-password-2026",
        token: replacementToken,
      },
      headers: sameOriginHeaders(),
    },
  );
  expect(wrongPassword.status()).toBe(400);
  await expect(page.locator("body")).not.toContainText(replacementToken);
  expect(await localStorageContains(page, replacementToken)).toBe(false);
});

test("Bootstrap and Core failures preserve the exact Session boundary", async ({ page }) => {
  const email = "browser-bootstrap-retry@example.test";
  const token = await issueInvitation(email);
  let bootstrapUnavailable = true;
  await page.route("**/api/researcher/bootstrap", async (route) => {
    if (bootstrapUnavailable) {
      await route.fulfill({ json: { code: "CORE_UNAVAILABLE" }, status: 503 });
    } else {
      await route.continue();
    }
  });
  await page.goto(`/accept-invitation#token=${encodeURIComponent(token)}`);
  await expect(page.getByLabel("Email")).toHaveValue(email);
  await page.getByLabel("Password", { exact: true }).fill(browserPassword);
  await page.getByLabel("Confirm password").fill(browserPassword);
  await page.getByRole("button", { name: "Accept invitation" }).click();
  await expect(page.getByRole("heading", { name: "Workspace setup unavailable" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Data overview" })).toHaveCount(0);
  bootstrapUnavailable = false;
  await page.getByRole("button", { name: "Retry setup" }).click();
  await expect(page).toHaveURL(/\/data$/);
  await expect(page.getByRole("heading", { name: "Data overview" })).toBeVisible();
  await page.unroute("**/api/researcher/bootstrap");

  await page.getByRole("link", { name: "Research", exact: true }).click();
  await expect(page.getByLabel("Research name")).toBeVisible();
  await page.route("**/api/data", (route) => route.fulfill({
    json: { code: "CORE_UNAVAILABLE" },
    status: 503,
  }));
  await page.getByRole("link", { name: "Data", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("Data unavailable");
  await expect(page.getByLabel("Account menu")).toBeVisible();
  await page.unroute("**/api/data");
  await page.getByRole("button", { name: "Retry" }).click();
  await expect(page.getByRole("heading", { name: "Data overview" })).toBeVisible();

  await page.route("**/api/auth/get-session", (route) => route.fulfill({
    json: { code: "AUTH_SERVICE_UNAVAILABLE" },
    status: 503,
  }));
  await page.evaluate(() => window.dispatchEvent(new Event("focus")));
  await expect(page.getByRole("heading", { name: "Authentication unavailable" })).toBeVisible();
  await expect(page.getByText("Existing session data has been retained.")).toBeVisible();
  await page.unroute("**/api/auth/get-session");
  await page.getByRole("button", { name: "Retry" }).click();
  await expect(page.getByRole("heading", { name: "Data overview" })).toBeVisible();

  await page.getByRole("link", { name: "Research", exact: true }).click();
  await page.route("**/api/data", (route) => route.fulfill({
    json: { code: "AUTHENTICATION_REQUIRED" },
    status: 401,
  }));
  await page.getByRole("link", { name: "Data", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Log in to ThesisTrace" })).toBeVisible();
  await expect(page.getByLabel("Account menu")).toHaveCount(0);
});

test.describe("tablet touch presentation", () => {
  test.use({
    hasTouch: true,
    viewport: { width: 820, height: 1180 },
  });

  test("Auth and account controls keep 44px touch targets above the mobile breakpoint", async ({ page }) => {
    const email = "browser-tablet-touch@example.test";
    const invitationToken = await issueInvitation(email);

    await page.goto(`/accept-invitation#token=${encodeURIComponent(invitationToken)}`);
    const password = page.getByLabel("Password", { exact: true });
    const confirmation = page.getByLabel("Confirm password");
    const acceptInvitation = page.getByRole("button", { name: "Accept invitation" });
    await expectTouchTargets(password, confirmation, acceptInvitation);
    await password.fill(browserPassword);
    await confirmation.fill(browserPassword);
    await acceptInvitation.click();

    await expect(page.getByRole("heading", { name: "Data overview" })).toBeVisible();
    await openAccountMenu(page);
    const accountMenu = page.getByLabel("Account menu");
    const changePassword = page.getByRole("button", {
      name: "Change password",
      exact: true,
    });
    const logOut = page.getByRole("button", { name: "Log out" });
    await expectTouchTargets(accountMenu, changePassword, logOut);

    await changePassword.click();
    await expectTouchTargets(
      page.getByLabel("Current password"),
      page.getByLabel("New password", { exact: true }),
      page.getByLabel("Confirm password"),
      page.getByRole("button", { name: "Change password", exact: true }).last(),
    );
  });
});

test("Two Researchers isolate Drafts, receipts, cursors, and system Folder identity", async ({ page }) => {
  test.setTimeout(180_000);
  const researcherA = await createResearcher(page, "browser-isolation-a@example.test");
  const bootstrapA = await bootstrap(page);
  await page.goto("/research");
  await page.getByLabel("Research name").fill("Researcher A draft");
  await replaceFormula(page, "close");
  const keyA = `thesistrace.research-draft.${researcherA.id}.folder_default`;
  await expect.poll(() => page.evaluate((key) => localStorage.getItem(key), keyA)).not.toBeNull();

  const researcherB = await createResearcher(page, "browser-isolation-b@example.test");
  const bootstrapB = await bootstrap(page);
  expect(bootstrapA.system_folders).toEqual(bootstrapB.system_folders);
  expect(bootstrapB.system_folders).toEqual({
    default: "folder_default",
    batch_research: "folder_batch_research",
  });
  await page.goto("/research");
  await expect(page.getByLabel("Research name")).toHaveValue("");
  await page.getByLabel("Research name").fill("Researcher B draft");
  await replaceFormula(page, "volume");
  const keyB = `thesistrace.research-draft.${researcherB.id}.folder_default`;
  await expect.poll(() => page.evaluate((key) => localStorage.getItem(key), keyB)).not.toBeNull();

  const folderBResponse = await page.request.post("/api/research-folders", {
    data: { name: "Researcher B private folder" },
    headers: sameOriginHeaders(),
  });
  expect(folderBResponse.status()).toBe(201);
  const folderB = (await folderBResponse.json()) as { id: string };
  const batchB = await admitBatch(page, "browser-owner-batch-b");
  const strategyRunB = await admitStrategyRun(page, "browser-owner-track-run-b");
  await expect.poll(async () => {
    const response = await page.request.get(`/api/research-runs/${strategyRunB}`);
    return ((await response.json()) as { status: string }).status;
  }, { timeout: 90_000 }).toBe("succeeded");
  const trackBResponse = await page.request.post(
    `/api/research-runs/${strategyRunB}/daily-tracks`,
    {
      data: { request_id: "browser-owner-track-b" },
      headers: sameOriginHeaders(),
    },
  );
  expect(trackBResponse.status()).toBe(201);
  const trackB = (await trackBResponse.json()) as { id: string };

  const sharedRequestId = "browser-shared-owner-receipt";
  const runB = await admitRun(page, sharedRequestId, "Researcher B shared receipt");
  await restoreResearcherSession(page, researcherA);
  await bootstrap(page);
  await page.goto("/research");
  await expect(page.getByLabel("Research name")).toHaveValue("Researcher A draft");
  const runA = await admitRun(page, sharedRequestId, "Researcher A shared receipt");
  await admitRun(page, "browser-owner-cursor-second", "Researcher A cursor second");
  expect(runA).not.toBe(runB);
  expect((await page.request.get(`/api/research-runs/${runB}`)).status()).toBe(404);
  expect((await page.request.get(`/api/research-batches/${batchB}`)).status()).toBe(404);
  expect((await page.request.get(`/api/daily-tracks/${trackB.id}`)).status()).toBe(404);
  const foldersA = (await (await page.request.get("/api/research-folders")).json()) as {
    items: Array<{ id: string }>;
  };
  expect(foldersA.items.map((folder) => folder.id)).not.toContain(folderB.id);
  const firstPage = await page.request.get("/api/research-runs?limit=1");
  expect(firstPage.status()).toBe(200);
  const firstPageBody = await firstPage.json() as { next_cursor: string | null };
  expect(firstPageBody.next_cursor).not.toBeNull();
  if (firstPageBody.next_cursor === null) throw new Error("Researcher A cursor was not created");

  await restoreResearcherSession(page, researcherB);
  await bootstrap(page);
  expect((await page.request.get(`/api/research-runs/${runA}`)).status()).toBe(404);
  expect((await page.request.get(
    `/api/research-runs?limit=1&cursor=${encodeURIComponent(firstPageBody.next_cursor)}`,
  )).status()).toBe(400);
  await page.goto("/research");
  await expect(page.getByLabel("Research name")).toHaveValue("Researcher B draft");
  expect(await page.evaluate(() => Object.keys(localStorage).sort())).toEqual([keyA, keyB].sort());
  expect(await page.evaluate(() => localStorage.getItem(
    "thesistrace.research-draft.folder_default",
  ))).toBeNull();
});

async function loginThroughUi(page: Page, email: string, password: string): Promise<void> {
  const emailInput = page.getByLabel("Email");
  const passwordInput = page.getByLabel("Password");
  const logIn = page.getByRole("button", { name: "Log in" });
  await expectTouchTargets(emailInput, passwordInput, logIn);
  await emailInput.fill(email);
  await passwordInput.fill(password);
  await logIn.click();
}

async function openAccountMenu(page: Page): Promise<void> {
  const menu = page.getByLabel("Account menu");
  if ((await menu.locator("xpath=..").getAttribute("open")) === null) await menu.click();
}

async function expectTouchTargets(...targets: Locator[]): Promise<void> {
  for (const target of targets) {
    await expect(target).toBeVisible();
    const box = await target.boundingBox();
    expect(box, "touch target should have a rendered bounding box").not.toBeNull();
    expect(box?.height, "touch target height").toBeGreaterThanOrEqual(44);
    expect(box?.width, "touch target width").toBeGreaterThanOrEqual(44);
  }
}

async function localStorageContains(page: Page, value: string): Promise<boolean> {
  return page.evaluate((secret) => Object.values(localStorage).some((item) => item.includes(secret)), value);
}

async function bootstrap(page: Page): Promise<{
  researcher_id: string;
  system_folders: { default: string; batch_research: string };
}> {
  const response = await page.request.post("/api/researcher/bootstrap", {
    data: {},
    headers: { origin: requiredOrigin() },
  });
  expect(response.status()).toBe(200);
  return response.json();
}

async function admitRun(page: Page, requestId: string, name: string): Promise<string> {
  const response = await page.request.post("/api/research-runs", {
    data: {
      request_id: requestId,
      folder_id: "folder_default",
      name,
      formula: "close",
      hypothesis: null,
      start_date: "2026-08-04",
      end_date: "2026-08-05",
      universe: "top300",
      neutralization: "none",
      research_kind: "factor_evaluation",
    },
    headers: { origin: requiredOrigin() },
  });
  expect(response.status()).toBe(202);
  const body = await response.json() as { id?: unknown };
  if (typeof body.id !== "string") throw new Error("Research Run admission returned no id");
  return body.id;
}

async function admitBatch(page: Page, requestId: string): Promise<string> {
  const response = await page.request.post("/api/research-batches", {
    data: {
      request_id: requestId,
      batch_kind: "factor_evaluation",
      start_date: "2026-08-04",
      end_date: "2026-08-05",
      universe: "top300",
      neutralization: "none",
      factors: [{ item_key: "private-factor", formula: "close" }],
    },
    headers: sameOriginHeaders(),
  });
  expect(response.status()).toBe(202);
  const body = (await response.json()) as { id?: unknown };
  if (typeof body.id !== "string") throw new Error("Research Batch returned no id");
  return body.id;
}

async function admitStrategyRun(page: Page, requestId: string): Promise<string> {
  const response = await page.request.post("/api/research-runs", {
    data: {
      request_id: requestId,
      folder_id: "folder_default",
      name: "Researcher B private Track seed",
      formula: "close",
      hypothesis: null,
      start_date: "2026-08-04",
      end_date: "2026-08-05",
      universe: "top300",
      neutralization: "none",
      research_kind: "strategy_backtest",
      holdings_count: 10,
      rebalance_every_sessions: 1,
    },
    headers: sameOriginHeaders(),
  });
  expect(response.status()).toBe(202);
  const body = (await response.json()) as { id?: unknown };
  if (typeof body.id !== "string") throw new Error("Strategy Run returned no id");
  return body.id;
}

async function replaceFormula(page: Page, formula: string): Promise<void> {
  const editor = page.locator(".cm-content");
  await editor.click();
  await page.keyboard.press(process.platform === "darwin" ? "Meta+A" : "Control+A");
  await page.keyboard.type(formula);
}

function requiredOrigin(): string {
  const origin = process.env.THESISTRACE_TEST_WEB_ORIGIN;
  if (origin === undefined) throw new Error("Missing THESISTRACE_TEST_WEB_ORIGIN");
  return origin;
}
