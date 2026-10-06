import { expect, test } from './workbench-fixture';
import type { Page } from '@playwright/test';

const A = '00000000-0000-4000-8000-000000000111';
const B = '00000000-0000-4000-8000-000000000112';
test.use({ viewport: { width: 1440, height: 960 } });

const time = '2026-10-06T00:00:00.000000Z';

async function install(page: Page, running = false, longHistory = false) {
  let complete = !running;
  let holdA = false;
  let releaseA = () => {};
  let held = Promise.resolve();
  const requests: { method: string; path: string }[] = [];
  const summary = (id: string) => {
    const status = id === A && !complete ? 'running' : 'completed';
    const turn = { id: id === A ? '00000000-0000-4000-8000-000000000211' : '00000000-0000-4000-8000-000000000212',
      kind: 'prompt', model_key: 'fixture', reasoning_effort: 'medium', question: null,
      status, started_at: time, terminal_error_code: null };
    return { id, title: id === A ? 'Chat A' : 'Chat B', message_title: null,
      activity_at: time, created_at: time, version: complete ? '2026-10-06T00:00:01.000Z' : '2026-10-06T00:00:00.000Z',
      current_turn: status === 'running' ? turn : null, latest_turn: turn };
  };
  await page.route('https://workbench.fixture/api/agent/**', async route => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    requests.push({ method: route.request().method(), path });
    if (path === '/api/agent/models') return route.fulfill({ json: { default_model_key: 'fixture', models: [
      { key: 'fixture', display_name: 'Fixture', default_reasoning_effort: 'medium', reasoning_efforts: ['medium'] },
    ] } });
    if (path === '/api/agent/context-window') return route.fulfill({ json: {
      model_key: 'fixture', context_window: 128000, input_tokens: 100, measured_at: time,
    } });
    if (path === '/api/agent/copilotkit/info') return route.fulfill({ json: {
      version: '1.70.0', agents: { research: { name: 'research', description: 'Diagnostic fixture' } },
    } });
    if (path === '/api/agent/sessions') return route.fulfill({ json: { sessions: [summary(B), summary(A)], next_cursor: null } });
    for (const id of [A, B]) {
      if (path === `/api/agent/sessions/${id}/preferences`) return route.fulfill({ json: {
        model_key: 'fixture', reasoning_effort: 'medium', selection_mode: 'manual',
      } });
      if (path === `/api/agent/sessions/${id}`) return route.fulfill({ json: summary(id) });
      if (path === `/api/agent/sessions/${id}/timeline`) {
        if (id === A && holdA) await held;
        const session = summary(id);
        const turn = session.latest_turn;
        return route.fulfill({ json: { next_cursor: null, turns: [{
          id: turn.id, status: turn.status, started_at: time, completed_at: turn.status === 'running' ? null : time,
          entries: [
            { entry_id: `prompt-${id}`, turn_id: turn.id, created_at: time, kind: 'user_input',
              payload: { content: id === A ? 'Question A' : 'Question B', inputId: id, source: 'prompt' } },
            { entry_id: `answer-${id}`, turn_id: turn.id, created_at: time, kind: 'assistant_message',
              payload: { content: id === A ? (complete ? 'Answer A complete' : 'Answer A pending')
                + (longHistory ? Array.from({ length: 40 }, (_, index) => `\n\nHistory paragraph ${index + 1}. This is a deterministic conversation reading-position fixture.`).join('') : '')
                : 'Answer B complete',
                status: turn.status === 'running' ? 'streaming' : 'complete' } },
          ],
        }] } });
      }
    }
    return route.fallback();
  });
  const open = async (id: string) => {
    await page.locator(`a[href="/chat?session=${id}"]`).click();
    await expect(page.getByText(id === A ? (complete ? 'Answer A complete' : 'Answer A pending') : 'Answer B complete', { exact: true })).toBeVisible();
  };
  return { requests, open, finish: () => { complete = true; }, hold: () => {
    holdA = true; held = new Promise<void>(resolve => { releaseA = resolve; });
  }, release: () => { holdA = false; releaseA(); } };
}

test('repeated and rapid conversation switches keep messages isolated', async ({ page }, info) => {
  const fixture = await install(page);
  await page.goto(`/chat?session=${A}`);
  await expect(page.getByText('Answer A complete', { exact: true })).toBeVisible();
  for (let index = 0; index < 3; index++) {
    await fixture.open(B);
    await expect(page.getByText('Answer A complete', { exact: true })).toHaveCount(0);
    await fixture.open(A);
    await expect(page.getByText('Answer B complete', { exact: true })).toHaveCount(0);
  }
  for (let index = 0; index < 3; index++) {
    await page.locator(`a[href="/chat?session=${B}"]`).click();
    await page.locator(`a[href="/chat?session=${A}"]`).click();
    await expect(page.getByText('Answer A complete', { exact: true })).toBeVisible();
    await expect(page.getByText('Answer B complete', { exact: true })).toHaveCount(0);
  }
  await info.attach('session-reads', { body: JSON.stringify(fixture.requests), contentType: 'application/json' });
  await page.screenshot({ path: info.outputPath('switch-isolation.png') });
});

