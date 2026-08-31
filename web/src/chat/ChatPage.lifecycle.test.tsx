// @vitest-environment happy-dom

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, expect, test, vi } from "vitest";

import { AuthProvider } from "../auth/AuthProvider";
import { ChatShell } from "./ChatPage";
import { ResearchChatCopilotProvider } from "./ResearchChatCopilotProvider";

vi.mock("../auth/client", () => ({ authClient: { getSession: async () => ({ data: null, error: null }) } }));

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let root: Root | undefined;
afterEach(async () => {
  await act(async () => { root?.unmount(); });
  root = undefined;
  vi.unstubAllGlobals();
  document.body.replaceChildren();
});

test("Chat waits for runtime discovery before enabling its private Agent proxy", async () => {
  const pending = await mountChat();
  expect(composer().disabled).toBe(true);
  await act(async () => { pending.resolveInfo(); });
  expect(composer().disabled).toBe(false);
});

test("a login that expires before the first Turn remains Authentication Required", async () => {
  const pending = await mountChat();
  await act(async () => { pending.resolveInfo(); });
  expect(composer().disabled).toBe(false);
  pending.expireLogin();
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!.call(composer(), "An Alpha idea.");
    composer().dispatchEvent(new Event("input", { bubbles: true }));
  });
  await act(async () => {
    document.querySelector<HTMLFormElement>("form.chat-composer-dock")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  });
  expect(document.querySelector(".chat-run-error")?.getAttribute("data-failure-code")).toBe("AUTHENTICATION_REQUIRED");
  expect(document.querySelector('.chat-run-error a')?.getAttribute("href")).toBe("/login");
  expect(document.querySelectorAll(".chat-message-user")).toHaveLength(0);
  expect(composer().value).toBe("An Alpha idea.");
  expect(pending.requests.filter((path) => path.endsWith("/info"))).toHaveLength(1);
});

function composer(): HTMLTextAreaElement { return document.querySelector('textarea[aria-label="Message"]')!; }

async function mountChat() {
  const requests: string[] = [];
  let expired = false;
  let resolveInfo!: () => void;
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const path = String(input);
    requests.push(path);
    if (path.endsWith("/info") && !expired) return new Promise<Response>((resolve) => {
      resolveInfo = () => resolve(Response.json({ version: "1.69.3", agents: { research: { description: "Research Agent" } }, mode: "sse" }));
    });
    if (path.includes("/api/agent/")) return Response.json({ code: "AUTHENTICATION_REQUIRED" }, { status: 401 });
    return Response.json(null);
  }));
  const container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  await act(async () => {
    root!.render(<AuthProvider><ResearchChatCopilotProvider><ChatShell
      catalogState={{ status: "ready", catalog: { default_model_key: "registered-model", models: [{
        key: "registered-model", display_name: "Registered model", default_reasoning_effort: "medium", reasoning_efforts: ["medium"],
      }] } }}
      navigateChat={vi.fn()}
      preferenceState={{ status: "not-required" }}
      reloadCatalog={vi.fn()}
      selectedSessionState={{ status: "not-required" }}
      sessionHistory={{ status: "ready", error: null, sessions: [], nextCursor: null, loadingMore: false, refreshVersion: 0,
        refresh: vi.fn(), loadMore: vi.fn(async () => undefined), watchGeneratedTitle: vi.fn(),
        deleteSession: vi.fn(async () => undefined), renameSession: vi.fn(async (session) => session),
      }}
      thread={{ kind: "new", id: "00000000-0000-4000-8000-000000000010" }}
    /></ResearchChatCopilotProvider></AuthProvider>);
  });
  return { requests, resolveInfo: () => resolveInfo(), expireLogin: () => { expired = true; } };
}
