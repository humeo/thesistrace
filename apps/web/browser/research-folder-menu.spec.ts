import { expect, test } from "./workbench-fixture";

test("Duplicate folder names keep the form open with a specific error and allow correction", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 960 });
  const folders = [
    { id: "folder_default", name: "Default", is_default: true, created_at: "2026-08-01T00:00:00Z" },
    { id: "folder_signals", name: "Signals", is_default: false, created_at: "2026-08-01T00:00:00Z" },
  ];
  await page.route("**/api/research-folders**", async route => {
    const request = route.request();
    if (request.method() === "GET") return route.fulfill({ json: { items: folders, next_cursor: null } });
    const name = request.postDataJSON().name.trim();
    const id = request.url().split("/").at(-1);
    if (folders.some(folder => folder.id !== id && folder.name.toLowerCase() === name.toLowerCase())) {
      return route.fulfill({ status: 409, json: { detail: { code: "FOLDER_NAME_EXISTS" } } });
    }
    const target = folders.find(folder => folder.id === id)!;
    target.name = name;
    return route.fulfill({ json: target });
  });
  await page.goto("/research?new");
  await page.getByRole("button", { name: "Factor Evaluation", exact: true }).click();
  const notes = page.getByRole("textbox", { name: "Research notes (optional)", exact: true });
  await notes.fill("Keep this active draft");
  const trigger = page.getByRole("button", { name: "Research Folders", exact: true });
  const menu = page.getByRole("menu", { name: "Research Folders", exact: true });
  await trigger.click();
  await menu.getByRole("menuitem", { name: "New Folder", exact: true }).click();
  const createForm = page.getByRole("dialog", { name: "New Folder", exact: true });
  const createName = createForm.getByRole("textbox", { name: "Folder name", exact: true });
  await createName.fill("  signals  ");
  await createForm.getByRole("button", { name: "Create", exact: true }).click();
  await expect(createForm).toContainText("A folder with this name already exists.");
  await expect(createName).toHaveValue("  signals  ");
  await expect(createName).toHaveAttribute("aria-invalid", "true");
  await expect(trigger).toContainText("Default folder");
  await createForm.getByRole("button", { name: "Cancel", exact: true }).click();
  await expect(menu.getByRole("menuitem", { name: "Signals", exact: true })).toHaveCount(1);

  await menu.getByRole("menuitem", { name: "Signals Folder actions", exact: true }).click();
  await page.getByRole("menu", { name: "Signals Folder actions", exact: true }).getByRole("menuitem", { name: "Rename Folder", exact: true }).click();
  const renameForm = page.getByRole("dialog", { name: "Rename Folder", exact: true });
  const renameName = renameForm.getByRole("textbox", { name: "Folder name", exact: true });
  await renameName.fill("default");
  await renameForm.getByRole("button", { name: "Rename Folder", exact: true }).click();
  await expect(renameForm).toContainText("A folder with this name already exists.");
  await expect(renameName).toHaveAttribute("aria-invalid", "true");
  await renameName.fill("Momentum");
  await renameForm.getByRole("button", { name: "Rename Folder", exact: true }).click();
  await expect(renameForm).toHaveCount(0);
  await expect(menu.getByRole("menuitem", { name: "Momentum", exact: true })).toBeVisible();
  await expect(trigger).toContainText("Default folder");
  await expect(notes).toHaveValue("Keep this active draft");
});

