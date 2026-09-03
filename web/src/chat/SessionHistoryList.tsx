import {
  ChatCircle,
  DotsThree,
  NotePencil,
  Trash,
  X,
} from "@phosphor-icons/react";
import {
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
} from "react";
import { createPortal } from "react-dom";

import { chatSessionHref, handleChatNavigation } from "./chatNavigation";
import {
  AgentSessionActiveRunError,
  AgentSessionChangedError,
  AgentSessionInvalidError,
  AgentSessionNotFoundError,
  AgentSessionTitleInvalidError,
  groupSessionsByRecency,
  type AgentSessionSummary,
} from "./sessionHistory";
import type { SessionHistoryController } from "./useSessionHistory";

type SessionDialog = Readonly<{
  kind: "rename" | "delete";
  session: AgentSessionSummary;
}>;

type SessionMenuPlacement = Readonly<{
  left: number;
  top: number;
}>;

const SESSION_MENU_WIDTH = 150;
const SESSION_MENU_MAX_HEIGHT = 104;
const SESSION_MENU_GAP = 4;
const SESSION_MENU_VIEWPORT_MARGIN = 8;

export function SessionHistoryList({
  controller,
  currentSessionId,
  navigate,
  navigationInteractive,
  restoreFocus,
}: {
  controller: SessionHistoryController;
  currentSessionId: string | null;
  navigate: (href: string) => void;
  navigationInteractive: boolean;
  restoreFocus: (deletedCurrentSession: boolean) => void;
}) {
  const [openMenu, setOpenMenu] = useState<string | null>(null);
  const [menuPlacement, setMenuPlacement] = useState<SessionMenuPlacement | null>(null);
  const [dialog, setDialog] = useState<SessionDialog | null>(null);
  const menuButtons = useRef(new Map<string, HTMLButtonElement>());
  const openMenuActivity = useRef<Readonly<{
    activeRun: boolean;
    id: string;
  }> | null>(null);
  const groups = groupSessionsByRecency(controller.sessions);
  const openMenuSession = controller.sessions.find((session) => session.id === openMenu);
  const openMenuHasActiveTurn = openMenuSession?.current_turn !== null
    && openMenuSession?.current_turn !== undefined;

  useEffect(() => {
    if (openMenu === null) return;
    const menu = document.getElementById(`chat-session-menu-${openMenu}`);
    menu?.querySelector<HTMLButtonElement>('button[role="menuitem"]')?.focus();
  }, [openMenu]);

  useEffect(() => {
    if (openMenu === null || openMenuSession !== undefined) return;
    const removedSessionId = openMenu;
    setOpenMenu(null);
    setMenuPlacement(null);
    window.requestAnimationFrame(() => {
      const trigger = menuButtons.current.get(removedSessionId);
      if (trigger?.isConnected) trigger.focus();
      else restoreFocus(false);
    });
  }, [openMenu, openMenuSession, restoreFocus]);

  useEffect(() => {
    if (openMenu === null || openMenuSession === undefined) {
      openMenuActivity.current = null;
      return;
    }
    const previous = openMenuActivity.current;
    openMenuActivity.current = {
      activeRun: openMenuHasActiveTurn,
      id: openMenuSession.id,
    };
    if (
      previous?.id === openMenuSession.id
      && !previous.activeRun
      && openMenuHasActiveTurn
    ) {
      closeMenu(true);
    }
  }, [openMenu, openMenuHasActiveTurn, openMenuSession]);

  useEffect(() => {
    if (openMenu === null) return;
    const dismissForLayoutChange = () => closeMenu(true);
    const dismissFromOutside = (event: PointerEvent) => {
      const target = event.target;
      if (!(target instanceof Node)) {
        closeMenu(false);
        return;
      }
      const menu = document.getElementById(`chat-session-menu-${openMenu}`);
      const trigger = menuButtons.current.get(openMenu);
      if (menu?.contains(target) || trigger?.contains(target)) return;
      closeMenu(false);
    };
    window.addEventListener("resize", dismissForLayoutChange);
    document.addEventListener("pointerdown", dismissFromOutside, true);
    document.addEventListener("scroll", dismissForLayoutChange, true);
    return () => {
      window.removeEventListener("resize", dismissForLayoutChange);
      document.removeEventListener("pointerdown", dismissFromOutside, true);
      document.removeEventListener("scroll", dismissForLayoutChange, true);
    };
  }, [openMenu]);

  useEffect(() => {
    if (navigationInteractive) return;
    const hadOpenMenu = openMenu !== null;
    setOpenMenu(null);
    setMenuPlacement(null);
    if (hadOpenMenu) window.requestAnimationFrame(() => restoreFocus(false));
  }, [navigationInteractive, openMenu, restoreFocus]);

  useEffect(() => {
    if (openMenu !== null) closeMenu(true);
  }, [currentSessionId]);

  function closeMenu(shouldRestoreFocus: boolean): void {
    const sessionId = openMenu;
    setOpenMenu(null);
    setMenuPlacement(null);
    if (shouldRestoreFocus && sessionId !== null) {
      window.requestAnimationFrame(() => {
        const trigger = menuButtons.current.get(sessionId);
        if (trigger?.isConnected) trigger.focus();
        else restoreFocus(false);
      });
    }
  }

  function openDialog(kind: SessionDialog["kind"], session: AgentSessionSummary): void {
    setDialog({ kind, session });
    setOpenMenu(null);
    setMenuPlacement(null);
  }

  function toggleMenu(sessionId: string, trigger: HTMLButtonElement): void {
    if (openMenu === sessionId) {
      closeMenu(false);
      return;
    }
    const bounds = trigger.getBoundingClientRect();
    const opensToRight = bounds.right <= SESSION_MENU_WIDTH + SESSION_MENU_VIEWPORT_MARGIN * 2;
    const unclampedLeft = opensToRight
      ? bounds.right + SESSION_MENU_GAP
      : bounds.right - SESSION_MENU_WIDTH;
    const maxLeft = Math.max(
      SESSION_MENU_VIEWPORT_MARGIN,
      window.innerWidth - SESSION_MENU_WIDTH - SESSION_MENU_VIEWPORT_MARGIN,
    );
    const preferredTop = bounds.bottom + SESSION_MENU_GAP;
    const opensBelow = preferredTop + SESSION_MENU_MAX_HEIGHT
      <= window.innerHeight - SESSION_MENU_VIEWPORT_MARGIN;
    const unclampedTop = opensBelow
      ? preferredTop
      : bounds.top - SESSION_MENU_MAX_HEIGHT - SESSION_MENU_GAP;
    setMenuPlacement({
      left: Math.min(Math.max(unclampedLeft, SESSION_MENU_VIEWPORT_MARGIN), maxLeft),
      top: Math.max(unclampedTop, SESSION_MENU_VIEWPORT_MARGIN),
    });
    setOpenMenu(sessionId);
  }

  function closeDialog(): void {
    const sessionId = dialog?.session.id;
    setDialog(null);
    if (sessionId !== undefined) {
      window.requestAnimationFrame(() => {
        const trigger = menuButtons.current.get(sessionId);
        if (trigger?.isConnected) trigger.focus();
        else restoreFocus(false);
      });
    }
  }

  function completeDelete(sessionId: string): void {
    const deletedCurrentSession = sessionId === currentSessionId;
    setDialog(null);
    if (deletedCurrentSession) navigate("/chat");
    window.requestAnimationFrame(() => restoreFocus(deletedCurrentSession));
  }

  const historyContent = controller.status === "loading" ? (
    <p
      className="chat-session-status chat-session-status-loading"
      role="status"
      title="Loading Chats…"
    >
      Loading Chats…
    </p>
  ) : controller.status === "error" && controller.sessions.length === 0 ? (
      <div className="chat-session-status chat-session-status-error">
        <p role="alert">{controller.error}</p>
        <button className="button-quiet" onClick={controller.refresh} type="button">Retry</button>
      </div>
  ) : controller.sessions.length === 0 ? (
      <div className="chat-session-empty" title="No conversations yet">
        <ChatCircle aria-hidden="true" size={16} weight="regular" />
        <span className="chat-session-empty-full">No conversations yet</span>
        <span className="chat-session-empty-compact">Empty</span>
      </div>
  ) : (
    <>
      <div className="chat-session-groups">
        {groups.map((group) => (
          <section aria-labelledby={`chat-session-group-${group.label.replaceAll(" ", "-")}`} key={group.label}>
            <h3
              data-collapsed-label={collapsedGroupLabel(group.label)}
              id={`chat-session-group-${group.label.replaceAll(" ", "-")}`}
            >
              {group.label}
            </h3>
            <div className="chat-session-list">
              {group.sessions.map((session) => (
                <div
                  className={`chat-session-row${session.id === currentSessionId ? " chat-session-row-current" : ""}`}
                  key={session.id}
                >
                  <a
                    aria-current={session.id === currentSessionId ? "page" : undefined}
                    aria-label={`${session.title}${session.current_turn === null ? "" : `, ${session.current_turn.status === "waiting_for_user" ? "Waiting for answer" : "Running"}`}`}
                    href={chatSessionHref(session.id)}
                    onClick={(event) => handleChatNavigation(event, () => {
                      if (session.id !== currentSessionId) navigate(chatSessionHref(session.id));
                    })}
                    title={`${session.title}${session.current_turn === null ? "" : session.current_turn.status === "waiting_for_user" ? " — Waiting for answer" : " — Running"}`}
                  >
                    <ChatCircle aria-hidden="true" size={15} weight="regular" />
                    <span>{session.title}</span>
                    {session.current_turn === null ? null : (
                      <em>
                        <span className="chat-session-run-full">{session.current_turn.status === "waiting_for_user" ? "Waiting" : "Running"}</span>
                        <span className="chat-session-run-compact">Run</span>
                      </em>
                    )}
                  </a>
                  <button
                    aria-controls={openMenu === session.id
                      ? `chat-session-menu-${session.id}`
                      : undefined}
                    aria-expanded={openMenu === session.id}
                    aria-haspopup="menu"
                    aria-label={`Actions for ${session.title}`}
                    className="chat-session-menu-trigger"
                    onClick={(event) => toggleMenu(session.id, event.currentTarget)}
                    ref={(element) => {
                      if (element === null) menuButtons.current.delete(session.id);
                      else menuButtons.current.set(session.id, element);
                    }}
                    type="button"
                  >
                    <DotsThree aria-hidden="true" size={17} weight="bold" />
                  </button>
                </div>
              ))}
            </div>
          </section>
        ))}
      </div>
      {controller.error === null ? null : (
        <p
          className="chat-session-pagination-error"
          role="alert"
          title={controller.error}
        >
          {controller.error}
        </p>
      )}
      {controller.nextCursor === null ? null : (
        <button
          className="chat-session-load-more button-quiet"
          disabled={controller.loadingMore}
          onClick={() => void controller.loadMore()}
          type="button"
        >
          {controller.loadingMore ? "Loading…" : "Load more"}
        </button>
      )}
    </>
  );

  return (
    <>
      {historyContent}
      {openMenuSession === undefined
        || menuPlacement === null
        || !navigationInteractive
        || typeof document === "undefined"
        ? null
        : createPortal(
            <div
              aria-label={`Actions for ${openMenuSession.title}`}
              className="chat-session-menu"
              id={`chat-session-menu-${openMenuSession.id}`}
              onKeyDown={(event) => handleMenuKeyDown(event, () => closeMenu(true))}
              role="menu"
              style={menuPlacement}
            >
              <button
                onClick={() => openDialog("rename", openMenuSession)}
                role="menuitem"
                type="button"
              >
                <NotePencil aria-hidden="true" size={15} />
                Rename
              </button>
              {openMenuSession.current_turn === null ? (
                <button
                  onClick={() => openDialog("delete", openMenuSession)}
                  role="menuitem"
                  type="button"
                >
                  <Trash aria-hidden="true" size={15} />
                  Delete Chat
                </button>
              ) : null}
            </div>,
            document.body,
          )}
      {dialog === null ? null : (
        <SessionDecisionDialog
          controller={controller}
          dialog={dialog}
          onClose={closeDialog}
          onDeleted={completeDelete}
        />
      )}
    </>
  );
}

