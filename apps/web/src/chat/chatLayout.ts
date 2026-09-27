/** Chat workspace sizing and composition; rendered Markdown has its own scoped rules. */
export const chatLayout = {
  main: "grid h-dvh min-h-0 min-w-0 grid-rows-[minmax(0,1fr)_auto] overflow-hidden",
  newMain: "grid-rows-[1fr]",
  conversationMain: "grid-rows-[auto_minmax(0,1fr)_auto]",
  start: "grid min-h-0 w-full content-center justify-items-center gap-6 overflow-y-auto py-8 max-[768px]:pt-16",
  dock: "w-[min(800px,calc(100%-64px))] justify-self-center pb-4 max-[1024px]:w-[min(800px,calc(100%-48px))] max-[768px]:w-[min(800px,calc(100%-32px))]",
  surface: "min-w-0 rounded-lg border border-border bg-card has-[textarea:focus-visible]:outline-2 has-[textarea:focus-visible]:outline-offset-2 has-[textarea:focus-visible]:outline-ring",
  input: "block min-h-20 max-h-[min(180px,40dvh)] w-full resize-none overflow-y-auto rounded-lg border-0 bg-transparent p-4 text-sm leading-[22px] shadow-none focus-visible:outline-none focus-visible:[box-shadow:none]! max-[768px]:max-h-[min(180px,32dvh)]",
  question: "max-h-[min(560px,65dvh)]",
  questionInput: "min-w-0 max-h-[min(140px,20dvh)] resize-none border-0 bg-transparent shadow-none focus-visible:outline-none focus-visible:[box-shadow:none]!",
  timelineShell: "relative min-h-0 min-w-0 overflow-hidden",
  timeline: "h-full min-h-0 w-full overflow-auto overscroll-contain focus-visible:-outline-offset-2 focus-visible:outline-2 focus-visible:outline-ring",
  content: "mx-auto flex w-[min(800px,calc(100%-64px))] flex-col gap-6 pt-8 pb-14 max-[1024px]:w-[min(800px,calc(100%-48px))] max-[768px]:w-[min(800px,calc(100%-32px))] max-[768px]:pt-6",
  header: "flex min-h-16 min-w-0 items-center border-b border-border py-3 [&_h1]:mx-auto [&_h1]:w-[min(800px,calc(100%-64px))] max-[1024px]:[&_h1]:w-[min(800px,calc(100%-48px))] max-[768px]:[&_h1]:w-[min(800px,calc(100%-32px))] max-[768px]:[&_h1]:pl-12",
} as const;
