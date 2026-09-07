// @vitest-environment happy-dom

import { act, useState, type ReactNode } from "react";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, expect, test, vi } from "vitest";

import { resolveModelSelection } from "./chatState";
import type { AgentModelCatalog } from "./modelCatalog";
import { ModelPicker } from "./ModelPicker";
import { decodeAgentModelCatalog } from "./modelCatalog";

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let root: Root | undefined;

afterEach(async () => {
  await act(async () => root?.unmount());
  root = undefined;
  document.body.replaceChildren();
  vi.restoreAllMocks();
});

test("shows all configured Luna efforts and selects Max", async () => {
  const configured = JSON.parse(readFileSync(
    resolve(dirname(fileURLToPath(import.meta.url)), "../../../agent/config/model-registry.json"), "utf8",
  ));
  const current = decodeAgentModelCatalog({
    default_model_key: configured.default_model_key,
    models: configured.models.filter((model: { enabled: boolean }) => model.enabled)
      .map(({ key, display_name, default_reasoning_effort, reasoning_efforts }: AgentModelCatalog["models"][number]) =>
        ({ key, display_name, default_reasoning_effort, reasoning_efforts })),
  });
  const onReasoningChange = vi.fn();
  await mount(<ModelPicker catalog={current} onModelChange={vi.fn()}
    onReasoningChange={onReasoningChange}
    selection={resolveModelSelection(current, current.default_model_key, null)} />);
  await act(async () => document.querySelector<HTMLButtonElement>(".chat-model-picker-trigger")!.click());
  const options = [...document.querySelectorAll<HTMLButtonElement>('[data-picker-column="reasoning"]')];
  expect(options.map((button) => button.textContent)).toEqual(["None", "Low", "Medium", "High", "X-high", "Max"]);
  await act(async () => options[5].click());
  expect(onReasoningChange).toHaveBeenCalledWith("max");
  expect(document.querySelector('[role="dialog"]')).toBeNull();
});

test("keeps a two-column picker open for Model, then closes and restores focus for Reasoning", async () => {
  await mount();
  const trigger = document.querySelector<HTMLButtonElement>(".chat-model-picker-trigger")!;
  await act(async () => trigger.click());

  const menu = document.querySelector<HTMLElement>('[role="dialog"]')!;
  expect(menu.querySelectorAll('.chat-model-picker-column[role="group"]')).toHaveLength(2);
  const sol = [...menu.querySelectorAll<HTMLButtonElement>('[data-picker-column="model"]')]
    .find((button) => button.textContent?.includes("GPT-5.6 Sol"))!;
  await act(async () => sol.click());
  expect(document.querySelector('[role="dialog"]')).not.toBeNull();
  expect(trigger.textContent).toContain("GPT-5.6 Sol");
  expect(trigger.textContent).toContain("X-high");

  const medium = [...document.querySelectorAll<HTMLButtonElement>('[data-picker-column="reasoning"]')]
    .find((button) => button.textContent?.includes("Medium"))!;
  await act(async () => medium.click());
  expect(document.querySelector('[role="dialog"]')).toBeNull();
  expect(document.activeElement).toBe(trigger);
  expect(trigger.textContent).toContain("Medium");
});

test("supports keyboard opening, column movement, and Escape focus restoration", async () => {
  await mount();
  const trigger = document.querySelector<HTMLButtonElement>(".chat-model-picker-trigger")!;
  trigger.focus();
  await act(async () => trigger.dispatchEvent(new KeyboardEvent("keydown", { bubbles: true, key: "ArrowDown" })));
  await act(async () => new Promise<void>((resolve) => requestAnimationFrame(() => resolve())));
  const selectedModel = document.querySelector<HTMLButtonElement>(
    '[data-picker-column="model"][aria-pressed="true"]',
  )!;
  expect(document.activeElement).toBe(selectedModel);

  await act(async () => selectedModel.dispatchEvent(new KeyboardEvent("keydown", { bubbles: true, key: "ArrowRight" })));
  expect((document.activeElement as HTMLElement)?.dataset.pickerColumn).toBe("reasoning");
  await act(async () => document.activeElement?.dispatchEvent(new KeyboardEvent("keydown", { bubbles: true, key: "Escape" })));
  expect(document.querySelector('[role="dialog"]')).toBeNull();
  expect(document.activeElement).toBe(trigger);
});

test("focuses the first Model when a removed selection must be replaced", async () => {
  await mount(
    <ModelPicker
      catalog={catalog}
      onModelChange={vi.fn()}
      onReasoningChange={vi.fn()}
      selection={null}
    />,
  );
  const trigger = document.querySelector<HTMLButtonElement>(".chat-model-picker-trigger")!;
  trigger.focus();
  await act(async () => trigger.dispatchEvent(new KeyboardEvent("keydown", { bubbles: true, key: "ArrowDown" })));
  await act(async () => new Promise<void>((resolve) => requestAnimationFrame(() => resolve())));

  expect(document.activeElement).toBe(document.querySelector('[data-picker-column="model"]'));
});

async function mount(element: ReactNode = <Harness />): Promise<void> {
  const container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  await act(async () => root?.render(element));
}

function Harness() {
  const [modelKey, setModelKey] = useState("luna");
  const [reasoning, setReasoning] = useState<string | null>("high");
  const selection = resolveModelSelection(catalog, modelKey, reasoning);
  return (
    <ModelPicker
      catalog={catalog}
      onModelChange={(model) => {
        setModelKey(model);
        setReasoning(null);
      }}
      onReasoningChange={setReasoning}
      selection={selection}
    />
  );
}

const catalog: AgentModelCatalog = {
  default_model_key: "luna",
  models: [{
    default_reasoning_effort: "high",
    display_name: "GPT-5.6 Luna",
    key: "luna",
    reasoning_efforts: ["medium", "high"],
  }, {
    default_reasoning_effort: "xhigh",
    display_name: "GPT-5.6 Sol",
    key: "sol",
    reasoning_efforts: ["medium", "xhigh"],
  }],
};
