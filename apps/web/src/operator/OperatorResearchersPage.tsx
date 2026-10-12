import { Fragment } from "react";
import { CaretRight } from "@phosphor-icons/react";
import { MagnifyingGlass } from "@phosphor-icons/react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "../i18n";
import { formatNumber, formatTimestamp as formatLocaleTimestamp } from "../i18n/format";

import {
  loadResearcherPage,
  OperatorPageNotFoundError,
  type OperatorPage,
  type OperatorResearcher,
} from "./operatorDirectoryClient";
import { OperatorConsoleNavigation } from "./OperatorConsoleNavigation";
import {
  OperatorSessionRevocationDialog,
  type SessionRevocationTarget,
} from "./OperatorSessionRevocationDialog";

import { Button } from "../components/ui/button";
import { Badge } from "../components/ui/badge";
import { InputGroup, InputGroupInput, InputGroupAddon } from "../components/ui/input-group";
import { Field, FieldLabel } from "../components/ui/field";
import { Alert, AlertDescription } from "../components/ui/alert";
import { PageHeader } from "../components/layout/Page";
import { PageNavigation } from "../components/layout/PageNavigation";
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell, TableCaption } from "../components/ui/table";
import { operatorAccessLayout } from "./operatorAccessLayout";
const operatorRetryButtonId = "operator-console-retry";
const operatorPageFallbackId = "operator-console-focus-fallback";

export function OperatorResearchersPage({ operatorResearcherId }: Readonly<{
  operatorResearcherId: string;
}>) {
  const { t } = useTranslation("operator");
  const [researchers, setResearchers] = useState<OperatorPage<OperatorResearcher> | null>(null);
  const [search, setSearch] = useState("");
  const [researcherCursor, setResearcherCursor] = useState<string | null>(null);
  const [researcherHistory, setResearcherHistory] = useState<Array<string | null>>([]);
  const [reloadGeneration, setReloadGeneration] = useState(0);
  const [state, setState] = useState<"loading" | "not-found" | "ready" | "unavailable">("loading");
  const [sessionTarget, setSessionTarget] = useState<SessionRevocationTarget | null>(null);
  const [sessionMutationNotice, setSessionMutationNotice] = useState<{ count: number; email: string } | null>(null);
  const mutationFocusTargetId = useRef<string | null>(null);
  const mutationFocusFallbackId = useRef<string>(operatorPageFallbackId);
  const restoreMutationFocusAfterLoad = useRef(false);

  const load = useCallback(async (signal: AbortSignal) => {
    setState("loading");
    try {
      const researcherPage = await loadResearcherPage(search, researcherCursor, signal);
      if (signal.aborted) return;
      setResearchers(researcherPage);
    } catch (error) {
      if (signal.aborted) return;
      setResearchers(null);
      setState(error instanceof OperatorPageNotFoundError ? "not-found" : "unavailable");
      return;
    }
    setState("ready");
  }, [researcherCursor, search]);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load, reloadGeneration]);

  useEffect(() => {
    if (state === "loading" || !restoreMutationFocusAfterLoad.current) return;
    restoreMutationFocusAfterLoad.current = false;
    const frame = window.requestAnimationFrame(() => {
      restoreMutationFocus(
        mutationFocusTargetId.current,
        mutationFocusFallbackId.current,
      );
    });
    return () => window.cancelAnimationFrame(frame);
  }, [state]);

  if (state === "not-found") {
    return (
      <section
        aria-label={t("researchers.directory.notFound")}
        className="page-section state-section outline-none"
        id={operatorPageFallbackId}
        tabIndex={-1}
      >
        <h1>{t("researchers.directory.notFound")}</h1>
        <p>{t("researchers.directory.notFoundDescription")}</p>
      </section>
    );
  }

  function closeSessionDialog(afterReload = false): void {
    setSessionTarget(null);
    if (afterReload) {
      restoreMutationFocusAfterLoad.current = true;
      return;
    }
    restoreMutationFocusAfterLoad.current = false;
    window.requestAnimationFrame(() => {
      restoreMutationFocus(
        mutationFocusTargetId.current,
        mutationFocusFallbackId.current,
      );
    });
  }

  function openSessionDialog(
    trigger: HTMLButtonElement,
    target: SessionRevocationTarget,
  ): void {
    mutationFocusTargetId.current = trigger.id || null;
    mutationFocusFallbackId.current = operatorPageFallbackId;
    setSessionMutationNotice(null);
    setSessionTarget(target);
  }

  return (
    <>
      <OperatorResearchersView
        operatorResearcherId={operatorResearcherId}
        onResearcherNext={() => {
          if (state !== "ready" || researchers === null || researchers.next_cursor === null) {
            return;
          }
          setState("loading");
          setResearcherHistory((history) => [...history, researcherCursor]);
          setResearcherCursor(researchers.next_cursor);
        }}
        onResearcherPrevious={() => {
          if (state !== "ready") return;
          const previous = researcherHistory.at(-1);
          if (previous === undefined) return;
          setState("loading");
          setResearcherHistory((history) => history.slice(0, -1));
          setResearcherCursor(previous);
        }}
        onSessionRevocation={openSessionDialog}
        onRetry={() => {
          if (state === "loading") return;
          setState("loading");
          setReloadGeneration((value) => value + 1);
        }}
        onSearch={(value) => {
          if (state !== "ready") return;
          const reloadCurrent = value === search && researcherCursor === null;
          setState("loading");
          setSearch(value);
          setResearcherCursor(null);
          setResearcherHistory([]);
          if (reloadCurrent) setReloadGeneration((generation) => generation + 1);
        }}
        researcherCursorDepth={researcherHistory.length}
        researchers={researchers}
        search={search}
        sessionMutationNotice={sessionMutationNotice}
        state={state}
      />

      {sessionTarget === null ? null : (
        <OperatorSessionRevocationDialog
          onDismiss={closeSessionDialog}
          onSucceeded={({ revokedSessionCount }) => {
            setSessionMutationNotice({ count: revokedSessionCount, email: sessionTarget.email });
            setResearcherCursor(null);
            setResearcherHistory([]);
            setState("loading");
            setReloadGeneration((value) => value + 1);
            closeSessionDialog(true);
          }}
          target={sessionTarget}
        />
      )}
    </>
  );
}

