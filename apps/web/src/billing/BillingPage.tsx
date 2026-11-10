import { PolicyLinks } from "../legal/PolicyLinks";
import { useRef, useState } from "react";
import "../i18n/billing";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowClockwise } from "@phosphor-icons/react";
import { Page, PageContent, PageHeader } from "../components/layout/Page";
import { Dialog, DialogTrigger } from "../components/ui/dialog";
import { Alert, AlertDescription } from "../components/ui/alert";
import { Card } from "../components/ui/card";
import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogDescription,
  AlertDialogFooter,
} from "../components/ui/alert-dialog";
import { Button } from "../components/ui/button";
import { Skeleton } from "../components/ui/skeleton";
import { Spinner } from "../components/ui/spinner";
import { useTranslation } from "../i18n";
import { formatTimestamp } from "../i18n/format";
import {
  BillingRequestError,
  billingPortal,
  hostedPaymentUrl,
  readBilling,
  readCoreUsage,
  readModelUsage,
  submitBilling,
  type BillingCommand,
  type Plan,
} from "./client";
import { BillingUsage } from "./BillingUsage";
import { PlanPicker, planName, planPrice } from "./PlanPicker";

export function BillingPage() {
  const { t } = useTranslation("billing");
  const queryClient = useQueryClient();
  const [pollUntil, setPollUntil] = useState(() => Date.now() + 120_000);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [command, setCommand] = useState<BillingCommand | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<"error" | "paymentRequired" | null>(null);
  const inFlight = useRef(false);
  const billing = useQuery({
    queryKey: ["workspace", "billing"],
    queryFn: ({ signal }) => readBilling(signal),
    refetchInterval: (query) =>
      Date.now() < pollUntil &&
      (query.state.data?.pending_operation ||
        new URLSearchParams(window.location.search).has("payment_return"))
        ? 5000
        : false,
  });
  const core = useQuery({
    queryKey: ["workspace", "billing-usage", "core", billing.data?.plan],
    enabled: billing.isSuccess,
    queryFn: ({ signal }) => readCoreUsage(signal),
  });
  const model = useQuery({
    queryKey: ["workspace", "billing-usage", "model", billing.data?.plan],
    enabled: billing.isSuccess,
    queryFn: ({ signal }) => readModelUsage(signal),
  });
  const summary = billing.data;
  const refresh = () => {
    setPollUntil(Date.now() + 120_000);
    void queryClient.invalidateQueries({ queryKey: ["workspace", "billing"] });
    void queryClient.invalidateQueries({
      queryKey: ["workspace", "billing-usage"],
    });
  };
  async function confirm() {
    if (!command || inFlight.current) return;
    inFlight.current = true;
    setBusy(true);
    setError(null);
    try {
      const result = await submitBilling(command);
      if (result.url) window.location.assign(result.url);
      setCommand(null);
      setPickerOpen(false);
      refresh();
    } catch (error) {
      setError(
        error instanceof BillingRequestError &&
          error.code === "BILLING_PAYMENT_REQUIRED"
          ? "paymentRequired"
          : "error",
      );
      refresh();
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }
  async function portal() {
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(true);
    setError(null);
    try {
      window.location.assign(await billingPortal());
    } catch {
      setError("error");
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }
  function choose(plan: Exclude<Plan, "free">) {
    if (!summary) return;
    setError(null);
    setCommand({
      kind:
        !summary.subscription_status ||
        summary.subscription_status === "canceled"
          ? "checkout"
          : "change",
      plan,
      request_id: crypto.randomUUID(),
    });
  }
  const ending =
    summary?.subscription_status === "scheduled_cancel" ||
    summary?.subscription_status === "canceled";
  const higher =
    summary && command?.plan
      ? summary.plans[command.plan].monthly_price_usd >
        summary.plans[summary.plan].monthly_price_usd
      : false;
  const reviewPlan = command?.plan;
  const confirmation = (
    <AlertDialog
      open={command !== null}
      onOpenChange={(open) => {
        if (!open && !busy) setCommand(null);
      }}
    >
      <AlertDialogContent
        className="w-[calc(100%-2rem)] gap-5 rounded-[18px] border border-input bg-card p-6 ring-0 data-[size=default]:max-w-[500px] data-[size=default]:sm:max-w-[500px]"
        overlayProps={{ forceRender: true, className: "bg-black/75" }}
      >
        <AlertDialogHeader className="gap-2">
          <AlertDialogTitle className="m-0 text-2xl">
            {command?.kind === "cancel"
              ? t("cancelTitle")
              : t(command?.kind === "checkout" || higher ? "upgradeTo" : "changeTitle", {
                  plan: reviewPlan ? planName[reviewPlan] : "",
                })}
          </AlertDialogTitle>
          {reviewPlan && summary ? (
            <p className="m-0 flex w-full justify-between gap-3 border-b border-border pt-5 pb-7 text-base">
              {planName[reviewPlan]} <span className="font-medium tabular-nums">
                {planPrice(summary.plans[reviewPlan].monthly_price_usd)} {t("monthly")}
              </span>
            </p>
          ) : null}
          <AlertDialogDescription className="m-0">
            {command?.kind === "cancel"
              ? t(summary?.paid_until ? "cancelDescription" : "cancelDescriptionFree")
              : command?.kind === "checkout"
                ? t("tax")
                : t(higher ? "upgrade" : "downgrade")}
          </AlertDialogDescription>
        </AlertDialogHeader>
        {error ? <Alert variant="destructive"><AlertDescription>{t(error)}</AlertDescription></Alert> : null}
        <AlertDialogFooter>
          <Button variant="outline" size="sm" className="h-11 min-w-24 rounded-full px-5" disabled={busy} onClick={() => setCommand(null)}>
            {t("back")}
          </Button>
          <Button
            variant="outline"
            size="sm"
            className="h-11 rounded-full border-transparent bg-foreground px-5 text-background hover:bg-foreground/90 hover:text-background"
            disabled={busy}
            onClick={() => void confirm()}
          >
            {busy ? <Spinner data-icon="inline-start" /> : null}
            {t(busy ? "working" : command?.kind === "checkout" ? "continueCheckout" : "confirm")}
          </Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );

  return (
    <Page className="console-workspace" aria-label={t("title")}>
      <PageContent width="settings" className="flex flex-col gap-10 px-5 pt-14 pb-10">
        <PageHeader
          variant="console"
          className="mb-0 [&_h1]:text-[34px] [&_h1]:leading-[48px]"
          title={t("title")}
          actions={
            <Button variant="ghost" size="icon-sm" aria-label={t("retry")} title={t("retry")} disabled={billing.isFetching} onClick={refresh}>
              <ArrowClockwise aria-hidden="true" />
            </Button>
          }
        />
        {billing.isError ? <Alert variant="destructive"><AlertDescription>{t("unavailable")}</AlertDescription></Alert> : null}
        {error && !command ? <Alert variant="destructive"><AlertDescription>{t(error)}</AlertDescription></Alert> : null}
        {!summary ? (
          billing.isPending ? <Skeleton className="h-64 w-full" /> : null
        ) : (
          <>
            <section aria-label={t("current")} className="grid gap-3">
              <Dialog open={pickerOpen} onOpenChange={(open) => {
                if (busy) return;
                setPickerOpen(open);
                if (!open) setCommand(null);
              }}>
                <Card className="min-h-[108px] flex-row flex-wrap items-center justify-between gap-4 rounded-[14px]! border-input! p-[22px]">
                  <div className="grid gap-1">
                    <h2 className="m-0 text-2xl font-semibold">{planName[summary.plan]}</h2>
                    <p className="m-0 text-sm text-muted-foreground tabular-nums">
                      {planPrice(summary.plans[summary.plan].monthly_price_usd)} {t("monthly")}
                    </p>
                  </div>
                  <DialogTrigger disabled={busy} render={
                    <Button variant="outline" size="sm" className="h-11 min-w-36 rounded-full border-transparent bg-foreground px-6 text-background hover:bg-foreground/90 hover:text-background aria-expanded:bg-foreground" />
                  }>
                    {t("changePlan")}
                  </DialogTrigger>
                </Card>
                <PlanPicker summary={summary} busy={busy} choose={choose}>
                  {command && command.kind !== "cancel" ? confirmation : null}
                </PlanPicker>
              </Dialog>
              {command?.kind === "cancel" ? confirmation : null}
              {summary.paid_until ? (
                <p className="m-0 text-sm text-muted-foreground">
                  {t("until", { date: formatTimestamp(summary.paid_until, { dateStyle: "medium", timeStyle: "short" }) })}
                </p>
              ) : null}
              {summary.renewal_plan && summary.renewal_plan !== summary.plan && !ending ? (
                <p className="m-0 text-sm text-muted-foreground">{t("renewal", { plan: planName[summary.renewal_plan] })}</p>
              ) : null}
              {ending ? <p role="status" className="m-0 text-sm">{t(summary.paid_until ? "ending" : "endingFree")}</p> : null}
              {summary.pending_operation ? (
                <Alert role="status"><AlertDescription>{t("pending")}</AlertDescription></Alert>
              ) : null}
              {summary.subscription_status || (summary.pending_checkout_url && summary.checkout_available) ? (
                <div className="flex flex-wrap gap-2">
                  {summary.pending_checkout_url && summary.checkout_available ? (
                    <Button nativeButton={false} render={<a href={hostedPaymentUrl(summary.pending_checkout_url)} />}>
                      {t("continueCheckout")}
                    </Button>
                  ) : null}
                  {summary.subscription_status ? (
                    <>
                      <Button variant="outline" disabled={busy || !summary.checkout_available} onClick={() => void portal()}>
                        {t("portal")}
                      </Button>
                      {!ending ? (
                        <Button
                          variant="outline"
                          disabled={busy || !summary.checkout_available}
                          onClick={() => {
                            setError(null);
                            setCommand({ kind: "cancel", request_id: crypto.randomUUID() });
                          }}
                        >
                          {t("cancelRenewal")}
                        </Button>
                      ) : null}
                    </>
                  ) : null}
                </div>
              ) : null}
            </section>
            <BillingUsage core={core.data} model={model.data} coreFailed={core.isError} modelFailed={model.isError} />
          </>
        )}
        <PolicyLinks includePricing={false} />
      </PageContent>
    </Page>
  );
}
