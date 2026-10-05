// @vitest-environment happy-dom
import { act, StrictMode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { i18n } from "../i18n";
import { mcpEn } from "../i18n/messages/mcp";
import { McpPage } from "./McpPage";
import { toolPresentation } from "./toolPresentation";

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let root: Root;
let host: HTMLDivElement;
const endpoint = "https://research.example.test/mcp";
let apps: { id: string; name: string; client_id: string; scopes: string[]; authorized_at: string }[];
let failCheck: boolean;
let failRevoke: boolean;
const copied = vi.fn(async () => undefined);
const requested: string[] = [];
const button = (text: string) => [...host.querySelectorAll("button")].find(element => (element.getAttribute("aria-label") ?? element.textContent) === text)!;
async function click(element: HTMLElement) { await act(async () => { element.click(); }); }
beforeEach(async () => {
  await i18n.changeLanguage("en");
  apps = []; failCheck = false; failRevoke = false; copied.mockClear(); requested.length = 0;
  vi.stubGlobal("navigator", { clipboard: { writeText: copied } });
  vi.stubGlobal("fetch", vi.fn(async (input: string, init?: RequestInit) => {
    requested.push(input);
    if (init?.signal?.aborted) throw new DOMException("Aborted", "AbortError");
    if (input === "/api/auth/mcp/connections") return Response.json({ server_url: endpoint, apps });
    if (input === "/api/agent/mcp/connection") return failCheck ? Response.json({}, { status: 502 }) : Response.json({ checked_at: "2026-09-05T00:00:00Z", tools: [{ name: "get_research_context", description: "Live discovery description" }] });
    if (input === "/api/auth/mcp/revoke") return failRevoke ? Response.json({}, { status: 502 }) : new Response(null, { status: 204 });
    throw Error(`Unexpected request: ${input}`);
  }));
  host = document.createElement("div"); document.body.append(host); root = createRoot(host);
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
async function mount() { await act(async () => root.render(<StrictMode><McpPage /></StrictMode>)); }

describe("MCP product page", () => {
  it("has a translated presentation for each known MCP tool", () => {
    expect(Object.keys(mcpEn.toolNames).sort()).toEqual(Object.keys(toolPresentation).sort());
    expect(Object.keys(mcpEn.toolNames).sort()).toEqual(Object.keys(mcpEn.toolDetails).sort());
  });
  it("discovers real tools and copies English setup without granting access", async () => {
    await mount();
    expect(host.textContent).toContain("Service available");
    expect(host.textContent).toContain("1 tool");
    expect(host.textContent).not.toContain("Browse daily tracks");
    expect(host.textContent).not.toContain("Built into QAgentis chat");
    await click(button("Copy"));
    expect(copied).toHaveBeenLastCalledWith(expect.stringContaining(`Add QAgentis MCP to Codex using ${endpoint}.`));
    expect(host.textContent).toContain("No authorized apps yet");
    await click(button("Claude Code"));
    await click(button("Copy"));
    expect(copied).toHaveBeenLastCalledWith(expect.stringContaining("Add QAgentis MCP to Claude Code"));
    await click(button("Other client"));
    await click(button("Copy URL"));
    expect(copied).toHaveBeenLastCalledWith(endpoint);
    expect(requested.every(path => !path.includes("revoke") && !path.includes("consent"))).toBe(true);
  });
  it("preserves the configured server alias in client setup and login instructions", async () => {
    await mount();
    expect(host.querySelector('pre[aria-label="Codex add command"] code')?.textContent).toBe(`codex mcp add quantgrove --url '${endpoint}'`);
    expect(host.textContent).toContain("codex mcp login quantgrove");
    await click(button("Copy command"));
    expect(copied).toHaveBeenLastCalledWith(`codex mcp add quantgrove --url '${endpoint}'`);
    await click(button("Copy login command"));
    expect(copied).toHaveBeenLastCalledWith("codex mcp login quantgrove");
    await click(button("Claude Code"));
    expect(host.querySelector('pre[aria-label="Claude Code add command"] code')?.textContent).toBe(`claude mcp add --transport http --scope user quantgrove '${endpoint}'`);
    expect(host.textContent).toContain("Select quantgrove");
    await click(button("Copy login command"));
    expect(copied).toHaveBeenLastCalledWith("/mcp");
  });
  it("localizes expanded tool instructions while preserving discovery and protocol identifiers", async () => {
    await mount();
    const requestsBeforeSwitch = [...requested];
    const toolTrigger = [...host.querySelectorAll<HTMLButtonElement>("button")].find(el => el.textContent?.includes("Check research readiness"))!;
    await click(toolTrigger);
    const tool = toolTrigger.closest('[data-slot="collapsible"]')!;
    await act(async () => { await i18n.changeLanguage("zh-CN"); });
    expect(toolTrigger.getAttribute("aria-expanded")).toBe("true");
    expect(tool.textContent).toContain("folder_limit 默认 20，最多 50");
    expect(tool.textContent).toContain("get_research_context");
    expect(tool.textContent).not.toContain("Live discovery description");
    expect(requested).toEqual(requestsBeforeSwitch);
  });
  it("does not erase authorizations when a service check fails", async () => {
    apps = [{ id: "00000000-0000-4000-8000-000000000001", name: "Codex", client_id: "codex-client", scopes: ["research:read"], authorized_at: "2026-09-05T00:00:00Z" }];
    await mount(); failCheck = true;
    await click(button("Check service"));
    expect(host.textContent).toContain("Service unavailable");
    expect(host.textContent).toContain("Tool set not verified");
    expect(host.textContent).toContain("Revoke access");
    expect(host.textContent).not.toContain("Live discovery description");
  });
  it("requires confirmation and retains access after a failed revoke", async () => {
    apps = [{ id: "00000000-0000-4000-8000-000000000001", name: "Codex", client_id: "codex-client", scopes: ["research:read"], authorized_at: "2026-09-05T00:00:00Z" }];
    await mount();
    await click(host.querySelector("article button")!);
    expect(requested).not.toContain("/api/auth/mcp/revoke");
    failRevoke = true;
    await click(document.querySelector('[role="alertdialog"] button:last-child')!);
    expect(host.querySelector("article")).not.toBeNull();
    expect(document.querySelector('[role="alertdialog"]')?.textContent).toContain("Access could not be revoked");
    failRevoke = false;
    await click(document.querySelector('[role="alertdialog"] button:last-child')!);
    expect(host.querySelector("article")).toBeNull();
    expect(host.textContent).toContain("Codex access revoked.");
  });
  it("translates a visible revoke error without changing access or MCP configuration", async () => {
    apps = [{ id: "00000000-0000-4000-8000-000000000001", name: "Codex", client_id: "codex-client", scopes: ["research:read"], authorized_at: "2026-09-05T00:00:00Z" }];
    await mount();
    await click(host.querySelector("article button")!);
    failRevoke = true;
    await click(document.querySelector('[role="alertdialog"] button:last-child')!);
    expect(document.querySelector('[role="alertdialog"]')?.textContent).toContain("Access could not be revoked");
    const requestsBeforeSwitch = [...requested];
    await act(async () => { await i18n.changeLanguage("zh-CN"); });
    expect(requested).toEqual(requestsBeforeSwitch);
    expect(document.querySelector('[role="alertdialog"]')?.textContent).toContain("无法撤销访问权限");
    expect(host.querySelector("article")?.textContent).toContain("读取研究上下文、运行和结果");
    expect(host.textContent).toContain("检查研究准备情况");
    await click(document.querySelector('[role="alertdialog"] button')!);
    await click(button("复制"));
    expect(copied).toHaveBeenLastCalledWith(expect.stringContaining(endpoint));
    await click(button("Claude Code"));
    const command = [...host.querySelectorAll("pre code")].find(element => element.textContent?.startsWith("claude mcp add"));
    expect(command?.textContent).toBe(`claude mcp add --transport http --scope user quantgrove '${endpoint}'`);
    expect(requested).not.toContain("/api/auth/oauth2/consent");
  });
});