test("Folder menu supports keyboard navigation and anchored management forms", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1440, height: 960 });
  const folders = [{ id: "folder_default", name: "Default", is_default: true, created_at: "2026-08-01T00:00:00Z" }];
  let rejectCreate = true;
  let rejectDelete = true;
  await page.route("**/api/research-folders**", async route => {
    const request = route.request();
    if (request.method() === "GET") return route.fulfill({ json: { items: folders, next_cursor: null } });
    if (request.method() === "POST") {
      if (rejectCreate) return route.fulfill({ status: 503, json: { detail: "Temporarily unavailable" } });
      const folder = { ...folders[0], id: "folder_signals", name: request.postDataJSON().name, is_default: false };
      folders.push(folder);
      return route.fulfill({ status: 201, json: folder });
    }
    if (request.method() === "PATCH") {
      folders[1].name = request.postDataJSON().name;
      return route.fulfill({ json: folders[1] });
    }
    if (rejectDelete) return route.fulfill({ status: 409, json: { detail: { code: "FOLDER_NOT_EMPTY" } } });
    folders.splice(1, 1);
    return route.fulfill({ status: 204, body: "" });
  });
  await page.goto("/research?new");
  await page.getByRole("button", { name: "Factor Evaluation", exact: true }).click();
  const trigger = page.getByRole("button", { name: "Research Folders", exact: true });
  await trigger.focus();
  await trigger.press("ArrowDown");
  const menu = page.getByRole("menu", { name: "Research Folders", exact: true });
  await expect(menu).toBeVisible();
  await expect(menu.getByRole("menuitem", { name: "Default", exact: true })).toBeFocused();
  const menuBackground = await menu.evaluate(element => getComputedStyle(element).backgroundColor);
  await expect(menu.getByRole("menuitem", { name: "Default", exact: true })).not.toHaveCSS("background-color", menuBackground);
  await expect(menu.getByRole("menuitem", { name: "Rename Folder", exact: true })).toHaveCount(0);
  await expect(menu.getByRole("menuitem", { name: "Delete Folder", exact: true })).toHaveCount(0);
  await page.keyboard.press("ArrowDown");
  await expect(menu.getByRole("menuitem", { name: "New Folder", exact: true })).toBeFocused();
  const triggerBounds = await trigger.boundingBox();
  await page.keyboard.press("Enter");
  const createDialog = page.getByRole("dialog", { name: "New Folder", exact: true });
  await expect(createDialog).toBeVisible();
  await expect(menu).toHaveCount(0);
  const newName = createDialog.getByRole("textbox", { name: "Folder name", exact: true });
  await expect(newName).toBeFocused();
  await expect(createDialog.getByRole("button", { name: "Create", exact: true })).toBeDisabled();
  expect(triggerBounds).not.toBeNull();
  await expect.poll(async () => {
    const bounds = await createDialog.boundingBox();
    if (bounds === null) return Infinity;
    return Math.max(Math.abs(bounds.x - triggerBounds!.x),
      Math.abs(bounds.y - triggerBounds!.y - triggerBounds!.height - 4));
  }).toBeLessThan(2);
  await newName.press("Escape");
  await expect(createDialog).toHaveCount(0);
  await expect(trigger).toBeFocused();

  await trigger.click();
  await menu.getByRole("menuitem", { name: "New Folder", exact: true }).click();
  await createDialog.getByRole("button", { name: "Cancel", exact: true }).click();
  await expect(createDialog).toHaveCount(0);
  await expect(menu).toBeVisible();
  await expect(trigger).toHaveAttribute("aria-expanded", "true");

  await menu.getByRole("menuitem", { name: "New Folder", exact: true }).click();
  await page.getByRole("heading", { name: "Evaluation conditions", exact: true }).click();
  await expect(createDialog).toHaveCount(0);

  await trigger.click();
  await menu.getByRole("menuitem", { name: "New Folder", exact: true }).click();
  await newName.fill("Signals");
  await newName.press("Enter");
  await expect(createDialog.getByRole("alert")).toContainText("Research Folders unavailable");
  await expect(newName).toHaveValue("Signals");
  rejectCreate = false;
  await createDialog.getByRole("button", { name: "Create", exact: true }).click();
  await expect(createDialog).toHaveCount(0);
  await expect(trigger).toContainText("Signals folder");
  await expect(menu).toBeVisible();
  await expect(menu.getByRole("menuitem", { name: "Signals", exact: true })).toHaveAttribute("aria-current", "page");

  const signalsRow = menu.getByRole("group", { name: "Signals", exact: true });
  const overflowAction = signalsRow.getByRole("menuitem", { name: "Signals Folder actions", exact: true });
  const actionsMenu = page.getByRole("menu", { name: "Signals Folder actions", exact: true });
  await expect(signalsRow.getByRole("menuitem")).toHaveCount(2);
  await expect(actionsMenu).toHaveCount(0);
  const signalsBounds = await menu.getByRole("menuitem", { name: "Signals", exact: true }).boundingBox();
  const overflowBounds = await overflowAction.boundingBox();
  expect(signalsBounds).not.toBeNull();
  expect(overflowBounds).not.toBeNull();
  expect(overflowBounds!.x).toBeGreaterThanOrEqual(signalsBounds!.x + signalsBounds!.width);
  expect(Math.abs(overflowBounds!.y + overflowBounds!.height / 2 - signalsBounds!.y - signalsBounds!.height / 2)).toBeLessThan(2);
  await overflowAction.hover();
  await expect(actionsMenu).toHaveCount(0);
  await overflowAction.click();
  await expect(actionsMenu.getByRole("menuitem", { name: "Rename Folder", exact: true })).toBeVisible();
  await expect(actionsMenu.getByRole("menuitem", { name: "Delete Folder", exact: true })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("folder-actions.png") });
  await page.keyboard.press("Escape");
  await expect(actionsMenu).toHaveCount(0);
  await expect(menu).toBeVisible();
  await expect(overflowAction).toBeFocused();
  await overflowAction.press("Enter");
  await actionsMenu.getByRole("menuitem", { name: "Rename Folder", exact: true }).click();
  const renameDialog = page.getByRole("dialog", { name: "Rename Folder", exact: true });
  const renameName = renameDialog.getByRole("textbox", { name: "Folder name", exact: true });
  await expect(renameName).toBeFocused();
  await expect(renameName).toHaveValue("Signals");
  await renameName.fill("Abandoned rename");
  await renameDialog.getByRole("button", { name: "Cancel", exact: true }).click();
  await expect(renameDialog).toHaveCount(0);
  await expect(menu).toBeVisible();
  await expect(trigger).toContainText("Signals folder");
  await overflowAction.click();
  await actionsMenu.getByRole("menuitem", { name: "Rename Folder", exact: true }).click();
  await expect(renameName).toBeFocused();
  await expect(renameName).toHaveValue("Signals");
  await renameName.fill("Momentum");
  await renameDialog.getByRole("button", { name: "Rename Folder", exact: true }).click();
  await expect(renameDialog).toHaveCount(0);
  await expect(trigger).toContainText("Momentum folder");
  await expect(menu).toBeVisible();

  await menu.getByRole("menuitem", { name: "Momentum Folder actions", exact: true }).click();
  await page.getByRole("menu", { name: "Momentum Folder actions", exact: true }).getByRole("menuitem", { name: "Delete Folder", exact: true }).click();
  const deleteDialog = page.getByRole("alertdialog", { name: "Delete Folder", exact: true });
  await deleteDialog.getByRole("button", { name: "Delete Folder", exact: true }).click();
  await expect(deleteDialog.getByRole("alert")).toContainText("A nonempty Folder cannot be deleted");
  rejectDelete = false;
  await deleteDialog.getByRole("button", { name: "Delete Folder", exact: true }).click();
  await expect(deleteDialog).toHaveCount(0);
  await expect(trigger).toContainText("Default folder");
});

