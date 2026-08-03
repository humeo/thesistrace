from __future__ import annotations

import copy
from collections.abc import Callable, Mapping
from datetime import date
from typing import Protocol

from thesistrace.data import CanonicalSourceBatch, CollectionPlan, DataSourceError
from thesistrace.tushare_source import (
    SOURCE_CONTRACT_VERSION,
    TushareSourceError,
    normalize_tushare_increment,
    normalize_tushare_snapshot,
)


class TushareProvider(Protocol):
    def collect_bootstrap_snapshot(
        self,
        as_of: date,
    ) -> dict[str, list[dict[str, object]]]: ...

    def collect_incremental_snapshot(
        self,
        *,
        last_session: str,
        known_ts_codes: set[str],
        as_of: date,
    ) -> dict[str, list[dict[str, object]]]: ...


class TushareDataSource:
    def __init__(
        self,
        *,
        provider: TushareProvider,
        clock: Callable[[], date] = date.today,
    ) -> None:
        self._provider = provider
        self._clock = clock

    def collect(self, plan: CollectionPlan) -> CanonicalSourceBatch:
        try:
            if plan.kind == "bootstrap":
                snapshot = self._provider.collect_bootstrap_snapshot(self._clock())
                lineage, canonical = normalize_tushare_snapshot(snapshot)
            else:
                previous = plan.previous_canonical
                if previous is None or plan.after_session is None:
                    raise DataSourceError(
                        "invalid_source_data",
                        detail_code="PREVIOUS_CANONICAL_REQUIRED",
                    )
                instruments = previous.get("instruments")
                if not isinstance(instruments, list):
                    raise DataSourceError(
                        "invalid_source_data",
                        detail_code="INVALID_PREVIOUS_CANONICAL",
                    )
                known_codes = {
                    str(item["ts_code"])
                    for item in instruments
                    if isinstance(item, dict) and "ts_code" in item
                }
                snapshot = self._provider.collect_incremental_snapshot(
                    last_session=plan.after_session,
                    known_ts_codes=known_codes,
                    as_of=self._clock(),
                )
                try:
                    lineage, delta = normalize_tushare_increment(snapshot, previous)
                except TushareSourceError as error:
                    if error.reason_code != "NO_NEW_RESEARCH_SESSION":
                        raise
                    lineage = {
                        "source": "tushare",
                        "source_contract_version": SOURCE_CONTRACT_VERSION,
                        "responses": {
                            key: value for key, value in sorted(snapshot.items())
                        },
                        "no_change": True,
                    }
                    canonical = copy.deepcopy(dict(previous))
                else:
                    canonical = _materialize_increment(previous, delta)
        except TushareSourceError as error:
            raise DataSourceError(
                _error_category(error.reason_code),
                detail_code=error.reason_code,
            ) from error
        except (KeyError, IndexError, TypeError, ValueError) as error:
            raise DataSourceError(
                "invalid_source_data",
                detail_code="MALFORMED_PROVIDER_PAYLOAD",
            ) from error

        calendar = canonical.get("research_calendar")
        if not isinstance(calendar, list) or not calendar:
            raise DataSourceError(
                "invalid_source_data",
                detail_code="MISSING_RESEARCH_CALENDAR",
            )
        return CanonicalSourceBatch(
            source_name="tushare",
            collection_kind=plan.kind,
            source_lineage=lineage,
            canonical=canonical,
            covered_session_range=(str(calendar[0]), str(calendar[-1])),
        )


def _error_category(reason_code: str) -> str:
    if reason_code in {"TOKEN_MISSING", "MISSING_PERMISSION"}:
        return "authorization"
    if reason_code == "UPSTREAM_UNAVAILABLE":
        return "unavailable"
    return "invalid_source_data"


