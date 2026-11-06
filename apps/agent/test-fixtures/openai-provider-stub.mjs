import http from "node:http";

const apiKey = required("THESISTRACE_AGENT_TEST_OPENAI_API_KEY");
const model = "gpt-6-luna";
let responseOrdinal = 0;

http.createServer(async (request, response) => {
  if (request.method === "GET" && request.url === "/health/ready") {
    json(response, 200, { status: "ready" });
    return;
  }
  if (request.method !== "POST" || request.url !== "/v1/responses") {
    response.writeHead(404).end();
    return;
  }
  if (request.headers.authorization !== `Bearer ${apiKey}`) {
    response.writeHead(401).end();
    return;
  }

  const body = await readJson(request, response);
  if (body === null) return;
  if (
    body.model !== model
    || body.stream !== true
    || body.store !== false
    || body.reasoning?.effort !== "max"
    || !Array.isArray(body.input)
  ) {
    json(response, 400, { error: { message: "invalid_request", type: "invalid_request_error" } });
    return;
  }

  responseOrdinal += 1;
  response.writeHead(200, {
    "cache-control": "no-cache",
    "content-type": "text/event-stream",
  });
  const hasToolResult = body.input.some((item) => item?.type === "function_call_output");
  const hasResearchTool = Array.isArray(body.tools)
    && body.tools.some((tool) => tool?.type === "function" && tool?.name === "execute_typescript");
  const prompt = JSON.stringify(body.input);
  if (hasResearchTool && !hasToolResult && !prompt.includes("image-code-mode-text")) {
    const program = prompt.includes("image-code-mode-loop")
      ? 'const hold = new Array(5000000).fill(42); await external_get_research_context({}); let i=0; while (true) { hold[i++ % hold.length] ^= 1; }'
      : prompt.includes("image-code-mode-heap")
      ? 'const rows=[]; while (true) rows.push(new Array(10000).fill(42));'
      : prompt.includes("image-code-mode-arguments")
      ? 'return await external_get_research_context({value:"private-code-mode-image-canary".repeat(10000)});'
      : prompt.includes("image-code-mode-logs")
      ? 'for(let i=0;i<10000;i++) console.log("private-code-mode-image-canary"); return 42;'
      : 'return await external_get_research_context({});';
    streamToolCall(response, responseOrdinal, program);
  } else {
    streamText(response, responseOrdinal, hasToolResult);
  }
  response.write("data: [DONE]\n\n");
  response.end();
}).listen(8600, "0.0.0.0");

function streamToolCall(response, ordinal, code) {
  const argumentsJson = JSON.stringify({ code });
  const responseId = `resp_image_smoke_${ordinal}`;
  const itemId = `fc_image_smoke_${ordinal}`;
  const callId = `call_image_smoke_${ordinal}`;
  event(response, {
    type: "response.created",
    response: { id: responseId, created_at: 1_788_148_800, model },
  });
  event(response, {
    type: "response.output_item.added",
    output_index: 0,
    item: {
      type: "function_call",
      id: itemId,
      call_id: callId,
      name: "execute_typescript",
      arguments: "",
    },
  });
  event(response, {
    type: "response.function_call_arguments.delta",
    item_id: itemId,
    output_index: 0,
    delta: argumentsJson,
  });
  event(response, {
    type: "response.function_call_arguments.done",
    item_id: itemId,
    output_index: 0,
    arguments: argumentsJson,
  });
  event(response, {
    type: "response.output_item.done",
    output_index: 0,
    item: {
      type: "function_call",
      id: itemId,
      call_id: callId,
      name: "execute_typescript",
      arguments: argumentsJson,
      status: "completed",
    },
  });
  completed(response);
}

function streamText(response, ordinal, afterTool) {
  const responseId = `resp_image_smoke_${ordinal}`;
  const itemId = `msg_image_smoke_${ordinal}`;
  const text = afterTool
    ? "I checked the available research context and can refine the Alpha."
    : "Image smoke session";
  event(response, {
    type: "response.created",
    response: { id: responseId, created_at: 1_788_148_800, model },
  });
  event(response, {
    type: "response.output_item.added",
    output_index: 0,
    item: { type: "message", id: itemId },
  });
  event(response, {
    type: "response.output_text.delta",
    item_id: itemId,
    delta: text,
  });
  event(response, {
    type: "response.output_item.done",
    output_index: 0,
    item: { type: "message", id: itemId },
  });
  completed(response);
}

function completed(response) {
  event(response, {
    type: "response.completed",
    response: {
      usage: {
        input_tokens: 20,
        output_tokens: 12,
        output_tokens_details: { reasoning_tokens: 0 },
      },
    },
  });
}

function event(response, value) {
  response.write(`data: ${JSON.stringify(value)}\n\n`);
}

async function readJson(request, response) {
  let body = "";
  for await (const chunk of request) {
    body += chunk;
    if (Buffer.byteLength(body) > 1024 * 1024) {
      response.writeHead(413).end();
      return null;
    }
  }
  try {
    return JSON.parse(body);
  } catch {
    response.writeHead(400).end();
    return null;
  }
}

function json(response, status, value) {
  response.writeHead(status, { "content-type": "application/json" });
  response.end(JSON.stringify(value));
}

function required(name) {
  const value = process.env[name];
  if (value === undefined || value.length === 0) throw new Error("provider_stub_invalid");
  return value;
}
