import type { Locator, Page, Route } from "@playwright/test";

import {
  assertDataOperatorWorkerLeaseReleased,
  browserPassword,
  createResearcher,
  emailToken,
  ensureOperatorDataBaseline,
  exhaustDataRefresh,
  expireDataRefreshClaim,
  expect,
  fillPasswordInput,
  issueInvitation,
  markDataRefreshRunning,
  resetAuthRateLimits,
  restoreResearcherSession,
  runAuthOperator,
  sameOriginHeaders,
  seedOperatorDirectory,
  startDataOperatorWorker,
  stopDataOperatorWorker,
  securityTest as test,
  type AuthenticatedResearcher,
} from "./auth-fixture";

test("only the singleton Operator can open and read the Operator Console", async ({ page }) => {
  test.setTimeout(240_000);
  const operatorMutationRequests: Array<Readonly<{ path: string; body: string }>> = [];
  const marketStatusRequests: Array<Readonly<{
    asOf: string | null;
    idempotencyKey: string | null;
  }>> = [];
  const financialStatusRequests: Array<Readonly<{
    idempotencyKey: string | null;
    observationThroughSession: string | null;
  }>> = [];
  const industryStatusRequests: Array<Readonly<{
    idempotencyKey: string | null;
    observationThroughSession: string | null;
  }>> = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    const path = url.pathname;
    if (request.method() === "GET" && path === "/api/operator/data/refreshes/market") {
      marketStatusRequests.push({
        asOf: url.searchParams.get("as_of"),
        idempotencyKey: url.searchParams.get("idempotency_key"),
      });
    }
    if (request.method() === "GET" && path === "/api/operator/data/refreshes/financial") {
      financialStatusRequests.push({
        idempotencyKey: url.searchParams.get("idempotency_key"),
        observationThroughSession: url.searchParams.get("observation_through_session"),
      });
    }
    if (request.method() === "GET" && path === "/api/operator/data/refreshes/industry") {
      industryStatusRequests.push({
        idempotencyKey: url.searchParams.get("idempotency_key"),
        observationThroughSession: url.searchParams.get("observation_through_session"),
      });
    }
    if (
      request.method() === "POST"
      && (
        path === "/api/auth/operator/proofs"
        || path.startsWith("/api/auth/operator/invitations/")
        || path === "/api/auth/operator/researchers/sessions/revoke"
        || path === "/api/operator/data/refreshes/market"
        || path === "/api/operator/data/refreshes/financial"
        || path === "/api/operator/data/refreshes/industry"
        || path === "/api/operator/data/refreshes/cancel"
        || path === "/api/operator/data/refreshes/retry"
      )
    ) {
      operatorMutationRequests.push({ body: request.postData() ?? "", path });
    }
  });
  const operator = await createResearcher(page, "browser-operator@example.test");
  await bootstrapResearcher(page, operator);
  expect(runAuthOperator("assign-operator", "--researcher-id", operator.id)).toMatchObject({
    command: "assign-operator",
    researcher_id: operator.id,
    status: "assigned",
  });
  await ensureOperatorDataBaseline(page);

  const ordinary = await createResearcher(page, "browser-ordinary@example.test");
  await bootstrapResearcher(page, ordinary);
  await page.goto("/data");
  await expect(page.getByRole("heading", { name: "Data overview" })).toBeVisible();
  seedOperatorDirectory();
  const invitationEmail = "browser-reissued-invitation@example.test";
  await issueInvitation(invitationEmail);
  expect(runAuthOperator("reissue", "--email", invitationEmail)).toMatchObject({
    command: "reissue",
    email: invitationEmail,
    status: "delivered",
  });

  await restoreResearcherSession(page, operator);
  const operatorDocument = await page.goto("/operator/researchers");
  expect(operatorDocument?.status()).toBe(200);
  await expect(page.getByRole("link", { name: "Operator", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Researcher access" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Researchers" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Invitations" })).toBeVisible();
  const researcherTable = page.getByRole("table", { name: "Researchers" });
  const operatorRow = researcherTable.getByRole("row").filter({ hasText: operator.email });
  await expect(operatorRow.getByText("browser-operator", { exact: true })).toBeVisible();
  await expect(operatorRow.getByText(operator.email, { exact: true })).toBeVisible();
  await expect(operatorRow.locator('[data-label="Researcher ID"]')).toHaveText(operator.id);
  await expect(operatorRow.locator('[data-label="Access"]')).toHaveText("Active");
  await expect(operatorRow.locator('[data-label="Created"] time')).toHaveCount(1);
  await expect(operatorRow.locator('[data-label="Latest login"]')).toHaveText(/.+/);
  await expect(operatorRow.locator('[data-label="Current sessions"]')).toHaveText("1");
  await expect(operatorRow.locator('[data-label="Effective invitation"]')).toHaveText("None");
  await expect(researcherTable.getByText(ordinary.email, { exact: true })).toBeVisible();

  const initialViewport = page.viewportSize();
  const applicationShell = page.locator(".app-shell");
  const applicationSidebar = page.locator(".application-sidebar");
  const collapseSidebar = page.getByRole("button", { name: "Collapse sidebar" });
  await expect(collapseSidebar).toBeVisible();
  await collapseSidebar.focus();
  await collapseSidebar.press("Enter");
  await expect(applicationShell).toHaveClass(/app-shell-collapsed/);
  const expandSidebar = page.getByRole("button", { name: "Expand sidebar" });
  await expect(expandSidebar).toBeFocused();
  await expect(page.getByRole("link", { name: "Operator", exact: true })).toBeVisible();
  await expandSidebar.press("Enter");
  await expect(applicationShell).not.toHaveClass(/app-shell-collapsed/);

  await page.setViewportSize({ width: 820, height: 1_080 });
  await expect(collapseSidebar).toBeVisible();
  await collapseSidebar.click();
  await expect.poll(async () => applicationSidebar.evaluate(
    (element) => Number.parseFloat(getComputedStyle(element).width),
  )).toBeLessThan(100);
  await page.getByRole("button", { name: "Expand sidebar" }).click();
  await expect.poll(async () => applicationSidebar.evaluate(
    (element) => Number.parseFloat(getComputedStyle(element).width),
  )).toBeGreaterThan(200);

  await page.setViewportSize({ width: 375, height: 812 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  const openNavigation = page.getByRole("button", { name: "Open navigation" });
  await expect(openNavigation).toBeVisible();
  await expectMinimumTouchTarget(openNavigation);
  await openNavigation.focus();
  await openNavigation.press("Enter");
  await expect(applicationShell).toHaveClass(/app-shell-navigation-open/);
  const closeNavigation = page.locator(".mobile-navigation-close");
  await expect(closeNavigation).toBeFocused();
  await expectMinimumTouchTarget(closeNavigation);
  const mobileOperatorLink = page.getByRole("link", { name: "Operator", exact: true });
  const mobileHomeLink = page.getByRole("link", { name: "ThesisTrace home" });
  const mobileAccountMenu = applicationSidebar.getByLabel("Account menu");
  await expect(mobileOperatorLink).toBeVisible();
  await mobileHomeLink.focus();
  await mobileHomeLink.press("Shift+Tab");
  await expect(mobileAccountMenu).toBeFocused();
  await mobileAccountMenu.press("Tab");
  await expect(mobileHomeLink).toBeFocused();
  const reducedTransitionSeconds = await page.locator(".navigation-backdrop").evaluate(
    (element) => {
      const value = getComputedStyle(element).transitionDuration;
      const duration = Number.parseFloat(value) || 0;
      return value.endsWith("ms") ? duration / 1_000 : duration;
    },
  );
  expect(reducedTransitionSeconds).toBeLessThanOrEqual(0.00001);
  await page.keyboard.press("Escape");
  await expect(applicationShell).not.toHaveClass(/app-shell-navigation-open/);
  await expect(openNavigation).toBeFocused();
  await expect(operatorRow.locator('[data-label="Researcher ID"]')).toBeVisible();
  await expect(operatorRow.locator('[data-label="Access"]')).toHaveText("Active");
  await expect(operatorRow.locator('[data-label="Current sessions"]')).toHaveText("1");
  await expectMinimumTouchTarget(
    page.getByRole("button", { name: "Invite Researcher" }),
  );
  await page.emulateMedia({ reducedMotion: "no-preference" });
  if (initialViewport !== null) await page.setViewportSize(initialViewport);

  const invitationTable = page.getByRole("table", { name: "Invitations" });
  const invitationRows = invitationTable.getByRole("row").filter({ hasText: invitationEmail });
  await expect(invitationRows).toHaveCount(2);
  const effectiveInvitation = invitationRows.filter({ hasText: "Effective · Delivered" });
  const terminalInvitation = invitationRows.filter({ hasText: "Terminal · Revoked" });
  await expect(effectiveInvitation).toHaveCount(1);
  await expect(effectiveInvitation.locator("code")).toHaveText(
    /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/,
  );
  await expect(effectiveInvitation.locator("time")).toHaveCount(2);
  await expect(effectiveInvitation.locator('[data-label="Terminal"]')).toHaveText("—");
  await expect(terminalInvitation).toHaveCount(1);
  await expect(terminalInvitation.locator("time")).toHaveCount(3);

  const consoleInvitationEmail = "browser-console-invited@example.test";
  const inviteResearcher = page.getByRole("button", { name: "Invite Researcher" });
  await inviteResearcher.focus();
  await inviteResearcher.press("Enter");
  let confirmation = page.getByRole("dialog", { name: "Issue Invitation?" });
  await expect(confirmation).toBeVisible();
  await expect(confirmation).toContainText("Target email");
  await expect(confirmation).toContainText("A 48-hour Invitation");
  const issueEmail = confirmation.getByLabel("Target email");
  const issuePassword = confirmation.getByLabel("Current password");
  await expect(issueEmail).toBeFocused();
  await issueEmail.press("Shift+Tab");
  expect(await confirmation.evaluate((element) =>
    element.contains(document.activeElement)
  )).toBe(true);
  await page.keyboard.press("Tab");
  expect(await confirmation.evaluate((element) =>
    element.contains(document.activeElement)
  )).toBe(true);
  await issueEmail.fill(consoleInvitationEmail);
  await fillPasswordInput(issuePassword);
  await page.keyboard.press("Escape");
  await expect(confirmation).toHaveCount(0);
  await expect(inviteResearcher).toBeFocused();

  await inviteResearcher.press("Enter");
  confirmation = page.getByRole("dialog", { name: "Issue Invitation?" });
  await expect(confirmation.getByLabel("Current password")).toHaveValue("");
  await confirmation.getByRole("button", { name: "Cancel" }).click();
  await expect(confirmation).toHaveCount(0);
  await expect(inviteResearcher).toBeFocused();
  const cancelFocusPagination = page.getByRole("navigation", {
    name: "Invitations pagination",
  });
  await cancelFocusPagination.getByRole("button", { name: "Next" }).click();
  await expect(cancelFocusPagination).toContainText("Page 2");
  await expect(inviteResearcher).not.toBeFocused();
  await cancelFocusPagination.getByRole("button", { name: "Previous" }).click();
  await expect(cancelFocusPagination).toContainText("Page 1");
  await expect(inviteResearcher).toBeEnabled();

  await inviteResearcher.press("Enter");
  confirmation = page.getByRole("dialog", { name: "Issue Invitation?" });
  await confirmation.getByLabel("Target email").fill(consoleInvitationEmail);
  await confirmation.getByLabel("Target email").press("Tab");
  await expect(confirmation.getByLabel("Current password")).toBeFocused();
  await fillPasswordInput(confirmation.getByLabel("Current password"));
  await confirmation.getByLabel("Current password").press("Enter");
  await expect(confirmation).toHaveCount(0);
  await expect(page.getByRole("status").filter({
    hasText: `Invitation sent to ${consoleInvitationEmail}.`,
  })).toBeVisible();
  const consoleInvitationTable = page.getByRole("table", { name: "Invitations" });
  await expect(
    consoleInvitationTable.getByText(consoleInvitationEmail, { exact: true }),
  ).toBeVisible();
  await expect(inviteResearcher).toBeFocused();
  const oldConsoleToken = await emailToken(
    consoleInvitationEmail,
    "/accept-invitation#token=",
  );

  const reissueAction = page.getByRole("button", {
    name: `Reissue invitation for ${consoleInvitationEmail}`,
  });
  await reissueAction.click();
  const reissueConfirmation = page.getByRole("dialog", {
    name: "Reissue Invitation?",
  });
  await expect(reissueConfirmation).toContainText(consoleInvitationEmail);
  await expect(reissueConfirmation).toContainText(
    "The old link becomes invalid only after delivery succeeds.",
  );
  await fillPasswordInput(reissueConfirmation.getByLabel("Current password"));
  await reissueConfirmation.getByLabel("Current password").press("Enter");
  await expect(reissueConfirmation).toHaveCount(0);
  await expect(page.getByRole("status").filter({
    hasText: `Invitation reissued for ${consoleInvitationEmail}.`,
  })).toBeVisible();
  const reissuedRows = consoleInvitationTable.getByRole("row").filter({
    hasText: consoleInvitationEmail,
  });
  await expect(reissuedRows).toHaveCount(2);
  await expect(
    reissuedRows.filter({ hasText: "Terminal · Revoked" }).getByRole(
      "button",
      { name: `Reissue invitation for ${consoleInvitationEmail}` },
    ),
  ).toBeFocused();
  const newConsoleToken = await emailToken(
    consoleInvitationEmail,
    "/accept-invitation#token=",
  );
  expect(newConsoleToken).not.toBe(oldConsoleToken);
  const oldInspection = await page.request.post(
    "/api/auth/researcher-invitation/inspect",
    {
      data: { token: oldConsoleToken },
      headers: sameOriginHeaders(),
    },
  );
  expect(oldInspection.status()).toBe(400);
  const newInspection = await page.request.post(
    "/api/auth/researcher-invitation/inspect",
    {
      data: { token: newConsoleToken },
      headers: sameOriginHeaders(),
    },
  );
  expect(newInspection.status()).toBe(200);

  const proofRequests = operatorMutationRequests.filter((request) => {
    if (request.path !== "/api/auth/operator/proofs") return false;
    const body = JSON.parse(request.body) as { operation?: unknown };
    return body.operation === "invitation.issue" || body.operation === "invitation.reissue";
  });
  const invitationMutations = operatorMutationRequests.filter(
    (request) => request.path.startsWith("/api/auth/operator/invitations/"),
  );
  expect(proofRequests).toHaveLength(2);
  expect(proofRequests.every((request) => request.body.includes(browserPassword)))
    .toBe(true);
  expect(invitationMutations).toHaveLength(2);
  expect(invitationMutations.every((request) => !request.body.includes(browserPassword)))
    .toBe(true);
  expect(invitationMutations.map((request) => Object.keys(JSON.parse(request.body)).sort()))
    .toEqual([["email", "proof"], ["email", "proof"]]);

  const operatorSections = page.getByRole("navigation", {
    name: "Operator Console sections",
  });
  await operatorSections.getByRole("link", { name: "Data", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Data operations" })).toBeVisible();
  const marketRefreshSection = page.locator(
    'section[aria-labelledby="operator-market-refresh-heading"]',
  );
  await expect(marketRefreshSection.getByText(
    "Use the same free-form, timezone-aware inputs as the CLI.",
    { exact: true },
  )).toHaveCount(0);
  const marketAsOfDate = "2026-08-14";
  const marketAsOf = `${marketAsOfDate}T18:00:00+08:00`;
  const marketAsOfInput = marketRefreshSection.getByLabel("As-of", { exact: true });
  const marketKeyInput = marketRefreshSection.getByLabel("Idempotency key");
  await expect(marketAsOfInput).toHaveAttribute("type", "date");
  await marketAsOfInput.fill(marketAsOfDate);
  await expect(marketAsOfInput).toHaveValue(marketAsOfDate);
  await expect(marketKeyInput).toHaveValue(/^market-\d{8}T\d{6}Z$/);
  const reviewRefresh = marketRefreshSection.getByRole("button", {
    name: "Review Refresh",
  });
  const marketRefreshReceipt = page.locator(
    'section[aria-labelledby="operator-market-refresh-status"]',
  );
  const marketRefreshReconciliation = page.locator(
    'section[aria-labelledby="operator-market-refresh-reconciliation"]',
  );

  let releasePendingProof = (): void => {};
  let markPendingProofStarted = (): void => {};
  const pendingProofGate = new Promise<void>((resolve) => {
    releasePendingProof = resolve;
  });
  const pendingProofStarted = new Promise<void>((resolve) => {
    markPendingProofStarted = resolve;
  });
  const pendingKey = "browser-cancelled-market-refresh";
  const pendingProofHandler = async (route: Route): Promise<void> => {
    const body = route.request().postDataJSON() as {
      idempotency_key?: unknown;
      operation?: unknown;
    };
    if (
      body.operation === "data.refresh.market.submit"
      && body.idempotency_key === pendingKey
    ) {
      markPendingProofStarted();
      await pendingProofGate;
      try {
        await route.abort("aborted");
      } catch (error) {
        if (!(error instanceof Error) || !error.message.includes("already handled")) {
          throw error;
        }
      }
      return;
    }
    await route.continue();
  };
  await page.route("**/api/auth/operator/proofs", pendingProofHandler);
  await marketAsOfInput.fill(marketAsOfDate);
  await marketKeyInput.fill(pendingKey);
  await reviewRefresh.click();
  let marketConfirmation = page.getByRole("dialog", {
    name: "Submit Market Refresh?",
  });
  await fillPasswordInput(marketConfirmation.getByLabel("Current password"));
  await marketConfirmation.getByLabel("Current password").press("Enter");
  await pendingProofStarted;
  await expect(marketConfirmation.getByRole("button", { name: "Cancel" })).toBeEnabled();
  const pendingProofAborted = page.waitForEvent("requestfailed", (request) => {
    if (new URL(request.url()).pathname !== "/api/auth/operator/proofs") return false;
    const body = request.postDataJSON() as { idempotency_key?: unknown };
    return body.idempotency_key === pendingKey;
  });
  await page.keyboard.press("Escape");
  await expect(marketConfirmation).toHaveCount(0);
  await expect(reviewRefresh).toBeFocused();
  releasePendingProof();
  await pendingProofAborted;
  await page.unroute("**/api/auth/operator/proofs", pendingProofHandler);

  const marketKey = "\uFEFFbrowser-market-refresh-20260814";
  let releaseCoreResponse = (): void => {};
  let markCoreAccepted = (): void => {};
  let markCoreResponseDropped = (): void => {};
  const coreResponseGate = new Promise<void>((resolve) => {
    releaseCoreResponse = resolve;
  });
  const coreAccepted = new Promise<void>((resolve) => {
    markCoreAccepted = resolve;
  });
  const coreResponseDropped = new Promise<void>((resolve) => {
    markCoreResponseDropped = resolve;
  });
  const delayedCoreResponseHandler = async (route: Route): Promise<void> => {
    const request = route.request();
    if (request.method() !== "POST") {
      await route.continue();
      return;
    }
    const body = request.postDataJSON() as { idempotency_key?: unknown };
    if (body.idempotency_key !== marketKey) {
      await route.continue();
      return;
    }
    const response = await route.fetch();
    expect(response.status()).toBe(202);
    markCoreAccepted();
    await coreResponseGate;
    await route.abort("aborted");
    markCoreResponseDropped();
  };
  await page.route(
    "**/api/operator/data/refreshes/market**",
    delayedCoreResponseHandler,
  );
  await marketAsOfInput.fill(marketAsOfDate);
  await marketKeyInput.fill(marketKey);
  await reviewRefresh.focus();
  await reviewRefresh.press("Enter");
  marketConfirmation = page.getByRole("dialog", {
    name: "Submit Market Refresh?",
  });
  await expect(marketConfirmation).toContainText(marketAsOf);
  await expect(marketConfirmation).toContainText(marketKey);
  await expect(marketConfirmation).toContainText("durable FIFO");
  const marketPassword = marketConfirmation.getByLabel("Current password");
  await expect(marketPassword).toBeFocused();
  await fillPasswordInput(marketPassword);
  await marketPassword.press("Enter");
  await coreAccepted;
  await expect(marketConfirmation.getByRole("button", { name: "Cancel" })).toBeEnabled();
  await page.keyboard.press("Escape");
  await expect(marketConfirmation).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Confirming submission" })).toBeVisible();
  await expect(marketRefreshReconciliation.getByText(marketKey, { exact: true }))
    .toBeVisible();
  releaseCoreResponse();
  await coreResponseDropped;
  await page.unroute(
    "**/api/operator/data/refreshes/market**",
    delayedCoreResponseHandler,
  );
  await expect(page.getByRole("heading", { name: "Dataset published" }))
    .toBeVisible({ timeout: 30_000 });
  expect(marketStatusRequests).toContainEqual({
    asOf: marketAsOf,
    idempotencyKey: marketKey,
  });
  await expect(marketRefreshReceipt.getByText(marketKey, { exact: true })).toBeVisible();
  await expect(marketRefreshReceipt.getByText("Published", { exact: true })).toBeVisible();
  await expect(marketRefreshReceipt.getByText("2026-08-14", { exact: true }))
    .toBeVisible();
  await expect(reviewRefresh).toBeFocused();

  const conflictingMarketAsOfDate = "2026-08-12";
  const conflictingMarketAsOf = `${conflictingMarketAsOfDate}T18:00:00+08:00`;
  let releaseConflictResponse = (): void => {};
  let markConflictRejected = (): void => {};
  let markConflictResponseDropped = (): void => {};
  const conflictResponseGate = new Promise<void>((resolve) => {
    releaseConflictResponse = resolve;
  });
  const conflictRejected = new Promise<void>((resolve) => {
    markConflictRejected = resolve;
  });
  const conflictResponseDropped = new Promise<void>((resolve) => {
    markConflictResponseDropped = resolve;
  });
  const delayedConflictHandler = async (route: Route): Promise<void> => {
    const request = route.request();
    if (request.method() !== "POST") {
      await route.continue();
      return;
    }
    const body = request.postDataJSON() as {
      as_of?: unknown;
      idempotency_key?: unknown;
    };
    if (body.idempotency_key !== marketKey || body.as_of !== conflictingMarketAsOf) {
      await route.continue();
      return;
    }
    const response = await route.fetch();
    expect(response.status()).toBe(409);
    markConflictRejected();
    await conflictResponseGate;
    await route.abort("aborted");
    markConflictResponseDropped();
  };
  await page.route(
    "**/api/operator/data/refreshes/market**",
    delayedConflictHandler,
  );
  await marketAsOfInput.fill(conflictingMarketAsOfDate);
  await marketKeyInput.fill(marketKey);
  await reviewRefresh.click();
  marketConfirmation = page.getByRole("dialog", {
    name: "Submit Market Refresh?",
  });
  await fillPasswordInput(marketConfirmation.getByLabel("Current password"));
  await marketConfirmation.getByLabel("Current password").press("Enter");
  await conflictRejected;
  await page.keyboard.press("Escape");
  await expect(marketConfirmation).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Confirming submission" })).toBeVisible();
  releaseConflictResponse();
  await conflictResponseDropped;
  await page.unroute(
    "**/api/operator/data/refreshes/market**",
    delayedConflictHandler,
  );
  await expect(page.getByText(
    "This key is already bound to a different Market target.",
    { exact: true },
  )).toBeVisible({ timeout: 15_000 });
  await expect(marketKeyInput).toBeFocused();
  expect(marketStatusRequests).toContainEqual({
    asOf: conflictingMarketAsOf,
    idempotencyKey: marketKey,
  });

  const marketProofRequests = operatorMutationRequests.filter((request) => {
    if (request.path !== "/api/auth/operator/proofs") return false;
    const body = JSON.parse(request.body) as { operation?: unknown };
    return body.operation === "data.refresh.market.submit";
  });
  const marketMutations = operatorMutationRequests.filter(
    (request) => request.path === "/api/operator/data/refreshes/market",
  );
  expect(marketProofRequests).toHaveLength(3);
  const completedMarketProof = marketProofRequests.find((request) =>
    JSON.parse(request.body).idempotency_key === marketKey
  );
  expect(JSON.parse(completedMarketProof?.body ?? "{}")).toEqual({
    as_of: marketAsOf,
    idempotency_key: marketKey,
    operation: "data.refresh.market.submit",
    password: browserPassword,
  });
  expect(marketMutations).toHaveLength(2);
  const completedMarketMutation = marketMutations.find((request) =>
    JSON.parse(request.body).idempotency_key === marketKey
  );
  expect(JSON.parse(completedMarketMutation?.body ?? "{}")).toEqual({
    as_of: marketAsOf,
    idempotency_key: marketKey,
    proof: expect.any(String),
  });
  expect(marketMutations.every((request) => !request.body.includes(browserPassword)))
    .toBe(true);
  resetAuthRateLimits();

  const droppedAfterAcceptanceKey = "browser-dropped-after-acceptance";
  let markDroppedAfterAcceptance = (): void => {};
  const droppedAfterAcceptance = new Promise<void>((resolve) => {
    markDroppedAfterAcceptance = resolve;
  });
  const droppedAfterAcceptanceHandler = async (route: Route): Promise<void> => {
    const request = route.request();
    if (request.method() !== "POST") {
      await route.continue();
      return;
    }
    const body = request.postDataJSON() as { idempotency_key?: unknown };
    if (body.idempotency_key !== droppedAfterAcceptanceKey) {
      await route.continue();
      return;
    }
    const response = await route.fetch();
    expect(response.status()).toBe(202);
    await route.abort("aborted");
    markDroppedAfterAcceptance();
  };
  await page.route(
    "**/api/operator/data/refreshes/market**",
    droppedAfterAcceptanceHandler,
  );
  await marketAsOfInput.fill(marketAsOfDate);
  await marketKeyInput.fill(droppedAfterAcceptanceKey);
  await reviewRefresh.click();
  marketConfirmation = page.getByRole("dialog", {
    name: "Submit Market Refresh?",
  });
  await fillPasswordInput(marketConfirmation.getByLabel("Current password"));
  await marketConfirmation.getByLabel("Current password").press("Enter");
  await droppedAfterAcceptance;
  await expect(marketConfirmation).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Confirming submission" })).toBeVisible();
  await page.unroute(
    "**/api/operator/data/refreshes/market**",
    droppedAfterAcceptanceHandler,
  );
  await expect(page.getByRole("heading", { name: "Refresh completed" }))
    .toBeVisible({ timeout: 30_000 });
  expect(marketStatusRequests).toContainEqual({
    asOf: marketAsOf,
    idempotencyKey: droppedAfterAcceptanceKey,
  });
  await expect(marketRefreshReceipt.getByText(droppedAfterAcceptanceKey, { exact: true }))
    .toBeVisible();
  resetAuthRateLimits();

  const staleMarketKey = "browser-stale-response-a";
  const currentMarketKey = "browser-current-response-b";
  let releaseStaleResponse = (): void => {};
  let releaseCurrentResponse = (): void => {};
  let markStaleSubmissionStarted = (): void => {};
  let markCurrentSubmissionStarted = (): void => {};
  const staleResponseGate = new Promise<void>((resolve) => {
    releaseStaleResponse = resolve;
  });
  const currentResponseGate = new Promise<void>((resolve) => {
    releaseCurrentResponse = resolve;
  });
  const staleSubmissionStarted = new Promise<void>((resolve) => {
    markStaleSubmissionStarted = resolve;
  });
  const currentSubmissionStarted = new Promise<void>((resolve) => {
    markCurrentSubmissionStarted = resolve;
  });
  const terminalReceipt = (idempotencyKey: string) => ({
    as_of: "2026-08-11T10:00:00+00:00",
    attempt_count: 1,
    data_through_session: "2026-08-11",
    failure_code: null,
    idempotency_key: idempotencyKey,
    kind: "market",
    last_failure_code: null,
    last_refresh_at: "2026-08-11T10:01:00+00:00",
    outcome: "no_change",
    status: "succeeded",
  });
  const recoveredBeforePostKey = "browser-recovered-before-post-response";
  let releaseRecoveredPostResponse = (): void => {};
  let markRecoveredPostStarted = (): void => {};
  const recoveredPostResponseGate = new Promise<void>((resolve) => {
    releaseRecoveredPostResponse = resolve;
  });
  const recoveredPostStarted = new Promise<void>((resolve) => {
    markRecoveredPostStarted = resolve;
  });
  const recoveredBeforePostHandler = async (route: Route): Promise<void> => {
    const request = route.request();
    const url = new URL(request.url());
    if (
      request.method() === "GET"
      && url.pathname === "/api/operator/data/refreshes/market"
      && url.searchParams.get("idempotency_key") === recoveredBeforePostKey
    ) {
      await route.fulfill({
        body: JSON.stringify(terminalReceipt(recoveredBeforePostKey)),
        contentType: "application/json",
        status: 200,
      });
      return;
    }
    if (request.method() !== "POST") {
      await route.continue();
      return;
    }
    const body = request.postDataJSON() as { idempotency_key?: unknown };
    if (body.idempotency_key !== recoveredBeforePostKey) {
      await route.continue();
      return;
    }
    markRecoveredPostStarted();
    await recoveredPostResponseGate;
    await route.fulfill({
      body: JSON.stringify({
        as_of: "2026-08-11T10:00:00+00:00",
        attempt_count: 0,
        data_through_session: null,
        failure_code: null,
        idempotency_key: recoveredBeforePostKey,
        kind: "market",
        last_failure_code: null,
        last_refresh_at: null,
        outcome: null,
        status: "accepted",
      }),
      contentType: "application/json",
      status: 202,
    });
  };
  await page.route(
    "**/api/operator/data/refreshes/market**",
    recoveredBeforePostHandler,
  );
  await marketAsOfInput.fill(marketAsOfDate);
  await marketKeyInput.fill(recoveredBeforePostKey);
  await reviewRefresh.click();
  marketConfirmation = page.getByRole("dialog", {
    name: "Submit Market Refresh?",
  });
  await fillPasswordInput(marketConfirmation.getByLabel("Current password"));
  await marketConfirmation.getByLabel("Current password").press("Enter");
  await recoveredPostStarted;
  await page.keyboard.press("Escape");
  await expect(page.getByRole("heading", { name: "Confirming submission" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Refresh completed" }))
    .toBeVisible({ timeout: 15_000 });
  await expect(marketRefreshReceipt.getByText("No change", { exact: true })).toBeVisible();
  const recoveredLatePostResponse = page.waitForResponse((response) => {
    const request = response.request();
    if (
      request.method() !== "POST"
      || new URL(request.url()).pathname !== "/api/operator/data/refreshes/market"
    ) return false;
    const body = request.postDataJSON() as { idempotency_key?: unknown };
    return body.idempotency_key === recoveredBeforePostKey;
  });
  releaseRecoveredPostResponse();
  await recoveredLatePostResponse;
  await settleReactUpdates(page);
  await expect(page.getByRole("heading", { name: "Refresh completed" })).toBeVisible();
  await expect(marketRefreshReceipt.getByText(recoveredBeforePostKey, { exact: true }))
    .toBeVisible();
  await expect(marketRefreshReceipt.getByText("No change", { exact: true })).toBeVisible();
  await page.unroute(
    "**/api/operator/data/refreshes/market**",
    recoveredBeforePostHandler,
  );
  resetAuthRateLimits();

  const submissionRaceHandler = async (route: Route): Promise<void> => {
    const request = route.request();
    if (request.method() !== "POST") {
      await route.continue();
      return;
    }
    const body = request.postDataJSON() as { idempotency_key?: unknown };
    if (body.idempotency_key === staleMarketKey) {
      markStaleSubmissionStarted();
      await staleResponseGate;
      await route.fulfill({
        body: JSON.stringify(terminalReceipt(staleMarketKey)),
        contentType: "application/json",
        status: 202,
      });
      return;
    }
    if (body.idempotency_key === currentMarketKey) {
      markCurrentSubmissionStarted();
      await currentResponseGate;
      await route.fulfill({
        body: JSON.stringify(terminalReceipt(currentMarketKey)),
        contentType: "application/json",
        status: 202,
      });
      return;
    }
    await route.continue();
  };
  await page.route(
    "**/api/operator/data/refreshes/market**",
    submissionRaceHandler,
  );
  await marketAsOfInput.fill(marketAsOfDate);
  await marketKeyInput.fill(staleMarketKey);
  await reviewRefresh.click();
  marketConfirmation = page.getByRole("dialog", {
    name: "Submit Market Refresh?",
  });
  await fillPasswordInput(marketConfirmation.getByLabel("Current password"));
  await marketConfirmation.getByLabel("Current password").press("Enter");
  await staleSubmissionStarted;
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "Stop checking" }).click();

  await marketKeyInput.fill(currentMarketKey);
  await reviewRefresh.click();
  const currentMarketConfirmation = page.getByRole("dialog", {
    name: "Submit Market Refresh?",
  });
  await fillPasswordInput(currentMarketConfirmation.getByLabel("Current password"));
  await currentMarketConfirmation.getByLabel("Current password").press("Enter");
  await currentSubmissionStarted;
  const staleBrowserResponse = page.waitForResponse((response) => {
    const request = response.request();
    if (
      request.method() !== "POST"
      || new URL(request.url()).pathname !== "/api/operator/data/refreshes/market"
    ) return false;
    const body = request.postDataJSON() as { idempotency_key?: unknown };
    return body.idempotency_key === staleMarketKey;
  });
  releaseStaleResponse();
  await staleBrowserResponse;
  await settleReactUpdates(page);
  await expect(currentMarketConfirmation).toBeVisible();
  await expect(currentMarketConfirmation).toContainText(currentMarketKey);
  await expect(marketRefreshReceipt.getByText(staleMarketKey, { exact: true })).toHaveCount(0);

  const currentBrowserResponse = page.waitForResponse((response) => {
    const request = response.request();
    if (
      request.method() !== "POST"
      || new URL(request.url()).pathname !== "/api/operator/data/refreshes/market"
    ) return false;
    const body = request.postDataJSON() as { idempotency_key?: unknown };
    return body.idempotency_key === currentMarketKey;
  });
  releaseCurrentResponse();
  await currentBrowserResponse;
  await expect(currentMarketConfirmation).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Refresh completed" })).toBeVisible();
  await expect(marketRefreshReceipt.getByText(currentMarketKey, { exact: true })).toBeVisible();
  await page.unroute(
    "**/api/operator/data/refreshes/market**",
    submissionRaceHandler,
  );
  resetAuthRateLimits();

  const polledMarketKey = "browser-polled-response-a";
  const newerMarketKey = "browser-newer-response-b";
  let releasePolledRequest = (): void => {};
  let markPolledRequestStarted = (): void => {};
  let markPolledRequestSettled = (): void => {};
  const polledRequestGate = new Promise<void>((resolve) => {
    releasePolledRequest = resolve;
  });
  const polledRequestStarted = new Promise<void>((resolve) => {
    markPolledRequestStarted = resolve;
  });
  const polledRequestSettled = new Promise<void>((resolve) => {
    markPolledRequestSettled = resolve;
  });
  const acceptedReceipt = {
    as_of: "2026-08-11T10:00:00+00:00",
    attempt_count: 0,
    data_through_session: null,
    failure_code: null,
    idempotency_key: polledMarketKey,
    kind: "market",
    last_failure_code: null,
    last_refresh_at: null,
    outcome: null,
    status: "accepted",
  };
  const pollingRaceHandler = async (route: Route): Promise<void> => {
    const request = route.request();
    const url = new URL(request.url());
    if (
      request.method() === "GET"
      && url.pathname === "/api/operator/data/refreshes/market"
      && url.searchParams.get("idempotency_key") === polledMarketKey
    ) {
      markPolledRequestStarted();
      await polledRequestGate;
      try {
        await route.fulfill({
          body: JSON.stringify(terminalReceipt(polledMarketKey)),
          contentType: "application/json",
          status: 200,
        });
      } catch (error) {
        if (!(error instanceof Error) || !error.message.includes("already handled")) {
          throw error;
        }
      } finally {
        markPolledRequestSettled();
      }
      return;
    }
    if (request.method() !== "POST") {
      await route.continue();
      return;
    }
    const body = request.postDataJSON() as { idempotency_key?: unknown };
    if (body.idempotency_key === polledMarketKey) {
      await route.fulfill({
        body: JSON.stringify(acceptedReceipt),
        contentType: "application/json",
        status: 202,
      });
      return;
    }
    if (body.idempotency_key === newerMarketKey) {
      await route.fulfill({
        body: JSON.stringify(terminalReceipt(newerMarketKey)),
        contentType: "application/json",
        status: 202,
      });
      releasePolledRequest();
      return;
    }
    await route.continue();
  };
  await page.route(
    "**/api/operator/data/refreshes/market**",
    pollingRaceHandler,
  );
  await marketAsOfInput.fill(marketAsOfDate);
  await marketKeyInput.fill(polledMarketKey);
  await reviewRefresh.click();
  marketConfirmation = page.getByRole("dialog", {
    name: "Submit Market Refresh?",
  });
  await fillPasswordInput(marketConfirmation.getByLabel("Current password"));
  await marketConfirmation.getByLabel("Current password").press("Enter");
  await expect(page.getByRole("heading", { name: "Refresh accepted" })).toBeVisible();
  await polledRequestStarted;

  await marketKeyInput.fill(newerMarketKey);
  await reviewRefresh.click();
  const newerMarketConfirmation = page.getByRole("dialog", {
    name: "Submit Market Refresh?",
  });
  await expect(marketRefreshReceipt.getByText(polledMarketKey, { exact: true })).toBeVisible();
  await fillPasswordInput(newerMarketConfirmation.getByLabel("Current password"));
  await newerMarketConfirmation.getByLabel("Current password").press("Enter");
  await expect(newerMarketConfirmation).toHaveCount(0);
  await polledRequestSettled;
  await settleReactUpdates(page);
  await expect(page.getByRole("heading", { name: "Refresh completed" })).toBeVisible();
  await expect(marketRefreshReceipt.getByText(newerMarketKey, { exact: true })).toBeVisible();
  await expect(marketRefreshReceipt.getByText(polledMarketKey, { exact: true })).toHaveCount(0);
  await page.unroute(
    "**/api/operator/data/refreshes/market**",
    pollingRaceHandler,
  );
  resetAuthRateLimits();

  const financialRefreshSection = page.locator(
    'section[aria-labelledby="operator-financial-refresh-heading"]',
  );
  const financialTarget = financialRefreshSection.getByLabel(
    "Observation-through Research Session",
  );
  const financialKeyInput = financialRefreshSection.getByLabel("Idempotency key");
  const financialReview = financialRefreshSection.getByRole("button", {
    name: "Review Refresh",
  });
  await expect(financialTarget).toHaveAttribute("type", "date");
  await expect(financialTarget).toHaveAttribute("required", "");
  await expect(financialKeyInput).toHaveValue(/^financial-\d{8}T\d{6}Z$/);
  const financialTargetSession = "2026-08-14";
  const financialKey = "browser-financial-refresh-20260814";
  await financialReview.click();
  expect(
    await financialTarget.evaluate(
      (input) => (input as HTMLInputElement).validity.valueMissing,
    ),
  ).toBe(true);
  await expect(financialTarget).toBeFocused();
  await expect(page.getByRole("dialog", { name: "Submit Financial Refresh?" }))
    .toHaveCount(0);
  await financialTarget.fill(financialTargetSession);
  await financialKeyInput.fill(financialKey);
  await financialReview.click();
  const financialConfirmation = page.getByRole("dialog", {
    name: "Submit Financial Refresh?",
  });
  await expect(financialConfirmation).toContainText("Financial");
  await expect(financialConfirmation).toContainText(financialTargetSession);
  await expect(financialConfirmation).toContainText(financialKey);
  await expect(financialConfirmation).toContainText("shared durable FIFO");
  await fillPasswordInput(financialConfirmation.getByLabel("Current password"));
  await financialConfirmation.getByLabel("Current password").press("Enter");
  await expect(financialConfirmation).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Financial Refresh accepted" }))
    .toBeVisible({ timeout: 10_000 });
  const financialReceipt = page.locator("section.operator-refresh-receipt").filter({
    hasText: financialKey,
  });
  await expect(financialReceipt.getByText(financialTargetSession, { exact: true }))
    .toBeVisible();
  await expect(page.getByRole("heading", {
    name: "Financial data published with unresolved coverage",
  })).toBeVisible({ timeout: 30_000 });
  await expect(financialReceipt.getByText("Degraded success", { exact: true }))
    .toBeVisible();
  await expect(financialReceipt).toContainText(
    "A usable Dataset was published, but discovery gaps remain",
  );
  await expect(financialReceipt.locator("dl div").filter({ hasText: "Discovery gaps" }))
    .toHaveText("Discovery gaps1");
  expect(financialStatusRequests).toContainEqual({
    idempotencyKey: financialKey,
    observationThroughSession: financialTargetSession,
  });
  const financialProof = operatorMutationRequests.find((request) => {
    if (request.path !== "/api/auth/operator/proofs") return false;
    const body = JSON.parse(request.body) as { operation?: unknown };
    return body.operation === "data.refresh.financial.submit";
  });
  expect(JSON.parse(financialProof?.body ?? "{}")).toEqual({
    idempotency_key: financialKey,
    observation_through_session: financialTargetSession,
    operation: "data.refresh.financial.submit",
    password: browserPassword,
  });
  const financialMutation = operatorMutationRequests.find(
    (request) => request.path === "/api/operator/data/refreshes/financial",
  );
  expect(JSON.parse(financialMutation?.body ?? "{}")).toEqual({
    idempotency_key: financialKey,
    observation_through_session: financialTargetSession,
    proof: expect.any(String),
  });
  expect(financialMutation?.body).not.toContain(browserPassword);
  resetAuthRateLimits();

  const industryRefreshSection = page.locator(
    'section[aria-labelledby="operator-industry-refresh-heading"]',
  );
  const industryTarget = industryRefreshSection.getByLabel(
    "Observation-through Research Session",
  );
  const industryKeyInput = industryRefreshSection.getByLabel("Idempotency key");
  const industryReview = industryRefreshSection.getByRole("button", {
    name: "Review Refresh",
  });
  await expect(industryTarget).toHaveAttribute("type", "date");
  await expect(industryTarget).toHaveAttribute("required", "");
  await expect(industryKeyInput).toHaveValue(/^industry-\d{8}T\d{6}Z$/);
  const industryTargetSession = "2026-08-14";
  const industryKey = "browser-industry-refresh-20260814";
  await industryReview.click();
  expect(
    await industryTarget.evaluate(
      (input) => (input as HTMLInputElement).validity.valueMissing,
    ),
  ).toBe(true);
  await expect(industryTarget).toBeFocused();
  await expect(page.getByRole("dialog", { name: "Submit Industry Refresh?" }))
    .toHaveCount(0);
  await industryTarget.fill(industryTargetSession);
  await industryKeyInput.fill(industryKey);
  await industryReview.click();
  let industryConfirmation = page.getByRole("dialog", {
    name: "Submit Industry Refresh?",
  });
  await expect(industryConfirmation).toContainText("Industry");
  await expect(industryConfirmation).toContainText(industryTargetSession);
  await expect(industryConfirmation).toContainText(industryKey);
  await expect(industryConfirmation).toContainText("shared durable FIFO");
  const industryPassword = industryConfirmation.getByLabel("Current password");
  await expect(industryPassword).toBeFocused();
  await fillPasswordInput(industryPassword);
  await industryPassword.press("Enter");
  await expect(industryConfirmation).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Industry Refresh accepted" }))
    .toBeVisible({ timeout: 10_000 });
  const industryReceipt = page.locator("section.operator-refresh-receipt").filter({
    hasText: industryKey,
  });
  await expect(page.getByRole("heading", { name: "Industry data published" }))
    .toBeVisible({ timeout: 30_000 });
  await expect(industryReceipt.getByText("Published", { exact: true })).toBeVisible();
  await expect(
    industryReceipt
      .locator("dt", { hasText: /^Observation through$/ })
      .locator("..")
      .locator("dd"),
  ).toHaveText(industryTargetSession);
  expect(industryStatusRequests).toContainEqual({
    idempotencyKey: industryKey,
    observationThroughSession: industryTargetSession,
  });
  const industryProof = operatorMutationRequests.find((request) => {
    if (request.path !== "/api/auth/operator/proofs") return false;
    const body = JSON.parse(request.body) as { operation?: unknown };
    return body.operation === "data.refresh.industry.submit";
  });
  expect(JSON.parse(industryProof?.body ?? "{}")).toEqual({
    idempotency_key: industryKey,
    observation_through_session: industryTargetSession,
    operation: "data.refresh.industry.submit",
    password: browserPassword,
  });
  const industryMutation = operatorMutationRequests.find(
    (request) => request.path === "/api/operator/data/refreshes/industry",
  );
  expect(JSON.parse(industryMutation?.body ?? "{}")).toEqual({
    idempotency_key: industryKey,
    observation_through_session: industryTargetSession,
    proof: expect.any(String),
  });
  expect(industryMutation?.body).not.toContain(browserPassword);
  resetAuthRateLimits();

  const industryNoChangeKey = "browser-industry-no-change-20260814";
  await industryKeyInput.fill(industryNoChangeKey);
  await industryReview.click();
  industryConfirmation = page.getByRole("dialog", {
    name: "Submit Industry Refresh?",
  });
  await fillPasswordInput(industryConfirmation.getByLabel("Current password"));
  await industryConfirmation.getByLabel("Current password").press("Enter");
  await expect(industryConfirmation).toHaveCount(0);
  const industryNoChangeReceipt = page.locator("section.operator-refresh-receipt").filter({
    hasText: industryNoChangeKey,
  });
  await expect(page.getByRole("heading", { name: "Industry Refresh completed" }))
    .toBeVisible({ timeout: 30_000 });
  await expect(industryNoChangeReceipt.getByText("No change", { exact: true }))
    .toBeVisible();
  resetAuthRateLimits();

  const industryRejectedKey = "browser-industry-business-rejected";
  const industryRejectedHandler = async (route: Route): Promise<void> => {
    const request = route.request();
    if (request.method() !== "POST") {
      await route.continue();
      return;
    }
    const body = request.postDataJSON() as { idempotency_key?: unknown };
    if (body.idempotency_key !== industryRejectedKey) {
      await route.continue();
      return;
    }
    await route.fulfill({
      body: JSON.stringify({
        attempt_count: 1,
        data_through_session: null,
        failure_code: "OVERLAPPING_PRIMARY_INDUSTRY_CLASSIFICATION",
        idempotency_key: industryRejectedKey,
        kind: "industry",
        last_failure_code: "OVERLAPPING_PRIMARY_INDUSTRY_CLASSIFICATION",
        last_refresh_at: null,
        observation_through_session: industryTargetSession,
        outcome: "business_rejected",
        status: "failed",
      }),
      contentType: "application/json",
      status: 202,
    });
  };
  await page.route(
    "**/api/operator/data/refreshes/industry",
    industryRejectedHandler,
  );
  await industryKeyInput.fill(industryRejectedKey);
  await industryReview.click();
  industryConfirmation = page.getByRole("dialog", {
    name: "Submit Industry Refresh?",
  });
  await fillPasswordInput(industryConfirmation.getByLabel("Current password"));
  await industryConfirmation.getByLabel("Current password").press("Enter");
  await expect(industryConfirmation).toHaveCount(0);
  const industryRejectedReceipt = page.locator("section.operator-refresh-receipt").filter({
    hasText: industryRejectedKey,
  });
  await expect(page.getByRole("heading", { name: "Industry Refresh rejected" }))
    .toBeVisible();
  await expect(industryRejectedReceipt.getByText("Rejected", { exact: true }))
    .toBeVisible();
  await expect(industryRejectedReceipt).toContainText("will not retry");
  await page.unroute(
    "**/api/operator/data/refreshes/industry",
    industryRejectedHandler,
  );
  resetAuthRateLimits();

  const droppedFinancialKey = "browser-financial-dropped-after-acceptance";
  let markFinancialResponseDropped = (): void => {};
  const financialResponseDropped = new Promise<void>((resolve) => {
    markFinancialResponseDropped = resolve;
  });
  const droppedFinancialResponseHandler = async (route: Route): Promise<void> => {
    const request = route.request();
    if (request.method() !== "POST") {
      await route.continue();
      return;
    }
    const body = request.postDataJSON() as { idempotency_key?: unknown };
    if (body.idempotency_key !== droppedFinancialKey) {
      await route.continue();
      return;
    }
    const response = await route.fetch();
    expect(response.status()).toBe(202);
    await route.abort("aborted");
    markFinancialResponseDropped();
  };
  await page.route(
    "**/api/operator/data/refreshes/financial**",
    droppedFinancialResponseHandler,
  );
  await financialTarget.fill(financialTargetSession);
  await financialKeyInput.fill(droppedFinancialKey);
  await financialReview.click();
  let recoverableFinancialConfirmation = page.getByRole("dialog", {
    name: "Submit Financial Refresh?",
  });
  await fillPasswordInput(
    recoverableFinancialConfirmation.getByLabel("Current password"),
  );
  await recoverableFinancialConfirmation.getByLabel("Current password").press("Enter");
  await financialResponseDropped;
  await expect(recoverableFinancialConfirmation).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Confirming submission" })).toBeVisible();
  await page.unroute(
    "**/api/operator/data/refreshes/financial**",
    droppedFinancialResponseHandler,
  );
  const recoveredFinancialReceipt = page.locator("section.operator-refresh-receipt").filter({
    hasText: droppedFinancialKey,
  });
  await expect(page.getByRole("heading", {
    name: "Financial data published with unresolved coverage",
  })).toBeVisible({ timeout: 30_000 });
  await expect(recoveredFinancialReceipt.getByText(
    financialTargetSession,
    { exact: true },
  )).toBeVisible();
  await expect(recoveredFinancialReceipt.getByText("Degraded success", { exact: true }))
    .toBeVisible();
  expect(financialStatusRequests).toContainEqual({
    idempotencyKey: droppedFinancialKey,
    observationThroughSession: financialTargetSession,
  });
  resetAuthRateLimits();

  const knownFailureKey = "browser-financial-known-failure";
  let releaseKnownFailure = (): void => {};
  let markKnownFailureStarted = (): void => {};
  const knownFailureGate = new Promise<void>((resolve) => {
    releaseKnownFailure = resolve;
  });
  const knownFailureStarted = new Promise<void>((resolve) => {
    markKnownFailureStarted = resolve;
  });
  const knownFailureHandler = async (route: Route): Promise<void> => {
    const request = route.request();
    if (request.method() !== "POST") {
      await route.continue();
      return;
    }
    const body = request.postDataJSON() as { idempotency_key?: unknown };
    if (body.idempotency_key !== knownFailureKey) {
      await route.continue();
      return;
    }
    markKnownFailureStarted();
    await knownFailureGate;
    await route.fulfill({
      body: JSON.stringify({ code: "DATA_NOT_READY" }),
      contentType: "application/json",
      status: 409,
    });
  };
  await page.route(
    "**/api/operator/data/refreshes/financial",
    knownFailureHandler,
  );
  await financialTarget.fill(financialTargetSession);
  await financialKeyInput.fill(knownFailureKey);
  await financialReview.click();
  recoverableFinancialConfirmation = page.getByRole("dialog", {
    name: "Submit Financial Refresh?",
  });
  await fillPasswordInput(recoverableFinancialConfirmation.getByLabel("Current password"));
  await recoverableFinancialConfirmation.getByLabel("Current password").press("Enter");
  await knownFailureStarted;
  await page.keyboard.press("Escape");
  await expect(page.getByRole("heading", { name: "Confirming submission" })).toBeVisible();
  // Restoring focus belongs to the committed UI, not the next animation frame.
  await page.clock.pauseAt(new Date());
  try {
    releaseKnownFailure();
    await expect(page.getByRole("alert").filter({
      hasText: "The current Dataset is not ready for a Financial Refresh.",
    })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Confirming submission" })).toHaveCount(0);
    await expect(financialReview).toBeFocused();
  } finally {
    await page.clock.resume();
  }
  await page.unroute(
    "**/api/operator/data/refreshes/financial",
    knownFailureHandler,
  );
  resetAuthRateLimits();

  const retryKey = "browser-financial-retry-exact";
  let releaseUncertainSubmission = (): void => {};
  let markUncertainSubmissionStarted = (): void => {};
  let markMissingReceiptObserved = (): void => {};
  const uncertainSubmissionGate = new Promise<void>((resolve) => {
    releaseUncertainSubmission = resolve;
  });
  const uncertainSubmissionStarted = new Promise<void>((resolve) => {
    markUncertainSubmissionStarted = resolve;
  });
  const missingReceiptObserved = new Promise<void>((resolve) => {
    markMissingReceiptObserved = resolve;
  });
  const retryHandler = async (route: Route): Promise<void> => {
    const request = route.request();
    const url = new URL(request.url());
    if (
      request.method() === "GET"
      && url.searchParams.get("idempotency_key") === retryKey
    ) {
      markMissingReceiptObserved();
      await route.fulfill({
        body: JSON.stringify({ code: "REFRESH_NOT_FOUND" }),
        contentType: "application/json",
        status: 404,
      });
      return;
    }
    if (request.method() !== "POST") {
      await route.continue();
      return;
    }
    const body = request.postDataJSON() as { idempotency_key?: unknown };
    if (body.idempotency_key !== retryKey) {
      await route.continue();
      return;
    }
    markUncertainSubmissionStarted();
    await uncertainSubmissionGate;
    await route.fulfill({
      body: JSON.stringify({ code: "DATA_REFRESH_UNAVAILABLE" }),
      contentType: "application/json",
      status: 503,
    });
  };
  await page.route("**/api/operator/data/refreshes/financial**", retryHandler);
  await financialKeyInput.fill(retryKey);
  await financialReview.click();
  recoverableFinancialConfirmation = page.getByRole("dialog", {
    name: "Submit Financial Refresh?",
  });
  await fillPasswordInput(recoverableFinancialConfirmation.getByLabel("Current password"));
  await recoverableFinancialConfirmation.getByLabel("Current password").press("Enter");
  await uncertainSubmissionStarted;
  await page.keyboard.press("Escape");
  releaseUncertainSubmission();
  await missingReceiptObserved;
  const retryExactRequest = page.getByRole("button", { name: "Retry exact request" });
  await expect(page.getByRole("alert").filter({
    hasText: "Receipt unavailable; retrying while visible.",
  })).toBeVisible();
  await retryExactRequest.click();
  recoverableFinancialConfirmation = page.getByRole("dialog", {
    name: "Submit Financial Refresh?",
  });
  await expect(recoverableFinancialConfirmation).toContainText(retryKey);
  await expect(recoverableFinancialConfirmation).toContainText(financialTargetSession);
  await recoverableFinancialConfirmation.getByRole("button", { name: "Cancel" }).click();
  await expect(financialReview).toBeFocused();
  await page.unroute("**/api/operator/data/refreshes/financial**", retryHandler);
  resetAuthRateLimits();

  const stopKey = "browser-financial-stop-checking";
  let markStopSubmissionStarted = (): void => {};
  let releaseStopSubmission = (): void => {};
  const stopSubmissionStarted = new Promise<void>((resolve) => {
    markStopSubmissionStarted = resolve;
  });
  const stopSubmissionGate = new Promise<void>((resolve) => {
    releaseStopSubmission = resolve;
  });
  const stopHandler = async (route: Route): Promise<void> => {
    const request = route.request();
    if (request.method() !== "POST") {
      await route.continue();
      return;
    }
    const body = request.postDataJSON() as { idempotency_key?: unknown };
    if (body.idempotency_key !== stopKey) {
      await route.continue();
      return;
    }
    markStopSubmissionStarted();
    await stopSubmissionGate;
    await route.fulfill({
      body: JSON.stringify({ code: "DATA_REFRESH_UNAVAILABLE" }),
      contentType: "application/json",
      status: 503,
    });
  };
  await page.route("**/api/operator/data/refreshes/financial", stopHandler);
  await financialKeyInput.fill(stopKey);
  await financialReview.click();
  recoverableFinancialConfirmation = page.getByRole("dialog", {
    name: "Submit Financial Refresh?",
  });
  await fillPasswordInput(recoverableFinancialConfirmation.getByLabel("Current password"));
  await recoverableFinancialConfirmation.getByLabel("Current password").press("Enter");
  await stopSubmissionStarted;
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "Stop checking" }).click();
  await expect(page.getByRole("alert").filter({
    hasText: "Automatic receipt checks stopped.",
  })).toBeVisible();
  await expect(financialReview).toBeFocused();
  releaseStopSubmission();
  await settleReactUpdates(page);
  await expect(page.getByRole("heading", { name: "Confirming submission" })).toHaveCount(0);
  await page.unroute("**/api/operator/data/refreshes/financial", stopHandler);
  resetAuthRateLimits();

  const capabilityLossKey = "browser-financial-capability-loss";
  const capabilityLossHandler = async (route: Route): Promise<void> => {
    const request = route.request();
    if (request.method() !== "POST") {
      await route.continue();
      return;
    }
    const body = request.postDataJSON() as { idempotency_key?: unknown };
    if (body.idempotency_key !== capabilityLossKey) {
      await route.continue();
      return;
    }
    await route.fulfill({
      body: JSON.stringify({
        progress: null,
        accepted_instrument_count: null,
        attempt_count: 0,
        checked_no_structured_change_count: null,
        data_through_session: null,
        discovery_gap_count: null,
        failed_instrument_count: null,
        failure_code: null,
        financial_complete_through_session: null,
        idempotency_key: capabilityLossKey,
        kind: "financial",
        last_failure_code: null,
        last_refresh_at: null,
        matched_trigger_count: null,
        observation_through_session: financialTargetSession,
        outcome: null,
        pending_instrument_count: null,
        status: "accepted",
      }),
      contentType: "application/json",
      status: 202,
    });
  };
  await page.route(
    "**/api/operator/data/refreshes/financial",
    capabilityLossHandler,
  );
  await financialKeyInput.fill(capabilityLossKey);
  await financialReview.click();
  const capabilityLossConfirmation = page.getByRole("dialog", {
    name: "Submit Financial Refresh?",
  });
  await fillPasswordInput(capabilityLossConfirmation.getByLabel("Current password"));
  await capabilityLossConfirmation.getByLabel("Current password").press("Enter");
  await expect(page.getByRole("heading", { name: "Financial Refresh accepted" }))
    .toBeVisible();
  await restoreResearcherSession(page, ordinary);
  await page.evaluate(() => document.dispatchEvent(new Event("visibilitychange")));
  await expect(page.getByRole("heading", { name: "Not found" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Data operations" })).toHaveCount(0);
  await page.unroute(
    "**/api/operator/data/refreshes/financial",
    capabilityLossHandler,
  );
  await restoreResearcherSession(page, operator);
  await page.goto("/operator/data");
  await expect(page.getByRole("heading", { name: "Data operations" })).toBeVisible();

  const datasetStatus = page.locator(
    'section[aria-labelledby="operator-dataset-status-heading"]',
  );
  await expect(datasetStatus.getByRole("heading", {
    name: "Current research Dataset",
  })).toBeVisible();
  await expect(
    datasetStatus.locator("dl > div").filter({ hasText: "Data identity" }).locator("code"),
  ).toHaveText(/^[0-9a-f]{64}$/);
  await expect(datasetStatus.getByText("Market ready", { exact: true })).toBeVisible();
  await expect(datasetStatus.getByText("Benchmark ready", { exact: true })).toBeVisible();
  await expect(datasetStatus.getByText(/^Financial ready/)).toBeVisible();
  await expect(datasetStatus.getByText("Industry ready", { exact: true })).toBeVisible();

  const latestRefreshes = datasetStatus.getByRole("table", {
    name: "Latest Data Refresh operations",
  });
  for (const kind of ["Market Refresh", "Financial Refresh", "Industry Refresh"]) {
    await expect(latestRefreshes.getByRole("row").filter({ hasText: kind })).toHaveCount(1);
  }
  const operationHistory = datasetStatus.getByRole("table", {
    name: "Data Refresh operation history",
  });
  await expect(datasetStatus.getByText(
    "Newest first · 50 receipts per page · terminal receipts retained 180 days",
    { exact: true },
  )).toHaveCount(0);
  for (const key of [marketKey, financialKey, industryKey]) {
    await expect(operationHistory.getByText(key, { exact: true })).toBeVisible();
  }

  const marketHistoryRow = operationHistory.getByRole("row").filter({ hasText: marketKey });
  const marketDetails = marketHistoryRow.getByRole("button", { name: `View details for ${marketKey}` });
  await marketDetails.focus();
  await marketDetails.press("Enter");
  const operationDrawer = page.getByRole("dialog", { name: "Operation details" });
  await expect(operationDrawer).toBeVisible();
  await expect(operationDrawer).toContainText(marketKey);
  await expect(operationDrawer).toContainText("Last heartbeat");
  await expect(operationDrawer).not.toContainText(/manifest|owner token|object path|raw response/i);
  await expect(operationDrawer.getByRole("button", { name: "Close operation details" }))
    .toBeFocused();
  await page.keyboard.press("Tab");
  expect(await operationDrawer.evaluate((element) => element.contains(document.activeElement)))
    .toBe(true);
  await page.keyboard.press("Shift+Tab");
  expect(await operationDrawer.evaluate((element) => element.contains(document.activeElement)))
    .toBe(true);
  await page.keyboard.press("Escape");
  await expect(operationDrawer).toHaveCount(0);
  await expect(marketDetails).toBeFocused();

  const originalViewport = page.viewportSize();
  await page.setViewportSize({ width: 640, height: 900 });
  expect(await operationHistory.evaluate((element) => getComputedStyle(element).display))
    .toBe("block");
  expect(await marketHistoryRow.evaluate((element) => getComputedStyle(element).display))
    .toBe("grid");
  expect(await marketHistoryRow.locator('[data-label="State"]').evaluate(
    (element) => getComputedStyle(element, "::before").content,
  )).toBe('"State"');
  if (originalViewport !== null) await page.setViewportSize(originalViewport);

  const terminalStatusResponse = await page.request.get("/api/operator/data/status");
  expect(terminalStatusResponse.status()).toBe(200);
  const terminalStatus = await terminalStatusResponse.json() as {
    head: Record<string, unknown>;
    worker: { available: boolean; last_heartbeat_at: string | null };
    latest_by_kind: Array<Record<string, unknown>>;
    operations: Array<Record<string, unknown>>;
    next_cursor: string | null;
  };
  expect(Object.keys(terminalStatus).sort()).toEqual([
    "head",
    "latest_by_kind",
    "next_cursor",
    "operations",
    "worker",
  ]);
  expect(JSON.stringify(terminalStatus)).not.toMatch(
    /generation_manifest|owner_token|lease_expires_at|fingerprint|object_path/i,
  );
  const terminalMarket = terminalStatus.latest_by_kind.find(
    (operation) => operation.kind === "market",
  );
  expect(terminalMarket).toBeDefined();
  const acceptedMarket = {
    ...terminalMarket,
    attempt_count: 0,
    data_through_session: null,
    failure_code: null,
    finished_at: null,
    last_failure_code: null,
    last_heartbeat_at: null,
    last_refresh_at: null,
    outcome: null,
    phase: null,
    started_at: null,
    status: "accepted",
  };
  const acceptedStatus = {
    ...terminalStatus,
    latest_by_kind: terminalStatus.latest_by_kind.map((operation) => (
      operation.kind === "market" ? acceptedMarket : operation
    )),
    operations: terminalStatus.operations.map((operation) => (
      operation.kind === "market" && operation.idempotency_key === terminalMarket?.idempotency_key
        ? acceptedMarket
        : operation
    )),
  };
  let statusRouteCalls = 0;
  const statusPollingHandler = async (route: Route): Promise<void> => {
    statusRouteCalls += 1;
    await route.fulfill({
      body: JSON.stringify(statusRouteCalls === 1 ? acceptedStatus : terminalStatus),
      contentType: "application/json",
      status: 200,
    });
  };
  await page.route("**/api/operator/data/status**", statusPollingHandler);
  const acceptedResponse = page.waitForResponse(
    (response) => new URL(response.url()).pathname === "/api/operator/data/status",
  );
  await datasetStatus.getByRole("button", { name: "Reload" }).click();
  await acceptedResponse;
  await expect(
    latestRefreshes.getByRole("row").filter({ hasText: "Market Refresh" })
      .getByText("Accepted · queued", { exact: true }),
  ).toBeVisible();

  await page.evaluate(() => {
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      value: "hidden",
    });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  const hiddenRequestCount = statusRouteCalls;
  await page.waitForTimeout(5_200);
  expect(statusRouteCalls).toBe(hiddenRequestCount);

  const visibleRecoveryResponse = page.waitForResponse(
    (response) => new URL(response.url()).pathname === "/api/operator/data/status",
  );
  await page.evaluate(() => {
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      value: "visible",
    });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  await visibleRecoveryResponse;
  const terminalRequestCount = statusRouteCalls;
  await page.waitForTimeout(5_200);
  expect(statusRouteCalls).toBe(terminalRequestCount);

  for (const eventName of ["focus", "online"] as const) {
    const recoveryResponse = page.waitForResponse(
      (response) => new URL(response.url()).pathname === "/api/operator/data/status",
    );
    await page.evaluate((selectedEvent) => window.dispatchEvent(new Event(selectedEvent)), eventName);
    await recoveryResponse;
  }
  const manualResponse = page.waitForResponse(
    (response) => new URL(response.url()).pathname === "/api/operator/data/status",
  );
  await datasetStatus.getByRole("button", { name: "Reload" }).click();
  await manualResponse;
  await page.unroute("**/api/operator/data/status**", statusPollingHandler);

  stopDataOperatorWorker();
  assertDataOperatorWorkerLeaseReleased();
  resetAuthRateLimits();
  const recoveryKey = "browser-market-worker-recovery";
  await submitAcceptedMarket(recoveryKey);
  const unavailableReload = page.waitForResponse(
    (response) => new URL(response.url()).pathname === "/api/operator/data/status",
  );
  await datasetStatus.getByRole("button", { name: "Reload" }).click();
  await unavailableReload;
  await expect(datasetStatus.getByRole("alert")).toContainText(
    "Data Operator Worker unavailable",
  );
  await expect(datasetStatus.getByRole("alert")).toContainText(
    "Accepted work is durably queued but cannot start until the Worker recovers.",
  );
  const recoveryRow = operationHistory.getByRole("row").filter({ hasText: recoveryKey });
  await expect(recoveryRow.getByText("Accepted · queued", { exact: true })).toBeVisible();

  markDataRefreshRunning(recoveryKey);
  expireDataRefreshClaim(recoveryKey);
  const expiredClaimReload = page.waitForResponse(
    (response) => new URL(response.url()).pathname === "/api/operator/data/status",
  );
  await datasetStatus.getByRole("button", { name: "Reload" }).click();
  await expiredClaimReload;
  await expect(recoveryRow.locator('[data-label="Attempt / phase"] strong')).toHaveText("1");
  await expect(recoveryRow.getByText("Running · Claim", { exact: true })).toBeVisible();

  startDataOperatorWorker();
  await expect.poll(async () => {
    const response = await page.request.get("/api/operator/data/status");
    const snapshot = await response.json() as {
      worker?: { available?: unknown };
      operations?: Array<{ attempt_count?: unknown; idempotency_key?: unknown }>;
    };
    const recovered = snapshot.operations?.find(
      (operation) => operation.idempotency_key === recoveryKey,
    );
    return {
      attempt: recovered?.attempt_count,
      available: snapshot.worker?.available,
    };
  }, { timeout: 30_000 }).toEqual({ attempt: 2, available: true });
  const recoveredReload = page.waitForResponse(
    (response) => new URL(response.url()).pathname === "/api/operator/data/status",
  );
  await datasetStatus.getByRole("button", { name: "Reload" }).click();
  await recoveredReload;
  await expect(datasetStatus.getByText(
    "Data Operator Worker available",
    { exact: true },
  )).toBeVisible();
  await expect(recoveryRow.locator('[data-label="Attempt / phase"] strong')).toHaveText("2");

  stopDataOperatorWorker();
  assertDataOperatorWorkerLeaseReleased();
  const exhaustionKey = "browser-market-worker-exhaustion";
  await submitAcceptedMarket(exhaustionKey);
  markDataRefreshRunning(exhaustionKey);
  expireDataRefreshClaim(exhaustionKey);
  exhaustDataRefresh(exhaustionKey);
  const exhaustedReload = page.waitForResponse(
    (response) => new URL(response.url()).pathname === "/api/operator/data/status",
  );
  await datasetStatus.getByRole("button", { name: "Reload" }).click();
  await exhaustedReload;
  const exhaustedRow = operationHistory.getByRole("row").filter({ hasText: exhaustionKey });
  await expect(exhaustedRow.getByText("Failed", { exact: true })).toBeVisible();
  await expect(exhaustedRow.locator('[data-label="Attempt / phase"] strong')).toHaveText("3");
  await exhaustedRow.getByRole("button", {
    name: `View details for ${exhaustionKey}`,
  }).click();
  const exhaustedDrawer = page.getByRole("dialog", { name: "Operation details" });
  await expect(exhaustedDrawer).toContainText("RETRY_EXHAUSTED");
  await expect(exhaustedDrawer).toContainText("WORKER_LEASE_EXPIRED");
  await exhaustedDrawer.getByRole("button", { name: "Close operation details" }).click();

  async function submitAcceptedMarket(key: string): Promise<string> {
    const proofResponse = await page.request.post("/api/auth/operator/proofs", {
      data: {
        as_of: marketAsOf,
        idempotency_key: key,
        operation: "data.refresh.market.submit",
        password: browserPassword,
      },
      headers: sameOriginHeaders(),
    });
    expect(proofResponse.status()).toBe(200);
    const confirmed = await proofResponse.json() as { proof?: unknown };
    expect(typeof confirmed.proof).toBe("string");
    const submitted = await page.request.post("/api/operator/data/refreshes/market", {
      data: {
        as_of: marketAsOf,
        idempotency_key: key,
        proof: confirmed.proof,
      },
      headers: sameOriginHeaders(),
    });
    expect(submitted.status()).toBe(202);
    const receipt = await submitted.json() as { as_of?: unknown; status?: unknown };
    expect(receipt.status).toBe("accepted");
    expect(typeof receipt.as_of).toBe("string");
    return receipt.as_of as string;
  }

  resetAuthRateLimits();
  const cancelSourceKey = "browser-market-cancel-source";
  const cancelSourceTarget = await submitAcceptedMarket(cancelSourceKey);
  const cancelSourceReload = page.waitForResponse(
    (response) => new URL(response.url()).pathname === "/api/operator/data/status",
  );
  await datasetStatus.getByRole("button", { name: "Reload" }).click();
  await cancelSourceReload;
  const cancelSourceRow = operationHistory.getByRole("row").filter({
    hasText: cancelSourceKey,
  });
  await expect(cancelSourceRow.getByText("Accepted · queued", { exact: true })).toBeVisible();
  await expect(cancelSourceRow.getByRole("button", {
    name: `Cancel operation ${cancelSourceKey}`,
  })).toBeVisible();
  await expect(cancelSourceRow.getByRole("button", {
    name: `Retry operation ${cancelSourceKey}`,
  })).toHaveCount(0);

  await cancelSourceRow.getByRole("button", {
    name: `Cancel operation ${cancelSourceKey}`,
  }).click();
  const cancelDialog = page.getByRole("dialog", { name: "Cancel queued Refresh?" });
  await expect(cancelDialog).toContainText("Market Refresh");
  await expect(cancelDialog).toContainText(cancelSourceTarget);
  await expect(cancelDialog).toContainText(cancelSourceKey);
  await expect(cancelDialog).toContainText("The Worker will never claim this queued receipt");
  const cancelPassword = cancelDialog.getByLabel("Current password");
  await expect(cancelPassword).toBeFocused();
  await fillPasswordInput(cancelPassword);
  await cancelPassword.press("Enter");
  await expect(cancelDialog).toHaveCount(0);
  await expect(cancelSourceRow.getByText("Cancelled", { exact: true })).toBeVisible();
  await expect(cancelSourceRow.getByRole("button", {
    name: `Cancel operation ${cancelSourceKey}`,
  })).toHaveCount(0);
  const retrySource = cancelSourceRow.getByRole("button", {
    name: `Retry operation ${cancelSourceKey}`,
  });
  await expect(retrySource).toBeVisible();

  await cancelSourceRow.getByRole("button", {
    name: `View details for ${cancelSourceKey}`,
  }).click();
  const cancelledDrawer = page.getByRole("dialog", { name: "Operation details" });
  await expect(cancelledDrawer).toContainText(cancelSourceKey);
  await expect(cancelledDrawer.getByText("Cancelled", { exact: true })).toBeVisible();
  resetAuthRateLimits();
  await cancelledDrawer.getByRole("button", {
    name: `Retry operation ${cancelSourceKey}`,
  }).click();
  const retryDialog = page.getByRole("dialog", { name: "Retry cancelled Refresh?" });
  await expect(retryDialog).toContainText(
    "The original cancelled receipt remains unchanged and inspectable",
  );
  const actionRetryKey = "browser-market-retry-new";
  const retryKeyInput = retryDialog.getByLabel("New idempotency key");
  await expect(retryKeyInput).toHaveValue(/^market-retry-\d{8}T\d{6}Z$/);
  await retryKeyInput.fill(actionRetryKey);
  await fillPasswordInput(retryDialog.getByLabel("Current password"));
  await retryDialog.getByLabel("Current password").press("Enter");
  await expect(retryDialog).toHaveCount(0);
  await expect(cancelledDrawer).toBeVisible();
  await expect(cancelledDrawer).toContainText(cancelSourceKey);
  await expect(cancelledDrawer.getByText("Cancelled", { exact: true })).toBeVisible();
  await expect(cancelledDrawer).not.toContainText(actionRetryKey);
  await cancelledDrawer.getByRole("button", { name: "Close operation details" }).click();
  const retryRow = operationHistory.getByRole("row").filter({ hasText: actionRetryKey });
  await expect(retryRow.getByText("Accepted · queued", { exact: true })).toBeVisible();
  await expect(cancelSourceRow.getByText("Cancelled", { exact: true })).toBeVisible();

  resetAuthRateLimits();
  const claimedSourceKey = "browser-market-claimed-source";
  await submitAcceptedMarket(claimedSourceKey);
  const claimedSourceReload = page.waitForResponse(
    (response) => new URL(response.url()).pathname === "/api/operator/data/status",
  );
  await datasetStatus.getByRole("button", { name: "Reload" }).click();
  await claimedSourceReload;
  const claimedSourceRow = operationHistory.getByRole("row").filter({
    hasText: claimedSourceKey,
  });
  await claimedSourceRow.getByRole("button", {
    name: `Cancel operation ${claimedSourceKey}`,
  }).click();
  const rejectedCancel = page.getByRole("dialog", { name: "Cancel queued Refresh?" });
  markDataRefreshRunning(claimedSourceKey);
  await fillPasswordInput(rejectedCancel.getByLabel("Current password"));
  await rejectedCancel.getByLabel("Current password").press("Enter");
  await expect(rejectedCancel.getByRole("alert")).toContainText(
    "The Worker claimed this operation before Cancel won",
  );
  await expect(rejectedCancel.getByRole("button", { name: "Close" })).toBeVisible();
  await expect(claimedSourceRow.getByText("Running · Claim", { exact: true })).toBeVisible();
  await expect(claimedSourceRow.getByRole("button", {
    name: `Cancel operation ${claimedSourceKey}`,
  })).toHaveCount(0);
  await rejectedCancel.getByRole("button", { name: "Close" }).click();

  const actionProofRequests = operatorMutationRequests.filter((request) => {
    if (request.path !== "/api/auth/operator/proofs") return false;
    const body = JSON.parse(request.body) as { operation?: unknown };
    return body.operation === "data.refresh.cancel" || body.operation === "data.refresh.retry";
  });
  const actionMutations = operatorMutationRequests.filter(
    (request) => request.path === "/api/operator/data/refreshes/cancel"
      || request.path === "/api/operator/data/refreshes/retry",
  );
  expect(actionProofRequests).toHaveLength(3);
  expect(actionProofRequests.every((request) => request.body.includes(browserPassword)))
    .toBe(true);
  expect(actionMutations).toHaveLength(3);
  expect(actionMutations.every((request) => !request.body.includes(browserPassword)))
    .toBe(true);
  expect(actionMutations.map((request) => request.path)).toEqual([
    "/api/operator/data/refreshes/cancel",
    "/api/operator/data/refreshes/retry",
    "/api/operator/data/refreshes/cancel",
  ]);

  await page.getByRole("navigation", { name: "Operator Console sections" })
    .getByRole("link", { name: "Researchers", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Researcher access" })).toBeVisible();

  const currentOperatorRow = researcherTable.getByRole("row").filter({
    hasText: operator.email,
  });
  await expect(currentOperatorRow.getByText("Current Operator", { exact: true }))
    .toBeVisible();
  await expect(currentOperatorRow.getByRole("button", { name: /Revoke/ }))
    .toHaveCount(0);
  const ordinaryRow = researcherTable.getByRole("row").filter({
    hasText: ordinary.email,
  });
  await expect(ordinaryRow.locator('[data-label="Current sessions"]')).toHaveText("1");
  const revokeSessions = ordinaryRow.getByRole("button", {
    name: `Revoke 1 Login Sessions for ${ordinary.email}`,
  });
  await revokeSessions.focus();
  await revokeSessions.press("Enter");
  let revocationDialog = page.getByRole("dialog", {
    name: "Revoke Login Sessions?",
  });
  await expect(revocationDialog).toBeVisible();
  await expect(revocationDialog).toContainText("browser-ordinary");
  await expect(revocationDialog).toContainText(ordinary.email);
  await expect(revocationDialog).toContainText(ordinary.id);
  await expect(revocationDialog).toContainText("Current Login Sessions");
  await expect(revocationDialog).toContainText(
    "Every current Login Session for this Researcher will be revoked.",
  );
  const revocationPassword = revocationDialog.getByLabel("Current password");
  await expect(revocationPassword).toBeFocused();
  await fillPasswordInput(revocationPassword);
  await revocationPassword.press("Shift+Tab");
  expect(await revocationDialog.evaluate((element) =>
    element.contains(document.activeElement)
  )).toBe(true);
  await page.keyboard.press("Escape");
  await expect(revocationDialog).toHaveCount(0);
  await expect(revokeSessions).toBeFocused();

  await revokeSessions.press("Enter");
  revocationDialog = page.getByRole("dialog", {
    name: "Revoke Login Sessions?",
  });
  await expect(revocationDialog.getByLabel("Current password")).toHaveValue("");
  await fillPasswordInput(revocationDialog.getByLabel("Current password"));
  await revocationDialog.getByRole("button", { name: "Cancel" }).click();
  await expect(revocationDialog).toHaveCount(0);
  await expect(revokeSessions).toBeFocused();

  await revokeSessions.press("Enter");
  revocationDialog = page.getByRole("dialog", {
    name: "Revoke Login Sessions?",
  });
  await expect(revocationDialog.getByLabel("Current password")).toHaveValue("");
  await fillPasswordInput(revocationDialog.getByLabel("Current password"));
  await revocationDialog.getByLabel("Current password").press("Enter");
  await expect(revocationDialog).toHaveCount(0);
  await expect(page.getByRole("status").filter({
    hasText: `Revoked 1 Login Session for ${ordinary.email}.`,
  })).toBeVisible();
  await expect(ordinaryRow.locator('[data-label="Current sessions"]')).toHaveText("0");
  await expect(ordinaryRow.getByText("No active Sessions", { exact: true })).toBeVisible();
  await expect(ordinaryRow.getByRole("button", { name: /Revoke/ })).toHaveCount(0);
  await expect(page.locator("#operator-console-focus-fallback")).toBeFocused();

  const sessionProofRequests = operatorMutationRequests.filter((request) => {
    if (request.path !== "/api/auth/operator/proofs") return false;
    const body = JSON.parse(request.body) as { operation?: unknown };
    return body.operation === "researcher.sessions.revoke";
  });
  const sessionMutations = operatorMutationRequests.filter(
    (request) =>
      request.path === "/api/auth/operator/researchers/sessions/revoke",
  );
  expect(sessionProofRequests).toHaveLength(1);
  expect(JSON.parse(sessionProofRequests[0]?.body ?? "{}")).toEqual({
    operation: "researcher.sessions.revoke",
    password: browserPassword,
    researcher_id: ordinary.id,
  });
  expect(sessionMutations).toHaveLength(1);
  expect(JSON.parse(sessionMutations[0]?.body ?? "{}")).toEqual({
    proof: expect.any(String),
    researcher_id: ordinary.id,
  });
  expect(sessionMutations[0]?.body).not.toContain(browserPassword);

  await restoreResearcherSession(page, ordinary);
  await refreshRevokedSessionOnBrowserEvent(page);
  await expect(page.getByRole("heading", { name: "Log in to ThesisTrace" }))
    .toBeVisible();
  await restoreResearcherSession(page, operator);
  await refreshOperatorSessionOnBrowserEvent(page);
  await expect(page.getByRole("heading", { name: "Researcher access" })).toBeVisible();
  expect((await page.request.get("/api/auth/operator/capability")).status()).toBe(200);

  const invitationPagination = page.getByRole("navigation", {
    name: "Invitations pagination",
  });
  await invitationPagination.getByRole("button", { name: "Next" }).click();
  await expect(invitationPagination).toContainText("Page 2");
  const pagedInvitationEmail = "browser-invitation-01@example.test";
  const secondPageReissue = await findInvitationReissue(
    page,
    invitationPagination,
    pagedInvitationEmail,
  );
  await expect(secondPageReissue).toBeVisible();
  await secondPageReissue.click();
  const secondPageConfirmation = page.getByRole("dialog", {
    name: "Reissue Invitation?",
  });
  await fillPasswordInput(secondPageConfirmation.getByLabel("Current password"));
  await secondPageConfirmation.getByLabel("Current password").press("Enter");
  await expect(secondPageConfirmation).toHaveCount(0);
  await expect(invitationPagination).toContainText("Page 1");
  await expect(inviteResearcher).toBeFocused();

  const effectivePagedInvitation = page
    .getByRole("table", { name: "Invitations" })
    .getByRole("row")
    .filter({ hasText: pagedInvitationEmail })
    .filter({ hasText: "Effective · Delivered" });
  const failedReloadReissue = effectivePagedInvitation.getByRole("button", {
    name: `Reissue invitation for ${pagedInvitationEmail}`,
  });
  await expect(failedReloadReissue).toBeVisible();
  await failedReloadReissue.click();
  const failedReloadConfirmation = page.getByRole("dialog", {
    name: "Reissue Invitation?",
  });
  await fillPasswordInput(failedReloadConfirmation.getByLabel("Current password"));
  let failInvitationReload = true;
  await page.route("**/api/auth/operator/invitations*", async (route) => {
    if (route.request().method() !== "GET" || !failInvitationReload) {
      await route.continue();
      return;
    }
    failInvitationReload = false;
    await route.fulfill({
      body: JSON.stringify({ code: "OPERATOR_UNAVAILABLE" }),
      contentType: "application/json",
      status: 503,
    });
  });
  try {
    await failedReloadConfirmation.getByLabel("Current password").press("Enter");
    await expect(failedReloadConfirmation).toHaveCount(0);
    await expect(page.getByRole("alert").filter({
      hasText: "Operator Console unavailable.",
    })).toBeVisible();
    const retry = page.getByRole("button", { name: "Retry" });
    await expect(retry).toBeFocused();
  } finally {
    await page.unroute("**/api/auth/operator/invitations*");
  }
  await page.getByRole("button", { name: "Retry" }).click();
  await expect(page.getByRole("table", { name: "Invitations" })).toBeVisible();

  const search = page.getByRole("searchbox", { name: "Search researchers" });
  await search.fill("browser-page-");
  await page.getByRole("button", { name: "Search", exact: true }).click();
  await expect(researcherTable.getByText("browser-page-55@example.test", { exact: true }))
    .toBeVisible();
  await expect(researcherTable.getByText("browser-page-01@example.test", { exact: true }))
    .toHaveCount(0);

  const researcherPagination = page.getByRole("navigation", {
    name: "Researchers pagination",
  });
  const nextPage = researcherPagination.getByRole("button", { name: "Next" });
  const previousPage = researcherPagination.getByRole("button", { name: "Previous" });
  await expect(nextPage).toBeEnabled();
  let releaseCursorRequest: () => void = () => undefined;
  let markCursorRequestStarted: () => void = () => undefined;
  const cursorRequestReleased = new Promise<void>((resolve) => {
    releaseCursorRequest = resolve;
  });
  const cursorRequestStarted = new Promise<void>((resolve) => {
    markCursorRequestStarted = resolve;
  });
  await page.route("**/api/auth/operator/researchers?*", async (route) => {
    const url = new URL(route.request().url());
    if (!url.searchParams.has("cursor")) {
      await route.continue();
      return;
    }
    markCursorRequestStarted();
    await cursorRequestReleased;
    await route.continue();
  });
  try {
    await nextPage.click();
    await cursorRequestStarted;
    await expect(page.getByRole("status").filter({
      hasText: "Refreshing Operator Console…",
    })).toBeVisible();
    await expect(nextPage).toBeDisabled();
    await expect(previousPage).toBeDisabled();
    await expect(search).toBeDisabled();
    releaseCursorRequest();
    await expect(researcherPagination).toContainText("Page 2");
    await expect(researcherTable.getByText("browser-page-01@example.test", { exact: true }))
      .toBeVisible();
  } finally {
    releaseCursorRequest();
    await page.unroute("**/api/auth/operator/researchers?*");
  }
  await previousPage.click();
  await expect(researcherPagination).toContainText("Page 1");
  await expect(researcherTable.getByText("browser-page-55@example.test", { exact: true }))
    .toBeVisible();

  const capability = await page.request.get("/api/auth/operator/capability");
  expect(capability.status()).toBe(200);
  expect(await capability.json()).toEqual({ operator: true });
  const directory = await page.request.get("/api/auth/operator/researchers");
  expect(directory.status()).toBe(200);
  const serializedDirectory = JSON.stringify(await directory.json());
  expect(serializedDirectory).toContain(operator.id);
  expect(serializedDirectory).toContain(ordinary.id);
  expect(serializedDirectory).not.toMatch(/token|ip_address|user_agent/i);

  const deniedResearcher = await createResearcher(
    page,
    "browser-ordinary-denied@example.test",
  );
  await bootstrapResearcher(page, deniedResearcher);
  await page.goto("/data");
  await expect(page.getByRole("heading", { name: "Data overview" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Operator", exact: true })).toHaveCount(0);

  const deniedApi = await page.request.get("/api/auth/operator/researchers");
  expect(deniedApi.status()).toBe(404);
  expect(await deniedApi.text()).toBe("");
  for (const [path, data] of [
    [
      "/api/auth/operator/proofs",
      {
        email: "ordinary-denied@example.test",
        operation: "invitation.issue",
        password: browserPassword,
      },
    ],
    [
      "/api/auth/operator/invitations/issue",
      { email: "ordinary-denied@example.test", proof: oldConsoleToken },
    ],
    [
      "/api/auth/operator/proofs",
      {
        as_of: "2026-08-11T18:00:00+08:00",
        idempotency_key: "ordinary-denied-market-refresh",
        operation: "data.refresh.market.submit",
        password: browserPassword,
      },
    ],
    [
      "/api/auth/operator/proofs",
      {
        idempotency_key: "ordinary-denied-financial-refresh",
        observation_through_session: "2026-08-11",
        operation: "data.refresh.financial.submit",
        password: browserPassword,
      },
    ],
    [
      "/api/auth/operator/proofs",
      {
        idempotency_key: "ordinary-denied-industry-refresh",
        observation_through_session: "2026-08-11",
        operation: "data.refresh.industry.submit",
        password: browserPassword,
      },
    ],
    [
      "/api/auth/operator/proofs",
      {
        kind: "market",
        operation: "data.refresh.cancel",
        password: browserPassword,
        source_idempotency_key: "ordinary-denied-action-source",
        target: "2026-08-11T10:00:00Z",
      },
    ],
    [
      "/api/auth/operator/proofs",
      {
        kind: "industry",
        new_idempotency_key: "ordinary-denied-action-retry",
        operation: "data.refresh.retry",
        password: browserPassword,
        source_idempotency_key: "ordinary-denied-action-source",
        target: "2026-08-11",
      },
    ],
    [
      "/api/auth/operator/researchers/sessions/revoke",
      { proof: oldConsoleToken, researcher_id: deniedResearcher.id },
    ],
  ] as const) {
    const deniedMutation = await page.request.post(path, {
      data,
      headers: sameOriginHeaders(),
    });
    expect(deniedMutation.status()).toBe(404);
    expect(await deniedMutation.text()).toBe("");
  }
  const deniedMarketInspection = await page.request.get(
    "/api/operator/data/refreshes/market?idempotency_key=browser-market-refresh-20260811",
  );
  expect(deniedMarketInspection.status()).toBe(404);
  expect(await deniedMarketInspection.text()).toBe("");
  const deniedDatasetStatus = await page.request.get("/api/operator/data/status");
  expect(deniedDatasetStatus.status()).toBe(404);
  expect(await deniedDatasetStatus.text()).toBe("");
  for (const [path, data] of [
    [
      "/api/operator/data/refreshes/cancel",
      {
        kind: "market",
        proof: oldConsoleToken,
        source_idempotency_key: "ordinary-denied-action-source",
        target: "2026-08-11T10:00:00Z",
      },
    ],
    [
      "/api/operator/data/refreshes/retry",
      {
        kind: "industry",
        new_idempotency_key: "ordinary-denied-action-retry",
        proof: oldConsoleToken,
        source_idempotency_key: "ordinary-denied-action-source",
        target: "2026-08-11",
      },
    ],
  ] as const) {
    const deniedAction = await page.request.post(path, {
      data,
      headers: sameOriginHeaders(),
    });
    expect(deniedAction.status()).toBe(404);
    expect(await deniedAction.text()).toBe("");
  }
  const deniedMalformedInspection = await page.request.get(
    "/api/operator/data/refreshes/market",
  );
  expect(deniedMalformedInspection.status()).toBe(404);
  expect(await deniedMalformedInspection.text()).toBe("");
  const deniedMarketMutation = await page.request.post(
    "/api/operator/data/refreshes/market",
    {
      data: {
        as_of: "2026-08-11T18:00:00+08:00",
        idempotency_key: "ordinary-denied-market-refresh",
        proof: oldConsoleToken,
      },
      headers: sameOriginHeaders(),
    },
  );
  expect(deniedMarketMutation.status()).toBe(404);
  expect(await deniedMarketMutation.text()).toBe("");
  const deniedMalformedMutation = await page.request.post(
    "/api/operator/data/refreshes/market",
    { data: {}, headers: sameOriginHeaders() },
  );
  expect(deniedMalformedMutation.status()).toBe(404);
  expect(await deniedMalformedMutation.text()).toBe("");
  const deniedFinancialInspection = await page.request.get(
    "/api/operator/data/refreshes/financial?"
    + "idempotency_key=ordinary-denied-financial-refresh&"
    + "observation_through_session=2026-08-11",
  );
  expect(deniedFinancialInspection.status()).toBe(404);
  expect(await deniedFinancialInspection.text()).toBe("");
  const deniedFinancialMutation = await page.request.post(
    "/api/operator/data/refreshes/financial",
    {
      data: {
        idempotency_key: "ordinary-denied-financial-refresh",
        observation_through_session: "2026-08-11",
        proof: oldConsoleToken,
      },
      headers: sameOriginHeaders(),
    },
  );
  expect(deniedFinancialMutation.status()).toBe(404);
  expect(await deniedFinancialMutation.text()).toBe("");
  const deniedIndustryInspection = await page.request.get(
    "/api/operator/data/refreshes/industry?"
    + "idempotency_key=ordinary-denied-industry-refresh&"
    + "observation_through_session=2026-08-11",
  );
  expect(deniedIndustryInspection.status()).toBe(404);
  expect(await deniedIndustryInspection.text()).toBe("");
  const deniedIndustryMutation = await page.request.post(
    "/api/operator/data/refreshes/industry",
    {
      data: {
        idempotency_key: "ordinary-denied-industry-refresh",
        observation_through_session: "2026-08-11",
        proof: oldConsoleToken,
      },
      headers: sameOriginHeaders(),
    },
  );
  expect(deniedIndustryMutation.status()).toBe(404);
  expect(await deniedIndustryMutation.text()).toBe("");
  const deniedDocument = await page.goto("/operator/researchers");
  expect(deniedDocument?.status()).toBe(404);
  expect(await deniedDocument?.text()).toBe("");
  await expect(page.locator("#root")).toHaveCount(0);
  const deniedDataDocument = await page.goto("/operator/data");
  expect(deniedDataDocument?.status()).toBe(404);
  expect(await deniedDataDocument?.text()).toBe("");
  await expect(page.locator("#root")).toHaveCount(0);
});

async function bootstrapResearcher(
  page: Page,
  researcher: AuthenticatedResearcher,
): Promise<void> {
  const response = await page.request.post("/api/researcher/bootstrap", {
    data: {},
    headers: sameOriginHeaders(),
  });
  expect(response.status()).toBe(200);
  expect(await response.json()).toMatchObject({ researcher_id: researcher.id });
}

async function refreshRevokedSessionOnBrowserEvent(page: Page): Promise<void> {
  const sessionResponse = page.waitForResponse(
    (response) => new URL(response.url()).pathname === "/api/auth/get-session",
  );
  await page.evaluate(() => window.dispatchEvent(new Event("focus")));
  const response = await sessionResponse;
  expect(response.ok()).toBe(true);
  expect(await response.json()).toBeNull();
  await nextAnimationFrame(page);
}

async function refreshOperatorSessionOnBrowserEvent(page: Page): Promise<void> {
  const sessionResponse = page.waitForResponse(
    (response) => new URL(response.url()).pathname === "/api/auth/get-session",
  );
  const capabilityResponse = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === "/api/auth/operator/capability",
  );
  await page.evaluate(() => window.dispatchEvent(new Event("focus")));
  const responses = await Promise.all([sessionResponse, capabilityResponse]);
  expect(responses[0].ok()).toBe(true);
  expect(responses[1].status()).toBe(200);
  await nextAnimationFrame(page);
}

async function nextAnimationFrame(page: Page): Promise<void> {
  await page.evaluate(
    () => new Promise<void>((resolve) => window.requestAnimationFrame(() => resolve())),
  );
}

async function settleReactUpdates(page: Page): Promise<void> {
  await nextAnimationFrame(page);
  await nextAnimationFrame(page);
}

async function expectMinimumTouchTarget(locator: Locator): Promise<void> {
  const box = await locator.boundingBox();
  expect(box, "touch target should have a rendered bounding box").not.toBeNull();
  expect(box?.height, "touch target height").toBeGreaterThanOrEqual(44);
  expect(box?.width, "touch target width").toBeGreaterThanOrEqual(44);
}

async function findInvitationReissue(
  page: Page,
  pagination: Locator,
  email: string,
): Promise<Locator> {
  const previous = pagination.getByRole("button", { name: "Previous" });
  await expect(previous).toBeEnabled();
  for (let visitedPageCount = 0; visitedPageCount < 20; visitedPageCount += 1) {
    const action = page.getByRole("button", {
      name: `Reissue invitation for ${email}`,
    });
    if (await action.count() === 1) return action;

    const next = pagination.getByRole("button", { name: "Next" });
    if (!await next.isEnabled()) break;
    const currentPage = Number.parseInt(
      (await pagination.textContent())?.match(/Page (\d+)/)?.[1] ?? "",
      10,
    );
    await next.click();
    await expect(pagination).toContainText(`Page ${currentPage + 1}`);
    await expect(previous).toBeEnabled();
  }
  throw new Error(`Seeded invitation ${email} was not found in the paged directory.`);
}
