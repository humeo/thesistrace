import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useEffect, useState, type ReactNode } from "react";

/** Share authenticated reads only among research views in this open conversation. */
export function ResearchResourceProvider({ children }: { children: ReactNode }) {
  const [client] = useState(() => new QueryClient({ defaultOptions: { queries: {
    gcTime: 0, retry: false,
    refetchOnWindowFocus: false, refetchOnReconnect: false,
  } } }));
  useEffect(() => () => client.clear(), [client]);
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
