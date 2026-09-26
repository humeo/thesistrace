/** Keep canvas charts in the same semantic palette as the surrounding Classic UI. */
export function chartTheme(element: Element) {
  const styles = getComputedStyle(element);
  const color = (name: string) => styles.getPropertyValue(name).trim();
  return {
    background: color("--card"),
    text: color("--muted-foreground"),
    grid: color("--muted"),
    border: color("--border"),
    strategy: color("--chart-1"),
    benchmark: color("--chart-4"),
    zero: color("--muted-foreground"),
  };
}