function SessionDecisionDialog({
  controller,
  dialog,
  onClose,
  onDeleted,
}: {
  controller: SessionHistoryController;
  dialog: SessionDialog;
  onClose: () => void;
  onDeleted: (sessionId: string) => void;
}) {
  const panelRef = useRef<HTMLDialogElement>(null);
  const initialFocusRef = useRef<HTMLInputElement | HTMLButtonElement>(null);
  const [title, setTitle] = useState(dialog.session.title);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    const element = panelRef.current;
    if (element === null) return;
    element.showModal();
    initialFocusRef.current?.focus();
    return () => {
      if (element.open) element.close();
    };
  }, []);

  function dismissDialog(): void {
    panelRef.current?.close();
    onClose();
  }

  async function submit(event: FormEvent): Promise<void> {
    event.preventDefault();
    if (submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      if (dialog.kind === "rename") {
        await controller.renameSession(dialog.session, title);
        dismissDialog();
      } else {
        await controller.deleteSession(dialog.session);
        // Release native modality before the parent navigates and restores focus.
        panelRef.current?.close();
        onDeleted(dialog.session.id);
      }
    } catch (caught) {
      if (caught instanceof AgentSessionChangedError) {
        setError("This Chat title changed. Close the dialog and try again.");
        controller.refresh();
      } else if (caught instanceof AgentSessionActiveRunError) {
        setError("This Chat now has an active Agent run and cannot be deleted.");
        controller.refresh();
      } else if (caught instanceof AgentSessionNotFoundError) {
        setError("This Chat no longer exists.");
        controller.refresh();
      } else if (caught instanceof AgentSessionTitleInvalidError) {
        setError(sessionDialogErrorMessage(dialog.kind, caught));
      } else if (caught instanceof AgentSessionInvalidError) {
        setError(sessionDialogErrorMessage(dialog.kind, caught));
      } else {
        setError(dialog.kind === "rename"
          ? "The Chat title could not be saved."
          : "The Chat could not be deleted.");
      }
    } finally {
      setSubmitting(false);
    }
  }

  function handleKeyDown(event: KeyboardEvent<HTMLDialogElement>): void {
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      if (!submitting) dismissDialog();
      return;
    }
    if (event.key !== "Tab") return;
    const focusable = [...(panelRef.current?.querySelectorAll<HTMLElement>(
      'button:not([disabled]), input:not([disabled])',
    ) ?? [])];
    const first = focusable[0];
    const last = focusable.at(-1);
    if (first === undefined || last === undefined) return;
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  const titleId = `chat-session-${dialog.kind}-title`;
  const descriptionId = `chat-session-${dialog.kind}-description`;
  return (
    <dialog
      aria-describedby={descriptionId}
      aria-labelledby={titleId}
      aria-modal="true"
      className="chat-session-dialog"
      onCancel={(event) => {
        event.preventDefault();
        event.stopPropagation();
        if (!submitting) dismissDialog();
      }}
      onKeyDown={handleKeyDown}
      ref={panelRef}
    >
      <header>
        <div>
          <p className="eyebrow">Chat Session</p>
          <h2 id={titleId}>{dialog.kind === "rename" ? "Rename Chat" : "Delete Chat?"}</h2>
        </div>
        <button aria-label="Close dialog" disabled={submitting} onClick={dismissDialog} type="button">
          <X aria-hidden="true" size={18} />
        </button>
      </header>
      <form onSubmit={(event) => void submit(event)}>
        {dialog.kind === "rename" ? (
          <label className="chat-session-title-field">
            <span>Title</span>
            <input
              onChange={(event) => setTitle(event.target.value)}
              ref={initialFocusRef as React.RefObject<HTMLInputElement>}
              required
              value={title}
            />
          </label>
        ) : (
          <p id={descriptionId}>
            Permanently delete <strong>{dialog.session.title}</strong> and its Chat thread,
            messages, generated UI, and Agent run history. ResearchRuns, Results, and
            Daily Tracks remain independent and are not deleted.
          </p>
        )}
        {dialog.kind === "rename" ? (
          <p id={descriptionId}>This changes the single title shown for this Chat Session.</p>
        ) : null}
        {error === null ? null : <p className="chat-dialog-error" role="alert">{error}</p>}
        <footer>
          <button
            className="button-quiet"
            disabled={submitting}
            onClick={dismissDialog}
            ref={dialog.kind === "delete"
              ? initialFocusRef as React.RefObject<HTMLButtonElement>
              : undefined}
            type="button"
          >
            Cancel
          </button>
          <button
            className={dialog.kind === "delete" ? "button-danger" : "button-primary"}
            disabled={submitting}
            type="submit"
          >
            {submitting
              ? dialog.kind === "delete" ? "Deleting…" : "Saving…"
              : dialog.kind === "delete" ? "Delete Chat" : "Save title"}
          </button>
        </footer>
      </form>
    </dialog>
  );
}

