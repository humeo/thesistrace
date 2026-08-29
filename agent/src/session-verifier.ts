import { z } from "zod";

import { AgentAuthenticationUnavailableError } from "./failure.js";

const verifiedResearcherSchema = z
  .object({
    active: z.literal(true),
    display_label: z.string().min(1),
    email: z.email(),
    researcher_id: z.uuid(),
  })
  .strict();

export type VerifiedResearcher = Readonly<z.infer<typeof verifiedResearcherSchema>>;
type FetchImplementation = typeof globalThis.fetch;

export function createSessionVerifier(dependencies: Readonly<{
  authInternalOrigin: string;
  fetch?: FetchImplementation;
  timeoutMs?: number;
}>): (headers: Headers) => Promise<VerifiedResearcher | null> {
  const fetchImplementation = dependencies.fetch ?? globalThis.fetch;
  const timeoutMs = dependencies.timeoutMs ?? 2_000;
  return async (headers) => {
    const forwarded = new Headers();
    const cookie = headers.get("cookie");
    if (cookie !== null) forwarded.set("cookie", cookie);

    let response: Response;
    try {
      response = await fetchImplementation(
        `${dependencies.authInternalOrigin}/internal/session/verify`,
        {
          headers: forwarded,
          method: "POST",
          redirect: "error",
          signal: AbortSignal.timeout(timeoutMs),
        },
      );
    } catch {
      throw new AgentAuthenticationUnavailableError();
    }
    if (response.status === 401) return null;
    if (response.status !== 200) throw new AgentAuthenticationUnavailableError();

    try {
      const parsed = verifiedResearcherSchema.safeParse(await response.json());
      if (!parsed.success) throw new AgentAuthenticationUnavailableError();
      return parsed.data;
    } catch (error) {
      if (error instanceof AgentAuthenticationUnavailableError) throw error;
      throw new AgentAuthenticationUnavailableError();
    }
  };
}
