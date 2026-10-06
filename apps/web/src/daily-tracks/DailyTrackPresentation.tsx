import { useTranslation } from "react-i18next";
import { formatNumber } from "../i18n/format";
import { Section } from "../components/layout/Page";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../components/ui/table";
import { formatMoney, formatReturn, type DailyTrackObservation } from "./DailyTrackObservationView";

export function AccountAllocation({ observation }: { observation: DailyTrackObservation }) {
  const { t } = useTranslation("daily");
  const nav = Number(observation.net_asset_value_cny);
  const cash = Number(observation.cash_cny);
  const stockWeight = 1 - cash / nav;
  return <Section title={t("allocation")}>
    <p className="m-0 text-sm text-muted-foreground"><span className="block">{t("simulatedCny")}</span><span className="block whitespace-nowrap">{t("asOf", { date: observation.session })}</span></p>
    <div className="flex h-3 overflow-hidden rounded-sm bg-muted" aria-hidden="true"><div className="bg-primary" style={{ width: `${Math.max(0, Math.min(100, stockWeight * 100))}%` }} /></div>
    <dl className="m-0 grid gap-5 text-sm [&_dd]:m-0">
      <div className="grid grid-cols-[1fr_auto] gap-1"><dt className="flex items-center gap-2"><span className="size-2 rounded-full bg-primary" aria-hidden="true" />{t("invested")}</dt><dd className="tabular-nums">{formatReturn(stockWeight)}</dd><dd className="col-span-2 text-muted-foreground">{formatMoney(nav - cash)} · {formatNumber(observation.holdings.length)}{t("securities")}</dd></div>
      <div className="grid grid-cols-[1fr_auto] gap-1"><dt className="flex items-center gap-2"><span className="size-2 rounded-full bg-muted-foreground" aria-hidden="true" />{t("cash")}</dt><dd className="tabular-nums">{formatReturn(cash / nav)}</dd><dd className="col-span-2 text-muted-foreground">{formatMoney(cash)}</dd></div>
    </dl>
  </Section>;
}

export function HoldingsPreview({ observation }: { observation: DailyTrackObservation }) {
  const { t } = useTranslation("daily");
  const holdings = [...observation.holdings].sort((a, b) => b.weight - a.weight).slice(0, 5);
  return <Table scrollLabel={t("holdingsPreview")} className="tabular-nums [&_td]:text-right [&_th:not(:first-child)]:text-right">
    <TableHeader><TableRow><TableHead>{t("symbol")}</TableHead><TableHead>{t("marketValue")}</TableHead><TableHead>{t("weight")}</TableHead></TableRow></TableHeader>
    <TableBody>{holdings.map(row => <TableRow key={row.instrument_id}><TableHead scope="row">{row.instrument_id.replace(/^equity:/, "")}</TableHead><TableCell>{formatMoney(row.market_value_cny)}</TableCell><TableCell>{formatReturn(row.weight)}</TableCell></TableRow>)}
      {holdings.length === 0 && <TableRow><TableCell colSpan={3}>{t("cashOnly")}</TableCell></TableRow>}
    </TableBody>
  </Table>;
}
