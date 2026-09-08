import { SignOut, UserCircle } from "@phosphor-icons/react";
import {
  useRef,
  useState,
  type KeyboardEvent,
} from "react";

import { useAuth } from "./AuthProvider";
import type { PublicSession } from "./session";

type AccountActionResult = Readonly<{ ok: true }> | Readonly<{ ok: false; message: string }>;

type AccountMenuContentProps = Readonly<{
  session: PublicSession;
  signOut: () => Promise<AccountActionResult>;
}>;

export function AccountMenu() {
  const { signOut, state } = useAuth();
  if (state.session === null) return null;
  return (
    <AccountMenuContent
      key={state.session.researcherId}
      session={state.session}
      signOut={signOut}
    />
  );
}

export function AccountMenuContent({
  session,
  signOut,
}: AccountMenuContentProps) {
  const [open, setOpen] = useState(false);
  const [signingOut, setSigningOut] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const summaryRef = useRef<HTMLElement>(null);

  function handleMenuKeyDown(event: KeyboardEvent<HTMLDetailsElement>): void {
    if (!open) return;
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      setOpen(false);
      summaryRef.current?.focus();
      return;
    }
    if (event.key !== "Tab") return;

    const summary = summaryRef.current;
    const panel = panelRef.current;
    if (summary === null || panel === null) return;
    const focusable = [
      summary,
      ...panel.querySelectorAll<HTMLElement>(
        "button:not([disabled]), input:not([disabled])",
      ),
    ];
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

  async function submitSignOut(): Promise<void> {
    if (signingOut) return;
    setSigningOut(true);
    setMessage(null);
    const result = await signOut();
    if (!result.ok) {
      setSigningOut(false);
      setMessage(result.message);
    }
  }

  return (
    <details
      className="account-menu"
      onKeyDown={handleMenuKeyDown}
      onToggle={(event) => setOpen(event.currentTarget.open)}
      open={open}
    >
      <summary
        aria-expanded={open}
        aria-label="Account menu"
        ref={summaryRef}
      >
        <UserCircle aria-hidden="true" size={18} />
        <span>{session.displayLabel}</span>
      </summary>
      <div className="account-menu-panel" ref={panelRef}>
        <div className="account-identity">
          <strong>{session.displayLabel}</strong>
          <span>{session.email}</span>
        </div>
        {message !== null ? <p className="account-message" role="status">{message}</p> : null}
        <button
          className="account-action"
          disabled={signingOut}
          onClick={() => void submitSignOut()}
          type="button"
        >
          <SignOut aria-hidden="true" size={16} />
          {signingOut ? "Logging out…" : "Log out"}
        </button>
      </div>
    </details>
  );
}