export function OperatorResearchersView({
  operatorResearcherId,
  onResearcherNext,
  onResearcherPrevious,
  onSessionRevocation,
  onRetry,
  onSearch,
  researcherCursorDepth,
  researchers,
  search,
  sessionMutationNotice,
  state = "ready",
}: Readonly<{
  operatorResearcherId: string;
  onResearcherNext: () => void;
  onResearcherPrevious: () => void;
  onSessionRevocation?: (
    trigger: HTMLButtonElement,
    target: SessionRevocationTarget,
  ) => void;
  onRetry?: () => void;
  onSearch: (value: string) => void;
  researcherCursorDepth: number;
  researchers: OperatorPage<OperatorResearcher> | null;
  search: string;
  sessionMutationNotice?: { count: number; email: string } | null;
  state?: "loading" | "ready" | "unavailable";
}>) {
  const { t } = useTranslation("operator");
  const [draft, setDraft] = useState(search);
  const busy = state === "loading";
  return (
    <section
      aria-busy={busy}
      aria-label={t("researchers.directory.pageLabel")}
      className={`${operatorAccessLayout.page} outline-none`}
      id={operatorPageFallbackId}
      tabIndex={-1}
    >
      <PageHeader variant="console" title={t("researchers.directory.title")} className="mb-0" />

      <OperatorConsoleNavigation current="researchers" />

      <OperatorLoadState
        hasData={researchers !== null}
        onRetry={onRetry}
        state={state}
      />

      <section
        aria-busy={busy}
        aria-labelledby="operator-researchers-title"
        className={operatorAccessLayout.section}
      >
        <header className="flex flex-col items-start gap-3 [&_h2]:m-0 [&_h2]:text-xl [&_h2]:leading-7 [&_h2]:font-semibold">
          <div>
            <h2 id="operator-researchers-title">{t("researchers.directory.researchers")}</h2>
          </div>
          <form
            className={operatorAccessLayout.search}
            onSubmit={(event) => {
              event.preventDefault();
              onSearch(draft);
            }}
          >
            <Field><FieldLabel className="sr-only" htmlFor="operator-researcher-search">{t("researchers.directory.searchResearchers")}</FieldLabel>
            <InputGroup>
              <InputGroupAddon><MagnifyingGlass aria-hidden="true" /></InputGroupAddon>
              <InputGroupInput
                aria-label={t("researchers.directory.searchResearchers")}
                disabled={state !== "ready"}
                id="operator-researcher-search"
                onChange={(event) => setDraft(event.target.value)}
                placeholder={t("researchers.directory.searchPlaceholder")}
                type="search"
                value={draft}
              />
              <InputGroupAddon align="inline-end"><Button variant="ghost" disabled={state !== "ready"} type="submit">{t("researchers.directory.search")}</Button></InputGroupAddon>
            </InputGroup></Field>
          </form>
        </header>
        {sessionMutationNotice === null || sessionMutationNotice === undefined
          ? null
          : (
              <p aria-live="polite" className="inline-status" role="status">
                {t("researchers.directory.sessionsRevoked", { count: sessionMutationNotice.count, countLabel: formatNumber(sessionMutationNotice.count), email: sessionMutationNotice.email })}
              </p>
            )}
        <ResearcherTable
          disabled={state !== "ready"}
          items={researchers?.items ?? null}
          onRevoke={onSessionRevocation}
          operatorResearcherId={operatorResearcherId}
          state={state}
        />
        <Pagination
          disabled={state !== "ready" || researchers === null}
          depth={researcherCursorDepth}
          hasNext={researchers !== null && researchers.next_cursor !== null}
          label={t("researchers.directory.researchers")}
          onNext={onResearcherNext}
          onPrevious={onResearcherPrevious}
        />
      </section>


    </section>
  );
}

