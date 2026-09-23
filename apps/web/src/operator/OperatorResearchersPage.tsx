import { MagnifyingGlass } from "@phosphor-icons/react";
import { useCallback, useEffect, useRef, useState } from "react";
import { i18n, interfaceLocale, useTranslation } from "../i18n";
import { formatNumber } from "../i18n/format";

import {
  loadInvitationPage,
  loadResearcherPage,
  OperatorPageNotFoundError,
  type InvitationStatus,
  type OperatorInvitation,
  type OperatorPage,
  type OperatorResearcher,
} from "./operatorDirectoryClient";
import { OperatorInvitationDialog } from "./OperatorInvitationDialog";
import { OperatorConsoleNavigation } from "./OperatorConsoleNavigation";
import type { InvitationMutationOperation } from "./operatorMutationClient";
import {
  OperatorSessionRevocationDialog,
  type SessionRevocationTarget,
} from "./OperatorSessionRevocationDialog";

type InvitationAction = Readonly<{
  email: string;
  operation: InvitationMutationOperation;
}>;

const inviteResearcherButtonId = "operator-invite-researcher";
const operatorRetryButtonId = "operator-console-retry";
const operatorPageFallbackId = "operator-console-focus-fallback";

export function OperatorResearchersPage({ operatorResearcherId }: Readonly<{
  operatorResearcherId: string;
}>) {
  const { t } = useTranslation("operator");
  const [researchers, setResearchers] = useState<OperatorPage<OperatorResearcher> | null>(null);
  const [invitations, setInvitations] = useState<OperatorPage<OperatorInvitation> | null>(null);
  const [search, setSearch] = useState("");
  const [researcherCursor, setResearcherCursor] = useState<string | null>(null);
  const [researcherHistory, setResearcherHistory] = useState<Array<string | null>>([]);
  const [invitationCursor, setInvitationCursor] = useState<string | null>(null);
  const [invitationHistory, setInvitationHistory] = useState<Array<string | null>>([]);
  const [reloadGeneration, setReloadGeneration] = useState(0);
  const [state, setState] = useState<"loading" | "not-found" | "ready" | "unavailable">("loading");
  const [invitationAction, setInvitationAction] = useState<InvitationAction | null>(null);
  const [sessionTarget, setSessionTarget] = useState<SessionRevocationTarget | null>(null);
  const [mutationNotice, setMutationNotice] = useState<{ kind: "sent" | "reissued"; email: string } | null>(null);
  const [sessionMutationNotice, setSessionMutationNotice] = useState<{ count: number; email: string } | null>(null);
  const mutationFocusTargetId = useRef<string | null>(null);
  const mutationFocusFallbackId = useRef<string>(inviteResearcherButtonId);
  const restoreMutationFocusAfterLoad = useRef(false);

  const load = useCallback(async (signal: AbortSignal) => {
    setState("loading");
    try {
      const [researcherPage, invitationPage] = await Promise.all([
        loadResearcherPage(search, researcherCursor, signal),
        loadInvitationPage(invitationCursor, signal),
      ]);
      if (signal.aborted) return;
      setResearchers(researcherPage);
      setInvitations(invitationPage);
    } catch (error) {
      if (signal.aborted) return;
      setResearchers(null);
      setInvitations(null);
      setState(error instanceof OperatorPageNotFoundError ? "not-found" : "unavailable");
      return;
    }
    setState("ready");
  }, [invitationCursor, researcherCursor, search]);

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
        className="page-section state-section"
        id={operatorPageFallbackId}
        tabIndex={-1}
      >
        <h1>{t("researchers.directory.notFound")}</h1>
        <p>{t("researchers.directory.notFoundDescription")}</p>
      </section>
    );
  }

  function closeInvitationDialog(afterReload = false): void {
    setInvitationAction(null);
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

  function openInvitationDialog(
    trigger: HTMLButtonElement,
    action: InvitationAction,
  ): void {
    mutationFocusTargetId.current = trigger.id || null;
    mutationFocusFallbackId.current = inviteResearcherButtonId;
    setMutationNotice(null);
    setInvitationAction(action);
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
        invitationCursorDepth={invitationHistory.length}
        invitations={invitations}
        mutationNotice={mutationNotice}
        operatorResearcherId={operatorResearcherId}
        onInvitationAction={(trigger, action) => {
          openInvitationDialog(trigger, action);
        }}
        onInvitationNext={() => {
          if (state !== "ready" || invitations === null || invitations.next_cursor === null) {
            return;
          }
          setState("loading");
          setInvitationHistory((history) => [...history, invitationCursor]);
          setInvitationCursor(invitations.next_cursor);
        }}
        onInvitationPrevious={() => {
          if (state !== "ready") return;
          const previous = invitationHistory.at(-1);
          if (previous === undefined) return;
          setState("loading");
          setInvitationHistory((history) => history.slice(0, -1));
          setInvitationCursor(previous);
        }}
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
      {invitationAction === null ? null : (
        <OperatorInvitationDialog
          email={invitationAction.email}
          onDismiss={closeInvitationDialog}
          onSucceeded={({ email, operation }) => {
            setMutationNotice({ kind: operation === "issue" ? "sent" : "reissued", email });
            setInvitationCursor(null);
            setInvitationHistory([]);
            setState("loading");
            setReloadGeneration((value) => value + 1);
            closeInvitationDialog(true);
          }}
          operation={invitationAction.operation}
        />
      )}
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
  invitationCursorDepth,
  invitations,
  mutationNotice,
  operatorResearcherId,
  onInvitationAction,
  onInvitationNext,
  onInvitationPrevious,
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
  invitationCursorDepth: number;
  invitations: OperatorPage<OperatorInvitation> | null;
  mutationNotice?: { kind: "sent" | "reissued"; email: string } | null;
  operatorResearcherId: string;
  onInvitationAction?: (
    trigger: HTMLButtonElement,
    action: InvitationAction,
  ) => void;
  onInvitationNext: () => void;
  onInvitationPrevious: () => void;
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
      className="page-section operator-page"
      id={operatorPageFallbackId}
      tabIndex={-1}
    >
      <header className="page-hero">
        <div>
          <h1>{t("researchers.directory.title")}</h1>
        </div>
      </header>

      <OperatorConsoleNavigation current="researchers" />

      <OperatorLoadState
        hasData={researchers !== null || invitations !== null}
        onRetry={onRetry}
        state={state}
      />

      <section
        aria-busy={busy}
        aria-labelledby="operator-researchers-title"
        className="operator-section"
      >
        <header className="operator-section-header">
          <div>
            <h2 id="operator-researchers-title">{t("researchers.directory.researchers")}</h2>
          </div>
          <form
            className="operator-search"
            onSubmit={(event) => {
              event.preventDefault();
              onSearch(draft);
            }}
          >
            <label htmlFor="operator-researcher-search">{t("researchers.directory.searchResearchers")}</label>
            <div>
              <MagnifyingGlass aria-hidden="true" size={16} />
              <input
                aria-label={t("researchers.directory.searchResearchers")}
                disabled={state !== "ready"}
                id="operator-researcher-search"
                onChange={(event) => setDraft(event.target.value)}
                placeholder={t("researchers.directory.searchPlaceholder")}
                type="search"
                value={draft}
              />
              <button disabled={state !== "ready"} type="submit">{t("researchers.directory.search")}</button>
            </div>
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

      <section
        aria-busy={busy}
        aria-labelledby="operator-invitations-title"
        className="operator-section"
      >
        <header className="operator-section-header">
          <div>
            <h2 id="operator-invitations-title">{t("researchers.directory.invitations")}</h2>
          </div>
          {onInvitationAction === undefined ? null : (
            <button
              className="button-primary"
              disabled={state !== "ready"}
              id={inviteResearcherButtonId}
              onClick={(event) => onInvitationAction(event.currentTarget, {
                email: "",
                operation: "issue",
              })}
              type="button"
            >
              {t("researchers.directory.inviteResearcher")}
            </button>
          )}
        </header>
        {mutationNotice === null || mutationNotice === undefined ? null : (
          <p aria-live="polite" className="inline-status" role="status">
            {t(mutationNotice.kind === "sent" ? "researchers.directory.invitationSent" : "researchers.directory.invitationReissued", { email: mutationNotice.email })}
          </p>
        )}
        <InvitationTable
          disabled={state !== "ready"}
          items={invitations?.items ?? null}
          onReissue={onInvitationAction === undefined
            ? undefined
            : (trigger, email) => onInvitationAction(trigger, {
                email,
                operation: "reissue",
              })}
          state={state}
        />
        <Pagination
          disabled={state !== "ready" || invitations === null}
          depth={invitationCursorDepth}
          hasNext={invitations !== null && invitations.next_cursor !== null}
          label={t("researchers.directory.invitations")}
          onNext={onInvitationNext}
          onPrevious={onInvitationPrevious}
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
      <p aria-live="polite" className="operator-load-state" role="status">
        {hasData ? t("researchers.directory.refreshing") : t("researchers.directory.loading")}
      </p>
    );
  }
  return (
    <div className="operator-load-state operator-load-error">
      <p role="alert">
        {t("researchers.directory.unavailable")}{hasData ? t("researchers.directory.stale") : ""}
      </p>
      {onRetry === undefined ? null : (
        <button id={operatorRetryButtonId} onClick={onRetry} type="button">{t("researchers.directory.retry")}</button>
      )}
    </div>
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
  if (items === null) {
    return (
      <p className="operator-empty">
        {state === "unavailable" ? t("researchers.directory.researchersUnavailable") : t("researchers.directory.researchersLoading")}
      </p>
    );
  }
  if (items.length === 0) return <p className="operator-empty">{t("researchers.directory.noResearchers")}</p>;
  return (
    <div className="operator-table-scroll">
      <table className="operator-table operator-researcher-table">
        <caption className="visually-hidden">{t("researchers.directory.researchers")}</caption>
        <thead>
          <tr>
            <th scope="col">{t("researchers.directory.researcher")}</th>
            <th scope="col">{t("researchers.directory.researcherId")}</th>
            <th scope="col">{t("researchers.directory.access")}</th>
            <th scope="col">{t("researchers.directory.created")}</th>
            <th scope="col">{t("researchers.directory.latestLogin")}</th>
            <th scope="col">{t("researchers.directory.currentSessions")}</th>
            <th scope="col">{t("researchers.directory.effectiveInvitation")}</th>
            {onRevoke === undefined ? null : <th scope="col">{t("researchers.directory.sessionAction")}</th>}
          </tr>
        </thead>
        <tbody>
          {items.map((researcher) => (
            <tr key={researcher.researcher_id}>
              <th data-label={t("researchers.directory.researcher")} scope="row">
                <strong>{researcher.display_label}</strong>
                <small>{researcher.email}</small>
              </th>
              <td data-label={t("researchers.directory.researcherId")}><code>{researcher.researcher_id}</code></td>
              <td data-label={t("researchers.directory.access")}>
                <span className={`operator-state operator-state-${researcher.active ? "active" : "inactive"}`}>
                  {researcher.active ? t("researchers.directory.active") : t("researchers.directory.inactive")}
                </span>
              </td>
              <td data-label={t("researchers.directory.created")}><Timestamp value={researcher.created_at} /></td>
              <td data-label={t("researchers.directory.latestLogin")}>
                {researcher.latest_successful_login_at === null
                  ? t("researchers.directory.never")
                  : <Timestamp value={researcher.latest_successful_login_at} />}
              </td>
              <td data-label={t("researchers.directory.currentSessions")} className="operator-number">
                {formatNumber(researcher.current_session_count)}
              </td>
              <td data-label={t("researchers.directory.effectiveInvitation")}>
                {researcher.effective_invitation === null ? (
                  <span className="operator-muted">{t("researchers.directory.none")}</span>
                ) : (
                  <span className="operator-invitation-summary">
                    <strong>{statusLabel(researcher.effective_invitation.status)}</strong>
                    <small>{t("researchers.directory.expiresAt", { time: formatTimestamp(researcher.effective_invitation.expires_at) })}</small>
                  </span>
                )}
              </td>
              {onRevoke === undefined ? null : (
                <td data-label={t("researchers.directory.sessionAction")}>
                  {researcher.researcher_id === operatorResearcherId ? (
                    <span className="operator-muted">{t("researchers.directory.currentOperator")}</span>
                  ) : researcher.current_session_count === 0 ? (
                    <span className="operator-muted">{t("researchers.directory.noActiveSessions")}</span>
                  ) : (
                    <button
                      aria-label={t("researchers.directory.revokeSessionsAria", { count: researcher.current_session_count, email: researcher.email })}
                      className="button-quiet operator-row-action"
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
                    </button>
                  )}
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function InvitationTable({ disabled, items, onReissue, state }: Readonly<{
  disabled: boolean;
  items: readonly OperatorInvitation[] | null;
  onReissue?: (trigger: HTMLButtonElement, email: string) => void;
  state: "loading" | "ready" | "unavailable";
}>) {
  const { t } = useTranslation("operator");
  if (items === null) {
    return (
      <p className="operator-empty">
        {state === "unavailable" ? t("researchers.directory.invitationsUnavailable") : t("researchers.directory.invitationsLoading")}
      </p>
    );
  }
  if (items.length === 0) return <p className="operator-empty">{t("researchers.directory.noInvitations")}</p>;
  return (
    <div className="operator-table-scroll">
      <table className="operator-table operator-invitation-table">
        <caption className="visually-hidden">{t("researchers.directory.invitations")}</caption>
        <thead>
          <tr>
            <th scope="col">{t("researchers.directory.email")}</th>
            <th scope="col">{t("researchers.directory.state")}</th>
            <th scope="col">{t("researchers.directory.researcherId")}</th>
            <th scope="col">{t("researchers.directory.created")}</th>
            <th scope="col">{t("researchers.directory.expires")}</th>
            <th scope="col">{t("researchers.directory.terminal")}</th>
            {onReissue === undefined ? null : <th scope="col">{t("researchers.directory.action")}</th>}
          </tr>
        </thead>
        <tbody>
          {items.map((invitation) => (
            <tr key={invitation.invitation_id}>
              <th data-label={t("researchers.directory.email")} scope="row">
                <strong>{invitation.email}</strong>
                <small><code>{invitation.invitation_id}</code></small>
              </th>
              <td data-label={t("researchers.directory.state")}>
                <span className={`operator-state operator-state-${invitation.effective ? "effective" : "terminal"}`}>
                  {invitation.effective ? t("researchers.directory.effective") : t("researchers.directory.terminalState")} · {statusLabel(invitation.status)}
                </span>
              </td>
              <td data-label={t("researchers.directory.researcherId")}>
                {invitation.researcher_id === null
                  ? <span className="operator-muted">{t("researchers.directory.notCreated")}</span>
                  : <code>{invitation.researcher_id}</code>}
              </td>
              <td data-label={t("researchers.directory.created")}><Timestamp value={invitation.created_at} /></td>
              <td data-label={t("researchers.directory.expires")}><Timestamp value={invitation.expires_at} /></td>
              <td data-label={t("researchers.directory.terminal")}>
                {invitation.terminal_at === null
                  ? <span className="operator-muted">—</span>
                  : <Timestamp value={invitation.terminal_at} />}
              </td>
              {onReissue === undefined ? null : (
                <td data-label={t("researchers.directory.action")}>
                  <button
                    aria-label={t("researchers.directory.reissueAria", { email: invitation.email })}
                    className="button-quiet operator-row-action"
                    disabled={disabled}
                    id={`operator-invitation-reissue-${invitation.invitation_id}`}
                    onClick={(event) => onReissue(
                      event.currentTarget,
                      invitation.email,
                    )}
                    type="button"
                  >
                    {t("researchers.directory.reissue")}
                  </button>
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
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
  return (
    <nav aria-label={t("researchers.directory.pagination", { label })} className="operator-pagination">
      <button disabled={disabled || depth === 0} onClick={onPrevious} type="button">
        {t("researchers.directory.previous")}
      </button>
      <span>{t("researchers.directory.page", { page: formatNumber(depth + 1) })}</span>
      <button disabled={disabled || !hasNext} onClick={onNext} type="button">{t("researchers.directory.next")}</button>
    </nav>
  );
}

function Timestamp({ value }: { value: string }) {
  return <time dateTime={value}>{formatTimestamp(value)}</time>;
}

function statusLabel(status: InvitationStatus): string {
  return i18n.t(`operator:researchers.directory.statuses.${status}`);
}

function formatTimestamp(value: string): string {
  return new Intl.DateTimeFormat(interfaceLocale() === "en" ? "en-GB" : "zh-CN", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "UTC",
  }).format(new Date(value));
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
