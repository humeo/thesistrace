export const MEMORY_FACT = "ResearchRun run_memory_alpha failed with INSUFFICIENT_HISTORY; retain the 120-session formula.";

/** Deterministic Responses replay for the native Observer/Reflector protocol. */
export function openAIMemoryProvider(options: { tool?: string; toolArguments?: Record<string, unknown>; failObserver?: boolean; invalidObserver?: boolean; invalidSummary?: boolean; toolOnAnswer?: number; toolOnAnswers?: readonly number[]; lengthOnAnswers?: readonly number[]; contextOnAnswers?: readonly number[]; answerTexts?: Record<number, string>; onAnswerDelta?: (index: number, signal: AbortSignal | null | undefined) => Promise<void>; onObserver?: (signal: AbortSignal | null | undefined) => Promise<void> } = {}) {
  const requests: Array<{ phase: "answer" | "observer" | "reflector" | "summary"; prompt: string; body: Record<string, unknown> }> = [];
  const fetch: typeof globalThis.fetch = async (_url, init) => {
    const body = JSON.parse(String(init?.body));
    if (!body.stream) return Response.json({
      id: "resp_memory_title", created_at: 1, model: "gpt-5.6-luna",
      output: [{ type: "message", id: "msg_memory_title", role: "assistant",
        content: [{ type: "output_text", text: "Research memory", annotations: [] }] }],
      usage: { input_tokens: 20, output_tokens: 2 },
    });
    const prompt = JSON.stringify(body.input);
    const phase = prompt.includes("Produce a structured handoff summary") ? "summary" : prompt.includes("Your memory observation reflections") ? "reflector"
      : prompt.includes("You are the memory consciousness") ? "observer" : "answer";
    requests.push({ phase, prompt, body });
    if (phase === "observer") await options.onObserver?.(init?.signal);
    if (phase === "observer" && options.failObserver) return Response.json({
      error: { type: "rate_limit_exceeded", code: "rate_limit_exceeded", message: "private-observer-canary" },
    }, { status: 429 });
    if (phase === "answer" && options.contextOnAnswers?.includes(requests.filter(request => request.phase === "answer").length)) {
      return Response.json({ error: { type: "invalid_request_error", code: "context_length_exceeded", message: "private-context-canary" } }, { status: 400 });
    }
    const answerNumber = requests.filter(request => request.phase === "answer").length;
    const truncated = phase === "answer" && options.lengthOnAnswers?.includes(requests.filter((request) => request.phase === "answer").length);
    const remembers = prompt.includes("run_memory_alpha") && prompt.includes("INSUFFICIENT_HISTORY");
    const text = (phase === "answer" ? options.answerTexts?.[answerNumber] : undefined) ?? (truncated ? "TRUNCATED_ANSWER_CANARY" : phase === "summary" && options.invalidSummary ? "invalid-summary-fixture" : phase === "observer" && options.invalidObserver ? "private-invalid-observer-canary" : phase === "summary"
      ? ["## Goal", "Explain the research failure.", "## Constraints and preferences", "Keep the original formula.", "## Progress", "Completed: read the failure. In progress: explanation. Blockers: none.", "## Key decisions", "Keep the existing research.", "## Next steps", "1. Explain the recorded error.", "## Critical context", MEMORY_FACT].join("\n")
      : phase === "answer"
      ? remembers ? "The retained failure is INSUFFICIENT_HISTORY." : "No earlier failure is known."
      : `<observations>\nDate: Sep 6, 2026\n* 🔴 ${remembers ? MEMORY_FACT : "No earlier failure is known."}\n</observations>`);
    const id = `memory_${requests.length}`;
    const item = { type: "message", id: `msg_${id}` };
    const tool = phase === "answer" && options.tool && (options.toolOnAnswers ?? [options.toolOnAnswer ?? 1]).includes(requests.filter((request) => request.phase === "answer").length)
      ? { type: "function_call", id: `fc_${id}`, call_id: `call_${id}`, name: options.tool, arguments: JSON.stringify(options.toolArguments ?? {}) } : undefined;
    const frames = [
      { type: "response.created", response: { id: `resp_${id}`, model: "gpt-5.6-luna", created_at: 1 } },
      ...(tool ? [
        { type: "response.output_item.added", output_index: 0, item: { ...tool, arguments: "" } },
        { type: "response.function_call_arguments.delta", output_index: 0, item_id: tool.id, delta: tool.arguments },
        { type: "response.function_call_arguments.done", output_index: 0, item_id: tool.id, arguments: tool.arguments },
        { type: "response.output_item.done", output_index: 0, item: { ...tool, status: "completed" } },
      ] : [
      { type: "response.output_item.added", output_index: 0, item },
      { type: "response.output_text.delta", item_id: item.id, delta: text },
      { type: "response.output_item.done", output_index: 0, item },
      ]),
      { type: truncated ? "response.incomplete" : "response.completed", response: {
        ...(truncated ? { incomplete_details: { reason: "max_output_tokens" } } : {}), usage: { input_tokens: 100, output_tokens: 30 } } },
    ];
    if (phase === "answer" && options.onAnswerDelta) {
      const encoder = new TextEncoder();
      return new Response(new ReadableStream<Uint8Array>({ async start(controller) {
        try {
          for (const frame of frames) {
            controller.enqueue(encoder.encode(`data: ${JSON.stringify(frame)}\n\n`));
            if (frame.type === "response.output_text.delta") await options.onAnswerDelta!(answerNumber, init?.signal);
          }
          controller.enqueue(encoder.encode("data: [DONE]\n\n")); controller.close();
        } catch (error) { controller.error(error); }
      } }), { headers: { "Content-Type": "text/event-stream" } });
    }
    return new Response(frames.map((frame) => `data: ${JSON.stringify(frame)}\n\n`).join("") + "data: [DONE]\n\n", {
      headers: { "Content-Type": "text/event-stream" },
    });
  };
  return { fetch, requests };
}