function OperatorLoadState({ hasData, onRetry, state }: Readonly<{
  hasData: boolean;
  onRetry?: () => void;
  state: "loading" | "ready" | "unavailable";
}>) {
  const { t } = useTranslation("operator");
  if (state === "ready") return null;
  if (state === "loading") {
    return (
      <p aria-live="polite" className="m-0 text-sm text-muted-foreground" role="status">
        {hasData ? t("researchers.directory.refreshing") : t("researchers.directory.loading")}
      </p>
    );
  }
  return (
    <Alert variant="destructive">
      <AlertDescription>
        {t("researchers.directory.unavailable")}{hasData ? t("researchers.directory.stale") : ""}
      </AlertDescription>
      {onRetry === undefined ? null : (
        <Button variant="outline" id={operatorRetryButtonId} onClick={onRetry} type="button">{t("researchers.directory.retry")}</Button>
      )}
    </Alert>
  );
}

function ResearcherTable({
  disabled,
  items,
  onRevoke,
  operatorResearcherId,
  state,
}: Readonly<{
  disabled: boolean;
  items: readonly OperatorResearcher[] | null;
  onRevoke?: (
    trigger: HTMLButtonElement,
    target: SessionRevocationTarget,
  ) => void;
  operatorResearcherId: string;
  state: "loading" | "ready" | "unavailable";
}>) {
  const { t } = useTranslation("operator");
  const [expanded, setExpanded] = useState<string | null>(null);
  if (items === null) {
    return (
      <p className="m-0 py-4 text-sm text-muted-foreground">
        {state === "unavailable" ? t("researchers.directory.researchersUnavailable") : t("researchers.directory.researchersLoading")}
      </p>
    );
  }
  if (items.length === 0) return <p className="m-0 py-4 text-sm text-muted-foreground">{t("researchers.directory.noResearchers")}</p>;
  return (
    <div className="min-w-0 overflow-hidden rounded-xl border border-border bg-card [&_thead]:bg-muted/50">
      <Table density="comfortable" scrollLabel={t("researchers.directory.researchers")}>
        <TableCaption className="sr-only">{t("researchers.directory.researchers")}</TableCaption>
        <TableHeader>
          <TableRow>
            <TableHead scope="col"><span className="sr-only">{t("researchers.directory.details")}</span></TableHead>
            <TableHead scope="col">{t("researchers.directory.researcher")}</TableHead>
            <TableHead scope="col">{t("researchers.directory.access")}</TableHead>
            <TableHead scope="col">{t("researchers.directory.latestLogin")}</TableHead>
            <TableHead scope="col">{t("researchers.directory.currentSessions")}</TableHead>
            {onRevoke === undefined ? null : <TableHead scope="col">{t("researchers.directory.sessionAction")}</TableHead>}
          </TableRow>
        </TableHeader>
        <TableBody>
          {items.map((researcher) => (
            <Fragment key={researcher.researcher_id}><TableRow>
              <TableCell><Button variant="ghost" size="icon" aria-label={`${t("researchers.directory.details")} · ${researcher.display_label}`} aria-expanded={expanded === researcher.researcher_id} aria-controls={`researcher-details-${researcher.researcher_id}`} onClick={() => setExpanded(current => current === researcher.researcher_id ? null : researcher.researcher_id)}><CaretRight className={expanded === researcher.researcher_id ? "rotate-90" : undefined} /></Button></TableCell>
              <TableHead data-label={t("researchers.directory.researcher")} scope="row">
                <div className={operatorAccessLayout.identity}><strong className="line-clamp-2" title={researcher.display_label}>{researcher.display_label}</strong><small>{researcher.email}</small></div>
              </TableHead>
              <TableCell data-label={t("researchers.directory.access")}>
                <Badge variant={researcher.active ? "default" : "secondary"}>
                  {researcher.active ? t("researchers.directory.active") : t("researchers.directory.inactive")}
                </Badge>
              </TableCell>
              <TableCell data-label={t("researchers.directory.latestLogin")}>
                {researcher.latest_successful_login_at === null
                  ? t("researchers.directory.never")
                  : <Timestamp value={researcher.latest_successful_login_at} />}
              </TableCell>
              <TableCell data-label={t("researchers.directory.currentSessions")} className="text-right tabular-nums">
                {formatNumber(researcher.current_session_count)}
              </TableCell>
              {onRevoke === undefined ? null : (
                <TableCell data-label={t("researchers.directory.sessionAction")}>
                  {researcher.researcher_id === operatorResearcherId ? (
                    <span className="text-muted-foreground">{t("researchers.directory.currentOperator")}</span>
                  ) : researcher.current_session_count === 0 ? (
                    <span className="text-muted-foreground">{t("researchers.directory.noActiveSessions")}</span>
                  ) : (
                    <Button variant="outline"
                      aria-label={t("researchers.directory.revokeSessionsAria", { count: researcher.current_session_count, email: researcher.email })}

                      disabled={disabled}
                      id={`operator-session-revoke-${researcher.researcher_id}`}
                      onClick={(event) => onRevoke(event.currentTarget, {
                        currentSessionCount: researcher.current_session_count,
                        displayLabel: researcher.display_label,
                        email: researcher.email,
                        researcherId: researcher.researcher_id,
                      })}
                      type="button"
                    >
                      {t("researchers.directory.revokeSessions")}
                    </Button>
                  )}
                </TableCell>
              )}
            </TableRow>{expanded === researcher.researcher_id ? <TableRow id={`researcher-details-${researcher.researcher_id}`}><TableCell /><TableCell colSpan={onRevoke === undefined ? 4 : 5}><dl className="m-0 grid grid-cols-2 gap-6 rounded-md border border-border bg-muted/40 p-4 text-sm [&_dd]:m-0 [&_dt]:text-muted-foreground">
                    <div><dt>{t("researchers.directory.researcherId")}</dt><dd><code className="break-all">{researcher.researcher_id}</code></dd></div>
                    <div><dt>{t("researchers.directory.created")}</dt><dd><Timestamp value={researcher.created_at} /></dd></div>

                  </dl></TableCell></TableRow> : null}</Fragment>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

function Pagination({ depth, disabled, hasNext, label, onNext, onPrevious }: Readonly<{
  depth: number;
  disabled: boolean;
  hasNext: boolean;
  label: string;
  onNext: () => void;
  onPrevious: () => void;
}>) {
  const { t } = useTranslation("operator");
  return <PageNavigation label={t("researchers.directory.pagination", { label })}
    previousLabel={t("researchers.directory.previous")} nextLabel={t("researchers.directory.next")}
    previousDisabled={disabled || depth === 0} nextDisabled={disabled || !hasNext}
    onPrevious={onPrevious} onNext={onNext}>
    {t("researchers.directory.page", { page: formatNumber(depth + 1) })}
  </PageNavigation>;
}

function Timestamp({ value }: { value: string }) {
  return <time dateTime={value}>{formatTimestamp(value)}</time>;
}

function formatTimestamp(value: string): string {
  return formatLocaleTimestamp(value, {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "UTC",
  });
}

function restoreMutationFocus(
  targetId: string | null,
  fallbackId: string,
): void {
  const target = focusableElement(targetId)
    ?? focusableElement(fallbackId)
    ?? focusableElement(operatorRetryButtonId)
    ?? document.getElementById(operatorPageFallbackId);
  target?.focus();
}

function focusableElement(id: string | null): HTMLElement | null {
  if (id === null) return null;
  const element = document.getElementById(id);
  if (element === null) return null;
  if (element instanceof HTMLButtonElement && element.disabled) return null;
  return element;
}
