import { Disclosure } from "../components/layout/Disclosure";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../components/ui/table";
import Decimal from "decimal.js";
import { useTranslation } from "../i18n";
import { formatNumber } from "../i18n/format";

export type CloseRiskPosition = {
  instrument_id: string;
  execution_shares: number;
  remaining_acquisition_cost_cny: string;
  holding_cycle_started_session: string;
  holding_age: number;
  adjusted_units: string;
  last_close_adjusted_price: string;
};

export function CloseRiskFacts({ session, nav, positions, variant }: {
  session: string; nav: string; positions: CloseRiskPosition[];
  variant?: "panel" | "row";
}) {
  const { t } = useTranslation("strategy");
  const decimal = (value: string, digits: number) => formatNumber(new Decimal(value).toNumber(), {
    minimumFractionDigits: digits, maximumFractionDigits: digits,
  });
  return <Disclosure variant={variant} title={t("closeRisk.title")}>
    <div className="flex min-w-0 flex-col gap-4">
      <dl className="m-0 flex flex-wrap gap-x-10 gap-y-3 [&_dt]:text-muted-foreground [&_dd]:m-0 [&_dd]:mt-1 [&_dd]:text-base [&_dd]:font-medium [&_dd]:tabular-nums">
        <div><dt>{t("closeRisk.session")}</dt><dd><time dateTime={session}>{session}</time></dd></div>
        <div><dt>{t("closeRisk.nav")}</dt><dd title={new Decimal(nav).toFixed()}>{decimal(nav, 2)}</dd></div>
        <div><dt>{t("closeRisk.count")}</dt><dd>{formatNumber(positions.length)}</dd></div>
      </dl>
      <p className="m-0 text-muted-foreground">{t("closeRisk.help")}</p>
      {positions.length === 0 ? <p className="m-0 text-muted-foreground">{t("closeRisk.empty")}</p> :
        <div className="overflow-hidden rounded-md border border-border">
          <Table density="catalog" aria-label={t("closeRisk.holdings")} scrollLabel={t("closeRisk.holdings")} className="tabular-nums">
            <TableHeader><TableRow>
              <TableHead scope="col">{t("closeRisk.instrument")}</TableHead>
              <TableHead scope="col" className="text-right">{t("closeRisk.shares")}</TableHead>
              <TableHead scope="col" className="text-right">{t("closeRisk.acquisition")}</TableHead>
              <TableHead scope="col" className="text-right">{t("closeRisk.adjustedClose")}</TableHead>
              <TableHead scope="col" className="text-right">{t("closeRisk.age")}</TableHead>
              <TableHead scope="col" className="text-right">{t("closeRisk.started")}</TableHead>
            </TableRow></TableHeader>
            <TableBody>{positions.map(position => <TableRow key={position.instrument_id}>
              <TableHead scope="row" className="font-medium">{position.instrument_id.replace(/^equity:/, "")}</TableHead>
              <TableCell className="text-right">{formatNumber(position.execution_shares)}</TableCell>
              <TableCell className="text-right" title={new Decimal(position.remaining_acquisition_cost_cny).toFixed()}>{decimal(position.remaining_acquisition_cost_cny, 2)}</TableCell>
              <TableCell className="text-right" title={new Decimal(position.last_close_adjusted_price).toFixed()}>{decimal(position.last_close_adjusted_price, 4)}</TableCell>
              <TableCell className="text-right">{formatNumber(position.holding_age)}</TableCell>
              <TableCell className="text-right"><time dateTime={position.holding_cycle_started_session}>{position.holding_cycle_started_session}</time></TableCell>
            </TableRow>)}</TableBody>
          </Table>
        </div>}
    </div>
  </Disclosure>;
}
