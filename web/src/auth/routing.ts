export type BrowserLocation = Readonly<{
  pathname: string;
  search: string;
  hash: string;
}>;

export type InitialAuthSecret = Readonly<{
  kind: "invitation" | "password-reset";
  token: string;
}>;

const AUTH_PATHS = new Set([
  "/login",
  "/accept-invitation",
  "/forgot-password",
  "/reset-password",
]);

const PRODUCT_ROOTS = new Set([
  "/chat",
  "/data",
  "/research",
  "/research-runs",
  "/daily-tracks",
]);

export function locationHref(location: BrowserLocation): string {
  return `${location.pathname}${location.search}${location.hash}`;
}

export function isAuthPath(pathname: string): boolean {
  return AUTH_PATHS.has(pathname);
}

export function isProductPath(pathname: string): boolean {
  return PRODUCT_ROOTS.has(pathname)
    || /^\/research-runs\/run_[a-f0-9]+$/.test(pathname)
    || /^\/daily-tracks\/track_[a-f0-9]+$/.test(pathname);
}

export function extractInitialAuthSecret(location: BrowserLocation): Readonly<{
  location: BrowserLocation;
  secret: InitialAuthSecret | null;
}> {
  if (
    location.pathname !== "/accept-invitation"
    && location.pathname !== "/reset-password"
  ) {
    return { location, secret: null };
  }

  const cleared = { ...location, hash: "" };
  const fragment = new URLSearchParams(location.hash.startsWith("#")
    ? location.hash.slice(1)
    : location.hash);
  const token = fragment.get("token");
  if (fragment.size !== 1 || token === null || token.length === 0) {
    return { location: cleared, secret: null };
  }
  return {
    location: cleared,
    secret: {
      kind: location.pathname === "/accept-invitation"
        ? "invitation"
        : "password-reset",
      token,
    },
  };
}

export function safeReturnTo(
  candidate: string | null | undefined,
  publicOrigin: string,
): string | null {
  if (
    candidate === null
    || candidate === undefined
    || candidate === ""
    || !candidate.startsWith("/")
    || candidate.startsWith("//")
    || candidate.includes("\\")
  ) return null;

  try {
    const origin = new URL(publicOrigin).origin;
    const destination = new URL(candidate, origin);
    if (destination.origin !== origin || !isProductPath(destination.pathname)) {
      return null;
    }
    return `${destination.pathname}${destination.search}${destination.hash}`;
  } catch {
    return null;
  }
}
