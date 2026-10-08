import type { Locator, Page, Route } from "@playwright/test";

import {
  assertDataOperatorWorkerLeaseReleased,
  browserPassword,
  createResearcher,
  emailToken,
  emailCode,
  ensureOperatorDataBaseline,
  exhaustDataRefresh,
  expireDataRefreshClaim,
  expect,
  fillOperatorCode,
  requestOperatorCode,
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

test("Operator confirms session revocation with an emailed code", {tag:"@isolated"}, async ({page}) => {
  const operator = await createResearcher(page,"otp-operator-e2e@example.test");
  expect(runAuthOperator("assign-operator","--researcher-id",operator.id)).toMatchObject({status:"assigned"});
  const ordinary = await createResearcher(page,"otp-target-e2e@example.test");
  await restoreResearcherSession(page,operator);
  await page.goto("/operator/researchers");
  const row = page.getByRole("row").filter({hasText:ordinary.email});
  await row.getByRole("button",{name:`Revoke 1 Login Sessions for ${ordinary.email}`}).click();
  const dialog = page.getByRole("alertdialog",{name:"Revoke Login Sessions?"});
  await expect(dialog.getByLabel("Verification code")).toBeFocused();
  await dialog.getByRole("button",{name:"Send confirmation code"}).click();
  await expect(dialog.getByRole("status")).toContainText("A code was sent");
  const code = await emailCode(operator.email);
  await dialog.getByLabel("Verification code").fill(code === "000000" ? "111111" : "000000");
  await dialog.getByRole("button",{name:"Revoke sessions",exact:true}).click();
  await expect(dialog.getByRole("alert")).toContainText("incorrect or has expired");
  await dialog.getByLabel("Verification code").fill(code);
  await dialog.getByRole("button",{name:"Revoke sessions",exact:true}).click();
  await expect(dialog).not.toBeVisible();
  await expect(row.locator('[data-label="Current sessions"]')).toHaveText("0");
  const session = await (await page.request.get("/api/auth/get-session")).json();
  expect(session.user.id).toBe(operator.id);
});

test("Operator access control and desktop navigation", { tag: "@isolated" }, async ({ page }) => {
  test.setTimeout(240_000);
  const { operatorMutationRequests, operator, ordinary } = await prepareOperator(page);
  const { invitationEmail, researcherTable, operatorRow } = await prepareOperatorDirectory(page, operator, ordinary);
  const oldConsoleToken = await emailToken(invitationEmail, "/accept-invitation#token=");
  const applicationShell = page.locator(".app-shell");
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
  await expect(page.getByRole("heading", { name: "Data", exact: true })).toBeVisible();
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
        otp: "123456",
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
        idempotency_key: "ordinary-denied-dataset-refresh",
        operation: "data.refresh.dataset.submit",
      },
    ],
    [
      "/api/auth/operator/proofs",
      {
        kind: "dataset",
        operation: "data.refresh.cancel",
        source_idempotency_key: "ordinary-denied-action-source",
        target: "2026-08-11T10:00:00Z",
      },
    ],
    [
      "/api/auth/operator/proofs",
      {
        kind: "dataset",
        new_idempotency_key: "ordinary-denied-action-retry",
        operation: "data.refresh.retry",
        source_idempotency_key: "ordinary-denied-action-source",
        target: "2026-08-11T10:00:00Z",
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
  const deniedDatasetInspection = await page.request.get(
    "/api/operator/data/refreshes/dataset?idempotency_key=browser-dataset-refresh-20260811",
  );
  expect(deniedDatasetInspection.status()).toBe(404);
  expect(await deniedDatasetInspection.text()).toBe("");
  const deniedDatasetStatus = await page.request.get("/api/operator/data/status");
  expect(deniedDatasetStatus.status()).toBe(404);
  expect(await deniedDatasetStatus.text()).toBe("");
  for (const [path, data] of [
    [
      "/api/operator/data/refreshes/cancel",
      {
        kind: "dataset",
        proof: oldConsoleToken,
        source_idempotency_key: "ordinary-denied-action-source",
        target: "2026-08-11T10:00:00Z",
      },
    ],
    [
      "/api/operator/data/refreshes/retry",
      {
        kind: "dataset",
        new_idempotency_key: "ordinary-denied-action-retry",
        proof: oldConsoleToken,
        source_idempotency_key: "ordinary-denied-action-source",
        target: "2026-08-11T10:00:00Z",
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
    "/api/operator/data/refreshes/dataset",
  );
  expect(deniedMalformedInspection.status()).toBe(404);
  expect(await deniedMalformedInspection.text()).toBe("");
  const deniedDatasetMutation = await page.request.post(
    "/api/operator/data/refreshes/dataset",
    {
      data: {
        as_of: "2026-08-11T18:00:00+08:00",
        idempotency_key: "ordinary-denied-dataset-refresh",
        proof: oldConsoleToken,
      },
      headers: sameOriginHeaders(),
    },
  );
  expect(deniedDatasetMutation.status()).toBe(404);
  expect(await deniedDatasetMutation.text()).toBe("");
  const deniedMalformedMutation = await page.request.post(
    "/api/operator/data/refreshes/dataset",
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
  const deniedIndustryInspection = await page.request.get(
    "/api/operator/data/refreshes/industry?"
    + "idempotency_key=ordinary-denied-industry-refresh&"
    + "observation_through_session=2026-08-11",
  );
  expect(deniedIndustryInspection.status()).toBe(404);
  expect(await deniedIndustryInspection.text()).toBe("");
  const deniedDocument = await page.goto("/operator/researchers");
  expect(deniedDocument?.status()).toBe(404);
  expect(await deniedDocument?.text()).toBe("");
  await expect(page.locator("#root")).toHaveCount(0);
  const deniedDataDocument = await page.goto("/operator/data");
  expect(deniedDataDocument?.status()).toBe(404);
  expect(await deniedDataDocument?.text()).toBe("");
  await expect(page.locator("#root")).toHaveCount(0);
});

test("Operator researchers and invitations", { tag: "@isolated" }, async ({ page }) => {
  test.setTimeout(240_000);
  const { operatorMutationRequests, operator, ordinary } = await prepareOperator(page);
  const { invitationEmail, researcherTable, operatorRow } = await prepareOperatorDirectory(page, operator, ordinary);
  const invitationTable = page.getByRole("table", { name: "Invitations" });
  const invitationRows = invitationTable.getByRole("row").filter({ hasText: invitationEmail });
  await expect(invitationRows).toHaveCount(2);
  const effectiveInvitation = invitationRows.filter({ hasText: "Effective · Delivered" });
  const terminalInvitation = invitationRows.filter({ hasText: "Terminal · Revoked" });
  await expect(effectiveInvitation).toHaveCount(1);
  await effectiveInvitation.getByRole("button", { name: "Details", exact: true }).click();
  await expect(effectiveInvitation.locator("dt").filter({ hasText: /^ID$/ }).locator("xpath=following-sibling::dd/code")).toHaveText(
    /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/,
  );
  await expect(effectiveInvitation.locator("time")).toHaveCount(2);
  await expect(effectiveInvitation.locator("dt").filter({ hasText: /^Terminal$/ }).locator("xpath=following-sibling::dd")).toHaveText("—");
  await expect(terminalInvitation).toHaveCount(1);
  await terminalInvitation.getByRole("button", { name: "Details", exact: true }).click();
  await expect(terminalInvitation.locator("time")).toHaveCount(3);

  const consoleInvitationEmail = "browser-console-invited@example.test";
  const inviteResearcher = page.getByRole("button", { name: "Invite Researcher" });
  await inviteResearcher.focus();
  await inviteResearcher.press("Enter");
  let confirmation = page.getByRole("dialog", { name: "Issue Invitation?" });
  await expect(confirmation).toBeVisible();
  await expect(confirmation).toContainText("Target email");
  await expect(confirmation).toContainText("48-hour invitation link");
  const issueEmail = confirmation.getByLabel("Target email");
  const issuePassword = confirmation.getByLabel("Verification code");
  await expect(issueEmail).toBeFocused();
  await issueEmail.press("Shift+Tab");
  await expect(confirmation.getByRole("button", { name: "Send Invitation" })).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(issueEmail).toBeFocused();
  await issueEmail.fill(consoleInvitationEmail);
  await issuePassword.fill("123456");
  await page.keyboard.press("Escape");
  await expect(confirmation).toHaveCount(0);
  await expect(inviteResearcher).toBeFocused();

  await inviteResearcher.press("Enter");
  confirmation = page.getByRole("dialog", { name: "Issue Invitation?" });
  await expect(confirmation.getByLabel("Verification code")).toHaveValue("");
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
  await expect(confirmation.getByLabel("Verification code")).toBeFocused();
  await fillOperatorCode(confirmation.getByLabel("Verification code"));
  await confirmation.getByLabel("Verification code").press("Enter");
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
  await fillOperatorCode(reissueConfirmation.getByLabel("Verification code"));
  await reissueConfirmation.getByLabel("Verification code").press("Enter");
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
  expect(proofRequests.every((request) => /^[0-9]{6}$/.test(JSON.parse(request.body).otp)))
    .toBe(true);
  expect(invitationMutations).toHaveLength(2);
  expect(invitationMutations.every((request) => !request.body.includes(browserPassword)))
    .toBe(true);
  expect(invitationMutations.map((request) => Object.keys(JSON.parse(request.body)).sort()))
    .toEqual([["email", "proof"], ["email", "proof"]]);

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
  let revocationDialog = page.getByRole("alertdialog", {
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
  const revocationPassword = revocationDialog.getByLabel("Verification code");
  await expect(revocationPassword).toBeFocused();
  await revocationPassword.fill("123456");
  await revocationPassword.press("Shift+Tab");
  expect(await revocationDialog.evaluate((element) =>
    element.contains(document.activeElement)
  )).toBe(true);
  await page.keyboard.press("Escape");
  await expect(revocationDialog).toHaveCount(0);
  await expect(revokeSessions).toBeFocused();

  await revokeSessions.press("Enter");
  revocationDialog = page.getByRole("alertdialog", {
    name: "Revoke Login Sessions?",
  });
  await expect(revocationDialog.getByLabel("Verification code")).toHaveValue("");
  await revocationDialog.getByLabel("Verification code").fill("123456");
  await revocationDialog.getByRole("button", { name: "Cancel" }).click();
  await expect(revocationDialog).toHaveCount(0);
  await expect(revokeSessions).toBeFocused();

  await revokeSessions.press("Enter");
  revocationDialog = page.getByRole("alertdialog", {
    name: "Revoke Login Sessions?",
  });
  await expect(revocationDialog.getByLabel("Verification code")).toHaveValue("");
  await fillOperatorCode(revocationDialog.getByLabel("Verification code"));
  await revocationDialog.getByLabel("Verification code").press("Enter");
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
    otp: expect.any(String),
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
  await expect(page.getByRole("heading", { name: "Welcome to QAgentis" }))
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
  await fillOperatorCode(secondPageConfirmation.getByLabel("Verification code"));
  await secondPageConfirmation.getByLabel("Verification code").press("Enter");
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
  await fillOperatorCode(failedReloadConfirmation.getByLabel("Verification code"));
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
    await failedReloadConfirmation.getByLabel("Verification code").press("Enter");
    await expect(failedReloadConfirmation).toHaveCount(0);
    await expect(page.getByRole("alert").filter({
      hasText: "Operator Console unavailable.",
    })).toBeVisible();
    const retry = page.getByRole("region", { name: "Operator Researchers" })
      .getByRole("button", { name: "Retry", exact: true });
    await expect(retry).toBeFocused();
  } finally {
    await page.unroute("**/api/auth/operator/invitations*");
  }
  await page.getByRole("region", { name: "Operator Researchers" })
    .getByRole("button", { name: "Retry", exact: true }).click();
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


});

test("Operator Dataset submission and response recovery", { tag: "@isolated" }, async ({ page }) => {
  test.setTimeout(240_000);
  const { operatorMutationRequests, datasetStatusRequests, ordinary } = await prepareOperator(page);
  const operatorSections = page.getByRole("navigation", {
    name: "Operator Console sections",
  });
  await operatorSections.getByRole("link", { name: "Data", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Data operations" })).toBeVisible();
  const datasetRefreshSection = page.locator(
    'section[aria-labelledby="operator-market-refresh-heading"]',
  );
  await expect(datasetRefreshSection.getByText(
    "Use the same free-form, timezone-aware inputs as the CLI.",
    { exact: true },
  )).toHaveCount(0);
  const datasetAsOfDate = "2026-08-14";
  const datasetAsOf = `${datasetAsOfDate}T18:00:00+08:00`;
  const datasetAsOfInput = datasetRefreshSection.getByLabel("As-of", { exact: true });
  await expect(datasetAsOfInput).toHaveAttribute("placeholder", "YYYY-MM-DD");
  await datasetAsOfInput.fill(datasetAsOfDate);
  await expect(datasetAsOfInput).toHaveValue(datasetAsOfDate);
  await expect(datasetRefreshSection.getByLabel("Idempotency key")).toHaveCount(0);
  const reviewRefresh = datasetRefreshSection.getByRole("button", {
    name: "Review Refresh",
  });
  const datasetRefreshReceipt = page.locator(
    'section[aria-labelledby="operator-market-refresh-status"]',
  );
  const datasetRefreshReconciliation = page.locator(
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
  let pendingKey = "";
  const pendingProofHandler = async (route: Route): Promise<void> => {
    const body = route.request().postDataJSON() as {
      idempotency_key?: unknown;
      operation?: unknown;
    };
    if (
      body.operation === "data.refresh.dataset.submit"
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
  await datasetAsOfInput.fill(datasetAsOfDate);
  pendingKey = await reviewGeneratedRefresh(page, reviewRefresh);
  let datasetConfirmation = page.getByRole("dialog", {
    name: "Refresh all data?",
  });
  await expect(datasetConfirmation.getByLabel("Verification code")).toHaveCount(0);
  await datasetConfirmation.getByRole("button", { name: "Submit Refresh" }).click();
  await pendingProofStarted;
  await expect(datasetConfirmation.getByRole("button", { name: "Cancel" })).toBeEnabled();
  const pendingProofAborted = page.waitForEvent("requestfailed", (request) => {
    if (new URL(request.url()).pathname !== "/api/auth/operator/proofs") return false;
    const body = request.postDataJSON() as { idempotency_key?: unknown };
    return body.idempotency_key === pendingKey;
  });
  await page.keyboard.press("Escape");
  await expect(datasetConfirmation).toHaveCount(0);
  await expect(reviewRefresh).toBeFocused();
  releasePendingProof();
  await pendingProofAborted;
  await page.unroute("**/api/auth/operator/proofs", pendingProofHandler);

  let datasetKey = "";
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
    if (body.idempotency_key !== datasetKey) {
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
    "**/api/operator/data/refreshes/dataset**",
    delayedCoreResponseHandler,
  );
  await datasetAsOfInput.fill(datasetAsOfDate);
  datasetKey = await reviewGeneratedRefresh(page, reviewRefresh);
  datasetConfirmation = page.getByRole("dialog", {
    name: "Refresh all data?",
  });
  await expect(datasetConfirmation).toContainText(datasetAsOf);
  await expect(datasetConfirmation).toContainText(datasetKey);
  await expect(datasetConfirmation).toContainText("Publication happens once");
  await expect(datasetConfirmation.getByLabel("Verification code")).toHaveCount(0);
  await datasetConfirmation.getByRole("button", { name: "Submit Refresh" }).click();
  await coreAccepted;
  await expect(datasetConfirmation.getByRole("button", { name: "Cancel" })).toBeEnabled();
  await page.keyboard.press("Escape");
  await expect(datasetConfirmation).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Confirming submission" })).toBeVisible();
  await expect(datasetRefreshReconciliation.getByText(datasetKey, { exact: true }))
    .toBeVisible();
  releaseCoreResponse();
  await coreResponseDropped;
  await page.unroute(
    "**/api/operator/data/refreshes/dataset**",
    delayedCoreResponseHandler,
  );
  await expect(page.getByRole("heading", { name: "Dataset published" }))
    .toBeVisible({ timeout: 30_000 });
  expect(datasetStatusRequests).toContainEqual({
    asOf: datasetAsOf,
    idempotencyKey: datasetKey,
  });
  await expect(datasetRefreshReceipt.getByText(datasetKey, { exact: true })).toBeVisible();
  await expect(datasetRefreshReceipt.getByRole("status").getByText("Published", { exact: true })).toBeVisible();
  await expect(datasetRefreshReceipt.getByText("2026-08-14", { exact: true }))
    .toBeVisible();
  await expect(reviewRefresh).toBeFocused();

  // Keys are generated by the UI. Verify deliberate reuse with a changed
  // target at the HTTP contract, rather than inventing an editable key field.
  const conflictStatus = await page.evaluate(async ({ key }) => {
    const target = { as_of: "2026-08-12T18:00:00+08:00", idempotency_key: key };
    const proofResponse = await fetch("/api/auth/operator/proofs", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...target, operation: "data.refresh.dataset.submit" }),
    });
    if (!proofResponse.ok) return proofResponse.status;
    const { proof } = await proofResponse.json();
    return (await fetch("/api/operator/data/refreshes/dataset", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...target, proof }),
    })).status;
  }, { key: datasetKey });
  expect(conflictStatus).toBe(409);
  await expect(datasetRefreshReceipt.getByText(datasetKey, { exact: true })).toBeVisible();

  const datasetProofRequests = operatorMutationRequests.filter((request) => {
    if (request.path !== "/api/auth/operator/proofs") return false;
    const body = JSON.parse(request.body) as { operation?: unknown };
    return body.operation === "data.refresh.dataset.submit";
  });
  const datasetMutations = operatorMutationRequests.filter(
    (request) => request.path === "/api/operator/data/refreshes/dataset",
  );
  expect(datasetProofRequests).toHaveLength(3);
  const completedDatasetProof = datasetProofRequests.find((request) =>
    JSON.parse(request.body).idempotency_key === datasetKey
  );
  expect(JSON.parse(completedDatasetProof?.body ?? "{}")).toEqual({
    as_of: datasetAsOf,
    idempotency_key: datasetKey,
    operation: "data.refresh.dataset.submit",
  });
  expect(datasetMutations).toHaveLength(2);
  const completedDatasetMutation = datasetMutations.find((request) =>
    JSON.parse(request.body).idempotency_key === datasetKey
  );
  expect(JSON.parse(completedDatasetMutation?.body ?? "{}")).toEqual({
    as_of: datasetAsOf,
    idempotency_key: datasetKey,
    proof: expect.any(String),
  });
  expect(datasetMutations.every((request) => !request.body.includes(browserPassword)))
    .toBe(true);
  resetAuthRateLimits();

  let droppedAfterAcceptanceKey = "";
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
    "**/api/operator/data/refreshes/dataset**",
    droppedAfterAcceptanceHandler,
  );
  await datasetAsOfInput.fill(datasetAsOfDate);
  droppedAfterAcceptanceKey = await reviewGeneratedRefresh(page, reviewRefresh);
  datasetConfirmation = page.getByRole("dialog", {
    name: "Refresh all data?",
  });
  await expect(datasetConfirmation.getByLabel("Verification code")).toHaveCount(0);
  await datasetConfirmation.getByRole("button", { name: "Submit Refresh" }).click();
  await droppedAfterAcceptance;
  await expect(datasetConfirmation).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Confirming submission" })).toBeVisible();
  await page.unroute(
    "**/api/operator/data/refreshes/dataset**",
    droppedAfterAcceptanceHandler,
  );
  await expect(page.getByRole("heading", { name: "Dataset published" }))
    .toBeVisible({ timeout: 30_000 });
  expect(datasetStatusRequests).toContainEqual({
    asOf: datasetAsOf,
    idempotencyKey: droppedAfterAcceptanceKey,
  });
  await expect(datasetRefreshReceipt.getByText(droppedAfterAcceptanceKey, { exact: true }))
    .toBeVisible();
  resetAuthRateLimits();

  let staleDatasetKey = "";
  let currentDatasetKey = "";
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
    kind: "dataset",
    phase: null,
    completed_stages: [],
    last_failure_code: null,
    last_refresh_at: "2026-08-11T10:01:00+00:00",
    outcome: "no_change",
    status: "succeeded",
  });
  let recoveredBeforePostKey = "";
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
      && url.pathname === "/api/operator/data/refreshes/dataset"
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
        kind: "dataset",
        phase: null,
        completed_stages: [],
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
    "**/api/operator/data/refreshes/dataset**",
    recoveredBeforePostHandler,
  );
  await datasetAsOfInput.fill(datasetAsOfDate);
  recoveredBeforePostKey = await reviewGeneratedRefresh(page, reviewRefresh);
  datasetConfirmation = page.getByRole("dialog", {
    name: "Refresh all data?",
  });
  await expect(datasetConfirmation.getByLabel("Verification code")).toHaveCount(0);
  await datasetConfirmation.getByRole("button", { name: "Submit Refresh" }).click();
  await recoveredPostStarted;
  await page.keyboard.press("Escape");
  await expect(page.getByRole("heading", { name: "Confirming submission" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Refresh completed" }))
    .toBeVisible({ timeout: 15_000 });
  await expect(datasetRefreshReceipt.getByText("No change", { exact: true })).toBeVisible();
  const recoveredLatePostResponse = page.waitForResponse((response) => {
    const request = response.request();
    if (
      request.method() !== "POST"
      || new URL(request.url()).pathname !== "/api/operator/data/refreshes/dataset"
    ) return false;
    const body = request.postDataJSON() as { idempotency_key?: unknown };
    return body.idempotency_key === recoveredBeforePostKey;
  });
  releaseRecoveredPostResponse();
  await recoveredLatePostResponse;
  await settleReactUpdates(page);
  await expect(page.getByRole("heading", { name: "Refresh completed" })).toBeVisible();
  await expect(datasetRefreshReceipt.getByText(recoveredBeforePostKey, { exact: true }))
    .toBeVisible();
  await expect(datasetRefreshReceipt.getByText("No change", { exact: true })).toBeVisible();
  await page.unroute(
    "**/api/operator/data/refreshes/dataset**",
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
    if (body.idempotency_key === staleDatasetKey) {
      markStaleSubmissionStarted();
      await staleResponseGate;
      await route.fulfill({
        body: JSON.stringify(terminalReceipt(staleDatasetKey)),
        contentType: "application/json",
        status: 202,
      });
      return;
    }
    if (body.idempotency_key === currentDatasetKey) {
      markCurrentSubmissionStarted();
      await currentResponseGate;
      await route.fulfill({
        body: JSON.stringify(terminalReceipt(currentDatasetKey)),
        contentType: "application/json",
        status: 202,
      });
      return;
    }
    await route.continue();
  };
  await page.route(
    "**/api/operator/data/refreshes/dataset**",
    submissionRaceHandler,
  );
  await datasetAsOfInput.fill(datasetAsOfDate);
  staleDatasetKey = await reviewGeneratedRefresh(page, reviewRefresh);
  datasetConfirmation = page.getByRole("dialog", {
    name: "Refresh all data?",
  });
  await expect(datasetConfirmation.getByLabel("Verification code")).toHaveCount(0);
  await datasetConfirmation.getByRole("button", { name: "Submit Refresh" }).click();
  await staleSubmissionStarted;
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "Stop checking" }).click();

  currentDatasetKey = await reviewGeneratedRefresh(page, reviewRefresh);
  const currentDatasetConfirmation = page.getByRole("dialog", {
    name: "Refresh all data?",
  });
  await expect(currentDatasetConfirmation.getByLabel("Verification code")).toHaveCount(0);
  await currentDatasetConfirmation.getByRole("button", { name: "Submit Refresh" }).click();
  await currentSubmissionStarted;
  const staleBrowserResponse = page.waitForResponse((response) => {
    const request = response.request();
    if (
      request.method() !== "POST"
      || new URL(request.url()).pathname !== "/api/operator/data/refreshes/dataset"
    ) return false;
    const body = request.postDataJSON() as { idempotency_key?: unknown };
    return body.idempotency_key === staleDatasetKey;
  });
  releaseStaleResponse();
  await staleBrowserResponse;
  await settleReactUpdates(page);
  await expect(currentDatasetConfirmation).toBeVisible();
  await expect(currentDatasetConfirmation).toContainText(currentDatasetKey);
  await expect(datasetRefreshReceipt.getByText(staleDatasetKey, { exact: true })).toHaveCount(0);

  const currentBrowserResponse = page.waitForResponse((response) => {
    const request = response.request();
    if (
      request.method() !== "POST"
      || new URL(request.url()).pathname !== "/api/operator/data/refreshes/dataset"
    ) return false;
    const body = request.postDataJSON() as { idempotency_key?: unknown };
    return body.idempotency_key === currentDatasetKey;
  });
  releaseCurrentResponse();
  await currentBrowserResponse;
  await expect(currentDatasetConfirmation).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Refresh completed" })).toBeVisible();
  await expect(datasetRefreshReceipt.getByText(currentDatasetKey, { exact: true })).toBeVisible();
  await page.unroute(
    "**/api/operator/data/refreshes/dataset**",
    submissionRaceHandler,
  );
  resetAuthRateLimits();

  let polledDatasetKey = "";
  let newerDatasetKey = "";
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
    kind: "dataset",
    phase: null,
    completed_stages: [],
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
      && url.pathname === "/api/operator/data/refreshes/dataset"
      && url.searchParams.get("idempotency_key") === polledDatasetKey
    ) {
      markPolledRequestStarted();
      await polledRequestGate;
      try {
        await route.fulfill({
          body: JSON.stringify(terminalReceipt(polledDatasetKey)),
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
    if (body.idempotency_key === polledDatasetKey) {
      await route.fulfill({
        body: JSON.stringify({ ...acceptedReceipt, idempotency_key: polledDatasetKey }),
        contentType: "application/json",
        status: 202,
      });
      return;
    }
    if (body.idempotency_key === newerDatasetKey) {
      await route.fulfill({
        body: JSON.stringify(terminalReceipt(newerDatasetKey)),
        contentType: "application/json",
        status: 202,
      });
      releasePolledRequest();
      return;
    }
    await route.continue();
  };
  await page.route(
    "**/api/operator/data/refreshes/dataset**",
    pollingRaceHandler,
  );
  await datasetAsOfInput.fill(datasetAsOfDate);
  polledDatasetKey = await reviewGeneratedRefresh(page, reviewRefresh);
  datasetConfirmation = page.getByRole("dialog", {
    name: "Refresh all data?",
  });
  await expect(datasetConfirmation.getByLabel("Verification code")).toHaveCount(0);
  await datasetConfirmation.getByRole("button", { name: "Submit Refresh" }).click();
  await expect(page.getByRole("heading", { name: "Refresh accepted" })).toBeVisible();
  await polledRequestStarted;

  newerDatasetKey = await reviewGeneratedRefresh(page, reviewRefresh);
  const newerDatasetConfirmation = page.getByRole("dialog", {
    name: "Refresh all data?",
  });
  await expect(datasetRefreshReceipt.getByText(polledDatasetKey, { exact: true })).toBeVisible();
  await expect(newerDatasetConfirmation.getByLabel("Verification code")).toHaveCount(0);
  await newerDatasetConfirmation.getByRole("button", { name: "Submit Refresh" }).click();
  await expect(newerDatasetConfirmation).toHaveCount(0);
  await polledRequestSettled;
  await settleReactUpdates(page);
  await expect(page.getByRole("heading", { name: "Refresh completed" })).toBeVisible();
  await expect(datasetRefreshReceipt.getByText(newerDatasetKey, { exact: true })).toBeVisible();
  await expect(datasetRefreshReceipt.getByText(polledDatasetKey, { exact: true })).toHaveCount(0);
  await page.unroute(
    "**/api/operator/data/refreshes/dataset**",
    pollingRaceHandler,
  );
  resetAuthRateLimits();

  // Retry from the mounted reconciliation UI must preserve the exact request.
  const unavailableHandler = async (route: Route): Promise<void> => {
    await route.fulfill({
      status: route.request().method() === "POST" ? 503 : 404,
      body: "",
    });
  };
  await page.route("**/api/operator/data/refreshes/dataset**", unavailableHandler);
  const retryKey = await reviewGeneratedRefresh(page, reviewRefresh);
  await page.getByRole("dialog", { name: "Refresh all data?" })
    .getByRole("button", { name: "Submit Refresh" }).click();
  await expect(datasetRefreshReconciliation).toBeVisible();
  await page.evaluate(() => document.dispatchEvent(new Event("visibilitychange")));
  await expect(datasetRefreshReconciliation).toContainText("receipt is not available yet");
  await datasetRefreshReconciliation.getByRole("button", { name: "Retry exact request" }).click();
  const retryDialog = page.getByRole("dialog", { name: "Refresh all data?" });
  await expect(retryDialog).toContainText(retryKey);
  await expect(retryDialog).toContainText(datasetAsOf);
  await page.unroute("**/api/operator/data/refreshes/dataset**", unavailableHandler);
  await retryDialog.getByRole("button", { name: "Submit Refresh" }).click();
  await expect(datasetRefreshReceipt).toContainText(retryKey);
  await expect(page.getByRole("heading", { name: "Dataset published" }))
    .toBeVisible({ timeout: 30_000 });

  // Losing Operator authority while polling must clear the protected page.
  const capabilityLossHandler = async (route: Route): Promise<void> => {
    const request = route.request();
    if (request.method() !== "POST") return route.continue();
    await route.fulfill({ status: 202, contentType: "application/json",
      body: JSON.stringify({ ...acceptedReceipt,
        as_of: request.postDataJSON().as_of,
        idempotency_key: request.postDataJSON().idempotency_key }),
    });
  };
  await page.route("**/api/operator/data/refreshes/dataset", capabilityLossHandler);
  await reviewGeneratedRefresh(page, reviewRefresh);
  await page.getByRole("dialog", { name: "Refresh all data?" })
    .getByRole("button", { name: "Submit Refresh" }).click();
  await expect(page.getByRole("heading", { name: "Refresh accepted" })).toBeVisible();
  await restoreResearcherSession(page, ordinary);
  await page.evaluate(() => document.dispatchEvent(new Event("visibilitychange")));
  await expect(page.getByRole("heading", { name: "Not found" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Data operations" })).toHaveCount(0);
  await page.unroute("**/api/operator/data/refreshes/dataset", capabilityLossHandler);

});

test("Operator Dataset operations and Worker recovery", { tag: "@isolated" }, async ({ page }) => {
  test.setTimeout(240_000);
  const { operatorMutationRequests, datasetStatusRequests } = await prepareOperator(page);
  await page.goto("/operator/data");
  await expect(page.getByRole("heading", { name: "Data operations" })).toBeVisible();
  const datasetAsOf = "2026-08-14T18:00:00+08:00";
  const datasetKey = await prepareDatasetOperation(page);
  await page.reload();
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
  await expect(latestRefreshes.getByRole("row").filter({ hasText: "Data Refresh" })).toHaveCount(1);
  const operationHistory = datasetStatus.getByRole("table", {
    name: "Data Refresh operation history",
  });
  await expect(datasetStatus.getByText(
    "Newest first · 50 receipts per page · terminal receipts retained 180 days",
    { exact: true },
  )).toHaveCount(0);
  await expect(operationHistory.getByText(datasetKey, { exact: true })).toBeVisible();

  const datasetHistoryRow = operationHistory.getByRole("row").filter({ hasText: datasetKey });
  const datasetDetails = datasetHistoryRow.getByRole("button", { name: `View details for ${datasetKey}` });
  await datasetDetails.focus();
  await datasetDetails.press("Enter");
  const operationDrawer = page.getByRole("dialog", { name: "Operation details" });
  await expect(operationDrawer).toBeVisible();
  await expect(operationDrawer).toContainText(datasetKey);
  await expect(operationDrawer).toContainText("Last heartbeat");
  await expect(operationDrawer).not.toContainText(/manifest|owner token|object path|raw response/i);
  await expect(operationDrawer.getByRole("button", { name: "Close operation details" }))
    .toBeFocused();
  await page.keyboard.press("Tab");
  await expect(operationDrawer.getByRole("button", { name: "Close operation details" }))
    .toBeFocused();
  await page.keyboard.press("Shift+Tab");
  await expect(operationDrawer.getByRole("button", { name: "Close operation details" }))
    .toBeFocused();
  await page.keyboard.press("Escape");
  await expect(operationDrawer).toHaveCount(0);
  await expect(datasetDetails).toBeFocused();

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
  // Polling lifecycle is covered with controlled time in OperatorDatasetStatus.test.tsx.


  stopDataOperatorWorker();
  assertDataOperatorWorkerLeaseReleased();
  resetAuthRateLimits();
  const recoveryKey = "browser-dataset-worker-recovery";
  await submitAcceptedDataset(recoveryKey);
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
  const exhaustionKey = "browser-dataset-worker-exhaustion";
  await submitAcceptedDataset(exhaustionKey);
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

  async function submitAcceptedDataset(key: string): Promise<string> {
    const proofResponse = await page.request.post("/api/auth/operator/proofs", {
      data: {
        as_of: datasetAsOf,
        idempotency_key: key,
        operation: "data.refresh.dataset.submit",
      },
      headers: sameOriginHeaders(),
    });
    expect(proofResponse.status()).toBe(200);
    const confirmed = await proofResponse.json() as { proof?: unknown };
    expect(typeof confirmed.proof).toBe("string");
    const submitted = await page.request.post("/api/operator/data/refreshes/dataset", {
      data: {
        as_of: datasetAsOf,
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
  const cancelSourceKey = "browser-dataset-cancel-source";
  const cancelSourceTarget = await submitAcceptedDataset(cancelSourceKey);
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
  const cancelDialog = page.getByRole("alertdialog", { name: "Cancel queued Refresh?" });
  await expect(cancelDialog).toContainText("Data Refresh");
  await expect(cancelDialog).toContainText(cancelSourceTarget);
  await expect(cancelDialog).toContainText(cancelSourceKey);
  await expect(cancelDialog).toContainText("The Worker will never claim this queued receipt");
  await expect(cancelDialog.getByLabel("Verification code")).toHaveCount(0);
  await cancelDialog.getByRole("button", { name: "Cancel queued operation" }).click();
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
  const retryDialog = page.getByRole("alertdialog", { name: "Retry cancelled Refresh?" });
  await expect(retryDialog).toContainText(
    "The original cancelled receipt remains unchanged and inspectable",
  );
  await expect(retryDialog.getByLabel("New idempotency key")).toHaveCount(0);
  const retryProofRequest = page.waitForRequest((request) =>
    new URL(request.url()).pathname === "/api/auth/operator/proofs"
    && request.method() === "POST"
    && request.postDataJSON().operation === "data.refresh.retry");
  await expect(retryDialog.getByLabel("Verification code")).toHaveCount(0);
  await retryDialog.getByRole("button", { name: "Create Retry" }).click();
  const actionRetryKey = (await retryProofRequest).postDataJSON().new_idempotency_key as string;
  expect(actionRetryKey).toMatch(/^dataset-retry-\d{8}T\d{6}Z-[a-f0-9-]{36}$/);
  expect(actionRetryKey).not.toBe(cancelSourceKey);
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
  const claimedSourceKey = "browser-dataset-claimed-source";
  await submitAcceptedDataset(claimedSourceKey);
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
  const rejectedCancel = page.getByRole("alertdialog", { name: "Cancel queued Refresh?" });
  markDataRefreshRunning(claimedSourceKey);
  await expect(rejectedCancel.getByLabel("Verification code")).toHaveCount(0);
  await rejectedCancel.getByRole("button", { name: "Cancel queued operation" }).click();
  await expect(rejectedCancel.getByRole("alert")).toContainText(
    "The Worker claimed this operation before Cancel won",
  );
  await expect(rejectedCancel.getByRole("button", { name: "Close" })).toBeVisible();
  await rejectedCancel.getByRole("button", { name: "Close" }).click();
  await expect(claimedSourceRow.getByText("Running · Claim", { exact: true })).toBeVisible();
  await expect(claimedSourceRow.getByRole("button", {
    name: `Cancel operation ${claimedSourceKey}`,
  })).toHaveCount(0);

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
  for (const request of actionProofRequests) {
    const proofRequest = JSON.parse(request.body);
    expect(proofRequest).not.toHaveProperty("otp");
    expect(proofRequest).not.toHaveProperty("password");
  }
  expect(actionMutations).toHaveLength(3);
  for (const request of actionMutations) expect(JSON.parse(request.body)).not.toHaveProperty("otp");
  expect(actionMutations.every((request) => !request.body.includes(browserPassword)))
    .toBe(true);
  expect(actionMutations.map((request) => request.path)).toEqual([
    "/api/operator/data/refreshes/cancel",
    "/api/operator/data/refreshes/retry",
    "/api/operator/data/refreshes/cancel",
  ]);


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

async function reviewGeneratedRefresh(page: Page, button: Locator): Promise<string> {
  await button.click();
  const dialog = page.getByRole("dialog", { name: "Refresh all data?", exact: true });
  await expect(dialog).toBeVisible();
  const key = await dialog.locator("dl > div").filter({ has: page.locator("dt").filter({ hasText: /^Idempotency key$/ }) }).locator("dd").innerText();
  expect(key).toMatch(/^dataset-\d{8}T\d{6}Z-[a-f0-9-]{36}$/);
  return key;
}

async function prepareOperator(page: Page) {
  const operatorMutationRequests: Array<Readonly<{ path: string; body: string }>> = [];
  const datasetStatusRequests: Array<Readonly<{
    asOf: string | null;
    idempotencyKey: string | null;
  }>> = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    const path = url.pathname;
    if (request.method() === "GET" && path === "/api/operator/data/refreshes/dataset") {
      datasetStatusRequests.push({
        asOf: url.searchParams.get("as_of"),
        idempotencyKey: url.searchParams.get("idempotency_key"),
      });
    }
    if (
      request.method() === "POST"
      && (
        path === "/api/auth/operator/proofs"
        || path.startsWith("/api/auth/operator/invitations/")
        || path === "/api/auth/operator/researchers/sessions/revoke"
        || path === "/api/operator/data/refreshes/dataset"
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
  const denied = await page.request.get("/api/operator/data/status", { headers: sameOriginHeaders() });
  expect(denied.status()).toBe(404);
  await page.goto("/data");
  await expect(page.getByRole("heading", { name: "Data", exact: true })).toBeVisible();
  await restoreResearcherSession(page, operator);
  await page.goto("/operator/data");
  await expect(page.getByRole("heading", { name: "Data operations" })).toBeVisible();
  return { operatorMutationRequests, datasetStatusRequests, operator, ordinary };
}

async function prepareOperatorDirectory(
  page: Page,
  operator: Awaited<ReturnType<typeof createResearcher>>,
  ordinary: Awaited<ReturnType<typeof createResearcher>>,
) {
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
  await operatorRow.getByRole("button", { name: "Details · browser-operator", exact: true }).click();
  const operatorDetails = researcherTable.getByRole("row").filter({ hasText: operator.id });
  await expect(operatorDetails.getByText(operator.id, { exact: true })).toBeVisible();
  await expect(operatorRow.locator('[data-label="Access"]')).toHaveText("Active");
  await expect(operatorDetails.locator("dt").filter({ hasText: /^Created$/ }).locator("xpath=following-sibling::dd/time")).toHaveCount(1);
  await expect(operatorRow.locator('[data-label="Latest login"]')).toHaveText(/.+/);
  await expect(operatorRow.locator('[data-label="Current sessions"]')).toHaveText("1");
  await expect(operatorDetails.locator("dt").filter({ hasText: /^Effective invitation$/ }).locator("xpath=following-sibling::dd")).toHaveText("None");
  await expect(researcherTable.getByText(ordinary.email, { exact: true })).toBeVisible();

  return { invitationEmail, researcherTable, operatorRow };
}

async function prepareDatasetOperation(page: Page): Promise<string> {
  const key = "browser-dataset-refresh";
  const target = { as_of: "2026-08-14T18:00:00+08:00" };
  const proof = await page.request.post("/api/auth/operator/proofs", {
    headers: sameOriginHeaders(), data: { ...target, idempotency_key: key,
      operation: "data.refresh.dataset.submit" },
  });
  expect(proof.status()).toBe(200);
  const submitted = await page.request.post("/api/operator/data/refreshes/dataset", {
    headers: sameOriginHeaders(), data: { ...target, idempotency_key: key, proof: (await proof.json()).proof },
  });
  expect(submitted.status()).toBe(202);
  await expect.poll(async () => {
    const response = await page.request.get("/api/operator/data/status", { headers: sameOriginHeaders() });
    expect(response.status()).toBe(200);
    return (await response.json()).operations.find((operation: { idempotency_key: string }) => operation.idempotency_key === key)?.status;
  }, { timeout: 60_000 }).toBe("succeeded");
  return key;
}
