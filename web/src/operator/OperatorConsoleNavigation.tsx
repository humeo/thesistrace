export function OperatorConsoleNavigation({
  current,
}: Readonly<{
  current: "data" | "researchers";
}>) {
  return (
    <nav aria-label="Operator Console sections" className="operator-subnav">
      <a
        aria-current={current === "researchers" ? "page" : undefined}
        href="/operator/researchers"
      >
        Researchers
      </a>
      <a
        aria-current={current === "data" ? "page" : undefined}
        href="/operator/data"
      >
        Data
      </a>
    </nav>
  );
}
