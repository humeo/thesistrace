export class CoreAuthenticationRequiredError extends Error {
  constructor() {
    super("Core authentication is required");
    this.name = "CoreAuthenticationRequiredError";
  }
}

export class CoreUnavailableError extends Error {
  readonly cause?: unknown;

  constructor(message = "Core is unavailable", options?: { cause?: unknown }) {
    super(message);
    this.name = "CoreUnavailableError";
    this.cause = options?.cause;
  }
}

type FetchImplementation = typeof globalThis.fetch;

export function createCoreFetch(dependencies: Readonly<{
  fetch: FetchImplementation;
  onUnauthorized: () => void;
}>): FetchImplementation {
  return async (input, init) => {
    const requestInit: RequestInit = { ...init, credentials: "same-origin" };
    if (requestInit.body !== undefined && requestInit.body !== null) {
      const headers = new Headers(requestInit.headers);
      if (!headers.has("Content-Type")) {
        headers.set("Content-Type", "application/json");
      }
      requestInit.headers = headers;
    }

    let response: Response;
    try {
      response = await dependencies.fetch(input, requestInit);
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") throw error;
      throw new CoreUnavailableError("Core network request failed", { cause: error });
    }
    if (response.status === 401) {
      dependencies.onUnauthorized();
      throw new CoreAuthenticationRequiredError();
    }
    if (response.status === 503) {
      throw new CoreUnavailableError();
    }
    return response;
  };
}

let coreFetchImplementation = createCoreFetch({
  fetch: (...args) => globalThis.fetch(...args),
  onUnauthorized: () => undefined,
});

export function setCoreUnauthorizedHandler(onUnauthorized: () => void): () => void {
  coreFetchImplementation = createCoreFetch({
    fetch: (...args) => globalThis.fetch(...args),
    onUnauthorized,
  });
  return () => {
    coreFetchImplementation = createCoreFetch({
      fetch: (...args) => globalThis.fetch(...args),
      onUnauthorized: () => undefined,
    });
  };
}

export const coreFetch: FetchImplementation = (input, init) =>
  coreFetchImplementation(input, init);
