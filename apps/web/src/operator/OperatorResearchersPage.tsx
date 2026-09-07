import { MagnifyingGlass } from "@phosphor-icons/react";
import { useCallback, useEffect, useRef, useState } from "react";

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
  const [mutationNotice, setMutationNotice] = useState<string | null>(null);
  const [sessionMutationNotice, setSessionMutationNotice] = useState<string | null>(null);
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
        aria-label="Not found"
        className="page-section state-section"
        id={operatorPageFallbackId}
        tabIndex={-1}
      >
        <h1>Not found</h1>
        <p>The requested resource is not available.</p>
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
            setMutationNotice(
              operation === "issue"
                ? `Invitation sent to ${email}.`
                : `Invitation reissued for ${email}.`,
            );
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
            setSessionMutationNotice(
              `Revoked ${revokedSessionCount} Login ${
                revokedSessionCount === 1 ? "Session" : "Sessions"
              } for ${sessionTarget.email}.`,
            );
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
  mutationNotice?: string | null;
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
  sessionMutationNotice?: string | null;
  state?: "loading" | "ready" | "unavailable";
}>) {
  const [draft, setDraft] = useState(search);
  const busy = state === "loading";
  return (
    <section
      aria-busy={busy}
      aria-label="Operator Researchers"
      className="page-section operator-page"
      id={operatorPageFallbackId}
      tabIndex={-1}
    >
      <header className="page-hero">
        <div>
          <h1>Researcher access</h1>
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
            <h2 id="operator-researchers-title">Researchers</h2>
          </div>
          <form
            className="operator-search"
            onSubmit={(event) => {
              event.preventDefault();
              onSearch(draft);
            }}
          >
            <label htmlFor="operator-researcher-search">Search researchers</label>
            <div>
              <MagnifyingGlass aria-hidden="true" size={16} />
              <input
                aria-label="Search researchers"
                disabled={state !== "ready"}
                id="operator-researcher-search"
                onChange={(event) => setDraft(event.target.value)}
                placeholder="Canonical email or display label"
                type="search"
                value={draft}
              />
              <button disabled={state !== "ready"} type="submit">Search</button>
            </div>
          </form>
        </header>
        {sessionMutationNotice === null || sessionMutationNotice === undefined
          ? null
          : (
              <p aria-live="polite" className="inline-status" role="status">
                {sessionMutationNotice}
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
          label="Researchers"
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
            <h2 id="operator-invitations-title">Invitations</h2>
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
              Invite Researcher
            </button>
          )}
        </header>
        {mutationNotice === null || mutationNotice === undefined ? null : (
          <p aria-live="polite" className="inline-status" role="status">
            {mutationNotice}
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
          label="Invitations"
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
  if (state === "ready") return null;
  if (state === "loading") {
    return (
      <p aria-live="polite" className="operator-load-state" role="status">
        {hasData ? "Refreshing Operator Console…" : "Loading Operator Console…"}
      </p>
    );
  }
  return (
    <div className="operator-load-state operator-load-error">
      <p role="alert">
        Operator Console unavailable.{hasData ? " Displayed data may be stale." : ""}
      </p>
      {onRetry === undefined ? null : (
        <button id={operatorRetryButtonId} onClick={onRetry} type="button">Retry</button>
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
  if (items === null) {
    return (
      <p className="operator-empty">
        {state === "unavailable" ? "Researchers unavailable." : "Loading Researchers…"}
      </p>
    );
  }
  if (items.length === 0) return <p className="operator-empty">No Researchers found.</p>;
  return (
    <div className="operator-table-scroll">
      <table className="operator-table operator-researcher-table">
        <caption className="visually-hidden">Researchers</caption>
        <thead>
          <tr>
            <th scope="col">Researcher</th>
            <th scope="col">Researcher ID</th>
            <th scope="col">Access</th>
            <th scope="col">Created</th>
            <th scope="col">Latest login</th>
            <th scope="col">Current sessions</th>
            <th scope="col">Effective invitation</th>
            {onRevoke === undefined ? null : <th scope="col">Session action</th>}
          </tr>
        </thead>
        <tbody>
          {items.map((researcher) => (
            <tr key={researcher.researcher_id}>
              <th data-label="Researcher" scope="row">
                <strong>{researcher.display_label}</strong>
                <small>{researcher.email}</small>
              </th>
              <td data-label="Researcher ID"><code>{researcher.researcher_id}</code></td>
              <td data-label="Access">
                <span className={`operator-state operator-state-${researcher.active ? "active" : "inactive"}`}>
                  {researcher.active ? "Active" : "Inactive"}
                </span>
              </td>
              <td data-label="Created"><Timestamp value={researcher.created_at} /></td>
              <td data-label="Latest login">
                {researcher.latest_successful_login_at === null
                  ? "Never"
                  : <Timestamp value={researcher.latest_successful_login_at} />}
              </td>
              <td data-label="Current sessions" className="operator-number">
                {researcher.current_session_count}
              </td>
              <td data-label="Effective invitation">
                {researcher.effective_invitation === null ? (
                  <span className="operator-muted">None</span>
                ) : (
                  <span className="operator-invitation-summary">
                    <strong>{statusLabel(researcher.effective_invitation.status)}</strong>
                    <small>Expires <Timestamp value={researcher.effective_invitation.expires_at} /></small>
                  </span>
                )}
              </td>
              {onRevoke === undefined ? null : (
                <td data-label="Session action">
                  {researcher.researcher_id === operatorResearcherId ? (
                    <span className="operator-muted">Current Operator</span>
                  ) : researcher.current_session_count === 0 ? (
                    <span className="operator-muted">No active Sessions</span>
                  ) : (
                    <button
                      aria-label={`Revoke ${researcher.current_session_count} Login Sessions for ${researcher.email}`}
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
                      Revoke sessions
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
  if (items === null) {
    return (
      <p className="operator-empty">
        {state === "unavailable" ? "Invitations unavailable." : "Loading Invitations…"}
      </p>
    );
  }
  if (items.length === 0) return <p className="operator-empty">No Invitations found.</p>;
  return (
    <div className="operator-table-scroll">
      <table className="operator-table operator-invitation-table">
        <caption className="visually-hidden">Invitations</caption>
        <thead>
          <tr>
            <th scope="col">Email</th>
            <th scope="col">State</th>
            <th scope="col">Researcher ID</th>
            <th scope="col">Created</th>
            <th scope="col">Expires</th>
            <th scope="col">Terminal</th>
            {onReissue === undefined ? null : <th scope="col">Action</th>}
          </tr>
        </thead>
        <tbody>
          {items.map((invitation) => (
            <tr key={invitation.invitation_id}>
              <th data-label="Email" scope="row">
                <strong>{invitation.email}</strong>
                <small><code>{invitation.invitation_id}</code></small>
              </th>
              <td data-label="State">
                <span className={`operator-state operator-state-${invitation.effective ? "effective" : "terminal"}`}>
                  {invitation.effective ? "Effective" : "Terminal"} · {statusLabel(invitation.status)}
                </span>
              </td>
              <td data-label="Researcher ID">
                {invitation.researcher_id === null
                  ? <span className="operator-muted">Not created</span>
                  : <code>{invitation.researcher_id}</code>}
              </td>
              <td data-label="Created"><Timestamp value={invitation.created_at} /></td>
              <td data-label="Expires"><Timestamp value={invitation.expires_at} /></td>
              <td data-label="Terminal">
                {invitation.terminal_at === null
                  ? <span className="operator-muted">—</span>
                  : <Timestamp value={invitation.terminal_at} />}
              </td>
              {onReissue === undefined ? null : (
                <td data-label="Action">
                  <button
                    aria-label={`Reissue invitation for ${invitation.email}`}
                    className="button-quiet operator-row-action"
                    disabled={disabled}
                    id={`operator-invitation-reissue-${invitation.invitation_id}`}
                    onClick={(event) => onReissue(
                      event.currentTarget,
                      invitation.email,
                    )}
                    type="button"
                  >
                    Reissue
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
  return (
    <nav aria-label={`${label} pagination`} className="operator-pagination">
      <button disabled={disabled || depth === 0} onClick={onPrevious} type="button">
        Previous
      </button>
      <span>Page {depth + 1}</span>
      <button disabled={disabled || !hasNext} onClick={onNext} type="button">Next</button>
    </nav>
  );
}

function Timestamp({ value }: { value: string }) {
  return <time dateTime={value}>{formatTimestamp(value)}</time>;
}

function statusLabel(status: InvitationStatus): string {
  return status.replaceAll("_", " ").replace(/^./, (value) => value.toUpperCase());
}

function formatTimestamp(value: string): string {
  return new Intl.DateTimeFormat("en-GB", {
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
