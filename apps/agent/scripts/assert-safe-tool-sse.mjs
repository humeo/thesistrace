import { readFileSync } from "node:fs";

const evidencePath = process.argv[2];
if (evidencePath === undefined) {
  throw new Error("usage: assert-safe-tool-sse.mjs <run.sse>");
}

const events = parseServerSentEvents(readFileSync(evidencePath, "utf8"));
const results = events.filter((event) => event?.type === "TOOL_CALL_RESULT");
if (results.length !== 1 || typeof results[0]?.content !== "string") {
  throw new Error(`expected exactly one structured Tool result, received ${results.length}`);
}

const marker = JSON.parse(results[0].content);
if (
  marker === null
  || typeof marker !== "object"
  || Array.isArray(marker)
  || marker.type !== "thesistrace.tool-result"
  || marker.version !== 1
  || marker.outcome !== "completed"
  || Object.keys(marker).sort().join(",") !== "outcome,type,version"
) {
  throw new Error("Tool result did not match the exact browser-safe marker schema");
}

function parseServerSentEvents(source) {
  const payloads = [];
  let dataLines = [];
  const flush = () => {
    if (dataLines.length === 0) return;
    payloads.push(dataLines.join("\n"));
    dataLines = [];
  };

  for (const line of source.split(/\r?\n/)) {
    if (line.length === 0) {
      flush();
    } else if (line === "data") {
      dataLines.push("");
    } else if (line.startsWith("data:")) {
      dataLines.push(line.slice(5).replace(/^ /, ""));
    }
  }
  flush();
  return payloads.map((payload) => JSON.parse(payload));
}
