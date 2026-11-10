import { CaretRight, CreditCard, Moon, SignOut, Translate } from "@phosphor-icons/react";
import { Alert, AlertDescription } from "../components/ui/alert";
import { Button, buttonVariants } from "../components/ui/button";
import { Popover, PopoverContent, PopoverTitle, PopoverTrigger } from "../components/ui/popover";
import { Separator } from "../components/ui/separator";
import { ToggleGroup, ToggleGroupItem } from "../components/ui/toggle-group";
import { changeInterfaceLanguage, interfaceLocale, useTranslation } from "../i18n";
import type { AuthErrorCode } from "./errors";

const actionLinkClass = buttonVariants({ variant: "ghost", size: "sm", className: "account-action" });

export default function AccountMenuActions({
  cooldown,
  message,
  signingOut,
  onSignOut,
}: {
  cooldown: number;
  message: AuthErrorCode | null;
  signingOut: boolean;
  onSignOut: () => void;
}) {
  const { t } = useTranslation(["common", "auth"]);
  const locale = interfaceLocale();

  return (
    <>
      <a className={actionLinkClass} href="/billing">
        <CreditCard aria-hidden="true" />
        {t("billing")}
      </a>
      <Separator className="account-menu-divider" />
      <Popover>
        <PopoverTrigger render={<Button variant="ghost" size="sm" className="account-action" />}>
          <Translate aria-hidden="true" />
          {t("language")}
          <span className="account-action-value">{locale === "en" ? "English" : "简体中文"}</span>
          <CaretRight aria-hidden="true" className="text-muted-foreground" />
        </PopoverTrigger>
        <PopoverContent side="right" align="start" className="account-language-panel">
          <PopoverTitle className="sr-only">{t("language")}</PopoverTitle>
          <ToggleGroup
            aria-label={t("language")}
            value={[locale]}
            onValueChange={([value]) => {
              const selected = value ?? locale;
              if (selected === "en" || selected === "zh-CN") void changeInterfaceLanguage(selected);
            }}
            className="account-language-options"
          >
            <ToggleGroupItem value="en" lang="en">English</ToggleGroupItem>
            <ToggleGroupItem value="zh-CN" lang="zh-CN">简体中文</ToggleGroupItem>
          </ToggleGroup>
        </PopoverContent>
      </Popover>
      <div className="account-action account-theme">
        <Moon aria-hidden="true" size={16} />
        {t("theme")}
        <span className="account-action-value">{t("darkTheme")}</span>
      </div>
      {message !== null ? <Alert variant="destructive"><AlertDescription>{message === "tooManyRequests" && cooldown > 0 ? t("auth:rateLimited", {seconds: cooldown}) : t(`auth:errors.${message}`)}</AlertDescription></Alert> : null}
      <a className={actionLinkClass} href="https://discord.gg/tdwxubVhMJ" target="_blank" rel="noopener noreferrer">
        <img src="/brand/discord-symbol-white.svg" alt="" width={20} height={16} />
        <span>{t("joinCommunity")}</span>
      </a>
      <Separator className="account-menu-divider" />
      <Button variant="ghost" size="sm" className="account-action account-sign-out" disabled={signingOut || cooldown > 0} onClick={onSignOut} type="button">
        <SignOut aria-hidden="true" size={18} />
        <span>{t(signingOut ? "signingOut" : "signOut")}</span>
      </Button>
    </>
  );
}
