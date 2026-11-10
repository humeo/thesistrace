import type { ReactNode } from "react";
import { Button } from "../components/ui/button";
import { Card, CardContent, CardTitle } from "../components/ui/card";
import { DialogContent, DialogTitle } from "../components/ui/dialog";
import { useTranslation } from "../i18n";
import { formatNumber } from "../i18n/format";
import type { BillingSummary, Plan } from "./client";

export const planName = { free: "Free", pro: "Pro", max: "Max" } satisfies Record<Plan, string>;
export const planPrice = (value: number) => `US${formatNumber(value, {
  style: "currency",
  currency: "USD",
  currencyDisplay: "narrowSymbol",
  maximumFractionDigits: 0,
})}`;

export function PlanPicker({
  summary,
  busy,
  choose,
  children,
}: {
  summary: BillingSummary;
  busy: boolean;
  choose: (plan: Exclude<Plan, "free">) => void;
  children: ReactNode;
}) {
  const { t } = useTranslation("billing");
  const canChange = summary.checkout_available && !busy && !summary.pending_operation
    && summary.subscription_status !== "scheduled_cancel";

  return (
    <DialogContent
      closeLabel={t("close")}
      className="top-0 left-0 block h-dvh max-w-none translate-x-0 translate-y-0 overflow-y-auto rounded-none bg-background px-6 pt-[103px] pb-12 ring-0 sm:max-w-none [&_[data-slot=dialog-close]]:top-9 [&_[data-slot=dialog-close]]:right-10 [&_[data-slot=dialog-close]]:size-11 [&_[data-slot=dialog-close]]:rounded-full [&_[data-slot=dialog-close]]:bg-secondary"
    >
      <div className="mx-auto grid max-w-[978px] gap-6">
        <DialogTitle className="mt-0 mb-[29px] grid min-h-[72px] place-items-center text-center text-4xl">{t("changePlan")}</DialogTitle>
        <div className="grid grid-cols-1 gap-[18px] md:grid-cols-3">
          {(["free", "pro", "max"] as const).map((plan) => {
            const limits = summary.plans[plan];
            const current = summary.plan === plan;
            const currentRenewal = current && (!summary.subscription_status || summary.renewal_plan === plan);
            const label = currentRenewal || (current && plan === "free")
              ? t("active")
              : plan === "free" ? t("freePlan")
                : current ? t("renewWith", { plan: planName[plan] })
                  : t(limits.monthly_price_usd > summary.plans[summary.plan].monthly_price_usd ? "upgradeTo" : "switchTo", { plan: planName[plan] });
            return (
              <Card key={plan} role="group" aria-label={planName[plan]} className="min-h-[304px] gap-[18px] rounded-[20px]! border-input! p-6">
                <CardTitle className="text-base">{planName[plan]}</CardTitle>
                <Button
                  variant="outline"
                  size="sm"
                  className="h-11 w-full rounded-full border-transparent bg-foreground text-background hover:bg-foreground/90 hover:text-background disabled:border-input disabled:bg-transparent disabled:text-muted-foreground disabled:opacity-100"
                  disabled={plan === "free" || currentRenewal || !canChange}
                  onClick={() => { if (plan !== "free") choose(plan); }}
                >
                  {label}
                </Button>
                <div className="flex items-baseline gap-1.5">
                  <span className="text-2xl font-semibold tabular-nums">{planPrice(limits.monthly_price_usd)}</span>
                  <span className="text-muted-foreground">{t("monthly")}</span>
                </div>
                <CardContent className="p-0">
                  <ul className="m-0 grid list-none gap-2 p-0 text-sm">
                    <li>{t("researchAmount", { count: limits.daily_run_limit })}</li>
                    <li>{t("trackAmount", { count: limits.active_daily_track_limit })}</li>
                    <li>{t(`aiAmount.${plan}`)}</li>
                  </ul>
                </CardContent>
              </Card>
            );
          })}
        </div>
        <p className="m-0 text-center text-xs text-muted-foreground">{t(summary.checkout_available ? "tax" : "disabled")}</p>
      </div>
      {children}
    </DialogContent>
  );
}
