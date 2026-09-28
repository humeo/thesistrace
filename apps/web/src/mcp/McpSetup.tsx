import { ChatCircle, Terminal } from "@phosphor-icons/react";
import { useState } from "react";
import { interfaceLocale, useTranslation } from "../i18n";
import { CopyButton } from "./CopyButton";
import { addCommand, clients, mcpServerName, setupPrompt, type McpClient } from "./setup";
import { ToggleGroup, ToggleGroupItem } from "../components/ui/toggle-group";
import { Disclosure } from "../components/layout/Disclosure";
import { mcpLayout } from "./mcpLayout";
export function McpSetup({ endpoint }: { endpoint: string }) {
  const { t } = useTranslation("mcp");
  const [client, setClient] = useState<McpClient>("codex");
  const prompt = setupPrompt(client, endpoint);
  const loginCommand = `codex mcp login ${mcpServerName}`;
  return <section className={`${mcpLayout.stack} rounded-xl border border-border bg-card p-5`} aria-labelledby="mcp-setup-heading">
    <div className={mcpLayout.row}><h2 id="mcp-setup-heading">{t("connect")}</h2>
      <ToggleGroup value={[client]} onValueChange={values => { if (values[0]) setClient(values[0] as McpClient); }} aria-label={t("client")} className="flex-wrap">
        {(Object.keys(clients) as McpClient[]).map(key => <ToggleGroupItem key={key} value={key}>{key === "other" ? t("otherClient") : clients[key]}</ToggleGroupItem>)}
      </ToggleGroup>
    </div>
    <div className={`${mcpLayout.row} justify-between border-t border-border pt-4`}><div><h3><ChatCircle size={17} />{t("setUpWith", { client: client === "other" ? t("yourAssistant") : clients[client] })}</h3><p>{t("copyIntro")}</p></div>
      <CopyButton key={client} text={prompt} label={t("copyPrompt")} primary />
    </div>
    <ol className={mcpLayout.steps} aria-label={t("steps")}>
      <li><strong>{t("addServer")}</strong><span>{t("addServerDescription")}</span></li>
      <li><strong>{t("approve")}</strong><span>{t("approveDescription")}</span></li>
      <li><strong>{t("verify")}</strong><span>{t("verifyDescription")}</span></li>
    </ol>
    <div key={client} className={mcpLayout.stack}>
      <Disclosure title={t("viewPrompt")}><p className={mcpLayout.prompt} lang={interfaceLocale()}>{prompt}</p></Disclosure>
      <Disclosure title={client === "other" ? t("addManual") : t("addCommand")}>
        <div className={mcpLayout.stack}>{client === "other" ? <><p>{t("manualDescription")}</p><div className={mcpLayout.row}><span>{t("serverUrl")}</span><code>{endpoint}</code><CopyButton text={endpoint} label={t("copyUrl")} /></div><p>{t("name")}: <strong>Quantgrove</strong> · {t("transport")}: <strong>Streamable HTTP</strong></p></> : <>
          <div className={mcpLayout.row}><h3><Terminal size={15} />{t("terminalStep")}</h3><CopyButton text={addCommand(client, endpoint)} label={t("copyCommand")} /></div>
          <pre className={mcpLayout.code} tabIndex={0} aria-label={t("addCommandAria", { client: clients[client] })}><code>{addCommand(client, endpoint)}</code></pre>
          <h3>{t("authorizeStep")}</h3>
          {client === "codex" ? <div className={mcpLayout.row}><code>{loginCommand}</code><CopyButton text={loginCommand} label={t("copyLogin")} /></div> : <p>{t("claudeOpen")} <code>/mcp</code>. {t("claudeSelect")} <code>{mcpServerName}</code> {t("claudeFollow")}</p>}
          <p>{t("thenList", { client: clients[client] })}</p>
        </>}</div>
      </Disclosure>
    </div>
  </section>;
}
