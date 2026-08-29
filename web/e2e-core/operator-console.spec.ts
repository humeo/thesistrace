import type { Page } from "@playwright/test";

import {
  createResearcher,
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
  const operator = await createResearcher(page, "browser-operator@example.test");
  await bootstrapResearcher(page, operator);
  expect(runAuthOperator("assign-operator", "--researcher-id", operator.id)).toMatchObject({
    command: "assign-operator",
    researcher_id: operator.id,
    status: "assigned",
  });

  const ordinary = await createResearcher(page, "browser-ordinary@example.test");
  await bootstrapResearcher(page, ordinary);
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
    await expect(page.getByRole("status")).toHaveText("Refreshing Operator Console…");
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

  await restoreResearcherSession(page, ordinary);
  await page.goto("/data");
  await expect(page.getByRole("heading", { name: "Data overview" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Operator", exact: true })).toHaveCount(0);

  const deniedApi = await page.request.get("/api/auth/operator/researchers");
  expect(deniedApi.status()).toBe(404);
  expect(await deniedApi.text()).toBe("");
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
