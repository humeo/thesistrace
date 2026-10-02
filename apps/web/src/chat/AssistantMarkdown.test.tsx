// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, expect, test } from "vitest";
import { AssistantMarkdown } from "./ChatTimeline";
(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let root: Root;
afterEach(async () => { await act(async () => root?.unmount()); document.body.replaceChildren(); });
async function render(content: string, streaming = false) {
  const container = document.createElement("div"); document.body.append(container); root = createRoot(container);
  await act(async () => root.render(<AssistantMarkdown content={content} streaming={streaming} />));
  return container;
}
test.each([false, true])("native Markdown renders CJK emphasis next to text (streaming=%s)", async streaming => {
  const container = await render("- **Daily Track 数量：**1\n- **数据截至：**2026-08-27\n- **原始研究记录：**仍关联至", streaming);
  expect(container.querySelector(".x-markdown")).not.toBeNull();
  expect([...container.querySelectorAll('strong')].map(element => element.textContent)).toEqual(["Daily Track 数量：", "数据截至：", "原始研究记录："]);
  expect(container.textContent).toContain("数量：1");
});
test("native Markdown preserves literal code and escaped emphasis", async () => {
  const container = await render("`**数据截至：**2026`\n\n```text\n**数据截至：**2026\n```\n\n\\*\\*数据截至：\\*\\*2026");
  expect(container.querySelector('strong')).toBeNull();
  expect(container.querySelector("code")?.textContent).toBe("**数据截至：**2026");
  expect(container.textContent).toContain("**数据截至：**2026");
});
test("native Markdown supports GFM tables and English emphasis", async () => {
  const container = await render("| Name | Value |\n| --- | --- |\n| **Status** | **状态：**正常 |");
  expect(container.querySelector("table")).not.toBeNull();
  expect([...container.querySelectorAll('strong')].map(element => element.textContent)).toEqual(["Status", "状态："]);
});
test("native Markdown retains approved links while omitting raw HTML and images", async () => {
  const container = await render("### Research completed\n\n[Open ResearchRun](/research-runs/run_0123456789abcdef0123)\n[External](https://example.com/private)\n![remote](https://example.com/pixel.png)\n<script>alert(\"unsafe\")</script>");
  expect(container.textContent).toContain("Research completed");
  expect(container.querySelector("a")?.getAttribute("href")).toBe("/research-runs/run_0123456789abcdef0123");
  expect(container.textContent).toContain("External");
  expect(container.querySelector('img,script,a[href^="https:"]')).toBeNull();
});
test("native Markdown replaces prior content with a research link", async () => {
  const container = await render("**数据截至：**2026-08-27\n\n`**原文：**保持`");
  await act(async () => root.render(<AssistantMarkdown content="[X](/research-runs/run_0123456789abcdef0123)" />));
  expect(container.querySelector("a")?.getAttribute("href")).toBe("/research-runs/run_0123456789abcdef0123");
});
