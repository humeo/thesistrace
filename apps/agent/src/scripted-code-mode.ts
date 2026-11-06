import type { LanguageModelV3CallOptions } from "@ai-sdk/provider";
import { CODE_MODE_READ_TOOLS, CODE_MODE_TOOL_NAME } from "./code-mode-activity.js";
import { codeModeReadThroughBatch, readCodeModeReadThrough, type CodeModeReadThrough } from "./code-mode-read-through.js";
import { latestUserText, toolObservations, type ScriptedResearchDecision } from "./scripted-research-support.js";

const reads = new Set<string>(CODE_MODE_READ_TOOLS);
type ToolPart = Extract<LanguageModelV3CallOptions["prompt"][number], { role: "tool" }>["content"][number];

export function scriptedCodeModeDecision(options: LanguageModelV3CallOptions): ScriptedResearchDecision | null {
  const user = latestUserText(options);
  if (!user || !/^\[scripted-code-mode(?:-stop)?\]/.test(user.text)) return null;
  const observed = toolObservations(options, user.index).find(item => item.name === CODE_MODE_TOOL_NAME);
  if (observed) return { kind: "text", text: observed.output.success === true
    ? "Compared 2 authenticated reads in one program." : "Code Mode did not complete." };
  return { kind: "tool", name: CODE_MODE_TOOL_NAME, input: { code: user.text.startsWith("[scripted-code-mode-stop]")
    ? 'await external_get_research_context({}); while (true) {}'
    : 'console.log("private-code-mode-console-canary"); const rows = await Promise.all([external_get_research_context({}), external_get_alpha_catalog({kind: "fields"})]); return {readCount: rows.length};',
  } };
}

/** The deterministic Provider emits real Code Mode calls, without executing fixture code itself. */
export function scriptedCodeModeCall(call: Readonly<{ name: string; input: Record<string, unknown> }>) {
  return reads.has(call.name)
    ? { name: CODE_MODE_TOOL_NAME, input: { code: `return await external_${call.name}(${JSON.stringify(call.input)});` } }
    : call;
}

export function scriptedReadCall(toolCallId: string) {
  const call = scriptedCodeModeCall({ name: "get_research_context", input: {} });
  return { type: "tool-call" as const, toolCallId, toolName: call.name, input: JSON.stringify(call.input) };
}

export function scriptedCodeModeBatch(calls: readonly { name: string; input: Record<string, unknown> }[]) {
  return { name: CODE_MODE_TOOL_NAME, input: { code: codeModeReadThroughBatch(calls) } };
}

export function scriptedCodeModeReads(input: unknown): Array<{ name: string; input: Record<string, unknown> }> {
  return readCodeModeReadThrough(input)?.calls ?? [];
}

/** Decode only this fixture's fixed single-read program, never arbitrary JavaScript. */
export function scriptedCodeModeRead(input: unknown): { name: string; input: Record<string, unknown> } | undefined {
  const calls = readCodeModeReadThrough(input)?.calls ?? [];
  return calls.length === 1 ? calls[0] : undefined;
}

/** Present business observations to fixture decisions; persistent model history stays untouched. */
export function scriptedCodeModeOptions(options: LanguageModelV3CallOptions): LanguageModelV3CallOptions {
  const calls = new Map<string, CodeModeReadThrough>();
  const prompt = options.prompt.map(message => {
    if (message.role === "assistant") return { ...message, content: message.content.flatMap(part => {
      if (part.type !== "tool-call" || part.toolName !== CODE_MODE_TOOL_NAME) return [part];
      const program = readCodeModeReadThrough(part.input);
      if (!program) return [part];
      calls.set(part.toolCallId, program);
      return program.calls.map((read, index) => ({ ...part, toolCallId: `${part.toolCallId}:read:${index}`, toolName: read.name, input: read.input }));
    }) };
    if (message.role === "tool") return { ...message, content: message.content.flatMap<ToolPart>(part => {
      if (part.type !== "tool-result") return [part];
      const program = calls.get(part.toolCallId);
      if (!program || part.output.type !== "json" || !part.output.value || typeof part.output.value !== "object" || Array.isArray(part.output.value)) return [part];
      const envelope = part.output.value;
      const results = program.kind === "batch" ? envelope.result : [envelope.result];
      const values = Array.isArray(results) ? results : [];
      if (envelope.success === true && values.length !== program.calls.length) return [part];
      return program.calls.map((read, index) => ({ ...part, toolCallId: `${part.toolCallId}:read:${index}`, toolName: read.name,
        output: { type: "json" as const, value: envelope.success === true
          ? values[index] ?? null : envelope } }));
    }) };
    return message;
  });
  const instructions = options.prompt.filter(message => message.role === "system").map(message => message.content).join("\n");
  const declarations = CODE_MODE_READ_TOOLS.filter(name => instructions.includes(`declare function external_${name}(`));
  return { ...options, prompt, tools: [...(options.tools ?? []), ...declarations.map(name => ({
    type: "function" as const, name, inputSchema: { type: "object" as const, properties: {} },
  }))] };
}
