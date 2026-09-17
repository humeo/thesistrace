"""Read TuShare's structured actual disclosures without announcement scraping."""

from datetime import datetime

from thesistrace.adapters.tushare_financial import RawTushareProvider
from thesistrace.adapters.tushare_provider import TushareSourceError
from thesistrace.data.financial_disclosures import (
    FinancialDisclosure,
    FinancialDisclosureDiscovery,
    FinancialDiscoveryGap,
    disclosure_periods,
    discovery_lineage,
)

DISCLOSURE_FIELDS = ("ts_code", "ann_date", "end_date", "pre_date", "actual_date", "modify_date")


class TushareDisclosureSource:
    def __init__(self, provider: RawTushareProvider) -> None:
        self._provider = provider

    def discover(self, *, start_date, end_date, allowed_ts_codes):
        completed, gaps, reports, responses = [], [], {}, []
        for period in disclosure_periods(start_date, end_date):
            try:
                raw = self._provider.query_raw(
                    "disclosure_date",
                    params={"end_date": period.replace("-", "")},
                    fields=DISCLOSURE_FIELDS,
                )
                if raw.fields != DISCLOSURE_FIELDS or len(raw.items) >= 6000:
                    raise ValueError("DISCLOSURE_RESPONSE_INCOMPLETE")
                current = {}
                for item in raw.items:
                    row = dict(zip(raw.fields, item, strict=True))
                    if _date(row["end_date"]) != period or not isinstance(row["ts_code"], str):
                        raise ValueError("DISCLOSURE_RESPONSE_INVALID")
                    actual = None if row["actual_date"] in (None, "") else _date(row["actual_date"])
                    if actual is not None and actual < period:
                        raise ValueError("DISCLOSURE_RESPONSE_INVALID")
                    if (
                        actual is None
                        or actual > end_date
                        or row["ts_code"] not in allowed_ts_codes
                    ):
                        continue
                    report = FinancialDisclosure(row["ts_code"], period, actual)
                    key = (report.ts_code, period)
                    if key in current and current[key] != report:
                        raise ValueError("DISCLOSURE_RESPONSE_CONFLICT")
                    current[key] = report
                reports.update(current)
                responses.append({"period": period, "fields": raw.fields, "items": raw.items})
                completed.append(period)
            except TushareSourceError as error:
                gaps.append(FinancialDiscoveryGap(period, error.reason_code))
            except (TypeError, ValueError):
                gaps.append(FinancialDiscoveryGap(period, "DISCLOSURE_RESPONSE_INVALID"))
        return FinancialDisclosureDiscovery(
            start_date,
            end_date,
            tuple(completed),
            tuple(reports[key] for key in sorted(reports)),
            tuple(gaps),
            discovery_lineage(
                {
                    "source": "tushare-disclosure_date",
                    "start_date": start_date,
                    "end_date": end_date,
                    "responses": responses,
                    "gaps": [gap.__dict__ for gap in gaps],
                }
            ),
        )


def _date(value):
    parsed = datetime.strptime(str(value), "%Y%m%d").date()
    if parsed.strftime("%Y%m%d") != value:
        raise ValueError("Invalid disclosure date")
    return parsed.isoformat()
