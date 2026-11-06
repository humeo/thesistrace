import { expect, it } from "vitest";
import { scriptedCodeModeBatch, scriptedCodeModeOptions } from "./scripted-code-mode.js";

it("retains one-read batch output when only one paginated fixture query remains", () => {
  const call = scriptedCodeModeBatch([{ name: "get_alpha_catalog", input: { kind: "fields", cursor: "last" } }]);
  const options = scriptedCodeModeOptions({ prompt: [
    { role: "assistant", content: [{ type: "tool-call", toolCallId: "last", toolName: call.name, input: call.input }] },
    { role: "tool", content: [{ type: "tool-result", toolCallId: "last", toolName: call.name,
      output: { type: "json", value: { success: true, result: [{ items: [], next_cursor: null }], logs: [] } } }] },
  ] });
  expect(options.prompt[1]).toMatchObject({ role: "tool", content: [{ toolName: "get_alpha_catalog",
    output: { type: "json", value: { items: [], next_cursor: null } } }] });
});