test('switching during a delayed timeline cannot display the abandoned conversation', async ({ page }) => {
  const fixture = await install(page);
  await page.goto(`/chat?session=${A}`);
  await expect(page.getByText('Answer A complete', { exact: true })).toBeVisible();
  await fixture.open(B);
  fixture.hold();
  try {
    const started = page.waitForRequest(request => new URL(request.url()).pathname === `/api/agent/sessions/${A}/timeline`);
    await page.locator(`a[href="/chat?session=${A}"]`).click();
    await started;
    await expect(page.getByRole('main', { name: 'Chat A', exact: true })).toBeVisible();
    await expect(page.getByText('Answer A complete', { exact: true })).toBeVisible();
    await fixture.open(B);
    fixture.release();
    await expect(page.getByText('Answer B complete', { exact: true })).toBeVisible();
    await expect(page.getByText('Answer A complete', { exact: true })).toHaveCount(0);
    await expect(page).toHaveURL(`/chat?session=${B}`);
  } finally { fixture.release(); }
});

test('a running conversation can finish while another conversation is selected', async ({ page }) => {
  const fixture = await install(page, true);
  await page.goto(`/chat?session=${A}`);
  await expect(page.getByText('Answer A pending', { exact: true })).toBeVisible();
  await fixture.open(B);
  fixture.finish();
  await fixture.open(A);
  await expect(page.getByText('Answer A complete', { exact: true })).toBeVisible();
  await expect(page.getByText('Answer B complete', { exact: true })).toHaveCount(0);
  expect(fixture.requests.filter(request => request.method !== 'GET')).toEqual([]);
});

test('unsent input remains in its original conversation after a round trip', async ({ page }, info) => {
  const fixture = await install(page);
  await page.goto(`/chat?session=${A}`);
  await expect(page.getByText('Answer A complete', { exact: true })).toBeVisible();
  await page.getByRole('textbox', { name: 'Message', exact: true }).fill('Unsent draft A');
  await fixture.open(B);
  await expect(page.getByRole('textbox', { name: 'Message', exact: true })).toHaveValue('');
  await page.getByRole('textbox', { name: 'Message', exact: true }).fill('Unsent draft B');
  await fixture.open(A);
  await page.screenshot({ path: info.outputPath('draft-after-return.png') });
  await expect(page.getByRole('textbox', { name: 'Message', exact: true })).toHaveValue('Unsent draft A');
  await fixture.open(B);
  await expect(page.getByRole('textbox', { name: 'Message', exact: true })).toHaveValue('Unsent draft B');
});

test('reading position remains in its original conversation after a round trip', async ({ page }, info) => {
  const fixture = await install(page, false, true);
  await page.goto(`/chat?session=${A}`);
  await expect(page.getByText('Answer A complete', { exact: true })).toBeVisible();
  const viewport = page.locator('.ant-bubble-list-scroll-box');
  await expect.poll(() => viewport.evaluate(el => el.scrollHeight - el.clientHeight)).toBeGreaterThan(900);
  await viewport.hover();
  await page.mouse.wheel(0, -900);
  await expect.poll(() => viewport.evaluate(el => el.scrollTop)).toBeLessThan(-500);
  const previous = await viewport.evaluate(el => el.scrollTop);
  await page.screenshot({ path: info.outputPath('reading-before-switch.png') });
  await fixture.open(B);
  await fixture.open(A);
  await expect.poll(() => viewport.evaluate(el => el.scrollHeight - el.clientHeight)).toBeGreaterThan(900);
  await page.screenshot({ path: info.outputPath('reading-after-return.png') });
  await expect.poll(() => viewport.evaluate(el => el.scrollTop)).toBeCloseTo(previous, 0);
});

test('reopening a conversation preserves content and composer while current facts are delayed', async ({ page }, info) => {
  const fixture = await install(page);
  await page.goto(`/chat?session=${A}`);
  const input = page.getByRole('textbox', { name: 'Message', exact: true });
  await expect(input).toBeEnabled();
  await expect(page.getByText('Answer A complete', { exact: true })).toBeVisible();
  const before = await page.locator('.ant-sender').boundingBox();
  await input.fill('Draft to keep while refreshing');
  await fixture.open(B);
  let release = () => {};
  const pending = new Promise<void>(resolve => { release = resolve; });
  await page.route('https://workbench.fixture/api/agent/**', async route => {
    await pending;
    await route.fallback();
  });
  try {
    await page.locator(`a[href="/chat?session=${A}"]`).click();
    await expect(page.getByText('Answer A complete', { exact: true })).toBeVisible();
    await expect(input).toBeEnabled();
    await expect(input).toHaveValue('Draft to keep while refreshing');
    await expect(page.getByRole('button', { name: 'Model Fixture, reasoning Medium', exact: true })).toBeVisible();
    expect(await page.locator('.ant-sender').boundingBox()).toEqual(before);
    await expect(page.getByText('Loading Session settings…', { exact: true })).toHaveCount(0);
    await page.screenshot({ path: info.outputPath('warm-conversation.png') });
  } finally { release(); }
});

test('first opening keeps the composer height stable while settings arrive', async ({ page }) => {
  await install(page);
  let release = () => {};
  const pending = new Promise<void>(resolve => { release = resolve; });
  await page.route(`https://workbench.fixture/api/agent/sessions/${A}/preferences`, async route => {
    await pending;
    await route.fallback();
  });
  try {
    await page.goto(`/chat?session=${A}`);
    await expect(page.getByText('Loading Session settings…', { exact: true })).toBeVisible();
    const opening = await page.locator('.ant-sender').boundingBox();
    release();
    await expect(page.getByRole('textbox', { name: 'Message', exact: true })).toBeEnabled();
    await expect(page.getByText('Answer A complete', { exact: true })).toBeVisible();
    expect(await page.locator('.ant-sender').boundingBox()).toEqual(opening);
  } finally { release(); }
});
