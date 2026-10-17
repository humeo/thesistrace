import { useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowClockwise } from "@phosphor-icons/react";
import { Page, PageContent, PageHeader } from "../components/layout/Page";
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
  CardFooter,
} from "../components/ui/card";
import { Alert, AlertDescription } from "../components/ui/alert";
import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogDescription,
  AlertDialogFooter,
} from "../components/ui/alert-dialog";
import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import { Skeleton } from "../components/ui/skeleton";
import { Separator } from "../components/ui/separator";
import { Spinner } from "../components/ui/spinner";
import { useTranslation } from "../i18n";
import { formatNumber, formatTimestamp } from "../i18n/format";
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

const planName = (plan: Plan) =>
  plan === "free" ? "Free" : plan === "pro" ? "Pro" : "Max";
const usd = (amount: number) =>
  formatNumber(amount, {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 6,
  });
export function BillingPage() {
  const { t } = useTranslation("billing");
  const queryClient = useQueryClient();
  const [pollUntil, setPollUntil] = useState(() => Date.now() + 120_000);
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
  return (
    <Page className="console-workspace" aria-label={t("title")}>
      <PageContent width="wide" className="flex flex-col gap-6 p-6">
        <PageHeader
          variant="console"
          className="mb-0"
          title={t("title")}
          description={t("subtitle")}
          actions={
            <Button
              variant="ghost"
              size="sm"
              disabled={billing.isFetching}
              onClick={refresh}
            >
              <ArrowClockwise data-icon="inline-start" />
              {t("retry")}
            </Button>
          }
        />
        {billing.isError ? (
          <Alert variant="destructive">
            <AlertDescription>{t("unavailable")}</AlertDescription>
          </Alert>
        ) : null}
        {error && !command ? (
          <Alert variant="destructive">
            <AlertDescription>{t(error ?? "error")}</AlertDescription>
          </Alert>
        ) : null}
        {!summary ? (
          <Skeleton className="h-64 w-full" />
        ) : (
          <>
            <section aria-label={t("current")} className="flex flex-col gap-3">
              <div className="flex flex-wrap items-center gap-3">
                <Badge variant="secondary">{planName(summary.plan)}</Badge>
                {summary.paid_until ? (
                  <span>
                    {t("until", {
                      date: formatTimestamp(summary.paid_until, {
                        dateStyle: "medium",
                        timeStyle: "short",
                      }),
                    })}
                  </span>
                ) : null}
                {summary.renewal_plan && !ending ? (
                  <span className="text-sm text-muted-foreground">
                    {t("renewal", { plan: planName(summary.renewal_plan) })}
                  </span>
                ) : null}
              </div>
              {ending ? (
                <p role="status">
                  {t(summary.paid_until ? "ending" : "endingFree")}
                </p>
              ) : null}
              {summary.pending_operation ? (
                <Alert role="status">
                  <AlertDescription>{t("pending")}</AlertDescription>
                </Alert>
              ) : null}
              {!summary.checkout_available ? (
                <Alert role="status">
                  <AlertDescription>{t("disabled")}</AlertDescription>
                </Alert>
              ) : null}
              <div className="flex flex-wrap gap-2">
                {summary.pending_checkout_url && summary.checkout_available ? (
                  <Button
                    nativeButton={false}
                    render={
                      <a
                        href={hostedPaymentUrl(summary.pending_checkout_url)}
                      />
                    }
                  >
                    {t("continueCheckout")}
                  </Button>
                ) : null}
                {summary.subscription_status ? (
                  <Button
                    variant="outline"
                    disabled={busy || !summary.checkout_available}
                    onClick={() => void portal()}
                  >
                    {t("portal")}
                  </Button>
                ) : null}
                {summary.subscription_status && !ending ? (
                  <Button
                    variant="outline"
                    disabled={busy || !summary.checkout_available}
                    onClick={() => {
                      setError(null);
                      setCommand({
                        kind: "cancel",
                        request_id: crypto.randomUUID(),
                      });
                    }}
                  >
                    {t("cancelRenewal")}
                  </Button>
                ) : null}
              </div>
            </section>
            <section className="grid grid-cols-3 gap-4" aria-label={t("title")}>
              {(["free", "pro", "max"] as const).map((plan) => {
                const limits = summary.plans[plan],
                  current = summary.plan === plan;
                return (
                  <Card key={plan}>
                    <CardHeader>
                      <CardTitle>{planName(plan)}</CardTitle>
                      <CardDescription>
                        {usd(limits.monthly_price_usd)} {t("monthly")}
                      </CardDescription>
                    </CardHeader>
                    <CardContent>
                      <ul className="flex flex-col gap-3">
                        <li>
                          {t("researchAmount", {
                            count: limits.daily_run_limit,
                          })}
                        </li>
                        <li>
                          {t("trackAmount", {
                            count: limits.active_daily_track_limit,
                          })}
                        </li>
                        <li>
                          {t("aiAmount", {
                            amount: usd(limits.daily_model_budget_usd),
                          })}
                        </li>
                      </ul>
                    </CardContent>
                    <CardFooter>
                      {plan === "free" ? (
                        <Badge variant="secondary">
                          {current ? t("active") : "Free"}
                        </Badge>
                      ) : (
                        <Button
                          variant={current ? "outline" : "default"}
                          disabled={
                            busy ||
                            !summary.checkout_available ||
                            summary.pending_operation ||
                            summary.subscription_status ===
                              "scheduled_cancel" ||
                            (current &&
                              (summary.renewal_plan === plan ||
                                !summary.subscription_status))
                          }
                          onClick={() => choose(plan)}
                        >
                          {current && summary.renewal_plan === plan
                            ? t("active")
                            : current
                              ? t("renewWith", { plan: planName(plan) })
                              : t("choose", { plan: planName(plan) })}
                        </Button>
                      )}
                    </CardFooter>
                  </Card>
                );
              })}
            </section>
            <p className="text-sm text-muted-foreground">{t("tax")}</p>
          </>
        )}
        <Separator />
        <section className="flex flex-col gap-4" aria-label={t("usage")}>
          <h2 className="text-lg font-semibold">{t("usage")}</h2>
          <p className="text-sm text-muted-foreground">{t("reset")}</p>
          <div className="grid grid-cols-2 gap-4">
            <Card>
              <CardHeader>
                <CardTitle>{t("research")}</CardTitle>
              </CardHeader>
              <CardContent>
                {core.data ? (
                  <UsageValues
                    actual={formatNumber(core.data.research.actual)}
                    reserved={formatNumber(core.data.research.reserved)}
                    remaining={
                      core.data.research.remaining === null
                        ? t("unlimited")
                        : formatNumber(core.data.research.remaining)
                    }
                  />
                ) : (
                  <p>{t("usageUnavailable")}</p>
                )}
              </CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle>{t("ai")}</CardTitle>
              </CardHeader>
              <CardContent>
                {model.data ? (
                  <UsageValues
                    actual={usd(model.data.actual_nanodollars / 1e9)}
                    reserved={usd(model.data.reserved_nanodollars / 1e9)}
                    remaining={
                      model.data.remaining_nanodollars === null
                        ? t("unlimited")
                        : usd(model.data.remaining_nanodollars / 1e9)
                    }
                  />
                ) : (
                  <p>{t("usageUnavailable")}</p>
                )}
              </CardContent>
            </Card>
          </div>
          {core.data ? (
            <div className="flex flex-col gap-2">
              <p>
                {t("trackingUsage", {
                  selected: core.data.tracking.selected_track_ids.length,
                  limit: core.data.tracking.limit ?? t("unlimited"),
                  retained: core.data.tracking.retained_count,
                })}
              </p>
              {core.data.tracking.selection_required ? (
                <Alert>
                  <AlertDescription>{t("selectionRequired")}</AlertDescription>
                </Alert>
              ) : null}
              <p className="text-sm text-muted-foreground">
                {t("trackingHistory")}
              </p>
            </div>
          ) : null}
        </section>
        <p className="text-sm text-muted-foreground">{t("refund")}</p>
        <AlertDialog
          open={command !== null}
          onOpenChange={(open) => {
            if (!open && !busy) setCommand(null);
          }}
        >
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>
                {command?.kind === "cancel"
                  ? t("cancelTitle")
                  : t("changeTitle", {
                      plan: command?.plan ? planName(command.plan) : "",
                    })}
              </AlertDialogTitle>
              <AlertDialogDescription>
                {command?.kind === "cancel"
                  ? t(
                      summary?.paid_until
                        ? "cancelDescription"
                        : "cancelDescriptionFree",
                    )
                  : command?.kind === "checkout"
                    ? t("checkout")
                    : t(higher ? "upgrade" : "downgrade")}
              </AlertDialogDescription>
            </AlertDialogHeader>
            {error ? (
              <Alert variant="destructive">
                <AlertDescription>{t(error ?? "error")}</AlertDescription>
              </Alert>
            ) : null}
            <AlertDialogFooter>
              <Button
                variant="outline"
                disabled={busy}
                onClick={() => setCommand(null)}
              >
                {t("back")}
              </Button>
              <Button disabled={busy} onClick={() => void confirm()}>
                {busy ? <Spinner data-icon="inline-start" /> : null}
                {t(busy ? "working" : "confirm")}
              </Button>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      </PageContent>
    </Page>
  );
}
function UsageValues({
  actual,
  reserved,
  remaining,
}: {
  actual: string;
  reserved: string;
  remaining: string;
}) {
  const { t } = useTranslation("billing");
  return (
    <dl className="grid grid-cols-3 gap-4">
      {(
        [
          ["actual", actual],
          ["reserved", reserved],
          ["remaining", remaining],
        ] as const
      ).map(([label, value]) => (
        <div key={label} className="flex flex-col gap-2">
          <dt className="text-xs text-muted-foreground">{t(label)}</dt>
          <dd className="m-0 tabular-nums">{value}</dd>
        </div>
      ))}
    </dl>
  );
}
