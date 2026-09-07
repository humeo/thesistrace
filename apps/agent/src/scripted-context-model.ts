import { randomUUID } from "node:crypto";
import type { LanguageModelV3CallOptions, LanguageModelV3StreamPart } from "@ai-sdk/provider";
import { isRecord, latestUserText, textContent, toolObservations } from "./scripted-research-support.js";

/** Deterministic browser cases still traverse the real controller, store and Tool boundary. */
export function scriptedContextStream(options: LanguageModelV3CallOptions): { stream: ReadableStream<LanguageModelV3StreamPart> } | undefined {
  const instructions = options.prompt.filter(message => message.role === "system").map(message => textContent(message.content)).join("\n");
  if (instructions.includes("You are the memory consciousness") || instructions.includes("Your memory observation reflections")) {
    if (latestUserText(options)?.text.includes("[scripted-observer-await-cancel]")) return awaitCancellation(options.abortSignal);
    return stream("<observations></observations>", "stop");
  }
  if (instructions.includes("Produce a structured handoff summary")) {
    const content = latestUserText(options)?.text ?? "";
    const jsonStart = content.indexOf("\n{");
    if (jsonStart < 0) throw new Error("SCRIPTED_CONTEXT_SOURCE_MISSING");
    const payload: unknown = JSON.parse(content.slice(jsonStart + 1));
    if (!payload || typeof payload !== "object" || !("requiredReferences" in payload)
      || !Array.isArray(payload.requiredReferences) || !payload.requiredReferences.every(value => typeof value === "string")) {
      throw new Error("SCRIPTED_CONTEXT_REFERENCES_INVALID");
    }
    return stream(["## Goal", "Scripted context checkpoint.", "## Constraints and preferences", "Keep existing research.",
      "## Progress", "Completed: retain earlier evidence. In progress: the current request. Blockers: none.",
      "## Key decisions", "Use authoritative Core results.", "## Next steps", "1. Continue the current request.",
      "## Critical context", payload.requiredReferences.join(" ") || "Fixed synthetic browser evidence."].join("\n"), "stop");
  }
  const user = latestUserText(options);
  if (!user) return undefined;
  if (user.text.startsWith("[scripted-context-recovery]") || user.text.startsWith("[scripted-context-recovery-fails]")) {
    const restored = instructions.includes("Scripted context checkpoint.");
    if (restored && user.text.startsWith("[scripted-context-recovery]")) return stream("The complete replacement answer uses the compacted Session.", "stop");
    return stream("This is the retained partial answer.", "length", [{ name: "get_research_context", input: {} }]);
  }
  if (user.text.startsWith("[scripted-context-tool-batch]")) {
    const observed = toolObservations(options, user.index);
    const pending: Array<{ name: string; input: Record<string, unknown> }> = [];
    for (const name of ["get_research_context", "get_alpha_catalog"]) {
      if (!options.tools?.some(tool => tool.type === "function" && tool.name === name)) throw new Error("SCRIPTED_CONTEXT_TOOL_MISSING");
      const pages = observed.filter(result => result.name === name);
      if (!pages.length) pending.push({ name, input: {} });
      else if (pages.length === 1) {
        const output = pages[0]!.output;
        const collection = name === "get_research_context" ? output.folders : output;
        if (!isRecord(collection)) throw new Error("SCRIPTED_CONTEXT_PAGE_INVALID");
        const cursor = collection.next_cursor;
        if (typeof cursor === "string") pending.push({ name, input: { [name === "get_research_context" ? "folder_cursor" : "cursor"]: cursor } });
      }
    }
    return pending.length ? stream("", "tool-calls", pending)
      : stream("I read bounded Core folder and catalog pages, continued their cursors after compaction, and retained any further-page indicators.", "stop");
  }
  if (!user.text.startsWith("[scripted-context-normal]")) return undefined;
  if (!options.tools?.some(tool => tool.type === "function" && tool.name === "get_research_context")) throw new Error("SCRIPTED_CONTEXT_TOOL_MISSING");
  if (!toolObservations(options, user.index).some(result => result.name === "get_research_context")) return stream("", "tool-calls", [{ name: "get_research_context", input: {} }]);
  return stream("I continued after compaction and read the current Core research context.", "stop");
}

function stream(text: string, reason: "stop" | "length" | "tool-calls", tools: readonly { name: string; input: Record<string, unknown> }[] = []) {
  const id = "scripted-context";
  const parts: LanguageModelV3StreamPart[] = [{ type: "stream-start", warnings: [] }];
  if (text) parts.push({ type: "text-start", id }, { type: "text-delta", id, delta: text }, { type: "text-end", id });
  for (const tool of tools) {
    const toolCallId = `context-read-${randomUUID()}`;
    parts.push({ type: "tool-input-start", id: toolCallId, toolName: tool.name },
      { type: "tool-input-delta", id: toolCallId, delta: JSON.stringify(tool.input) }, { type: "tool-input-end", id: toolCallId },
      { type: "tool-call", toolCallId, toolName: tool.name, input: JSON.stringify(tool.input) });
  }
  parts.push({ type: "finish", finishReason: { unified: reason, raw: "scripted" }, usage: {
    inputTokens: { total: 100, noCache: 100, cacheRead: 0, cacheWrite: 0 }, outputTokens: { total: 30, text: 30, reasoning: 0 },
  } });
  return { stream: new ReadableStream<LanguageModelV3StreamPart>({ start(controller) {
    for (const part of parts) controller.enqueue(part);
    controller.close();
  } }) };
}

/** Keep the synthetic auxiliary call pending until the real Run abort signal arrives. */
function awaitCancellation(signal: AbortSignal | undefined) {
  if (!signal) throw new Error("SCRIPTED_CONTEXT_ABORT_SIGNAL_MISSING");
  let abort = () => {};
  return { stream: new ReadableStream<LanguageModelV3StreamPart>({
    start(controller) {
      abort = () => { controller.enqueue({ type: "error", error: new DOMException("Scripted Observer cancelled", "AbortError") }); controller.close(); };
      if (signal.aborted) abort();
      else signal.addEventListener("abort", abort, { once: true });
    },
    cancel() { signal.removeEventListener("abort", abort); },
  }) };
}
