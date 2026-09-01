// @vitest-environment happy-dom

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, expect, test, vi } from "vitest";
import type { RunAgentInput } from "@ag-ui/core";

import { AuthProvider } from "../auth/AuthProvider";
import { ChatShell } from "./ChatPage";
import { ResearchChatCopilotProvider } from "./ResearchChatCopilotProvider";
import { SessionHistoryList } from "./SessionHistoryList";

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

test.each([false, true])("an unaccepted Turn retry preserves its original request (existing Session: %s)", async (existing) => {
  const submitted: RunAgentInput[] = [];
  const pending = await mountChat({ existing, run: (input) => {
    submitted.push(input);
    return eventStream([{ type: "RUN_ERROR", code: "AGENT_CAPACITY", message: "Agent at capacity" }]);
  } });
  await act(async () => { pending.resolveInfo(); });
  expect(composer().disabled).toBe(false);
  const original = "Inspect this new Alpha idea, not my earlier request.";
  await setDraft(original);
  await act(async () => {
    document.querySelector<HTMLFormElement>("form.chat-composer-dock")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  });
  expect(composer().value).toBe(original);
  expect(document.querySelector(".chat-run-error")?.getAttribute("data-failure-code")).toBe("AGENT_CAPACITY");
  await setDraft("An unsent edit is separate from retrying the rejected Turn.");
  await act(async () => {
    [...document.querySelectorAll<HTMLButtonElement>(".chat-run-error button")]
      .find((button) => button.textContent === "Retry with selected model")!.click();
  });
  expect(submitted).toHaveLength(2);
  expect(submitted.map((input) => input.messages.at(-1)?.content)).toEqual([original, original]);
  expect(submitted[1]?.forwardedProps.thesistrace.sessionMode).toBe(existing ? "existing" : "new");
});

test("once a retried Turn is accepted, later retry inspects durable history instead of repeating the original command", async () => {
  const submitted: RunAgentInput[] = [];
  const pending = await mountChat({ existing: true, run: (input) => {
    submitted.push(input);
    return eventStream(submitted.length === 1
      ? [{ type: "RUN_ERROR", code: "AGENT_CAPACITY", message: "Agent at capacity" }]
      : [{ type: "RUN_STARTED", threadId: input.threadId, runId: input.runId },
        { type: "RUN_ERROR", code: "PROVIDER_RATE_LIMIT", message: "Provider rate limit" }]);
  } });
  await act(async () => { pending.resolveInfo(); });
  await setDraft("Create the research run once.");
  await act(async () => {
    document.querySelector<HTMLFormElement>("form.chat-composer-dock")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  });
  for (let attempt = 0; attempt < 2; attempt++) {
    await act(async () => {
      [...document.querySelectorAll<HTMLButtonElement>(".chat-run-error button")]
        .find((button) => button.textContent === "Retry with selected model")!.click();
    });
  }
  expect(submitted.map((input) => input.messages.at(-1)?.content)).toEqual([
    "Create the research run once.", "Create the research run once.",
    "Retry the previous request. Inspect retained research before starting new work.",
  ]);
});

