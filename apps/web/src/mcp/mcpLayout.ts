/** Shared MCP page patterns composed from the product Tailwind tokens. */
export const mcpLayout = {
  page: "flex min-w-0 flex-col gap-8",
  sectionTitle: "m-0 font-heading text-xl leading-7 font-medium tracking-[-0.02em]",
  stack: "flex min-w-0 flex-col gap-3 [&_h2]:m-0 [&_h2]:text-xl [&_h2]:leading-7 [&_h2]:font-semibold [&_p]:m-0 [&_p]:text-sm [&_p]:leading-[22px] [&_p]:text-muted-foreground [&_ul]:m-0 [&_ul]:pl-4 [&_ul]:leading-6",
  row: "flex min-w-0 flex-wrap items-center gap-3 [&>svg]:size-4 [&>svg]:shrink-0",
  library: "grid grid-cols-[minmax(0,1.7fr)_minmax(320px,1fr)] gap-4 max-[960px]:grid-cols-1",
  steps: "m-0 grid list-decimal grid-cols-3 gap-6 pl-6 max-[768px]:grid-cols-1 py-4 [&_strong]:text-base [&_strong]:font-medium",
  prompt: "whitespace-pre-wrap [overflow-wrap:anywhere]",
  code: "m-0 min-w-0 flex-1 whitespace-pre-wrap [overflow-wrap:anywhere] px-3 py-2 font-mono text-sm font-normal [&_code]:[font:inherit]",
  toolLabel: "flex min-w-0 flex-1 flex-col gap-1 text-left",
} as const;