def _materialize_increment(
    previous: Mapping[str, object],
    delta: Mapping[str, object],
) -> dict[str, object]:
    canonical = copy.deepcopy(dict(previous))
    append_fields = {
        "research_calendar_append": "research_calendar",
        "prices_append": "prices",
        "trading_states_append": "trading_states",
        "price_limits_append": "price_limits",
        "base_pool_append": "base_pool",
        "adjustment_anchors_append": "adjustment_anchors",
        "st_designations_append": "st_designations",
    }
    for delta_name, canonical_name in append_fields.items():
        appended = delta.get(delta_name, [])
        current = canonical.get(canonical_name)
        if current is None and canonical_name == "st_designations":
            canonical[canonical_name] = []
            current = canonical[canonical_name]
        if not isinstance(appended, list) or not isinstance(current, list):
            raise DataSourceError(
                "invalid_source_data",
                detail_code="INVALID_CANONICAL_INCREMENT",
            )
        current.extend(copy.deepcopy(appended))

    replacement_fields = {
        "instruments_replace": "instruments",
        "industry_membership_replace": "industry_membership",
    }
    for delta_name, canonical_name in replacement_fields.items():
        replacement = delta.get(delta_name)
        if not isinstance(replacement, list):
            raise DataSourceError(
                "invalid_source_data",
                detail_code="INVALID_CANONICAL_INCREMENT",
            )
        canonical[canonical_name] = copy.deepcopy(replacement)

    universes = canonical.get("liquidity_universes")
    appended_universes = delta.get("liquidity_universes_append", {})
    replacement_universes = delta.get("liquidity_universes_replace", {})
    if not all(
        isinstance(value, dict)
        for value in (universes, appended_universes, replacement_universes)
    ):
        raise DataSourceError(
            "invalid_source_data",
            detail_code="INVALID_CANONICAL_INCREMENT",
        )
    assert isinstance(universes, dict)
    assert isinstance(appended_universes, dict)
    assert isinstance(replacement_universes, dict)
    for name, rows in appended_universes.items():
        current = universes.get(name)
        if not isinstance(current, list) or not isinstance(rows, list):
            raise DataSourceError(
                "invalid_source_data",
                detail_code="INVALID_CANONICAL_INCREMENT",
            )
        current.extend(copy.deepcopy(rows))
    for name, rows in replacement_universes.items():
        current = universes.get(name)
        if not isinstance(current, list) or not isinstance(rows, list):
            raise DataSourceError(
                "invalid_source_data",
                detail_code="INVALID_CANONICAL_INCREMENT",
            )
        replacement_by_session = {
            str(row["session"]): copy.deepcopy(row)
            for row in rows
            if isinstance(row, dict) and "session" in row
        }
        current[:] = [
            replacement_by_session.get(str(row.get("session")), row)
            if isinstance(row, dict)
            else row
            for row in current
        ]

    corrections = delta.get("price_corrections", [])
    prices = canonical.get("prices")
    if not isinstance(corrections, list) or not isinstance(prices, list):
        raise DataSourceError(
            "invalid_source_data",
            detail_code="INVALID_CANONICAL_INCREMENT",
        )
    price_by_position = {
        (str(row["session"]), str(row["instrument_id"])): row
        for row in prices
        if isinstance(row, dict)
        and "session" in row
        and "instrument_id" in row
    }
    for correction in corrections:
        if not isinstance(correction, dict):
            raise DataSourceError(
                "invalid_source_data",
                detail_code="INVALID_CANONICAL_INCREMENT",
            )
        required = {"session", "instrument_id", "field", "value"}
        if not required <= correction.keys():
            raise DataSourceError(
                "invalid_source_data",
                detail_code="INVALID_CANONICAL_INCREMENT",
            )
        position = (
            str(correction["session"]),
            str(correction["instrument_id"]),
        )
        target = price_by_position.get(position)
        if target is None:
            raise DataSourceError(
                "invalid_source_data",
                detail_code="INVALID_CANONICAL_INCREMENT",
            )
        target[str(correction["field"])] = str(correction["value"])
    return canonical
