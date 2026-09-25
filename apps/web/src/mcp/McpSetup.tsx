import { ChatCircle, Terminal } from "@phosphor-icons/react";
import { useState } from "react";
import { interfaceLocale, useTranslation } from "../i18n";
import { CopyButton } from "./CopyButton";
import { addCommand, clients, mcpServerName, setupPrompt, type McpClient } from "./setup";
export function McpSetup({ endpoint }: { endpoint: string }) {
  const { t } = useTranslation("mcp");
  const [client, setClient] = useState<McpClient>("codex");
  const prompt = setupPrompt(client, endpoint);
  const loginCommand = `codex mcp login ${mcpServerName}`;
  return <section className="mcp-setup" aria-labelledby="mcp-setup-heading">
    <div className="mcp-section-heading"><div><h2 id="mcp-setup-heading">{t("connect")}</h2><p className="mcp-muted">{t("chooseClient")}</p></div>
      <div className="mcp-client-picker" role="group" aria-label={t("client")}>
        {(Object.keys(clients) as McpClient[]).map(key => <button key={key} type="button" aria-pressed={key === client} onClick={() => setClient(key)}>{key === "other" ? t("otherClient") : clients[key]}</button>)}
      </div>
    </div>
    <div className="mcp-prompt-row"><div><h3><ChatCircle size={17} />{t("setUpWith", { client: client === "other" ? t("yourAssistant") : clients[client] })}</h3><p>{t("copyIntro")}</p></div>
      <CopyButton key={client} text={prompt} label={t("copyPrompt")} primary />
    </div>
    <ol className="mcp-setup-flow" aria-label={t("steps")}>
      <li><strong>{t("addServer")}</strong><span>{t("addServerDescription")}</span></li>
      <li><strong>{t("approve")}</strong><span>{t("approveDescription")}</span></li>
      <li><strong>{t("verify")}</strong><span>{t("verifyDescription")}</span></li>
    </ol>
    <div key={client} className="mcp-setup-details">
      <details><summary>{t("viewPrompt")}</summary><p className="mcp-agent-prompt" lang={interfaceLocale()}>{prompt}</p></details>
      <details><summary>{client === "other" ? t("addManual") : t("addCommand")}</summary>
        <div className="mcp-manual">{client === "other" ? <><p>{t("manualDescription")}</p><div className="mcp-endpoint"><span>{t("serverUrl")}</span><code>{endpoint}</code><CopyButton text={endpoint} label={t("copyUrl")} /></div><p>{t("name")}: <strong>Quantgrove</strong> · {t("transport")}: <strong>Streamable HTTP</strong></p></> : <>
          <div className="mcp-section-heading"><h3><Terminal size={15} />{t("terminalStep")}</h3><CopyButton text={addCommand(client, endpoint)} label={t("copyCommand")} /></div>
          <pre tabIndex={0} aria-label={t("addCommandAria", { client: clients[client] })}><code>{addCommand(client, endpoint)}</code></pre>
          <h3>{t("authorizeStep")}</h3>
          {client === "codex" ? <div className="mcp-login-command"><code>{loginCommand}</code><CopyButton text={loginCommand} label={t("copyLogin")} /></div> : <p>{t("claudeOpen")} <code>/mcp</code>. {t("claudeSelect")} <code>{mcpServerName}</code> {t("claudeFollow")}</p>}
          <p>{t("thenList", { client: clients[client] })}</p>
        </>}</div>
      </details>
    </div>
  </section>;
}