export function sessionDialogErrorMessage(
  kind: SessionDialog["kind"],
  error: AgentSessionInvalidError | AgentSessionTitleInvalidError,
): string {
  if (error instanceof AgentSessionTitleInvalidError) {
    return "Choose a title between 1 and 80 characters other than Untitled.";
  }
  return kind === "rename"
    ? "The Chat title response was invalid."
    : "The delete response was invalid.";
}

function handleMenuKeyDown(
  event: KeyboardEvent<HTMLDivElement>,
  close: () => void,
): void {
  if (event.key === "Escape") {
    event.preventDefault();
    event.stopPropagation();
    close();
    return;
  }
  if (!["ArrowDown", "ArrowUp", "Home", "End", "Tab"].includes(event.key)) return;
  event.preventDefault();
  const items = [...event.currentTarget.querySelectorAll<HTMLButtonElement>(
    'button[role="menuitem"]',
  )];
  if (items.length === 0) return;
  const current = items.indexOf(document.activeElement as HTMLButtonElement);
  const next = event.key === "Home"
    ? 0
    : event.key === "End"
      ? items.length - 1
      : event.key === "ArrowDown" || (event.key === "Tab" && !event.shiftKey)
        ? (current + 1 + items.length) % items.length
        : (current - 1 + items.length) % items.length;
  items[next]?.focus();
}

function collapsedGroupLabel(label: "Today" | "Previous 7 days" | "Older"): string {
  switch (label) {
    case "Today": return "T";
    case "Previous 7 days": return "7d";
    case "Older": return "O";
  }
}
