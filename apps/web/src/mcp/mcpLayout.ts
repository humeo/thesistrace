/** Shared MCP page patterns composed from the product Tailwind tokens. */
export const mcpLayout = {
  page: "flex min-w-0 flex-col gap-6 [&_h2]:m-0 [&_h2]:text-base [&_h2]:leading-6 [&_h2]:font-semibold [&_h3]:m-0 [&_h3]:flex [&_h3]:items-center [&_h3]:gap-2 [&_h3]:text-sm [&_h3]:leading-[22px] [&_h3]:font-semibold [&_p]:m-0 [&_p]:text-sm [&_p]:leading-[22px] [&_p]:text-muted-foreground [&_ul]:m-0 [&_ul]:pl-5 [&_ul]:leading-[22px] [&_code]:[overflow-wrap:anywhere] [&_code]:text-sm [&_small]:text-xs [&_small]:leading-[18px] [&_small]:text-muted-foreground",
  stack: "flex min-w-0 flex-col gap-3 [&_h2]:m-0 [&_h2]:text-base [&_h2]:leading-6 [&_h2]:font-semibold [&_p]:m-0 [&_p]:text-sm [&_p]:leading-[22px] [&_p]:text-muted-foreground [&_ul]:m-0 [&_ul]:pl-5 [&_ul]:leading-[22px]",
  row: "flex min-w-0 flex-wrap items-center gap-3 [&>svg]:size-4 [&>svg]:shrink-0",
  library: "grid grid-cols-[minmax(0,1.4fr)_minmax(280px,1fr)] gap-6 max-[960px]:grid-cols-1",
  steps: "m-0 grid list-decimal grid-cols-3 gap-6 pl-6 max-[768px]:grid-cols-1 [&_span]:mt-2 [&_span]:block [&_span]:text-sm [&_span]:leading-[22px] [&_span]:text-muted-foreground",
  prompt: "whitespace-pre-wrap [overflow-wrap:anywhere]",
  code: "max-w-full overflow-x-auto rounded-md border border-border bg-muted p-3",
  toolLabel: "flex min-w-0 flex-col gap-1 text-left",
} as const;
