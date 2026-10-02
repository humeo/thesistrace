import { useState } from "react";
import { interfaceLocale, useTranslation } from "../i18n";
import { CopyButton } from "./CopyButton";
import { addCommand, clients, mcpServerName, setupPrompt, type McpClient } from "./setup";
import { ToggleGroup, ToggleGroupItem } from "../components/ui/toggle-group";
import { Card, CardAction, CardContent, CardHeader, CardTitle } from "../components/ui/card";
import { Textarea } from "../components/ui/textarea";
import { InputGroup, InputGroupAddon } from "../components/ui/input-group";
import { mcpLayout } from "./mcpLayout";
export function McpSetup({ endpoint }: { endpoint: string }) {
  const { t } = useTranslation("mcp");
  const [client, setClient] = useState<McpClient>("codex");
  const prompt = setupPrompt(client, endpoint);
  const loginCommand = `codex mcp login ${mcpServerName}`;
  return <section className="flex min-w-0 flex-col gap-8" aria-label={t("connect")}>
    <ToggleGroup value={[client]} onValueChange={values => { if (values[0]) setClient(values[0] as McpClient); }} aria-label={t("client")} className="flex-wrap">
      {(Object.keys(clients) as McpClient[]).map(key => <ToggleGroupItem key={key} value={key}>{key === "other" ? t("otherClient") : clients[key]}</ToggleGroupItem>)}
    </ToggleGroup>
    <div className="grid min-w-0 grid-cols-2 items-start gap-6">
      <section className="min-w-0" aria-label={t("setupPromptTitle")}>
        <Card>
          <CardHeader><CardTitle><h2 className={mcpLayout.sectionTitle}>{t("assistantMethod")}</h2></CardTitle><CardAction><CopyButton key={client} text={prompt} label={t("copyPrompt")} /></CardAction></CardHeader>
          <CardContent><Textarea readOnly value={prompt} aria-label={t("setupPromptTitle")} lang={interfaceLocale()} className="resize-none bg-background p-4 font-sans leading-6 text-muted-foreground" /></CardContent>
        </Card>
      </section>
      <Card key={client}>
      <CardHeader><CardTitle><h2 className={mcpLayout.sectionTitle}>{client === "other" ? t("addManual") : t("addCommand")}</h2></CardTitle></CardHeader>
      <CardContent>
      {client === "other" ? <div className={mcpLayout.stack}>
        <p>{t("manualDescription")}</p>
        <p>{t("serverUrl")}</p>
        <InputGroup className="h-auto min-h-10 bg-muted">
          <pre className={mcpLayout.code} tabIndex={0} aria-label={t("serverUrl")}><code>{endpoint}</code></pre>
          <InputGroupAddon align="inline-end" className="py-0"><CopyButton iconOnly text={endpoint} label={t("copyUrl")} /></InputGroupAddon>
        </InputGroup>
        <p>{t("name")}: <strong>Quantgrove</strong> · {t("transport")}: <strong>Streamable HTTP</strong></p>
      </div> : <div className="grid min-w-0 gap-6">
        <div className={mcpLayout.stack}>
        <h3 className="m-0 text-base leading-6 font-medium">{t("terminalStep")}</h3>
        <InputGroup className="h-auto min-h-10 bg-muted">
          <pre className={mcpLayout.code} tabIndex={0} aria-label={t("addCommandAria", { client: clients[client] })}><code>{addCommand(client, endpoint)}</code></pre>
          <InputGroupAddon align="inline-end" className="py-0"><CopyButton iconOnly text={addCommand(client, endpoint)} label={t("copyCommand")} /></InputGroupAddon>
        </InputGroup>
        </div>
        <div className={mcpLayout.stack}>
        <h3 className="m-0 text-base leading-6 font-medium">{t("authorizeStep")}</h3>
        {client === "claude" && <p>{t("claudeOpen")}</p>}
        <InputGroup className="h-auto min-h-10 bg-muted">
          <pre className={mcpLayout.code} tabIndex={0} aria-label={t("authorizeCommandAria", { client: clients[client] })}><code>{client === "codex" ? loginCommand : "/mcp"}</code></pre>
          <InputGroupAddon align="inline-end" className="py-0"><CopyButton iconOnly text={client === "codex" ? loginCommand : "/mcp"} label={t("copyLogin")} /></InputGroupAddon>
        </InputGroup>
        {client === "claude" && <p>{t("claudeSelect")} <code className="font-mono text-sm font-normal">{mcpServerName}</code> {t("claudeFollow")}</p>}
        </div>
      </div>}
      </CardContent>
      </Card>
    </div>
  </section>;
}
