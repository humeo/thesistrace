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
  expect(host.textContent).toContain("Allow Research client to access Quantgrove?");
  expect(host.textContent).toContain("Read research context, runs and results");
  const requestsBeforeSwitch = coreFetch.mock.calls.length;
  for (const [url, options] of coreFetch.mock.calls) {
    expect(url).toBe("/api/auth/mcp/authorization");
    expect(JSON.parse((options as RequestInit).body as string).oauth_query).toBe(search.slice(1));
  }
  await act(async () => { await i18n.changeLanguage("zh-CN"); });
  expect(coreFetch).toHaveBeenCalledTimes(requestsBeforeSwitch);
  expect(host.textContent).toContain("允许 Research client 访问 Quantgrove？");
  expect(host.textContent).toContain("读取研究上下文、运行和结果");
  expect(host.textContent).toContain("researcher@example.test");
});
