import { Ajv, type AnySchema } from "ajv";

export type ToolFixtureCall = Readonly<{
  name: string;
  arguments: Record<string, unknown>;
}>;

type ProviderRequest = {
  input: Array<{ type?: string; call_id?: string; output?: string }>;
  tools?: Array<{ name: string; parameters: AnySchema }>;
  store?: boolean;
  stream?: boolean;
  reasoning?: { effort?: string };
};

/** Replays Responses over the real SDK boundary, never the network or a model. */
export function openAIToolProvider(calls: readonly ToolFixtureCall[]) {
  const requests: ProviderRequest[] = [];
  const schemaErrors: string[] = [];
  const validator = new Ajv({ strict: false, allErrors: true });
  let nextCall = 0;
  const fetch: typeof globalThis.fetch = async (_url, init) => {
    const body = JSON.parse(String(init?.body)) as ProviderRequest;
    // Independent session-title generation is outside the primary Turn.
    if (body.stream !== true) return Response.json({
      id: "resp_title_fixture", created_at: 1_788_148_800, model: "gpt-5.6-luna",
      output: [{ type: "message", id: "msg_title_fixture", role: "assistant",
        content: [{ type: "output_text", text: "Research clarification", annotations: [] }] }],
      usage: { input_tokens: 20, output_tokens: 12 },
    });
    requests.push(body);
    const call = calls[nextCall];
    const ordinal = requests.length;
    if (call !== undefined) {
      const schema = body.tools?.find((tool) => tool.name === call.name)?.parameters;
      if (schema === undefined) throw new Error("FIXTURE_TOOL_SCHEMA_MISSING");
      const validate = validator.compile(schema);
      if (!validate(call.arguments)) {
        schemaErrors.push(...(validate.errors ?? []).map((error) => `${error.instancePath}:${error.keyword}`));
        return Response.json({ error: {
          type: "invalid_request_error", message: "Fixture arguments rejected by the provider tool schema",
        } }, { status: 400 });
      }
      nextCall++;
      const item = {
        type: "function_call", id: `fc_tool_fixture_${ordinal}`,
        call_id: `call_tool_fixture_${ordinal}`, name: call.name,
      };
      const args = JSON.stringify(call.arguments);
      return events(ordinal, [
        { type: "response.output_item.added", output_index: 0, item: { ...item, arguments: "" } },
        { type: "response.function_call_arguments.delta", output_index: 0, item_id: item.id, delta: args },
        { type: "response.function_call_arguments.done", output_index: 0, item_id: item.id, arguments: args },
        { type: "response.output_item.done", output_index: 0, item: { ...item, arguments: args, status: "completed" } },
      ]);
    }
    const item = { type: "message", id: `msg_tool_fixture_${ordinal}` };
    return events(ordinal, [
      { type: "response.output_item.added", output_index: 0, item },
      { type: "response.output_text.delta", item_id: item.id, delta: "I will use your answer to continue the research." },
      { type: "response.output_item.done", output_index: 0, item },
    ]);
  };
  return { fetch, requests, schemaErrors };
}

function events(ordinal: number, output: Record<string, unknown>[]): Response {
  const frames = [
    { type: "response.created", response: {
      id: `resp_tool_fixture_${ordinal}`, created_at: 1_788_148_800, model: "gpt-5.6-luna",
    } },
    ...output,
    { type: "response.completed", response: { usage: {
      input_tokens: 20, output_tokens: 12, output_tokens_details: { reasoning_tokens: 0 },
    } } },
  ];
  return new Response(`${frames.map((frame) => `data: ${JSON.stringify(frame)}\n\n`).join("")}data: [DONE]\n\n`, {
    headers: { "Content-Type": "text/event-stream" },
  });
}
