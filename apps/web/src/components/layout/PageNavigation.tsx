import type { ReactNode } from "react";
import { CaretLeft, CaretRight } from "@phosphor-icons/react";
import { Button } from "../ui/button";
import { Pagination, PaginationContent, PaginationItem } from "../ui/pagination";

/** Shared pagination presentation; resource controllers own page state and requests. */
export function PageNavigation({
  label, previousLabel, nextLabel, previousDisabled, nextDisabled, onPrevious, onNext, children,
}: {
  label: string;
  previousLabel: string;
  nextLabel: string;
  previousDisabled: boolean;
  nextDisabled: boolean;
  onPrevious: () => void;
  onNext: () => void;
  children: ReactNode;
}) {
  return <Pagination aria-label={label}>
    <PaginationContent className="w-full flex-wrap justify-between gap-3">
      <PaginationItem><Button variant="outline" disabled={previousDisabled} onClick={onPrevious}><CaretLeft data-icon="inline-start" />{previousLabel}</Button></PaginationItem>
      <PaginationItem className="order-last w-full sm:order-none sm:w-auto sm:flex-1">
        <span aria-live="polite" className="flex flex-wrap justify-center gap-x-4 gap-y-1 text-center text-xs text-muted-foreground tabular-nums">{children}</span>
      </PaginationItem>
      <PaginationItem><Button variant="outline" disabled={nextDisabled} onClick={onNext}>{nextLabel}<CaretRight data-icon="inline-end" /></Button></PaginationItem>
    </PaginationContent>
  </Pagination>;
}
