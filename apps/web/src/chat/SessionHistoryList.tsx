import {
  ChatCircle, CircleNotch, DotsThree, NotePencil, Question, Trash,
} from "@phosphor-icons/react";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { Trans, useTranslation } from "react-i18next";

import { Alert, AlertDescription } from "../components/ui/alert";
import {
  AlertDialog, AlertDialogContent, AlertDialogDescription, AlertDialogFooter,
  AlertDialogHeader, AlertDialogTitle,
} from "../components/ui/alert-dialog";
import { Button } from "../components/ui/button";
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from "../components/ui/dialog";
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuGroup, DropdownMenuItem, DropdownMenuTrigger,
} from "../components/ui/dropdown-menu";
import { Field, FieldLabel } from "../components/ui/field";
import { Input } from "../components/ui/input";
import { useIsMobile } from "../hooks/use-mobile";
import { i18n } from "../i18n";
import type { ChatErrorKey } from "../i18n/messages/chat";
import { handleWorkspaceNavigation } from "../shell/navigation";
import { chatSessionHref } from "./chatNavigation";
import {
  AgentSessionActiveRunError, AgentSessionChangedError, AgentSessionInvalidError,
  AgentSessionNotFoundError, AgentSessionTitleInvalidError, groupSessionsByRecency,
  type AgentSessionSummary,
} from "./sessionHistory";
import type { SessionHistoryController } from "./useSessionHistory";

export type SessionDialog = Readonly<{ kind: "rename" | "delete"; session: AgentSessionSummary }>;

