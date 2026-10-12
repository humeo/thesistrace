export type BrowserLocation = Readonly<{
  pathname: string;
  search: string;
  hash: string;
}>;

const AUTH_PATHS = new Set([
  "/login",
]);

const PRODUCT_ROOTS = new Set([
  "/chat",
  "/data",
  "/research",
  "/research-runs",
  "/research-runs/batches",
  "/daily-tracks",
  "/connections/mcp",
  "/connections/mcp/authorize",
]);

export function locationHref(location: BrowserLocation): string {
  return `${location.pathname}${location.search}${location.hash}`;
}

export function isAuthPath(pathname: string): boolean {
  return AUTH_PATHS.has(pathname);
}

export function isProductPath(pathname: string): boolean {
  return PRODUCT_ROOTS.has(pathname)
    || pathname === "/operator/researchers"
    || pathname === "/operator/data"
    || /^\/research-runs\/run_[a-f0-9]+$/.test(pathname)
    || /^\/research-runs\/batches\/batch_[a-f0-9]+$/.test(pathname)
    || /^\/daily-tracks\/track_[a-f0-9]+$/.test(pathname);
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
