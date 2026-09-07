import { expect, test, type Page } from "@playwright/test";
import { waitForChatTurn } from "../e2e-core/chat-ui";

const previous = "00000000-0000-4000-8000-000000000001";
const current = "00000000-0000-4000-8000-000000000002";

test("Turn completion ignores the previous terminal state and unfinished current work", async ({ page }) => {
  await page.setContent(`<section data-turn-id="${current}"><footer class="chat-response-footer"><time>done</time></footer></section>`);
  const states = [{ id: previous, status: "completed" }, { id: current, status: "running" }, { id: current, status: "completed" }];
  let observedCompletion = false;
  const fake = {
    url: () => `http://test.invalid/chat?session=${previous}`,
    request: { get: async (_url: string, options: { headers: { origin: string } }) => {
      expect(options.headers.origin).toBe("http://test.invalid");
      const turn = states.shift()!;
      observedCompletion = turn.id === current && turn.status === "completed";
      return { ok: () => true, json: async () => ({ latest_turn: turn, current_turn: null }) };
    } },
    locator: (selector: string) => page.locator(selector),
  } as unknown as Page;
  await waitForChatTurn(fake, current);
  expect(observedCompletion).toBe(true);
});

for (const status of ["running", "failed"]) {
  test(`Turn completion rejects a current Turn that remains ${status}`, async () => {
    const fake = {
      url: () => `http://test.invalid/chat?session=${previous}`,
      request: { get: async () => ({ ok: () => true, json: async () => ({ latest_turn: { id: current, status } }) }) },
    } as unknown as Page;
    await expect(waitForChatTurn(fake, current, "completed", 100)).rejects.toThrow(`last=${status}`);
  });
}

test("Turn wait tolerates a delayed Session URL without reading the wrong Session", async ({ page }) => {
  await page.setContent(`<section data-turn-id="${current}"><footer class="chat-response-footer"><time>done</time></footer></section>`);
  let reads = 0;
  const fake = {
    url: () => ++reads < 3 ? "http://test.invalid/chat" : `http://test.invalid/chat?session=${previous}`,
    request: { get: async (url: string, options: { timeout: number }) => {
      expect(url).toBe(`/api/agent/sessions/${previous}`);
      expect(options.timeout).toBeGreaterThan(0);
      expect(options.timeout).toBeLessThanOrEqual(3000);
      return { ok: () => true, json: async () => ({ latest_turn: { id: current, status: "completed" } }) };
    } },
    locator: (selector: string) => page.locator(selector),
  } as unknown as Page;
  await waitForChatTurn(fake, current, "completed", 3000);
});

test("Answer recovery can finish the same accepted Turn", async ({ page }) => {
  await page.setContent(`<section data-turn-id="${current}"><footer class="chat-response-footer"><time>done</time></footer></section>`);
  let status = "waiting_for_user";
  const fake = {
    url: () => `http://test.invalid/chat?session=${previous}`,
    request: { get: async () => ({ ok: () => true, json: async () => ({ latest_turn: { id: current, status } }) }) },
    locator: (selector: string) => page.locator(selector),
  } as unknown as Page;
  await waitForChatTurn(fake, current, "waiting_for_user");
  status = "completed";
  await waitForChatTurn(fake, current);
});
