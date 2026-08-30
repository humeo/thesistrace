from __future__ import annotations

import json
import os
import stat
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path

from thesistrace.adapters.tushare_provider import TushareSourceError
from thesistrace.benchmark import (
    BENCHMARK_SOURCE_API_NAME,
    BENCHMARK_SOURCE_FIELDS,
    BENCHMARK_START_SESSION,
    BENCHMARK_TS_CODE,
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
        if not (
            (product_replay and value.get("version") == 1)
            or (
                replay_format
                in {
                    "thesistrace-tushare-bootstrap-replay",
                    "thesistrace-tushare-refresh-replay",
                }
                and value.get("version") == 2
            )
        ):
            raise ValueError("Tushare replay contract is incompatible")
        expected_fields = {
            "format",
            "version",
            "request_start",
            "request_end",
            "snapshot",
        }
        if product_replay:
            expected_fields.add("financial")
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
        self._financial = _financial_responses(value.get("financial", {}))
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
        ts_code = params.get("ts_code")
        if not isinstance(ts_code, str) or set(params) != {"ts_code"}:
            raise TushareSourceError("REPLAY_REQUEST_MISMATCH", source_code=0)
        response = self._financial.get((api_name, ts_code))
        if response is None or not set(fields) <= set(response.fields):
            raise TushareSourceError("REPLAY_REQUEST_MISMATCH", source_code=0)
        return response

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
        elif api_name == "index_member_all" and not params:
            rows = self._snapshot.get("industry_membership", [])
        else:
            raise TushareSourceError("REPLAY_REQUEST_MISMATCH", source_code=0)
        if any(
            not isinstance(row, dict) or not set(fields) <= set(row)
            for row in rows
        ):
            raise TushareSourceError("REPLAY_REQUEST_MISMATCH", source_code=0)
        return [{field: row[field] for field in fields} for row in rows]


class ReplayTushareRefreshBundle:
    """Select one exact replay window for each operation claimed by a single Worker."""

    def __init__(self, paths: Sequence[Path | str]) -> None:
        if not paths:
            raise ValueError("Tushare refresh replay bundle is empty")
        self._providers: dict[tuple[date, date], ReplayTushareProvider] = {}
        self._active: ReplayTushareProvider | None = None
        for path in paths:
            provider = ReplayTushareProvider(path)
            if provider._kind != "refresh":
                raise ValueError("Tushare refresh replay bundle contains a non-refresh replay")
            window = (provider._request_start, provider._request_end)
            if window in self._providers:
                raise ValueError("Tushare refresh replay bundle contains a duplicate window")
            self._providers[window] = provider

    def collect_bootstrap_snapshot(
        self,
        *,
        start_date: date,
        completed_through_date: date,
    ) -> dict[str, list[dict[str, object]]]:
        del start_date, completed_through_date
        raise TushareSourceError("REPLAY_REFRESH_ONLY", source_code=0)

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
        if name != "benchmark_index_daily"
    }


__all__ = ("ReplayTushareProvider",)
