import type { Connection } from "./api";
import { toolPresentation } from "./toolPresentation";
const groups = ["Research preparation", "Research runs", "Research batches", "Daily tracks", "Other tools"];
function group(name: string): string {
  if (name.includes("daily_track")) return "Daily tracks";
  if (name.includes("research_batch")) return "Research batches";
  if (name.includes("research_run")) return "Research runs";
  return toolPresentation[name] ? "Research preparation" : "Other tools";
}
function title(name: string): string { return name.replaceAll("_", " ").replace(/^./, char => char.toUpperCase()); }
export function McpTools({ tools, checking }: { tools: Connection["tools"] | null; checking: boolean }) {
  return <section aria-labelledby="mcp-tools-heading">
    <div className="mcp-section-heading"><h2 id="mcp-tools-heading">Tool set</h2><span className="mcp-tag">{checking ? "Checking…" : tools ? `${tools.length} tools` : "Unverified"}</span></div>
    {!tools ? <div className="mcp-empty"><div><strong>{checking ? "Discovering tools…" : "Tool set not verified"}</strong><p>{checking ? "Waiting for the MCP service." : "Check the connection again when the service is available."}</p></div></div> : groups.map(label => {
      const members = tools.filter(tool => group(tool.name) === label);
      return members.length ? <details className="mcp-tool-group" key={label}>
        <summary><span>{label}</span><small>{members.length} tools</small></summary>
        {members.map(tool => <details className="mcp-tool" key={tool.name}><summary>{toolPresentation[tool.name] ? <><span className="mcp-tool-label"><strong>{toolPresentation[tool.name].title}</strong><span>{toolPresentation[tool.name].description}</span></span><span className="mcp-tag">{toolPresentation[tool.name].effect}</span></> : title(tool.name)}</summary><div><code>{tool.name}</code>{toolPresentation[tool.name] ? <p>Permission: <code>{toolPresentation[tool.name].scope}</code></p> : null}<p>{tool.description}</p></div></details>)}
      </details> : null;
    })}
  </section>;
}
