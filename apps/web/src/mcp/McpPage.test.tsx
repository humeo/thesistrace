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
const button = (text: string) => [...host.querySelectorAll("button")].find(element => element.textContent === text)!;
async function click(element: HTMLElement) { await act(async () => { element.click(); }); }
beforeEach(async () => {
  await i18n.changeLanguage("en");
  apps = []; failCheck = false; failRevoke = false; copied.mockClear(); requested.length = 0;
  vi.stubGlobal("navigator", { clipboard: { writeText: copied } });
  vi.spyOn(HTMLDialogElement.prototype, "showModal").mockImplementation(function (this: HTMLDialogElement) { this.open = true; });
  vi.spyOn(HTMLDialogElement.prototype, "close").mockImplementation(function (this: HTMLDialogElement) { this.open = false; });
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
    expect(host.textContent).not.toContain("Built into Quantgrove chat");
    await click(button("Copy setup prompt"));
    expect(copied).toHaveBeenLastCalledWith(expect.stringContaining(`Add Quantgrove MCP to Codex using ${endpoint}.`));
    expect(host.textContent).toContain("No authorized apps yet");
    await click(button("Claude Code"));
    await click(button("Copy setup prompt"));
    expect(copied).toHaveBeenLastCalledWith(expect.stringContaining("Add Quantgrove MCP to Claude Code"));
    await click(button("Other client"));
    const manual = [...host.querySelectorAll("details")].find(element => element.querySelector("summary")?.textContent === "Add the server manually")!;
    await click(manual.querySelector("summary")!);
    await click(manual.querySelector<HTMLButtonElement>("button")!);
    expect(copied).toHaveBeenLastCalledWith(endpoint);
    expect(requested.every(path => !path.includes("revoke") && !path.includes("consent"))).toBe(true);
  });
  it("uses the Quantgrove server alias in client setup and login instructions", async () => {
    await mount();
    const details = [...host.querySelectorAll("details")].find(element => element.querySelector("summary")?.textContent === "Add with a command")!;
    await click(details.querySelector("summary")!);
    expect(details.textContent).toContain(`codex mcp add quantgrove --url '${endpoint}'`);
    expect(details.textContent).toContain("codex mcp login quantgrove");
    await click(button("Copy login command"));
    expect(copied).toHaveBeenLastCalledWith("codex mcp login quantgrove");
    await click(button("Claude Code"));
    const claudeDetails = [...host.querySelectorAll("details")].find(element => element.querySelector("summary")?.textContent === "Add with a command")!;
    await click(claudeDetails.querySelector("summary")!);
    expect(claudeDetails.textContent).toContain(`claude mcp add --transport http --scope user quantgrove '${endpoint}'`);
    expect(claudeDetails.textContent).toContain("Select quantgrove");
  });
  it("localizes expanded tool instructions while preserving discovery and protocol identifiers", async () => {
    await mount();
    const requestsBeforeSwitch = [...requested];
    const tool = host.querySelector<HTMLDetailsElement>(".mcp-tool")!;
    tool.open = true;
    await act(async () => { await i18n.changeLanguage("zh-CN"); });
    expect(tool.open).toBe(true);
    expect(tool.textContent).toContain("folder_limit 默认为 20，最多 50");
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
    await click(host.querySelector(".mcp-app button")!);
    expect(requested).not.toContain("/api/auth/mcp/revoke");
    failRevoke = true;
    await click(host.querySelector(".mcp-dialog .mcp-danger")!);
    expect(host.querySelector(".mcp-app")).not.toBeNull();
    expect(host.querySelector("dialog")?.textContent).toContain("Access could not be revoked");
    failRevoke = false;
    await click(host.querySelector(".mcp-dialog .mcp-danger")!);
    expect(host.querySelector(".mcp-app")).toBeNull();
    expect(host.textContent).toContain("Codex access revoked.");
  });
  it("translates a visible revoke error without changing access or MCP configuration", async () => {
    apps = [{ id: "00000000-0000-4000-8000-000000000001", name: "Codex", client_id: "codex-client", scopes: ["research:read"], authorized_at: "2026-09-05T00:00:00Z" }];
    await mount();
    await click(host.querySelector(".mcp-app button")!);
    failRevoke = true;
    await click(host.querySelector(".mcp-dialog .mcp-danger")!);
    expect(host.querySelector(".mcp-dialog")?.textContent).toContain("Access could not be revoked");
    const requestsBeforeSwitch = [...requested];
    await act(async () => { await i18n.changeLanguage("zh-CN"); });
    expect(requested).toEqual(requestsBeforeSwitch);
    expect(host.querySelector(".mcp-dialog")?.textContent).toContain("无法撤销访问权限");
    expect(host.querySelector(".mcp-app")?.textContent).toContain("读取研究上下文、运行和结果");
    expect(host.textContent).toContain("检查研究准备情况");
    await click(button("复制设置提示"));
    expect(copied).toHaveBeenLastCalledWith(expect.stringContaining(endpoint));
    await click(button("Claude Code"));
    const command = [...host.querySelectorAll("pre code")].find(element => element.textContent?.startsWith("claude mcp add"));
    expect(command?.textContent).toBe(`claude mcp add --transport http --scope user quantgrove '${endpoint}'`);
    expect(requested).not.toContain("/api/auth/oauth2/consent");
  });
});
