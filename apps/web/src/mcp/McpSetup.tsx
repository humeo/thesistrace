import { ChatCircle, Terminal } from "@phosphor-icons/react";
import { useState } from "react";
import { CopyButton } from "./CopyButton";
import { addCommand, clients, setupPrompt, type McpClient } from "./setup";
export function McpSetup({ endpoint }: { endpoint: string }) {
  const [client, setClient] = useState<McpClient>("codex");
  const prompt = setupPrompt(client, endpoint);
  return <section className="mcp-setup" aria-labelledby="mcp-setup-heading">
    <div className="mcp-section-heading"><h2 id="mcp-setup-heading">Connect your AI assistant</h2>
      <div className="mcp-client-picker" role="group" aria-label="MCP client">
        {(Object.keys(clients) as McpClient[]).map(key => <button key={key} type="button" aria-pressed={key === client} onClick={() => setClient(key)}>{clients[key]}</button>)}
      </div>
    </div>
    <div className="mcp-prompt-row"><div><h3><ChatCircle size={17} />Let your agent handle setup</h3><p>Paste the prompt into {client === "other" ? "your AI assistant" : clients[client]} and follow its sign-in instructions.</p></div>
      <CopyButton key={client} text={prompt} label="Copy setup prompt" primary />
    </div>
    <div key={client} className="mcp-setup-details">
      <details><summary>View setup prompt</summary><p className="mcp-agent-prompt" lang="en">{prompt}</p></details>
      <details><summary>{client === "other" ? "Add the server manually" : "Add with a command"}</summary>
        <div className="mcp-manual">{client === "other" ? <><p>In a client that supports remote MCP and account authorization, add the Server URL above, then sign in to ThesisTrace when prompted.</p><p>Name: <strong>ThesisTrace</strong> · Transport: <strong>Streamable HTTP</strong></p></> : <>
          <div className="mcp-section-heading"><h3><Terminal size={15} />1. Run in your terminal</h3><CopyButton text={addCommand(client, endpoint)} label="Copy command" /></div>
          <pre tabIndex={0} aria-label={`${clients[client]} add command`}><code>{addCommand(client, endpoint)}</code></pre>
          <h3>2. Sign in and authorize</h3>
          {client === "codex" ? <div className="mcp-login-command"><code>codex mcp login thesistrace</code><CopyButton text="codex mcp login thesistrace" label="Copy login command" /></div> : <p>Open Claude Code and run <code>/mcp</code>. Select ThesisTrace and follow the sign-in instructions.</p>}
          <p>Then ask {clients[client]} to list the available ThesisTrace tools.</p>
        </>}</div>
      </details>
    </div>
  </section>;
}
