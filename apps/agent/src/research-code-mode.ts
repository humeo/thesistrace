import { IsolatedVmCodeModeTransport } from "@mastra/isolated-vm";
import { createHash, randomUUID } from "node:crypto";
import { createCodeMode, createTool, generateStubs, isValidationError, noopObserve, type ToolExecutionContext } from "@mastra/core/tools";
import type { AgentFailureCode } from "@thesistrace/contracts/agent-failure";
import type { DiscoveredMcpTools, McpRun, McpToolFailure } from "./mcp-run.js";
import { AgentRunFailure } from "./run-failure.js";
import { DURABLE_TOOL_FAILURE, DURABLE_TOOL_OUTCOME_FIELD } from "./tool-outcome.js";
import { CODE_MODE_READ_TOOLS, CODE_MODE_TOOL_NAME, type CodeModeActivity } from "./code-mode-activity.js";

const DIRECT_COMMANDS = new Set(["submit_research_run", "submit_research_batch", "start_daily_track", "refresh_daily_track", "retry_daily_track"]);
const READ_TOOLS = new Set<string>(CODE_MODE_READ_TOOLS);
const LIMITS = Object.freeze({ sourceBytes: 64 * 1024, wallMs: 30_000, calls: 32, parallel: 4,
  inputBytes: 64 * 1024, cumulativeBytes: 8 * 1024 * 1024, resultBytes: 256 * 1024,
  hostPrograms: 8, heapMiB: 64, cleanupMs: 1_000 });

type RunOptions = Readonly<{
  mcpRun: McpRun;
  signal: AbortSignal;
  deadline: number;
  onFatal: (code: AgentFailureCode) => void;
  onActivity: (activity: CodeModeActivity) => void;
}>;
export type ResearchCodeMode = Readonly<{
  tools: DiscoveredMcpTools;
  instructions: string;
  toolFailure: (toolCallId: string) => McpToolFailure | undefined;
  hasFatalToolFailure: () => boolean;
}>;