export function SessionHistoryList({
  controller, currentSessionId, navigate, navigationInteractive, restoreFocus, onDecision,
}: {
  controller: SessionHistoryController;
  currentSessionId: string | null;
  navigate: (href: string) => void;
  navigationInteractive: boolean;
  restoreFocus: (deletedCurrentSession: boolean) => void;
  onDecision: (dialog: SessionDialog) => void;
}) {
  const { t } = useTranslation("chat");
  const isMobile = useIsMobile();
  const displayTitle = (title: string) => title === "Untitled" ? t("untitled") : title;
  const [openMenu, setOpenMenu] = useState<string | null>(null);
  const menuButtons = useRef(new Map<string, HTMLButtonElement>());
  const openMenuActivity = useRef<Readonly<{ activeRun: boolean; id: string }> | null>(null);
  const groups = groupSessionsByRecency(controller.sessions);
  const openMenuSession = controller.sessions.find((session) => session.id === openMenu);
  const openMenuHasActiveTurn = openMenuSession?.current_turn !== null
    && openMenuSession?.current_turn !== undefined;

  useEffect(() => {
    if (openMenu === null || openMenuSession !== undefined) return;
    setOpenMenu(null);
    restoreFocus(false);
  }, [openMenu, openMenuSession, restoreFocus]);

  useEffect(() => {
    if (openMenu === null || openMenuSession === undefined) {
      openMenuActivity.current = null;
      return;
    }
    const previous = openMenuActivity.current;
    openMenuActivity.current = { activeRun: openMenuHasActiveTurn, id: openMenuSession.id };
    if (previous?.id === openMenuSession.id && !previous.activeRun && openMenuHasActiveTurn) {
      setOpenMenu(null);
    }
  }, [openMenu, openMenuHasActiveTurn, openMenuSession]);

  useEffect(() => {
    if (openMenu === null) return;
    const close = () => setOpenMenu(null);
    const dismissForAnchorScroll = (event: Event) => {
      const trigger = menuButtons.current.get(openMenu);
      if (trigger && event.target instanceof Node && event.target.contains(trigger)) close();
    };
    window.addEventListener("resize", close);
    document.addEventListener("scroll", dismissForAnchorScroll, true);
    return () => {
      window.removeEventListener("resize", close);
      document.removeEventListener("scroll", dismissForAnchorScroll, true);
    };
  }, [openMenu]);

  useEffect(() => {
    if (!navigationInteractive) setOpenMenu(null);
  }, [navigationInteractive]);

  useEffect(() => {
    setOpenMenu(null);
  }, [currentSessionId]);

  function openDecision(kind: SessionDialog["kind"], session: AgentSessionSummary): void {
    setOpenMenu(null);
    onDecision({ kind, session });
  }

  const historyContent = controller.status === "loading" ? (
    <p className="chat-session-status chat-session-status-loading" role="status" title={t("historyLoading")}>
      {t("historyLoading")}
    </p>
  ) : controller.status === "error" && controller.sessions.length === 0 ? (
    <div className="chat-session-status chat-session-status-error">
      <p role="alert">{controller.error}</p>
      <Button variant="ghost" onClick={controller.refresh} type="button">{t("retry")}</Button>
    </div>
  ) : controller.sessions.length === 0 ? (
    <div className="chat-session-empty" title={t("historyEmpty")}>
      <ChatCircle aria-hidden="true" size={16} weight="regular" />
      <span className="chat-session-empty-full">{t("historyEmpty")}</span>
      <span className="chat-session-empty-compact">{t("empty")}</span>
    </div>
  ) : (
    <>
      <div className="chat-session-groups">
        {groups.map((group) => (
          <section aria-labelledby={`chat-session-group-${group.id}`} key={group.id}>
            <h3 data-collapsed-label={collapsedGroupLabel(group.id)} id={`chat-session-group-${group.id}`}>
              {t(`recency.${group.id}`)}
            </h3>
            <div className="chat-session-list">
              {group.sessions.map((session) => (
                <div
                  className={`chat-session-row${session.id === currentSessionId ? " chat-session-row-current" : ""}`}
                  key={session.id}
                >
                  <a
                    aria-current={session.id === currentSessionId ? "page" : undefined}
                    aria-label={`${displayTitle(session.title)}${session.current_turn === null ? "" : `, ${t(session.current_turn.status === "waiting_for_user" ? "waitingShort" : "runningShort")}`}`}
                    href={chatSessionHref(session.id)}
                    onClick={(event) => handleWorkspaceNavigation(event, () => {
                      if (session.id !== currentSessionId) navigate(chatSessionHref(session.id));
                    })}
                    title={`${displayTitle(session.title)}${session.current_turn === null ? "" : ` — ${t(session.current_turn.status === "waiting_for_user" ? "waitingShort" : "runningShort")}`}`}
                  >
                    <span>{displayTitle(session.title)}</span>
                    {session.current_turn === null ? null : (
                      <em aria-hidden="true" className="chat-session-turn-state">
                        {session.current_turn.status === "waiting_for_user"
                          ? <Question className="chat-session-waiting-icon" size={15} weight="bold" />
                          : <CircleNotch className="chat-session-active-spinner" size={15} />}
                      </em>
                    )}
                  </a>
                  <DropdownMenu
                    modal={isMobile}
                    open={openMenu === session.id && navigationInteractive}
                    onOpenChange={(next) => setOpenMenu(next ? session.id : null)}
                  >
                    <DropdownMenuTrigger
                      aria-label={t("actionsFor", { name: displayTitle(session.title) })}
                      render={<Button variant="ghost" size="icon-sm" className="chat-session-menu-trigger" type="button" />}
                      ref={(element) => {
                        if (element === null) menuButtons.current.delete(session.id);
                        else menuButtons.current.set(session.id, element);
                      }}
                    >
                      <DotsThree aria-hidden="true" size={17} weight="bold" />
                    </DropdownMenuTrigger>
                    <DropdownMenuContent
                      aria-label={t("actionsFor", { name: displayTitle(session.title) })}
                      className="chat-session-menu w-42"
                      id={`chat-session-menu-${session.id}`}
                      side="right"
                    >
                      <DropdownMenuGroup>
                        <DropdownMenuItem onClick={() => openDecision("rename", session)}>
                          <NotePencil aria-hidden="true" size={16} />{t("rename")}
                        </DropdownMenuItem>
                        {session.current_turn === null ? (
                          <DropdownMenuItem variant="destructive" onClick={() => openDecision("delete", session)}>
                            <Trash aria-hidden="true" size={16} />{t("deleteChat")}
                          </DropdownMenuItem>
                        ) : null}
                      </DropdownMenuGroup>
                    </DropdownMenuContent>
                  </DropdownMenu>
                </div>
              ))}
            </div>
          </section>
        ))}
      </div>
      {controller.error === null ? null : <p className="chat-session-pagination-error" role="alert" title={controller.error}>{controller.error}</p>}
      {controller.nextCursor === null ? null : (
        <Button variant="ghost" className="chat-session-load-more" disabled={controller.loadingMore} onClick={() => void controller.loadMore()} type="button">
          {t(controller.loadingMore ? "loadingMore" : "loadMore")}
        </Button>
      )}
    </>
  );

  return historyContent;
}

