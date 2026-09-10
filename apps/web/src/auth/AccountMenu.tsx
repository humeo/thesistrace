import { CaretRight, CaretUpDown, SignOut } from "@phosphor-icons/react";
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
  const initials = session.displayLabel.trim().split(/\s+/u)
    .map((part) => Array.from(part)[0]).slice(0, 2).join("").toLocaleUpperCase();

  const identity = (
    <>
      <span className="account-avatar" aria-hidden="true">{initials}</span>
      <span className="account-identity-copy">
        <strong>{session.displayLabel}</strong>
        <span title={session.email}>{session.email}</span>
      </span>
    </>
  );

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
        "a[href], button:not([disabled]), input:not([disabled])",
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
        {identity}
        <CaretUpDown className="account-trigger-chevron" aria-hidden="true" size={18} />
      </summary>
      <div className="account-menu-panel" ref={panelRef}>
        <div className="account-identity">
          {identity}
        </div>
        {message !== null ? <p className="account-message" role="status">{message}</p> : null}
        <a
          className="button account-action"
          href="https://discord.gg/tdwxubVhMJ"
          target="_blank"
          rel="noopener noreferrer"
        >
          <img src="/brand/discord-symbol-white.svg" alt="" width={20} height={16} />
          <span>Join Discord</span>
          <CaretRight className="account-action-chevron" aria-hidden="true" size={16} />
        </a>
        <button
          className="account-action"
          disabled={signingOut}
          onClick={() => void submitSignOut()}
          type="button"
        >
          <SignOut aria-hidden="true" size={20} />
          <span>{signingOut ? "Logging out…" : "Log out"}</span>
          <CaretRight className="account-action-chevron" aria-hidden="true" size={16} />
        </button>
      </div>
    </details>
  );
}
