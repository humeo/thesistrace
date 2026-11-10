import { CaretUpDown } from "@phosphor-icons/react";
import { lazy, Suspense, useState } from "react";

import { Button } from "../components/ui/button";
import { Popover, PopoverContent, PopoverTitle, PopoverTrigger } from "../components/ui/popover";
import { Separator } from "../components/ui/separator";
import { Skeleton } from "../components/ui/skeleton";
import { useTranslation } from "../i18n";
import { useAuthRetry } from "./useAuthRetry";
import { useAuth } from "./AuthProvider";
import type { AuthErrorCode, AuthResult } from "./errors";
import type { PublicSession } from "./session";

type AccountMenuContentProps = Readonly<{
  session: PublicSession;
  signOut: () => Promise<AuthResult>;
}>;
const AccountMenuActions = lazy(() => import("./AccountMenuActions"));

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

export function AccountMenuContent({ session, signOut }: AccountMenuContentProps) {
  const { t } = useTranslation("common");
  const [open, setOpen] = useState(false);
  const [retryAt, setRetryAt] = useState(0);
  const cooldown = useAuthRetry(retryAt);
  const [signingOut, setSigningOut] = useState(false);
  const [message, setMessage] = useState<AuthErrorCode | null>(null);
  const initials = session.displayLabel.trim().split(/\s+/u)
    .map((part) => Array.from(part)[0]).slice(0, 2).join("").toLocaleUpperCase();

  async function submitSignOut(): Promise<void> {
    if (signingOut || cooldown > 0) return;
    setSigningOut(true);
    setMessage(null);
    const result = await signOut();
    if (!result.ok) {
      setSigningOut(false);
      setMessage(result.code);
      if (result.retryAfterSeconds !== undefined) setRetryAt(Date.now() + result.retryAfterSeconds * 1_000);
    }
  }

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger aria-label={t("accountMenu")} render={<Button variant="ghost" type="button" className="account-trigger" />}>
        <span className="account-avatar account-trigger-avatar" aria-hidden="true">{initials}</span>
        <span className="account-trigger-name" title={session.displayLabel}>{session.displayLabel}</span>
        <CaretUpDown className="account-trigger-chevron" aria-hidden="true" size={16} />
        <span className="sr-only">{t("accountMenu")}</span>
      </PopoverTrigger>
      <PopoverContent side="top" align="start" className="account-menu-panel">
        <PopoverTitle className="sr-only">{t("accountMenu")}</PopoverTitle>
        <div className="account-identity">
          <span className="account-avatar account-menu-avatar" aria-hidden="true">{initials}</span>
          <span className="account-identity-copy">
            <strong>{session.displayLabel}</strong>
            <span title={session.email}>{session.email}</span>
          </span>
        </div>
        <Separator className="account-menu-divider" />
        <Suspense fallback={<Skeleton className="h-48 w-full" />}>
          <AccountMenuActions
            cooldown={cooldown}
            message={message}
            signingOut={signingOut}
            onSignOut={() => void submitSignOut()}
          />
        </Suspense>
      </PopoverContent>
    </Popover>
  );
}
