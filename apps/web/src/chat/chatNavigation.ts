import { isUuid } from "../uuid";

export type BrowserChatThread =
  | Readonly<{ id: string; kind: "new" }>
  | Readonly<{ id: string; kind: "session" }>
  | Readonly<{ id: null; kind: "invalid" }>;

export function chatSessionHref(sessionId: string): string {
  return `/chat?${new URLSearchParams({ session: sessionId }).toString()}`;
}

export function readBrowserChatThread(
  search: string,
  createId: () => string = () => crypto.randomUUID(),
): BrowserChatThread {
  const parameters = new URLSearchParams(search);
  const keys = [...parameters.keys()];
  const sessions = parameters.getAll("session");
  if (keys.length === 0) {
    return { id: createId(), kind: "new" };
  }
  const session = sessions.length === 1 ? sessions[0] : undefined;
  if (
    keys.every((key) => key === "session")
    && keys.length === 1
    && session !== undefined
    && isUuid(session)
  ) {
    return { id: session.toLowerCase(), kind: "session" };
  }
  return { id: null, kind: "invalid" };
}