export function SessionDecisionDialog({
  controller, dialog, onClose, onDeleted,
}: {
  controller: SessionHistoryController;
  dialog: SessionDialog;
  onClose: () => void;
  onDeleted: (sessionId: string) => void;
}) {
  const { t } = useTranslation("chat");
  const [title, setTitle] = useState(dialog.session.title);
  const [errorKey, setErrorKey] = useState<ChatErrorKey | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function submit(event: FormEvent): Promise<void> {
    event.preventDefault();
    if (submitting) return;
    setSubmitting(true);
    setErrorKey(null);
    try {
      if (dialog.kind === "rename") {
        await controller.renameSession(dialog.session, title);
        onClose();
      } else {
        await controller.deleteSession(dialog.session);
        onDeleted(dialog.session.id);
      }
    } catch (caught) {
      if (caught instanceof AgentSessionChangedError) {
        setErrorKey("titleChanged");
        controller.refresh();
      } else if (caught instanceof AgentSessionActiveRunError) {
        setErrorKey("activeRun");
        controller.refresh();
      } else if (caught instanceof AgentSessionNotFoundError) {
        setErrorKey("chatGone");
        controller.refresh();
      } else if (caught instanceof AgentSessionTitleInvalidError || caught instanceof AgentSessionInvalidError) {
        setErrorKey(sessionDialogErrorKey(dialog.kind, caught));
      } else {
        setErrorKey(dialog.kind === "rename" ? "renameFailed" : "deleteFailed");
      }
    } finally {
      setSubmitting(false);
    }
  }

  if (dialog.kind === "delete") {
    return (
      <AlertDialog open onOpenChange={(next) => { if (!next && !submitting) onClose(); }}>
        <AlertDialogContent className="chat-session-dialog w-[min(440px,calc(100vw-32px))] max-w-none text-muted-foreground">
          <AlertDialogHeader>
            <AlertDialogTitle>{t("deleteChatQuestion")}</AlertDialogTitle>
            <AlertDialogDescription>
              <Trans i18nKey="deleteDescription" ns="chat" components={{ name: <strong>{dialog.session.title === "Untitled" ? t("untitled") : dialog.session.title}</strong> }} />
            </AlertDialogDescription>
          </AlertDialogHeader>
          <form onSubmit={(event) => void submit(event)}>
            {errorKey === null ? null : <Alert variant="destructive"><AlertDescription>{t(`errors.${errorKey}`)}</AlertDescription></Alert>}
            <AlertDialogFooter>
              <Button autoFocus variant="outline" disabled={submitting} onClick={onClose} type="button">{t("cancel")}</Button>
              <Button variant="destructive" disabled={submitting} type="submit">{t(submitting ? "deleting" : "deleteChat")}</Button>
            </AlertDialogFooter>
          </form>
        </AlertDialogContent>
      </AlertDialog>
    );
  }

  return (
    <Dialog open onOpenChange={(next) => { if (!next && !submitting) onClose(); }}>
      <DialogContent className="chat-session-dialog w-[min(440px,calc(100vw-32px))] max-w-none text-muted-foreground" showCloseButton={false}>
        <DialogHeader>
          <DialogTitle>{t("renameChat")}</DialogTitle>
          <DialogDescription>{t("renameDescription")}</DialogDescription>
        </DialogHeader>
        <form onSubmit={(event) => void submit(event)}>
          <Field data-invalid={errorKey !== null}>
            <FieldLabel htmlFor="chat-session-title">{t("title")}</FieldLabel>
            <Input autoFocus id="chat-session-title" aria-invalid={errorKey !== null} onChange={(event) => setTitle(event.target.value)} required value={title} />
          </Field>
          {errorKey === null ? null : <Alert variant="destructive"><AlertDescription>{t(`errors.${errorKey}`)}</AlertDescription></Alert>}
          <DialogFooter>
            <Button variant="outline" disabled={submitting} onClick={onClose} type="button">{t("cancel")}</Button>
            <Button disabled={submitting} type="submit">{t(submitting ? "saving" : "saveTitle")}</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function sessionDialogErrorKey(
  kind: SessionDialog["kind"],
  error: AgentSessionInvalidError | AgentSessionTitleInvalidError,
): ChatErrorKey {
  if (error instanceof AgentSessionTitleInvalidError) return "titleInvalid";
  return kind === "rename" ? "titleResponseInvalid" : "deleteResponseInvalid";
}

export function sessionDialogErrorMessage(
  kind: SessionDialog["kind"],
  error: AgentSessionInvalidError | AgentSessionTitleInvalidError,
): string {
  return i18n.t(`chat:errors.${sessionDialogErrorKey(kind, error)}`);
}

function collapsedGroupLabel(id: "today" | "previous" | "older"): string {
  switch (id) {
    case "today": return "T";
    case "previous": return "7d";
    case "older": return "O";
  }
}
