// @vitest-environment happy-dom
import { act, StrictMode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { McpPage } from "./McpPage";

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
beforeEach(() => {
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
  it("discovers real tools and copies English setup without granting access", async () => {
    await mount();
    expect(host.textContent).toContain("Available");
    expect(host.textContent).toContain("1 tools");
    expect(host.textContent).not.toContain("Browse daily tracks");
    expect(host.textContent).not.toContain("Built into QuantTrace chat");
    await click(button("Copy setup prompt"));
    expect(copied).toHaveBeenLastCalledWith(expect.stringContaining(`Add QuantTrace MCP to Codex using ${endpoint}.`));
    expect(host.textContent).toContain("No authorized apps yet");
    await click(button("Claude Code"));
    await click(button("Copy setup prompt"));
    expect(copied).toHaveBeenLastCalledWith(expect.stringContaining("Add QuantTrace MCP to Claude Code"));
    expect(requested.every(path => !path.includes("revoke") && !path.includes("consent"))).toBe(true);
  });
  it("does not erase authorizations when a service check fails", async () => {
    apps = [{ id: "00000000-0000-4000-8000-000000000001", name: "Codex", client_id: "codex-client", scopes: ["research:read"], authorized_at: "2026-09-05T00:00:00Z" }];
    await mount(); failCheck = true;
    await click(button("Check connection"));
    expect(host.textContent).toContain("Unavailable");
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
});
