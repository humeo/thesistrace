from __future__ import annotations

import json
import os
import stat
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path

from thesistrace.adapters.tushare_daily_basic import DAILY_BASIC_SOURCE_FIELDS
from thesistrace.adapters.tushare_provider import TushareSourceError
from thesistrace.benchmark import (
    BENCHMARK_SOURCE_API_NAME,
    BENCHMARK_SOURCE_FIELDS,
    BENCHMARK_START_SESSION,
    BENCHMARK_TS_CODE,
)
from thesistrace.data.financial_disclosures import (
    FinancialDisclosure,
    FinancialDisclosureDiscovery,
    FinancialDiscoveryGap,
    disclosure_periods,
)
from thesistrace.data.source import RawSourceResponse

_REPLAY_MAX_BYTES = 128 * 1024 * 1024


class ReplayTushareProvider:
    def __init__(self, path: Path | str) -> None:
        flags = os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(Path(path), flags)
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode):
                raise ValueError("Tushare replay must be a regular file")
            if metadata.st_size > _REPLAY_MAX_BYTES:
                raise ValueError("Tushare replay exceeds its byte bound")
            content = bytearray()
            while chunk := os.read(
                descriptor,
                min(64 * 1024, _REPLAY_MAX_BYTES + 1 - len(content)),
            ):
                content.extend(chunk)
                if len(content) > _REPLAY_MAX_BYTES:
                    raise ValueError("Tushare replay exceeds its byte bound")
            if len(content) != metadata.st_size:
                raise ValueError("Tushare replay changed while reading")
        finally:
            os.close(descriptor)
        if len(content) > _REPLAY_MAX_BYTES:
            raise ValueError("Tushare replay exceeds its byte bound")
        value = json.loads(content)
        if not isinstance(value, dict):
            raise ValueError("Tushare replay contract is invalid")
        replay_format = value.get("format")
        product_replay = replay_format == "thesistrace-tushare-product-replay"
        bootstrap_replay = replay_format == "thesistrace-tushare-bootstrap-replay"
        refresh_replay = replay_format == "thesistrace-tushare-refresh-replay"
        if not (
            (product_replay and value.get("version") == 1)
            or (bootstrap_replay and value.get("version") == 2)
            or (refresh_replay and value.get("version") == 3)
        ):
            raise ValueError("Tushare replay contract is incompatible")
        expected_fields = {
            "format",
            "version",
            "request_start",
            "request_end",
            "snapshot",
        }
        if product_replay or refresh_replay:
            expected_fields.add("financial")
        if refresh_replay:
            expected_fields.add("financial_refresh")
        if set(value) != expected_fields:
            raise ValueError("Tushare replay contract is invalid")
        snapshot = value["snapshot"]
        if not isinstance(snapshot, dict) or any(
            not isinstance(key, str) or not isinstance(rows, list) for key, rows in snapshot.items()
        ):
            raise ValueError("Tushare replay snapshot is invalid")
        self._request_start = date.fromisoformat(str(value["request_start"]))
        self._request_end = date.fromisoformat(str(value["request_end"]))
        self._snapshot = snapshot
        self._daily_basic_index: dict[tuple[str, str | None], list[dict[str, object]]] | None = None
        self._financial = _financial_responses(value.get("financial", {}))
        self._financial_refresh = _financial_refresh(value.get("financial_refresh"))
        self._kind = (
            "bootstrap"
            if replay_format
            in {
                "thesistrace-tushare-bootstrap-replay",
                "thesistrace-tushare-product-replay",
            }
            else "refresh"
        )

    def collect_bootstrap_snapshot(
        self,
        *,
        start_date: date,
        completed_through_date: date,
    ) -> dict[str, list[dict[str, object]]]:
        if self._kind != "bootstrap":
            raise TushareSourceError("REPLAY_REFRESH_ONLY", source_code=0)
        if (start_date, completed_through_date) != (
            self._request_start,
            self._request_end,
        ):
            raise TushareSourceError("REPLAY_WINDOW_MISMATCH", source_code=0)
        return _market_snapshot(self._snapshot)

    def select_market_window(self, *, last_session: str, as_of: date) -> None:
        if self._kind != "refresh":
            raise TushareSourceError("REPLAY_BOOTSTRAP_ONLY", source_code=0)
        if (date.fromisoformat(last_session), as_of) != (self._request_start, self._request_end):
            raise TushareSourceError("REPLAY_WINDOW_MISMATCH", source_code=0)

    def collect_incremental_snapshot(
        self,
        *,
        last_session: str,
        as_of: date,
    ) -> dict[str, list[dict[str, object]]]:
        if self._kind != "refresh":
            raise TushareSourceError("REPLAY_BOOTSTRAP_ONLY", source_code=0)
        try:
            request_start = date.fromisoformat(last_session)
        except ValueError as error:
            raise TushareSourceError("REPLAY_WINDOW_MISMATCH", source_code=0) from error
        if (request_start, as_of) != (self._request_start, self._request_end):
            raise TushareSourceError("REPLAY_WINDOW_MISMATCH", source_code=0)
        return _market_snapshot(self._snapshot)

    def query_raw(
        self,
        api_name: str,
        *,
        params: Mapping[str, object],
        fields: Sequence[str],
    ) -> RawSourceResponse:
        if api_name == BENCHMARK_SOURCE_API_NAME:
            return self._query_benchmark(params=params, fields=fields)
        if api_name == "daily_basic":
            return self._query_daily_basic(params=params, fields=fields)
        if api_name == "fina_indicator":
            return self._query_indicator(params=params, fields=fields)
        if api_name == "disclosure_date":
            return self._query_disclosures(params=params, fields=fields)
        ts_code = params.get("ts_code")
        if not isinstance(ts_code, str) or set(params) != {"ts_code"}:
            raise TushareSourceError("REPLAY_REQUEST_MISMATCH", source_code=0)
        response = self._financial.get((api_name, ts_code))
        if response is None or not set(fields) <= set(response.fields):
            raise TushareSourceError("REPLAY_REQUEST_MISMATCH", source_code=0)
        return response

    def _query_indicator(
        self,
        *,
        params: Mapping[str, object],
        fields: Sequence[str],
    ) -> RawSourceResponse:
        try:
            if set(params) != {"ts_code", "start_date", "end_date"}:
                raise ValueError("Invalid indicator request")
            if any(not isinstance(value, str) for value in params.values()):
                raise ValueError("Invalid indicator request values")
            start = date.fromisoformat(_compact_date(params["start_date"]))
            end = date.fromisoformat(_compact_date(params["end_date"]))
            if start > end or end > self._request_end:
                raise ValueError("Unrecorded indicator period")
            response = self._financial.get(("fina_indicator", params["ts_code"]))
            if (
                response is None
                or not fields
                or len(set(fields)) != len(fields)
                or not set(fields) <= set(response.fields)
            ):
                raise ValueError("Unrecorded indicator response")
            identity_index = response.fields.index("ts_code")
            period_index = response.fields.index("end_date")
            selected = []
            for row in response.items:
                if row[identity_index] != params["ts_code"]:
                    raise ValueError("Indicator response identity mismatch")
                period = row[period_index]
                if not isinstance(period, str):
                    raise ValueError("Invalid indicator report date")
                report_date = date.fromisoformat(_compact_date(period))
                if start <= report_date <= end:
                    selected.append(row)
            return RawSourceResponse(fields=response.fields, items=tuple(selected[:100]))
        except (KeyError, TypeError, ValueError) as error:
            raise TushareSourceError("REPLAY_REQUEST_MISMATCH", source_code=0) from error

    def _query_daily_basic(
        self,
        *,
        params: Mapping[str, object],
        fields: Sequence[str],
    ) -> RawSourceResponse:
        try:
            if set(params) not in ({"trade_date"}, {"trade_date", "ts_code"}):
                raise ValueError("Invalid daily basic request")
            trade_date = params["trade_date"]
            if not isinstance(trade_date, str):
                raise ValueError("Invalid daily basic date")
            session = date.fromisoformat(_compact_date(trade_date))
            if not self._request_start <= session <= self._request_end:
                raise ValueError("Unrecorded daily basic date")
            if "ts_code" in params and (
                not isinstance(params["ts_code"], str) or not params["ts_code"]
            ):
                raise ValueError("Invalid daily basic security")
            if (
                not fields
                or len(set(fields)) != len(fields)
                or not set(fields) <= set(DAILY_BASIC_SOURCE_FIELDS)
            ):
                raise ValueError("Invalid daily basic columns")
            if self._daily_basic_index is None:
                index: dict[tuple[str, str | None], list[dict[str, object]]] = {}
                for row in self._snapshot["daily_basic"]:
                    if not isinstance(row, dict) or not set(DAILY_BASIC_SOURCE_FIELDS) <= set(row):
                        raise ValueError("Incomplete daily basic recording")
                    recorded_date, code = row["trade_date"], row["ts_code"]
                    if not isinstance(recorded_date, str) or not isinstance(code, str) or not code:
                        raise ValueError("Invalid daily basic recording identity")
                    recorded_session = date.fromisoformat(_compact_date(recorded_date))
                    if not self._request_start <= recorded_session <= self._request_end:
                        raise ValueError("Daily basic recording outside its window")
                    index.setdefault((recorded_date, None), []).append(row)
                    index.setdefault((recorded_date, code), []).append(row)
                self._daily_basic_index = index
            code = str(params["ts_code"]) if "ts_code" in params else None
            rows = self._daily_basic_index.get((trade_date, code), [])
            # Reproduce the supplier cap so Replay exercises the collector's split path.
            return RawSourceResponse(
                fields=tuple(fields),
                items=tuple(tuple(row[field] for field in fields) for row in rows[:6000]),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise TushareSourceError("REPLAY_REQUEST_MISMATCH", source_code=0) from error

    def discover(self, *, start_date, end_date, allowed_ts_codes):
        from thesistrace.adapters.tushare_disclosures import TushareDisclosureSource

        replay = self._financial_refresh
        if replay is None or (replay.start_date, replay.end_date) != (start_date, end_date):
            raise TushareSourceError("REPLAY_REQUEST_MISMATCH", source_code=0)
        return TushareDisclosureSource(self).discover(
            start_date=start_date,
            end_date=end_date,
            allowed_ts_codes=allowed_ts_codes,
        )

    def _query_disclosures(self, *, params, fields):
        from thesistrace.adapters.tushare_disclosures import DISCLOSURE_FIELDS

        replay = self._financial_refresh
        if replay is None or set(params) != {"end_date"} or tuple(fields) != DISCLOSURE_FIELDS:
            raise TushareSourceError("REPLAY_REQUEST_MISMATCH", source_code=0)
        period = _compact_date(str(params["end_date"]))
        for gap in replay.gaps:
            if gap.report_period == period:
                raise TushareSourceError(gap.failure_code, source_code=0)
        if period not in replay.completed_periods:
            raise TushareSourceError("REPLAY_REQUEST_MISMATCH", source_code=0)
        return RawSourceResponse(
            tuple(fields),
            tuple(
                (
                    report.ts_code,
                    report.actual_date.replace("-", ""),
                    report.report_period.replace("-", ""),
                    None,
                    report.actual_date.replace("-", ""),
                    None,
                )
                for report in replay.reports
                if report.report_period == period
            ),
        )

    def _query_benchmark(
        self,
        *,
        params: Mapping[str, object],
        fields: Sequence[str],
    ) -> RawSourceResponse:
        if set(params) != {"ts_code", "start_date", "end_date", "limit", "offset"}:
            raise TushareSourceError("REPLAY_REQUEST_MISMATCH", source_code=0)
        try:
            start = date.fromisoformat(_compact_date(str(params["start_date"])))
            end = date.fromisoformat(_compact_date(str(params["end_date"])))
            limit = int(params["limit"])
            offset = int(params["offset"])
        except (TypeError, ValueError) as error:
            raise TushareSourceError("REPLAY_REQUEST_MISMATCH", source_code=0) from error
        if (
            params["ts_code"] != BENCHMARK_TS_CODE
            or start < date.fromisoformat(BENCHMARK_START_SESSION)
            or end > self._request_end
            or start > end
            or limit <= 0
            or offset < 0
            or tuple(fields) != BENCHMARK_SOURCE_FIELDS
        ):
            raise TushareSourceError("REPLAY_REQUEST_MISMATCH", source_code=0)
        raw_rows = self._snapshot.get("benchmark_index_daily")
        if not isinstance(raw_rows, list):
            raise TushareSourceError("REPLAY_REQUEST_MISMATCH", source_code=0)
        selected: list[tuple[object, ...]] = []
        for row in raw_rows:
            if not isinstance(row, dict) or not set(fields) <= set(row):
                raise TushareSourceError("REPLAY_REQUEST_MISMATCH", source_code=0)
            trade_date = str(row["trade_date"])
            if str(params["start_date"]) <= trade_date <= str(params["end_date"]):
                selected.append(tuple(row[field] for field in fields))
        return RawSourceResponse(
            fields=tuple(fields),
            items=tuple(selected[offset : offset + limit]),
        )

    def query_paginated(
        self,
        api_name: str,
        *,
        params: Mapping[str, object],
        fields: Sequence[str],
        primary_key: Sequence[str],
    ) -> list[dict[str, object]]:
        del primary_key
        if api_name == "index_classify" and params == {"src": "SW2021"}:
            rows = self._snapshot.get("industry_classification", [])
        elif api_name == "index_member_all" and params in ({"is_new": "Y"}, {"is_new": "N"}):
            rows = [row for row in self._snapshot.get("industry_membership", [])
                    if row["is_new"] == params["is_new"]]
        else:
            raise TushareSourceError("REPLAY_REQUEST_MISMATCH", source_code=0)
        if any(not isinstance(row, dict) or not set(fields) <= set(row) for row in rows):
            raise TushareSourceError("REPLAY_REQUEST_MISMATCH", source_code=0)
        return [{field: row[field] for field in fields} for row in rows]


class ReplayTushareRefreshBundle:
    """Select one exact replay window for each operation claimed by a single Worker."""

    def __init__(self, paths: Sequence[Path | str]) -> None:
        if not paths:
            raise ValueError("Tushare refresh replay bundle is empty")
        self._providers: dict[tuple[date, date], ReplayTushareProvider] = {}
        self._financial_providers: dict[tuple[date, date], ReplayTushareProvider] = {}
        self._industry_providers: dict[date, ReplayTushareProvider] = {}
        self._active: ReplayTushareProvider | None = None
        for path in paths:
            provider = ReplayTushareProvider(path)
            if provider._kind != "refresh":
                raise ValueError("Tushare refresh replay bundle contains a non-refresh replay")
            window = (provider._request_start, provider._request_end)
            if window in self._providers:
                raise ValueError("Tushare refresh replay bundle contains a duplicate window")
            self._providers[window] = provider
            financial_refresh = provider._financial_refresh
            if financial_refresh is not None:
                financial_window = (
                    date.fromisoformat(financial_refresh.start_date),
                    date.fromisoformat(financial_refresh.end_date),
                )
                if financial_window in self._financial_providers:
                    raise ValueError(
                        "Tushare refresh replay bundle contains a duplicate Financial window"
                    )
                self._financial_providers[financial_window] = provider
            if provider._snapshot.get("industry_classification") and provider._snapshot.get(
                "industry_membership"
            ):
                industry_target = provider._request_end
                if industry_target in self._industry_providers:
                    raise ValueError(
                        "Tushare refresh replay bundle contains a duplicate Industry target"
                    )
                self._industry_providers[industry_target] = provider

    def collect_bootstrap_snapshot(
        self,
        *,
        start_date: date,
        completed_through_date: date,
    ) -> dict[str, list[dict[str, object]]]:
        del start_date, completed_through_date
        raise TushareSourceError("REPLAY_REFRESH_ONLY", source_code=0)

    def select_market_window(self, *, last_session: str, as_of: date) -> None:
        provider = self._providers.get((date.fromisoformat(last_session), as_of))
        if provider is None:
            raise TushareSourceError("REPLAY_WINDOW_MISMATCH", source_code=0)
        provider.select_market_window(last_session=last_session, as_of=as_of)
        self._active = provider

    def collect_incremental_snapshot(
        self,
        *,
        last_session: str,
        as_of: date,
    ) -> dict[str, list[dict[str, object]]]:
        try:
            request_start = date.fromisoformat(last_session)
        except ValueError as error:
            raise TushareSourceError("REPLAY_WINDOW_MISMATCH", source_code=0) from error
        provider = self._providers.get((request_start, as_of))
        if provider is None:
            raise TushareSourceError("REPLAY_WINDOW_MISMATCH", source_code=0)
        snapshot = provider.collect_incremental_snapshot(
            last_session=last_session,
            as_of=as_of,
        )
        self._active = provider
        return snapshot

    def query_raw(
        self,
        api_name: str,
        *,
        params: Mapping[str, object],
        fields: Sequence[str],
    ) -> RawSourceResponse:
        return self._selected().query_raw(api_name, params=params, fields=fields)

    def discover(self, *, start_date, end_date, allowed_ts_codes):
        self.select_financial_window(start_date, end_date)
        return self._selected().discover(
            start_date=start_date, end_date=end_date, allowed_ts_codes=allowed_ts_codes
        )

    def select_financial_window(self, start_date: str, end_date: str) -> None:
        """Select the exact persisted Financial discovery window before resuming."""
        self._active = self._select_financial_provider(start_date, end_date)

    def select_industry_target(self, observation_through_session: str) -> None:
        """Select the exact replay carrying one Industry observation target."""
        try:
            target = date.fromisoformat(observation_through_session)
        except ValueError as error:
            raise TushareSourceError("REPLAY_REQUEST_MISMATCH", source_code=0) from error
        provider = self._industry_providers.get(target)
        if provider is None:
            raise TushareSourceError("REPLAY_REQUEST_MISMATCH", source_code=0)
        self._active = provider

    def _select_financial_provider(
        self,
        start_date: str,
        end_date: str,
    ) -> ReplayTushareProvider:
        try:
            window = (date.fromisoformat(start_date), date.fromisoformat(end_date))
        except ValueError as error:
            raise TushareSourceError("REPLAY_REQUEST_MISMATCH", source_code=0) from error
        provider = self._financial_providers.get(window)
        if provider is None:
            raise TushareSourceError("REPLAY_REQUEST_MISMATCH", source_code=0)
        return provider

    def query_paginated(
        self,
        api_name: str,
        *,
        params: Mapping[str, object],
        fields: Sequence[str],
        primary_key: Sequence[str],
    ) -> list[dict[str, object]]:
        return self._selected().query_paginated(
            api_name,
            params=params,
            fields=fields,
            primary_key=primary_key,
        )

    def _selected(self) -> ReplayTushareProvider:
        if self._active is None:
            raise TushareSourceError("REPLAY_WINDOW_NOT_SELECTED", source_code=0)
        return self._active


def _financial_responses(value: object) -> dict[tuple[str, str], RawSourceResponse]:
    if not isinstance(value, dict):
        raise ValueError("Tushare replay financial contract is invalid")
    responses: dict[tuple[str, str], RawSourceResponse] = {}
    for endpoint, instruments in value.items():
        if not isinstance(endpoint, str) or not isinstance(instruments, dict):
            raise ValueError("Tushare replay financial contract is invalid")
        for ts_code, descriptor in instruments.items():
            if (
                not isinstance(ts_code, str)
                or not isinstance(descriptor, dict)
                or set(descriptor) != {"fields", "items"}
            ):
                raise ValueError("Tushare replay financial contract is invalid")
            fields = descriptor["fields"]
            items = descriptor["items"]
            if (
                not isinstance(fields, list)
                or not fields
                or any(not isinstance(field, str) for field in fields)
                or len(set(fields)) != len(fields)
                or not isinstance(items, list)
                or any(not isinstance(row, list) or len(row) != len(fields) for row in items)
            ):
                raise ValueError("Tushare replay financial contract is invalid")
            responses[(endpoint, ts_code)] = RawSourceResponse(
                fields=tuple(fields),
                items=tuple(tuple(row) for row in items),
            )
    return responses


def _financial_refresh(value: object) -> FinancialDisclosureDiscovery | None:
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {
        "request_start",
        "request_end",
        "completed_periods",
        "reports",
        "gaps",
        "source_lineage_sha256",
    }:
        raise ValueError("Tushare replay Financial Refresh contract is invalid")
    start = date.fromisoformat(str(value["request_start"])).isoformat()
    end = date.fromisoformat(str(value["request_end"])).isoformat()
    completed = tuple(value["completed_periods"])
    reports = tuple(FinancialDisclosure(**report) for report in value["reports"])
    gaps = tuple(FinancialDiscoveryGap(**gap) for gap in value["gaps"])
    expected = set(disclosure_periods(start, end))
    missing = {gap.report_period for gap in gaps}
    if (
        set(completed) & missing
        or set(completed) | missing != expected
        or len(completed) != len(set(completed))
        or any(
            report.report_period not in completed
            or not report.ts_code
            or not report.report_period <= report.actual_date <= end
            for report in reports
        )
    ):
        raise ValueError("Tushare replay Financial Refresh contract is invalid")
    return FinancialDisclosureDiscovery(
        start, end, completed, reports, gaps, str(value["source_lineage_sha256"])
    )


def _compact_date(value: str) -> str:
    if len(value) != 8 or not value.isdigit():
        raise ValueError("compact date is invalid")
    return f"{value[:4]}-{value[4:6]}-{value[6:]}"


def _market_snapshot(
    snapshot: Mapping[str, list[dict[str, object]]],
) -> dict[str, list[dict[str, object]]]:
    return {
        name: rows
        for name, rows in snapshot.items()
        if name not in {"benchmark_index_daily", "daily_basic"}
    }


__all__ = ("ReplayTushareProvider", "ReplayTushareRefreshBundle")
