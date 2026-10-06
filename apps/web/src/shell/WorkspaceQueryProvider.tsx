import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useEffect, useState, type ReactNode } from "react";

export function WorkspaceQueryProvider({ researcherId, children }: { researcherId: string; children: ReactNode }) {
  return <ResearcherQueries key={researcherId}>{children}</ResearcherQueries>;
}

function ResearcherQueries({ children }: { children: ReactNode }) {
  const [client] = useState(() => new QueryClient({
    defaultOptions: { queries: {
      staleTime: 30_000,
      gcTime: 5 * 60_000,
      retry: false,
      refetchOnWindowFocus: false,
    } },
  }));
  // Discard the previous Researcher's facts and cancel its pending reads.
  useEffect(() => () => client.clear(), [client]);
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