test("Folder row actions manage that folder without replacing another folder's draft", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 960 });
  const folders = [
    { id: "folder_default", name: "Default", is_default: true, created_at: "2026-08-01T00:00:00Z" },
    { id: "folder_signals", name: "Signals", is_default: false, created_at: "2026-08-01T00:00:00Z" },
  ];
  await page.route("**/api/research-folders**", async route => {
    const request = route.request();
    if (request.method() === "GET") return route.fulfill({ json: { items: folders, next_cursor: null } });
    if (!request.url().endsWith("/folder_signals")) return route.fulfill({ status: 404 });
    if (request.method() === "PATCH") {
      folders[1].name = request.postDataJSON().name;
      return route.fulfill({ json: folders[1] });
    }
    folders.splice(1, 1);
    return route.fulfill({ status: 204, body: "" });
  });
  await page.goto("/research?new");
  await page.getByRole("button", { name: "Factor Evaluation", exact: true }).click();
  const notes = page.getByRole("textbox", { name: "Research notes (optional)", exact: true });
  await notes.fill("Keep this active draft");
  const trigger = page.getByRole("button", { name: "Research Folders", exact: true });
  await trigger.click();
  const menu = page.getByRole("menu", { name: "Research Folders", exact: true });
  const defaultRow = menu.getByRole("group", { name: "Default", exact: true });
  await expect(defaultRow.getByRole("menuitem")).toHaveCount(1);
  const signalsRow = menu.getByRole("group", { name: "Signals", exact: true });
  const overflowAction = signalsRow.getByRole("menuitem", { name: "Signals Folder actions", exact: true });
  const actionsMenu = page.getByRole("menu", { name: "Signals Folder actions", exact: true });
  await menu.getByRole("menuitem", { name: "Signals", exact: true }).focus();
  await page.keyboard.press("ArrowDown");
  await expect(overflowAction).toBeFocused();
  await expect(actionsMenu).toHaveCount(0);
  await page.keyboard.press("ArrowRight");
  await expect(actionsMenu.getByRole("menuitem", { name: "Rename Folder", exact: true })).toBeFocused();
  await page.keyboard.press("Enter");
  const renameDialog = page.getByRole("dialog", { name: "Rename Folder", exact: true });
  await expect(renameDialog.getByRole("textbox", { name: "Folder name", exact: true })).toHaveValue("Signals");
  await renameDialog.getByRole("textbox", { name: "Folder name", exact: true }).fill("Momentum");
  await renameDialog.getByRole("button", { name: "Rename Folder", exact: true }).click();
  await expect(menu.getByRole("menuitem", { name: "Momentum", exact: true })).toBeVisible();
  await expect(trigger).toContainText("Default folder");
  await expect(notes).toHaveValue("Keep this active draft");
  await menu.getByRole("group", { name: "Momentum", exact: true }).getByRole("menuitem", { name: "Momentum Folder actions", exact: true }).click();
  await page.getByRole("menu", { name: "Momentum Folder actions", exact: true }).getByRole("menuitem", { name: "Delete Folder", exact: true }).click();
  const deleteDialog = page.getByRole("alertdialog", { name: "Delete Folder", exact: true });
  await expect(deleteDialog).toContainText("Momentum");
  await deleteDialog.getByRole("button", { name: "Delete Folder", exact: true }).click();
  await expect(deleteDialog).toHaveCount(0);
  await expect(trigger).toContainText("Default folder");
  await expect(notes).toHaveValue("Keep this active draft");
  await expect(page).toHaveURL(/\/research$/);
  await trigger.click();
  await expect(menu.getByRole("menuitem", { name: "Momentum", exact: true })).toHaveCount(0);
});
