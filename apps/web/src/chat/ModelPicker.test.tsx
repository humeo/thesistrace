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
import { ChatUiProvider } from "./ChatUiProvider";
import { decodeAgentModelCatalog } from "./modelCatalog";

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let root: Root | undefined;

afterEach(async () => {
  await act(async () => root?.unmount());
  root = undefined;
  document.body.replaceChildren();
  vi.restoreAllMocks();
});

test("offers only the configured GPT-6.1 Sol and maps its supported efforts to Max", async () => {
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
  await act(async () => document.querySelector<HTMLButtonElement>('button[aria-haspopup="dialog"]')!.click());
  const choices = [...document.querySelectorAll<HTMLInputElement>('input[type="radio"]')];
  expect(choices.map((choice) => choice.getAttribute("aria-label"))).toEqual(["GPT-6.1 Sol"]);
  expect(choices[0]?.checked).toBe(true);
  const slider = document.querySelector<HTMLInputElement>('[role="slider"]')!;
  expect(slider.getAttribute("aria-valuemin")).toBe("0");
  expect(slider.getAttribute("aria-valuemax")).toBe("4");
  expect(slider.getAttribute("aria-valuetext")).toBe("High");
  await act(async () => slider.dispatchEvent(new KeyboardEvent("keydown", { bubbles: true, key: "End", keyCode: 35 })));
  expect(onReasoningChange).toHaveBeenCalledWith("max");
  expect(document.querySelector('[role="dialog"]')).not.toBeNull();
});

test("updates the reasoning range when switching models and keeps the picker open while adjusting", async () => {
  await mount();
  const trigger = document.querySelector<HTMLButtonElement>('button[aria-haspopup="dialog"]')!;
  await act(async () => trigger.click());

  const menu = document.querySelector<HTMLElement>('[role="dialog"]')!;
  const sol = [...menu.querySelectorAll<HTMLInputElement>('input[type="radio"]')]
    .find((button) => button.getAttribute("aria-label") === "GPT-5.6 Sol")!;
  await act(async () => sol.click());
  expect(document.querySelector('[role="dialog"]')).not.toBeNull();
  expect(trigger.textContent).toContain("GPT-5.6 Sol");
  expect(trigger.textContent).toContain("X-high");

  const slider = document.querySelector<HTMLInputElement>('[role="slider"]')!;
  expect(slider.getAttribute("aria-valuetext")).toBe("X-high");
  await act(async () => slider.dispatchEvent(new KeyboardEvent("keydown", { bubbles: true, key: "Home", keyCode: 36 })));
  expect(slider.getAttribute("aria-valuetext")).toBe("Medium");
  expect(document.querySelector('[role="dialog"]')).not.toBeNull();
  expect(trigger.textContent).toContain("Medium");
});

test("supports keyboard opening, horizontal reasoning navigation, and Escape focus restoration", async () => {
  await mount();
  const trigger = document.querySelector<HTMLButtonElement>('button[aria-haspopup="dialog"]')!;
  trigger.focus();
  await act(async () => trigger.dispatchEvent(new KeyboardEvent("keydown", { bubbles: true, key: "ArrowDown" })));
  await act(async () => new Promise<void>((resolve) => requestAnimationFrame(() => resolve())));
  const selectedModel = document.querySelector<HTMLButtonElement>(
    'input[type="radio"]:checked',
  )!;
  expect(document.activeElement).toBe(selectedModel);

  const selectedReasoning = document.querySelector<HTMLInputElement>('[role="slider"]')!;
  await act(async () => selectedReasoning.focus());
  await act(async () => selectedReasoning.dispatchEvent(new KeyboardEvent("keydown", { bubbles: true, key: "ArrowLeft", keyCode: 37 })));
  expect(selectedReasoning.getAttribute("aria-valuetext")).toBe("Medium");
  expect(document.activeElement).toBe(selectedReasoning);
  await act(async () => document.activeElement?.dispatchEvent(new KeyboardEvent("keydown", { bubbles: true, key: "Escape" })));
  expect(trigger.getAttribute("aria-expanded")).toBe("false");
  expect(document.activeElement).toBe(trigger);
});

test("shows a fixed effort without an adjustable range when the model supports only one effort", async () => {
  const fixedCatalog: AgentModelCatalog = {
    default_model_key: "fixed",
    models: [{ key: "fixed", display_name: "Fixed model", default_reasoning_effort: "medium", reasoning_efforts: ["medium"] }],
  };
  const onReasoningChange = vi.fn();
  await mount(<ModelPicker catalog={fixedCatalog} onModelChange={vi.fn()} onReasoningChange={onReasoningChange}
    selection={resolveModelSelection(fixedCatalog, "fixed", null)} />);
  await act(async () => document.querySelector<HTMLButtonElement>('button[aria-haspopup="dialog"]')!.click());
  expect(document.querySelector('[role="dialog"]')?.textContent).toContain("Medium");
  expect(document.querySelector('[role="slider"]')).toBeNull();
  expect(onReasoningChange).not.toHaveBeenCalled();
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
  const trigger = document.querySelector<HTMLButtonElement>('button[aria-haspopup="dialog"]')!;
  trigger.focus();
  await act(async () => trigger.dispatchEvent(new KeyboardEvent("keydown", { bubbles: true, key: "ArrowDown" })));
  await act(async () => new Promise<void>((resolve) => requestAnimationFrame(() => resolve())));

  expect(document.activeElement).toBe(document.querySelector('input[type="radio"]'));
});

async function mount(element: ReactNode = <Harness />): Promise<void> {
  const container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  await act(async () => root?.render(<ChatUiProvider>{element}</ChatUiProvider>));
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
    reasoning_efforts: ["xhigh", "medium"],
  }],
};