test.each(["succeeds", "fails"])("Chat deletion preserves modal and navigation state when it %s", async (outcome) => {
  const session = {
    id: "00000000-0000-4000-8000-000000000010", title: "Earlier research", active_run: false,
    created_at: "2026-08-31T00:00:00.000000Z", activity_at: "2026-08-31T00:00:00.000000Z",
    version: "2026-08-31T00:00:00.000Z",
  };
  let navigation: { href: string; modalOpen: boolean } | undefined;
  const container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  await act(async () => {
    root!.render(<SessionHistoryList
      controller={{ status: "ready", error: null, sessions: [session], nextCursor: null,
        loadingMore: false, refreshVersion: 0, refresh: vi.fn(),
        loadMore: vi.fn(async () => undefined), watchGeneratedTitle: vi.fn(),
        deleteSession: async () => { if (outcome === "fails") throw new Error("Request failed"); },
        renameSession: vi.fn(async (item) => item),
      }}
      currentSessionId={session.id}
      navigate={(href) => { navigation = { href, modalOpen: document.querySelector("dialog[open]") !== null }; }}
      navigationInteractive
      restoreFocus={() => undefined}
    />);
  });
  await act(async () => {
    document.querySelector<HTMLButtonElement>('[aria-label="Actions for Earlier research"]')!.click();
  });
  await act(async () => {
    [...document.querySelectorAll<HTMLButtonElement>('[role="menuitem"]')]
      .find((button) => button.textContent?.trim() === "Delete Chat")!.click();
  });
  expect(document.querySelector<HTMLDialogElement>("dialog")?.open).toBe(true);
  await act(async () => {
    document.querySelector<HTMLFormElement>("dialog form")!
      .dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  });
  if (outcome === "succeeds") {
    expect(navigation).toEqual({ href: "/chat", modalOpen: false });
    expect(document.querySelector("dialog")).toBeNull();
  } else {
    expect(navigation).toBeUndefined();
    expect(document.querySelector<HTMLDialogElement>("dialog")?.open).toBe(true);
    expect(document.querySelector('dialog [role="alert"]')?.textContent)
      .toBe("The Chat could not be deleted.");
  }
});

function composer(): HTMLTextAreaElement { return document.querySelector('textarea[aria-label="Message"]')!; }

async function setDraft(content: string): Promise<void> {
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!.call(composer(), content);
    composer().dispatchEvent(new Event("input", { bubbles: true }));
  });
}

function eventStream(events: unknown[]): Response {
  return new Response(events.map((event) => `data: ${JSON.stringify(event)}\n\n`).join(""), { headers: { "content-type": "text/event-stream" } });
}

async function mountChat(options: { existing?: boolean; run?: (input: RunAgentInput) => Response } = {}) {
  const requests: string[] = [];
  const session = { id: "00000000-0000-4000-8000-000000000010", title: "Earlier research", active_run: false,
    created_at: "2026-08-31T00:00:00.000000Z", activity_at: "2026-08-31T00:00:00.000000Z", version: "2026-08-31T00:00:00.000Z" };
  let expired = false;
  let resolveInfo!: () => void;
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input);
    requests.push(path);
    if (path.endsWith("/info") && !expired) return new Promise<Response>((resolve) => {
      resolveInfo = () => resolve(Response.json({ version: "1.69.3", agents: { research: { description: "Research Agent" } }, mode: "sse" }));
    });
    if (options.run && path.endsWith("/run")) return options.run(JSON.parse(String(init?.body)) as RunAgentInput);
    if (options.existing && path.endsWith(`/sessions/${session.id}`)) return Response.json(session);
    if (options.existing && path.endsWith("/connect")) return eventStream([
      { type: "RUN_STARTED", threadId: session.id, runId: "earlier-run" },
      { type: "MESSAGES_SNAPSHOT", messages: [{ id: "earlier-message", role: "user", content: "An earlier, unrelated idea." }] },
      { type: "RUN_FINISHED", threadId: session.id, runId: "earlier-run" },
    ]);
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
      preferenceState={options.existing ? { status: "ready", preference: { model_key: "registered-model", reasoning_effort: "medium" } } : { status: "not-required" }}
      reloadCatalog={vi.fn()}
      selectedSessionState={options.existing ? { status: "ready", session } : { status: "not-required" }}
      sessionHistory={{ status: "ready", error: null, sessions: [], nextCursor: null, loadingMore: false, refreshVersion: 0,
        refresh: vi.fn(), loadMore: vi.fn(async () => undefined), watchGeneratedTitle: vi.fn(),
        deleteSession: vi.fn(async () => undefined), renameSession: vi.fn(async (session) => session),
      }}
      thread={{ kind: options.existing ? "session" : "new", id: session.id }}
    /></ResearchChatCopilotProvider></AuthProvider>);
  });
  return { requests, resolveInfo: () => resolveInfo(), expireLogin: () => { expired = true; } };
}
