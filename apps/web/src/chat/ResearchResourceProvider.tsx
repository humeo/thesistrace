import { dehydrate, hydrate, QueryClient, QueryClientProvider, useQueryClient } from "@tanstack/react-query";
import { useEffect, useId, useState, type ReactNode } from "react";

/** Mount per conversation; preserve each read's freshness across navigation. */
export function ResearchResourceProvider({ children, conversationId }: { children: ReactNode; conversationId?: string }) {
  const workspace = useQueryClient();
  const instanceId = useId();
  const scope = conversationId ?? instanceId;
  const [client] = useState(() => {
    const client = new QueryClient({ defaultOptions: { queries: {
      gcTime: 0, retry: false,
      refetchOnWindowFocus: false, refetchOnReconnect: false,
    } } });
    const snapshot = workspace.getQueryData(["chat-research-snapshot", scope]);
    if (snapshot) hydrate(client, snapshot);
    return client;
  });
  useEffect(() => () => {
    // The workspace cache expires these snapshots and clears on account change.
    workspace.setQueryData(["chat-research-snapshot", scope], dehydrate(client));
    client.clear();
  }, [client, scope, workspace]);
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