/** One Host owns admission; each Run owns tools, identities and cancellation. */
export function createResearchCodeModeHost() {
  const transport = new IsolatedVmCodeModeTransport({ memoryLimitMb: LIMITS.heapMiB });
  let hostPrograms = 0;
  return { forRun };

  function forRun(options: RunOptions): ResearchCodeMode {
    const { mcpRun } = options;
    const reads = Object.fromEntries(Object.entries(mcpRun.tools).filter(([name]) => READ_TOOLS.has(name))
      .map(([name, tool]) => [name, new Proxy(tool, { get: (target, property, receiver) => property === "id" ? name : Reflect.get(target, property, receiver) })]));
    const tools = Object.fromEntries(Object.entries(mcpRun.tools).filter(([name]) => DIRECT_COMMANDS.has(name)));
    const failures = new Map<string, McpToolFailure>();
    let active = false;
    if (Object.keys(reads).length === 0) return { tools, instructions: "", toolFailure: id => failures.get(id), hasFatalToolFailure: () => false };
    const runController = new AbortController();
    const native = createCodeMode({ tools: reads }, transport);
    tools[CODE_MODE_TOOL_NAME] = createTool({
      id: CODE_MODE_TOOL_NAME, description: native.tool.description, inputSchema: native.tool.inputSchema,
      execute: async (input: { code: string }, context) => execute(input.code, context),
    });
    return { tools, instructions: `${RESEARCH_CODE_MODE_INSTRUCTIONS}\nAvailable functions:\n${generateStubs(reads).map(stub => stub.declaration).join("\n\n")}`,
      toolFailure: id => failures.get(id), hasFatalToolFailure: () => [...failures.values()].some(failure => failure.fatal) };

    async function execute(code: string, context: ToolExecutionContext) {
      const parentId = context.agent?.toolCallId;
      if (!parentId) throw new Error("CODE_MODE_CALL_ID_REQUIRED");
      const executionId = randomUUID();
      const controller = new AbortController();
      const signal = AbortSignal.any([options.signal, runController.signal, controller.signal, ...(context.abortSignal ? [context.abortSignal] : [])]);
      let fatal: AgentFailureCode | undefined;
      const fatalCode = () => fatal ?? (runController.signal.aborted ? (runController.signal.reason as AgentRunFailure).code : undefined);
      let admitted = false;
      let calls = 0, parallel = 0, receivedBytes = 0;
      const waiting: Array<() => void> = [];
      const pending = new Set<Promise<unknown>>();
      const rejectedReads = new Map<string, McpToolFailure>();
      const fail = (code: AgentFailureCode) => {
        if (fatal) return;
        fatal = code;
        failures.set(parentId, { code, fatal: true });
        if (!runController.signal.aborted) {
          options.onFatal(code);
          runController.abort(new AgentRunFailure(code));
        }
        controller.abort(new AgentRunFailure(code));
        for (const wake of waiting.splice(0)) wake();
      };
      const abortWaiting = () => { for (const wake of waiting.splice(0)) wake(); };
      signal.addEventListener("abort", abortWaiting, { once: true });
      const remaining = Math.min(LIMITS.wallMs, options.deadline - performance.now());
      let timer: ReturnType<typeof setTimeout> | undefined;
      try {
        signal.throwIfAborted();
        if (Buffer.byteLength(code, "utf8") > LIMITS.sourceBytes || remaining <= 0) {
          fail("AGENT_LIMIT"); return failed("AGENT_LIMIT", "Narrow the program to the execution budget.");
        }
        if (active || hostPrograms >= LIMITS.hostPrograms) {
          fail("AGENT_CAPACITY"); return failed("AGENT_CAPACITY", "Code execution capacity is busy.");
        }
        active = true; hostPrograms++; admitted = true;
        timer = setTimeout(() => fail("AGENT_LIMIT"), remaining);
        const invocationReads = Object.fromEntries(Object.entries(reads).map(([name, tool]) => [name, new Proxy(tool, {
          get(target, property, receiver) {
            if (property !== "execute") return Reflect.get(target, property, receiver);
            return (args: unknown, inner: ToolExecutionContext) => {
              const invocation = dispatch(name, tool, args, inner);
              pending.add(invocation);
              void invocation.finally(() => pending.delete(invocation)).catch(() => {});
              return invocation;
            };
          },
        })]));
        const invocation = createCodeMode({ tools: invocationReads, timeout: Math.max(1, Math.floor(remaining)) }, transport);
        const result = await invocation.tool.execute!({ code }, { ...context, abortSignal: signal, observe: noopObserve });
        if (pending.size > 0 && !signal.aborted) fail("AGENT_LIMIT");
        const terminal = fatalCode();
        if (terminal) {
          failures.set(parentId, { code: terminal, fatal: true });
          return failed(terminal, "Code execution stopped; completed research remains available.");
        }
        options.signal.throwIfAborted();
        if (isValidationError(result) || !result || typeof result !== "object" || !("success" in result)) {
          failures.set(parentId, { code: "TOOL_REJECTION", fatal: false });
          return failed("TOOL_REJECTION", "Correct the TypeScript program and its tool arguments.");
        }
        if (!result.success) {
          const error = result.error;
          if (error?.name === "TimeoutError" || error?.name === "CodeModeLimitError") {
            fail("AGENT_LIMIT"); return failed("AGENT_LIMIT", "Narrow the program to the execution budget.");
          }
          failures.set(parentId, { code: "TOOL_REJECTION", fatal: false });
          return failed("TOOL_REJECTION", safeProgramError(error));
        }
        const rejected = rejectedReads.get(createHash("sha256").update(JSON.stringify(result.result) ?? "").digest("hex"));
        if (rejected) {
          failures.set(parentId, rejected);
        }
        const outcome = rejected ? { ...result, code: rejected.code, [DURABLE_TOOL_OUTCOME_FIELD]: DURABLE_TOOL_FAILURE } : result;
        if (Buffer.byteLength(JSON.stringify(outcome), "utf8") > LIMITS.resultBytes) {
          fail("AGENT_LIMIT"); return failed("AGENT_LIMIT", "Return fewer result fields.");
        }
        return outcome;
      } catch {
        const terminal = fatalCode();
        if (terminal) {
          failures.set(parentId, { code: terminal, fatal: true });
          return failed(terminal, "Code execution could not finish.");
        }
        if (options.signal.aborted || context.abortSignal?.aborted) throw new AgentRunFailure("AGENT_RUN_INTERRUPTED");
        if (!fatal) fail("TOOL_ERROR");
        return failed(fatal!, "Code execution could not finish.");
      } finally {
        if (timer) clearTimeout(timer);
        controller.abort();
        signal.removeEventListener("abort", abortWaiting);
        for (const wake of waiting.splice(0)) wake();
        if (pending.size > 0) {
          const cleanup = AbortSignal.timeout(LIMITS.cleanupMs);
          await Promise.race([Promise.allSettled([...pending, mcpRun.close()]), new Promise<void>(resolve => cleanup.addEventListener("abort", () => resolve(), { once: true }))]);
        }
        if (admitted) { active = false; hostPrograms--; }
      }

      async function dispatch(name: string, tool: DiscoveredMcpTools[string], args: unknown, inner: ToolExecutionContext) {
        signal.throwIfAborted();
        calls++;
        if (calls > LIMITS.calls || Buffer.byteLength(JSON.stringify(args) ?? "null", "utf8") > LIMITS.inputBytes) {
          fail("AGENT_LIMIT"); throw new AgentRunFailure("AGENT_LIMIT");
        }
        const childId = `${executionId}:external:${calls}`;
        while (parallel >= LIMITS.parallel) {
          await new Promise<void>(resolve => waiting.push(resolve));
          signal.throwIfAborted();
        }
        signal.throwIfAborted();
        parallel++;
        options.onActivity({ toolCallId: childId, name, status: "running" });
        let failure: McpToolFailure | undefined;
        let bytes: number | undefined;
        try {
          const result = await tool.execute!(args, { ...inner, ...context, agent: { ...context.agent!, toolCallId: childId }, abortSignal: signal, observe: noopObserve });
          signal.throwIfAborted();
          const serialized = JSON.stringify(result) ?? "null";
          bytes = Buffer.byteLength(serialized, "utf8");
          receivedBytes += bytes;
          failure = mcpRun.toolFailure(childId);
          if (failure && !failure.fatal) rejectedReads.set(createHash("sha256").update(serialized).digest("hex"), failure);
          if (receivedBytes > LIMITS.cumulativeBytes) { fail("AGENT_LIMIT"); failure = { code: "AGENT_LIMIT", fatal: true }; }
          if (failure?.fatal) fail(failure.code);
          if (isValidationError(result)) {
            failure = { code: "TOOL_REJECTION", fatal: false };
            throw new TypeError(result.message.slice(0, 1_024));
          }
          if (failure?.fatal) throw new AgentRunFailure(failure.code);
          return result;
        } catch (error) {
          failure ??= { code: signal.aborted ? fatalCode() ?? "AGENT_RUN_INTERRUPTED" : "TOOL_ERROR", fatal: signal.aborted };
          throw error;
        } finally {
          options.onActivity({ toolCallId: childId, name, status: failure ? "failed" : "complete",
            ...(failure ? { failureCode: failure.code } : {}), ...(bytes === undefined ? {} : { resultBytes: bytes }) });
          parallel--;
          waiting.shift()?.();
        }
      }
    }
  }
}

