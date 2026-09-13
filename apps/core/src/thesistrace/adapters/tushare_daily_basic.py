"""Bounded daily_basic collection without assuming unsupported pagination."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Protocol

from thesistrace.adapters.tushare_provider import (
    TushareSourceError,
    tushare_source_error_category,
)
from thesistrace.data.daily_basic_evidence import DailyBasicCheckpoint
from thesistrace.data.source import DataSourceError, RawSourceResponse

DAILY_BASIC_SOURCE_FIELDS = (
    "ts_code", "trade_date", "close", "turnover_rate", "turnover_rate_f",
    "volume_ratio", "pe", "pe_ttm", "pb", "ps", "ps_ttm", "dv_ratio", "dv_ttm",
    "total_share", "float_share", "free_share", "total_mv", "circ_mv", "limit_status",
)
_DAILY_BASIC_ROW_LIMIT = 6000
# Effective source-code changes; the canonical Instrument Identity stays stable.
# Evidence: issue07-source-code-identity.md in the field-expansion qualification.
_SECURITY_CODE_CHANGES = (
    ("000022.SZ", "001872.SZ", "2018-12-26"),
    ("000043.SZ", "001914.SZ", "2019-12-16"),
    ("300114.SZ", "302132.SZ", "2025-02-17"),
)


class RawDailyBasicProvider(Protocol):
    def query_raw(
        self, api_name: str, *, params: Mapping[str, object], fields: Sequence[str],
    ) -> RawSourceResponse: ...


class TushareDailyBasicSource:
    def __init__(self, provider: RawDailyBasicProvider) -> None:
        self._provider = provider

    def collect_session(
        self, *, session: str, instrument_codes: Sequence[str],
        checkpoint: DailyBasicCheckpoint | None = None,
    ) -> RawSourceResponse:
        """Collect one day for a complete historical security identity set.

        A response reaching the supplier cap is ambiguous. Re-query each known
        security for that exact day; neither offset nor an enlarged limit is used.
        Null columns and absent security rows remain source evidence, not zeros.
        """
        trade_date = date.fromisoformat(session).strftime("%Y%m%d")
        codes = frozenset(instrument_codes)
        if not codes or len(codes) != len(instrument_codes):
            raise ValueError("Daily basic collection requires unique historical identities")
        try:
            raw = self._query({"trade_date": trade_date}, trade_date, codes, checkpoint)
            if len(raw.items) < _DAILY_BASIC_ROW_LIMIT:
                if checkpoint is not None:
                    checkpoint.mark_session_collected(session)
                code_index = DAILY_BASIC_SOURCE_FIELDS.index("ts_code")
                return RawSourceResponse(raw.fields, tuple(
                    item for item in raw.items if item[code_index] in codes
                ))
            items: list[tuple[object, ...]] = []
            code_index = DAILY_BASIC_SOURCE_FIELDS.index("ts_code")
            observed_codes = {row[code_index] for row in raw.items}
            for code in sorted(codes):
                shard = self._query(
                    {"trade_date": trade_date, "ts_code": code}, trade_date, frozenset((code,)),
                    checkpoint, require_row=code in observed_codes,
                )
                items.extend(shard.items)
            if checkpoint is not None:
                checkpoint.mark_session_collected(session)
            return RawSourceResponse(fields=DAILY_BASIC_SOURCE_FIELDS, items=tuple(items))
        except TushareSourceError as error:
            raise DataSourceError(
                tushare_source_error_category(error.reason_code), detail_code=error.reason_code,
            ) from error
        except (KeyError, TypeError, ValueError) as error:
            raise DataSourceError(
                "invalid_source_data", detail_code="MALFORMED_DAILY_BASIC_PAYLOAD",
            ) from error

    def _query(
        self, params: Mapping[str, object], trade_date: str, codes: frozenset[str],
        checkpoint: DailyBasicCheckpoint | None,
        *, require_row: bool = False,
    ) -> RawSourceResponse:
        request = {
            "api_name": "daily_basic", "params": dict(params),
            "fields": list(DAILY_BASIC_SOURCE_FIELDS), "instrument_codes": sorted(codes),
        }
        cached = checkpoint.load(request) if checkpoint is not None else None
        raw = cached if cached is not None else self._provider.query_raw(
            "daily_basic", params=params, fields=DAILY_BASIC_SOURCE_FIELDS,
        )
        if (
            len(set(raw.fields)) != len(raw.fields)
            or not set(DAILY_BASIC_SOURCE_FIELDS) <= set(raw.fields)
            or any(len(item) != len(raw.fields) for item in raw.items)
        ):
            raise ValueError("Daily basic source columns are incomplete or duplicated")
        items: list[tuple[object, ...]] = []
        seen: set[str] = set()
        observed_codes = {item[raw.fields.index("ts_code")] for item in raw.items}
        # Whole-day responses can include both retired and current codes, with
        # differing backfilled ratios. The current identity's own source row is
        # authoritative; retain both raw rows, never merge their numeric values.
        retired_duplicates = {
            old for old, current, since in _SECURITY_CODE_CHANGES
            if "ts_code" not in params and trade_date < since.replace("-", "")
            and current in codes and current in observed_codes
        }
        # The canonical market universe is SSE/SZSE; whole-day source payloads
        # also contain Beijing/NEEQ history. Keep those raw rows for audit, but
        # never use them to broaden the requested identity set or hide a cap.
        outside_market = {
            code for code in observed_codes
            if "ts_code" not in params and isinstance(code, str)
            and len(code) == 9 and code.endswith(".BJ") and code[:6].isdigit()
        }
        allowed_codes = codes | retired_duplicates | outside_market
        for item in raw.items:
            row = dict(zip(raw.fields, item, strict=True))
            code = row["ts_code"]
            if (
                code not in allowed_codes or code in seen
                or row["trade_date"] != trade_date
            ):
                raise ValueError("Daily basic identity or session is invalid or duplicated")
            seen.add(code)
            items.append(tuple(row[field] for field in DAILY_BASIC_SOURCE_FIELDS))
        if require_row and not items:
            raise DataSourceError(
                "invalid_source_data", detail_code="DAILY_BASIC_SPLIT_INCOMPLETE",
            )
        if checkpoint is not None and cached is None:
            checkpoint.save(request, raw)
        return RawSourceResponse(fields=DAILY_BASIC_SOURCE_FIELDS, items=tuple(items))


# TuShare daily_basic: amounts in 10,000 CNY, equity in 10,000 shares,
# turnover/dividend yields in percent. See the recorded source qualification.
DAILY_BASIC_MULTIPLIERS = {
    "turnover_rate": Decimal("0.01"),
    "turnover_rate_f": Decimal("0.01"),
    "volume_ratio": Decimal(1),
    "pe": Decimal(1),
    "pe_ttm": Decimal(1),
    "pb": Decimal(1),
    "ps": Decimal(1),
    "ps_ttm": Decimal(1),
    "dv_ratio": Decimal("0.01"),
    "dv_ttm": Decimal("0.01"),
    "total_share": Decimal(10000),
    "float_share": Decimal(10000),
    "free_share": Decimal(10000),
    "total_mv": Decimal(10000),
    "circ_mv": Decimal(10000),
}


def normalize_daily_basic(
    raw: RawSourceResponse, *, instrument_ids: Mapping[str, str],
) -> tuple[dict[str, object], ...]:
    """Normalize observed rows only; dates and missing values are never filled."""
    try:
        if len(set(raw.fields)) != len(raw.fields) or not set(
            DAILY_BASIC_SOURCE_FIELDS
        ) <= set(raw.fields):
            raise ValueError("Daily basic source columns are incomplete or duplicated")
        rows: list[dict[str, object]] = []
        seen: set[tuple[str, str]] = set()
        for item in raw.items:
            source = dict(zip(raw.fields, item, strict=True))
            session = datetime.strptime(str(source["trade_date"]), "%Y%m%d").date().isoformat()
            instrument_id = instrument_ids[str(source["ts_code"])]
            coordinate = (session, instrument_id)
            if coordinate in seen:
                raise ValueError("Daily basic coordinates are duplicated")
            seen.add(coordinate)
            rows.append({
                "instrument_id": instrument_id,
                "session": session,
                "source_close": _normalized_decimal(source["close"], Decimal(1)),
                **{name: _normalized_decimal(source[name], multiplier)
                   for name, multiplier in DAILY_BASIC_MULTIPLIERS.items()},
            })
        return tuple(sorted(rows, key=lambda row: (row["session"], row["instrument_id"])))
    except (KeyError, TypeError, ValueError, InvalidOperation) as error:
        raise DataSourceError(
            "invalid_source_data", detail_code="MALFORMED_DAILY_BASIC_VALUES",
        ) from error


def _normalized_decimal(value: object, multiplier: Decimal) -> str | None:
    if value is None:
        return None
    number = Decimal(str(value))
    if not number.is_finite():
        raise ValueError("Daily basic value must be finite")
    return format((number * multiplier).normalize(), "f")
