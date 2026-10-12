// @vitest-environment happy-dom
import { act, StrictMode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { i18n } from "../i18n";
import { McpAuthorizePage } from "./McpAuthorizePage";

vi.mock("../auth/AuthProvider", () => ({ useAuth: () => ({ state: { session: { email: "researcher@example.test" } } }) }));
const coreFetch = vi.fn();
vi.mock("../auth/coreFetch", () => ({ coreFetch: (...args: unknown[]) => coreFetch(...args) }));

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let root: Root;
let host: HTMLDivElement;
beforeEach(async () => {
  await i18n.changeLanguage("en");
  coreFetch.mockReset();
  coreFetch.mockImplementation(async () => Response.json({ name: "Research client", scopes: ["research:read", "offline_access"] }));
  host = document.createElement("div"); document.body.append(host); root = createRoot(host);
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); });

test("switching language preserves the signed OAuth query and displayed authorization", async () => {
  const search = "?client_id=abc&state=opaque%2Bvalue&scope=research%3Aread";
  await act(async () => root.render(<StrictMode><McpAuthorizePage search={search} /></StrictMode>));
  expect(host.textContent).toContain("Allow Research client to access QAgentis?");
  expect(host.textContent).toContain("Read research context, runs and results");
  const requestsBeforeSwitch = coreFetch.mock.calls.length;
  for (const [url, options] of coreFetch.mock.calls) {
    expect(url).toBe("/api/auth/mcp/authorization");
    expect(JSON.parse((options as RequestInit).body as string).oauth_query).toBe(search.slice(1));
  }
  await act(async () => { await i18n.changeLanguage("zh-CN"); });
  expect(coreFetch).toHaveBeenCalledTimes(requestsBeforeSwitch);
  expect(host.textContent).toContain("允许 Research client 访问 QAgentis？");
  expect(host.textContent).toContain("读取研究上下文、运行和结果");
  expect(host.textContent).toContain("researcher@example.test");
});

test("failed denial retains the authorization request and signed query for retry", async () => {
  const search = "?client_id=abc&state=signed%2Bstate";
  await act(async () => root.render(<McpAuthorizePage search={search} />));
  coreFetch.mockImplementation(async () => new Response(null, { status: 503 }));
  const cancel = [...host.querySelectorAll("button")].find(button => button.textContent === "Cancel")!;
  await act(async () => cancel.click());
  const [url, init] = coreFetch.mock.calls.at(-1)!;
  expect(url).toBe("/api/auth/oauth2/consent");
  expect(JSON.parse(init.body)).toEqual({ accept: false, oauth_query: search.slice(1) });
  expect(host.querySelector('[role="alert"]')).not.toBeNull();
  expect(cancel.disabled).toBe(false);
  expect(host.textContent).toContain("Research client");
});

test.each([
  [true, "Allow access", "Access approved"],
  [false, "Cancel", "Access denied"],
] as const)("completed consent remains understandable when callback navigation retains the page: %s", async (accept, action, title) => {
  const search = "?client_id=abc&state=signed%2Bstate";
  const callback = "http://127.0.0.1:8765/callback?state=signed%2Bstate";
  await act(async () => root.render(<McpAuthorizePage search={search} />));
  coreFetch.mockImplementation(async () => Response.json({ url: callback, redirect: true }));
  const navigation = vi.spyOn(window.location, "assign").mockImplementation(() => undefined);
  try {
    const button = [...host.querySelectorAll("button")].find(button => button.textContent === action)!;
    await act(async () => button.click());
    expect(navigation).toHaveBeenCalledWith(callback);
    expect(host.querySelector("h1")?.textContent).toBe(title);
    expect(host.querySelector('[role="status"]')?.textContent).toContain("Return to Research client. You can close this page.");
    expect(host.textContent).not.toContain("Continuing…");
    expect(host.querySelectorAll("button")).toHaveLength(0);
    const [url, init] = coreFetch.mock.calls.at(-1)!;
    expect(url).toBe("/api/auth/oauth2/consent");
    expect(JSON.parse(init.body)).toEqual({ accept, oauth_query: search.slice(1) });
    await act(async () => { await i18n.changeLanguage("zh-CN"); });
    expect(host.querySelector("h1")?.textContent).toBe(accept ? "已批准访问" : "已拒绝访问");
    expect(host.querySelector('[role="status"]')?.textContent).toContain("请返回 Research client，你可以关闭此页。");
  } finally { navigation.mockRestore(); }
});

test("a failed callback navigation preserves the approved decision without offering consent again", async () => {
  await act(async () => root.render(<McpAuthorizePage search="?client_id=abc" />));
  coreFetch.mockImplementation(async () => Response.json({ url: "http://127.0.0.1:8765/callback", redirect: true }));
  const navigation = vi.spyOn(window.location, "assign").mockImplementation(() => { throw new DOMException("Navigation blocked", "SecurityError"); });
  try {
    const allow = [...host.querySelectorAll("button")].find(button => button.textContent === "Allow access")!;
    await act(async () => allow.click());
    expect(host.querySelector("h1")?.textContent).toBe("Access approved");
    expect(host.querySelector('[role="alert"]')?.textContent).toContain("Could not return automatically. Return to your AI client to continue.");
    expect(host.querySelectorAll("button")).toHaveLength(0);
    expect(host.textContent).not.toContain("Authorization could not be completed");
  } finally { navigation.mockRestore(); }
});

test.each([200, 503])("changing authorization requests ignores a pending consent response: %s", async status => {
  let complete!: (response: Response) => void;
  coreFetch.mockImplementation(async (url: string, init: RequestInit) => {
    if (url === "/api/auth/oauth2/consent") return new Promise<Response>(resolve => { complete = resolve; });
    const query = JSON.parse(init.body as string).oauth_query;
    return Response.json({ name: query.includes("client_id=new") ? "New client" : "Old client", scopes: ["research:read"] });
  });
  const navigation = vi.spyOn(window.location, "assign").mockImplementation(() => undefined);
  try {
    await act(async () => root.render(<McpAuthorizePage search="?client_id=old" />));
    await act(async () => [...host.querySelectorAll("button")].find(button => button.textContent === "Allow access")!.click());
    await act(async () => root.render(<McpAuthorizePage search="?client_id=new" />));
    expect(host.querySelector("h1")?.textContent).toBe("Allow New client to access QAgentis?");
    expect([...host.querySelectorAll("button")].every(button => !button.disabled)).toBe(true);
    await act(async () => { complete(status === 200 ? Response.json({ url: "http://127.0.0.1:8765/old", redirect: true }) : new Response(null, { status })); });
    expect(navigation).not.toHaveBeenCalled();
    expect(host.querySelector("h1")?.textContent).toBe("Allow New client to access QAgentis?");
    expect(host.querySelector('[role="alert"]')).toBeNull();
  } finally { navigation.mockRestore(); }
});
