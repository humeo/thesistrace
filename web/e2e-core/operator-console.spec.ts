import type { Page } from "@playwright/test";

import {
  browserPassword,
  createResearcher,
  emailToken,
  expect,
  issueInvitation,
  restoreResearcherSession,
  runAuthOperator,
  sameOriginHeaders,
  seedOperatorDirectory,
  securityTest as test,
  type AuthenticatedResearcher,
} from "./auth-fixture";

test("only the singleton Operator can open and read the Operator Console", async ({ page }) => {
  test.setTimeout(60_000);
  const operatorMutationRequests: Array<Readonly<{ path: string; body: string }>> = [];
  page.on("request", (request) => {
    const path = new URL(request.url()).pathname;
    if (
      request.method() === "POST"
      && (
        path === "/api/auth/operator/proofs"
        || path.startsWith("/api/auth/operator/invitations/")
        || path === "/api/auth/operator/researchers/sessions/revoke"
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
  await issuePassword.fill(browserPassword);
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
  await confirmation.getByLabel("Current password").fill(browserPassword);
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
  await reissueConfirmation.getByLabel("Current password").fill(browserPassword);
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

  const proofRequests = operatorMutationRequests.filter(
    (request) => request.path === "/api/auth/operator/proofs",
  );
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
  await revocationPassword.fill(browserPassword);
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
  await revocationDialog.getByLabel("Current password").fill(browserPassword);
  await revocationDialog.getByRole("button", { name: "Cancel" }).click();
  await expect(revocationDialog).toHaveCount(0);
  await expect(revokeSessions).toBeFocused();

  await revokeSessions.press("Enter");
  revocationDialog = page.getByRole("dialog", {
    name: "Revoke Login Sessions?",
  });
  await expect(revocationDialog.getByLabel("Current password")).toHaveValue("");
  await revocationDialog.getByLabel("Current password").fill(browserPassword);
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
  const secondPageEmail = "browser-invitation-01@example.test";
  await page.getByRole("button", {
    name: `Reissue invitation for ${secondPageEmail}`,
  }).click();
  const secondPageConfirmation = page.getByRole("dialog", {
    name: "Reissue Invitation?",
  });
  await secondPageConfirmation.getByLabel("Current password").fill(browserPassword);
  await secondPageConfirmation.getByLabel("Current password").press("Enter");
  await expect(secondPageConfirmation).toHaveCount(0);
  await expect(invitationPagination).toContainText("Page 1");
  await expect(inviteResearcher).toBeFocused();

  const failedReloadEmail = "browser-invitation-55@example.test";
  await page.getByRole("button", {
    name: `Reissue invitation for ${failedReloadEmail}`,
  }).click();
  const failedReloadConfirmation = page.getByRole("dialog", {
    name: "Reissue Invitation?",
  });
  await failedReloadConfirmation.getByLabel("Current password").fill(browserPassword);
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
  const deniedDocument = await page.goto("/operator/researchers");
  expect(deniedDocument?.status()).toBe(404);
  expect(await deniedDocument?.text()).toBe("");
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
