import { ChatCircle, Terminal } from "@phosphor-icons/react";
import { useState } from "react";
import { CopyButton } from "./CopyButton";
import { addCommand, clients, setupPrompt, type McpClient } from "./setup";
export function McpSetup({ endpoint }: { endpoint: string }) {
  const [client, setClient] = useState<McpClient>("codex");
  const prompt = setupPrompt(client, endpoint);
  return <section className="mcp-setup" aria-labelledby="mcp-setup-heading">
    <div className="mcp-section-heading"><div><h2 id="mcp-setup-heading">Connect an assistant</h2><p className="mcp-muted">Choose your client to get its setup instructions.</p></div>
      <div className="mcp-client-picker" role="group" aria-label="MCP client">
        {(Object.keys(clients) as McpClient[]).map(key => <button key={key} type="button" aria-pressed={key === client} onClick={() => setClient(key)}>{clients[key]}</button>)}
      </div>
    </div>
    <div className="mcp-prompt-row"><div><h3><ChatCircle size={17} />Set up with {client === "other" ? "your assistant" : clients[client]}</h3><p>Copy these instructions into a new conversation. Your assistant will guide you through connecting.</p></div>
      <CopyButton key={client} text={prompt} label="Copy setup prompt" primary />
    </div>
    <ol className="mcp-setup-flow" aria-label="Connection steps">
      <li><strong>Add the server</strong><span>Use the setup prompt or manual instructions below.</span></li>
      <li><strong>Approve access</strong><span>Sign in with your email and review the requested permissions.</span></li>
      <li><strong>Verify the tools</strong><span>Ask your assistant to list its QuantTrace tools.</span></li>
    </ol>
    <div key={client} className="mcp-setup-details">
      <details><summary>View setup prompt</summary><p className="mcp-agent-prompt" lang="en">{prompt}</p></details>
      <details><summary>{client === "other" ? "Add the server manually" : "Add with a command"}</summary>
        <div className="mcp-manual">{client === "other" ? <><p>In a client that supports remote MCP and account authorization, add the Server URL above, then sign in to QuantTrace when prompted.</p><p>Name: <strong>QuantTrace</strong> · Transport: <strong>Streamable HTTP</strong></p></> : <>
          <div className="mcp-section-heading"><h3><Terminal size={15} />1. Run in your terminal</h3><CopyButton text={addCommand(client, endpoint)} label="Copy command" /></div>
          <pre tabIndex={0} aria-label={`${clients[client]} add command`}><code>{addCommand(client, endpoint)}</code></pre>
          <h3>2. Sign in and authorize</h3>
          {client === "codex" ? <div className="mcp-login-command"><code>codex mcp login quanttrace</code><CopyButton text="codex mcp login quanttrace" label="Copy login command" /></div> : <p>Open Claude Code and run <code>/mcp</code>. Select QuantTrace and follow the sign-in instructions.</p>}
          <p>Then ask {clients[client]} to list the available QuantTrace tools.</p>
        </>}</div>
      </details>
    </div>
  </section>;
}
