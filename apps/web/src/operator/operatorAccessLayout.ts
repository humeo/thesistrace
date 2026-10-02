/** Shared researcher directory and confirmation layout. */
export const operatorAccessLayout = {
  page: "console-workspace flex min-w-0 flex-col gap-6",
  section: "flex min-w-0 flex-col gap-4",
  header: "flex flex-wrap items-end justify-between gap-4 [&_h2]:m-0 [&_h2]:text-xl [&_h2]:leading-7 [&_h2]:font-semibold",
  search: "w-full max-w-[520px]",
  identity: "flex min-w-[180px] max-w-80 flex-col gap-1 whitespace-normal [overflow-wrap:anywhere] [&_small]:text-sm [&_small]:leading-[22px] [&_small]:text-muted-foreground",
  form: "min-w-0",
  emailTarget: "min-w-0 [overflow-wrap:anywhere]",
  eyebrow: "m-0 text-xs text-muted-foreground",
  target: "m-0 grid gap-3 [&>div]:grid [&>div]:grid-cols-[minmax(100px,1fr)_minmax(0,2fr)] [&>div]:gap-3 max-[480px]:[&>div]:grid-cols-1 max-[480px]:[&>div]:gap-1 [&_dt]:text-xs [&_dt]:leading-[18px] [&_dt]:text-muted-foreground [&_dd]:m-0 [&_dd]:flex [&_dd]:min-w-0 [&_dd]:flex-col [&_dd]:gap-1 [&_dd]:[overflow-wrap:anywhere] [&_dd]:text-sm [&_dd]:leading-[22px] [&_code]:font-mono",
} as const;
