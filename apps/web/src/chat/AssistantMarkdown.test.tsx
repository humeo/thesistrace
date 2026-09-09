import { renderToStaticMarkup } from "react-dom/server";
import { expect, test } from "vitest";
import { AssistantMarkdown } from "./ChatTimeline";

test.each([false, true])("renders CJK emphasis next to punctuation and text (streaming=%s)", streaming => {
  const content = "- **Daily Track 数量：**1\n- **数据截至：**2026-08-27\n- **原始研究记录：**仍关联至";
  const html = renderToStaticMarkup(<AssistantMarkdown content={content} streaming={streaming} />);
  expect(html).toContain("<strong>Daily Track 数量：</strong>1");
  expect(html).toContain("<strong>数据截至：</strong>2026-08-27");
  expect(html).toContain("<strong>原始研究记录：</strong>仍关联至");
});

test("preserves literal code and escaped emphasis", () => {
  const content = "`**数据截至：**2026`\n\n```text\n**数据截至：**2026\n```\n\n\\*\\*数据截至：\\*\\*2026";
  const html = renderToStaticMarkup(<AssistantMarkdown content={content} />);
  expect(html).not.toContain("<strong>");
  expect(html).toContain("<code>**数据截至：**2026</code>");
  expect(html.match(/\*\*数据截至：\*\*2026/g)).toHaveLength(3);
});

test("preserves GFM tables, English emphasis and incomplete streaming delimiters", () => {
  const content = "| Name | Value |\n| --- | --- |\n| **Status** | **状态：**正常 |";
  const html = renderToStaticMarkup(<AssistantMarkdown content={content} />);
  expect(html).toContain("<table>");
  expect(html).toContain("<strong>Status</strong>");
  expect(html).toContain("<strong>状态：</strong>正常");
  expect(renderToStaticMarkup(<AssistantMarkdown content="**数据截至：" streaming />)).not.toContain("<strong>");
});