function failed(code: AgentFailureCode, message: string) {
  return { success: false, error: { name: code, message }, code, [DURABLE_TOOL_OUTCOME_FIELD]: DURABLE_TOOL_FAILURE };
}

function safeProgramError(error: { name?: string; message?: string } | undefined): string {
  return error?.name === "SyntaxError" || error?.name === "ReferenceError" || error?.name === "TypeError"
    ? (error.message ?? "Correct the program.").slice(0, 1_024) : "Correct the program or its tool arguments.";
}

const RESEARCH_CODE_MODE_INSTRUCTIONS = `Use execute_typescript for authenticated reads and diagnostics, including a single read. Only the declared external_* functions exist. Filter and rank through list_research_runs before reading selected details. Await every external call before returning; use Promise.all or Promise.allSettled for independent reads. The Host limits each program to 32 calls, four concurrent reads, 30 seconds, 64 KiB of code and 256 KiB of output. Return only needed fields with genuine resource IDs, units, missing/failed items and continuation cursors. Compare Research Kind, dates and Universe before ranking. Do not treat missing metrics as zero, diagnosis valid=false as accepted research, or failed reads as successful data. No console output, modules, network, filesystem or background work. Use the directly provided business commands for submissions and Tracking actions, ask_user for clarification and render_a2ui for fixed resource views. Program output is analysis, never an authoritative Research Result.`;
