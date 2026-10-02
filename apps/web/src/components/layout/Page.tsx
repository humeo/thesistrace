import type { HTMLAttributes, ReactNode } from "react";
import { cn } from "cn";

export function Page({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("min-w-0 w-full", className)} {...props} />;
}

export function PageHeader({
  title, description, actions, className, badges, variant = "default",
}: {
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  className?: string;
  badges?: ReactNode;
  variant?: "default" | "result" | "console";
}) {
  return (
    <header className={cn("mb-8 flex flex-col items-start justify-between gap-6 max-[768px]:mb-6 min-[769px]:flex-row min-[769px]:flex-wrap", className)}>
      <div className="grid w-full min-w-0 flex-1 gap-2 min-[769px]:flex-[1_1_20rem]">
        {variant !== "default" ? <div className="flex min-w-0 flex-wrap items-center gap-x-4 gap-y-2">
          <h1 className="m-0 min-w-0 font-heading text-2xl leading-8 font-semibold tracking-[-0.02em] [overflow-wrap:anywhere]">{title}</h1>
          {badges}
        </div> : <h1 className="m-0 font-heading text-2xl leading-8 font-semibold tracking-[-0.02em] [overflow-wrap:anywhere]">{title}</h1>}
        {description ? <p className="m-0 text-sm text-muted-foreground">{description}</p> : null}
      </div>
      {actions ? <div className="flex max-w-full shrink-0 flex-wrap items-center gap-2">{actions}</div> : null}
    </header>
  );
}

export function PageContent({
  width = "wide", className, ...props
}: HTMLAttributes<HTMLDivElement> & { width?: "wide" | "settings" | "reading" }) {
  const maxWidth = { wide: "max-w-[1280px]", settings: "max-w-[960px]", reading: "max-w-[800px]" }[width];
  return <div className={cn("mx-auto w-full min-w-0", maxWidth, className)} {...props} />;
}

export function Section({
  title, actions, children, className,
}: {
  title: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  variant?: "default" | "console";
}) {
  return (
    <section className={cn("grid min-w-0 gap-4", className)}>
      <header className="flex flex-col items-start justify-between gap-4 min-[769px]:flex-row min-[769px]:items-center">
        <h2 className="m-0 font-heading text-xl leading-7 font-semibold tracking-[-0.02em]">{title}</h2>
        {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
      </header>
      {children}
    </section>
  );
}
