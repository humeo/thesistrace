import type { HTMLAttributes, ReactNode } from "react";
import { cn } from "cn";

export function Page({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("min-w-0 w-full", className)} {...props} />;
}

export function PageHeader({
  title, description, actions, className,
}: {
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  className?: string;
}) {
  return (
    <header className={cn("mb-8 flex flex-col items-start justify-between gap-6 max-[768px]:mb-6 min-[769px]:flex-row", className)}>
      <div className="grid min-w-0 gap-2">
        <h1 className="m-0 text-2xl leading-8 font-semibold tracking-normal [overflow-wrap:anywhere]">{title}</h1>
        {description ? <p className="m-0 text-sm leading-[22px] text-muted-foreground">{description}</p> : null}
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </header>
  );
}

export function PageContent({
  width = "wide", className, ...props
}: HTMLAttributes<HTMLDivElement> & { width?: "wide" | "settings" | "reading" }) {
  const maxWidth = { wide: "max-w-[1440px]", settings: "max-w-[960px]", reading: "max-w-[800px]" }[width];
  return <div className={cn("mx-auto w-full min-w-0", maxWidth, className)} {...props} />;
}

export function Section({
  title, actions, children, className,
}: {
  title: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={cn("grid min-w-0 gap-4", className)}>
      <header className="flex flex-col items-start justify-between gap-4 min-[769px]:flex-row min-[769px]:items-center">
        <h2 className="m-0 text-base leading-6 font-semibold">{title}</h2>
        {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
      </header>
      {children}
    </section>
  );
}
