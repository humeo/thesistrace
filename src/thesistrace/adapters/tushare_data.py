from __future__ import annotations

import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from datetime import date, timedelta
from decimal import Decimal
from typing import Protocol

from thesistrace.adapters.tushare_provider import (
    SOURCE_CONTRACT_VERSION,
    TushareBootstrapArchive,
    TushareSessionNormalizer,
    TushareSourceError,
    normalize_industries,
    normalize_instruments,
    normalize_tushare_increment,
    normalize_tushare_snapshot,
)
from thesistrace.data.canonical_mapping import (
    SOURCE_CORRECTABLE_PRICE_FIELDS,
    field_catalog,
    liquidity_universes,
)
from thesistrace.data.generation_schema import GENERATION_SESSION_PARTITION_COUNT
from thesistrace.data.source import (
    BootstrapCollectionPlan,
    CanonicalBootstrapStream,
    CanonicalSessionPartition,
    CanonicalSourceBatch,
    CollectionPlan,
    DataSourceError,
)


class TushareProvider(Protocol):
    def collect_bootstrap_snapshot(
        self,
        *,
        start_date: date,
        completed_through_date: date,
    ) -> dict[str, list[dict[str, object]]] | TushareBootstrapArchive: ...

    def collect_incremental_snapshot(
        self,
        *,
        last_session: str,
        as_of: date,
    ) -> dict[str, list[dict[str, object]]]: ...


class TushareDataSource:
    def __init__(
        self,
        *,
        provider: TushareProvider,
        clock: Callable[[], date] = date.today,
        progress: Callable[[dict[str, object]], None] | None = None,
        monotonic: Callable[[], float] = time.perf_counter,
    ) -> None:
        self._provider = provider
        self._clock = clock
        self._progress = progress or (lambda _event: None)
        self._monotonic = monotonic

    @contextmanager
    def _timed_phase(self, phase: str) -> Iterator[None]:
        self._progress(
            {"event": "refresh_timing", "phase": phase, "status": "started"}
        )
        started_at = self._monotonic()
        try:
            yield
        except Exception:
            self._progress(
                {
                    "event": "refresh_timing",
                    "phase": phase,
                    "status": "failed",
                    "elapsed_seconds": round(self._monotonic() - started_at, 3),
                }
            )
            raise
        self._progress(
            {
                "event": "refresh_timing",
                "phase": phase,
                "status": "completed",
                "elapsed_seconds": round(self._monotonic() - started_at, 3),
            }
        )

    def collect(self, plan: CollectionPlan) -> CanonicalSourceBatch:
        try:
            if plan.kind not in {"incremental", "refresh"}:
                raise DataSourceError(
                    "invalid_source_data",
                    detail_code="REFRESH_OR_INCREMENTAL_PLAN_REQUIRED",
                )
            previous = plan.previous_canonical
            if previous is None or plan.after_session is None:
                raise DataSourceError(
                    "invalid_source_data",
                    detail_code="PREVIOUS_CANONICAL_REQUIRED",
                )
            request_start = (
                plan.overlap_start_session if plan.kind == "refresh" else plan.after_session
            )
            assert request_start is not None
            request_end = plan.completed_through_date or self._clock()
            with self._timed_phase("source_collection"):
                snapshot = self._provider.collect_incremental_snapshot(
                    last_session=request_start,
                    as_of=request_end,
                )
            with self._timed_phase("merge"):
                normalization_previous = previous
                if plan.kind == "refresh":
                    normalization_previous = _canonical_before_overlap(previous, request_start)
                    snapshot = _preserve_ordinary_overlap_absence(
                        snapshot,
                        previous,
                        overlap_start_session=request_start,
                    )
                    snapshot = _project_price_limits_to_stock_scope(snapshot)
                    assert plan.completed_through_date is not None
                    _validate_new_session_evidence(
                        snapshot,
                        plan.after_session,
                        completed_through_date=plan.completed_through_date,
                    )
                try:
                    lineage, delta = normalize_tushare_increment(snapshot, normalization_previous)
                except TushareSourceError as error:
                    if error.reason_code != "NO_NEW_RESEARCH_SESSION":
                        raise
                    lineage = {
                        "source": "tushare",
                        "source_contract_version": SOURCE_CONTRACT_VERSION,
                        "responses": {key: value for key, value in sorted(snapshot.items())},
                        "no_change": True,
                    }
                    canonical = dict(previous)
                else:
                    canonical = _materialize_increment(normalization_previous, delta)
                    if plan.kind == "refresh":
                        _remove_synthetic_predecessor(canonical, request_start)
                        _recompute_liquidity_universes(canonical)
                lineage = _compact_source_lineage(lineage)
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
        if (
            plan.kind == "refresh"
            and plan.completed_through_date is not None
            and str(calendar[-1]) > plan.completed_through_date.isoformat()
        ):
            raise DataSourceError(
                "invalid_source_data",
                detail_code="REFRESH_WINDOW_VIOLATION",
            )
        return CanonicalSourceBatch(
            source_name="tushare",
            collection_kind=plan.kind,
            source_lineage=lineage,
            canonical=canonical,
            covered_session_range=(str(calendar[0]), str(calendar[-1])),
        )

    def collect_bootstrap(
        self,
        plan: BootstrapCollectionPlan,
    ) -> CanonicalSourceBatch | CanonicalBootstrapStream:
        try:
            snapshot = self._provider.collect_bootstrap_snapshot(
                start_date=plan.start_date,
                completed_through_date=plan.completed_through_date,
            )
            if isinstance(snapshot, TushareBootstrapArchive):
                return _stream_bootstrap_archive(snapshot, plan)
            lineage, canonical = normalize_tushare_snapshot(snapshot)
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
        if str(calendar[0]) < plan.start_date.isoformat() or str(calendar[-1]) > (
            plan.completed_through_date.isoformat()
        ):
            raise DataSourceError(
                "invalid_source_data",
                detail_code="BOOTSTRAP_WINDOW_VIOLATION",
            )
        return CanonicalSourceBatch(
            source_name="tushare",
            collection_kind="bootstrap",
            source_lineage=lineage,
            canonical=canonical,
            covered_session_range=(str(calendar[0]), str(calendar[-1])),
        )


def _stream_bootstrap_archive(
    archive: TushareBootstrapArchive,
    plan: BootstrapCollectionPlan,
) -> CanonicalBootstrapStream:
    if (archive.request_start, archive.request_end) != (
        plan.start_date,
        plan.completed_through_date,
    ):
        raise DataSourceError(
            "invalid_source_data",
            detail_code="BOOTSTRAP_WINDOW_VIOLATION",
        )
    sse_open = {
        str(row["cal_date"])
        for row in archive.foundation["calendar_sse"]
        if str(row["is_open"]) == "1"
    }
    szse_open = {
        str(row["cal_date"])
        for row in archive.foundation["calendar_szse"]
        if str(row["is_open"]) == "1"
    }
    sessions = tuple(sorted(sse_open & szse_open))
    if sessions != archive.sessions or not sessions:
        raise DataSourceError(
            "invalid_source_data",
            detail_code="INCOMPLETE_EXCHANGE_CALENDARS",
        )
    iso_sessions = [
        f"{session[:4]}-{session[4:6]}-{session[6:]}" for session in sessions
    ]
    instruments = normalize_instruments(archive.foundation["stock_basic"])
    industries = normalize_industries(
        archive.industry_membership,
        allowed_codes={str(row["ts_code"]) for row in instruments},
    )
    static = {
        "schema_version": "canonical-eod",
        "research_calendar": iso_sessions,
        "instruments": instruments,
        "industry_membership": industries,
        "field_catalog": field_catalog(iso_sessions[-1]),
    }

    def partitions() -> Iterator[CanonicalSessionPartition]:
        normalizer = TushareSessionNormalizer(instruments)
        prior_sessions: list[str] = []
        prior_prices: list[dict[str, str]] = []
        prior_states: list[dict[str, str]] = []
        prior_base_pool: list[dict[str, object]] = []
        for start in range(0, len(sessions), GENERATION_SESSION_PARTITION_COUNT):
            session_keys = sessions[start : start + GENERATION_SESSION_PARTITION_COUNT]
            block_prices: list[dict[str, str]] = []
            block_states: list[dict[str, str]] = []
            block_limits: list[dict[str, str]] = []
            block_base_pool: list[dict[str, object]] = []
            for session_key in session_keys:
                try:
                    normalized = normalizer.normalize(
                        session_key,
                        archive.load_session(session_key),
                    )
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
                block_prices.extend(normalized["prices"])
                block_states.extend(normalized["trading_states"])
                block_limits.extend(normalized["price_limits"])
                block_base_pool.extend(normalized["base_pool"])
            block_iso_sessions = [
                f"{session[:4]}-{session[4:6]}-{session[6:]}" for session in session_keys
            ]
            combined_sessions = [*prior_sessions, *block_iso_sessions]
            combined_prices = [*prior_prices, *block_prices]
            combined_states = [*prior_states, *block_states]
            combined_base_pool = [*prior_base_pool, *block_base_pool]
            combined_universes = liquidity_universes(
                combined_sessions,
                combined_base_pool,
                combined_prices,
                combined_states,
            )
            selected = set(block_iso_sessions)
            block_universes = {
                name: [row for row in rows if str(row["session"]) in selected]
                for name, rows in combined_universes.items()
            }
            yield CanonicalSessionPartition(
                sessions=tuple(block_iso_sessions),
                canonical={
                    "prices": block_prices,
                    "trading_states": block_states,
                    "price_limits": block_limits,
                    "base_pool": block_base_pool,
                    "liquidity_universes": block_universes,
                },
            )
            retained = set(combined_sessions[-19:])
            prior_sessions = combined_sessions[-19:]
            prior_prices = [
                row for row in combined_prices if str(row["session"]) in retained
            ]
            prior_states = [
                row for row in combined_states if str(row["session"]) in retained
            ]
            prior_base_pool = [
                row for row in combined_base_pool if str(row["session"]) in retained
            ]

    return CanonicalBootstrapStream(
        source_name="tushare",
        source_lineage=archive.source_lineage,
        static=static,
        covered_session_range=(iso_sessions[0], iso_sessions[-1]),
        partitions=partitions,
    )


def _error_category(reason_code: str) -> str:
    if reason_code in {"TOKEN_MISSING", "MISSING_PERMISSION"}:
        return "authorization"
    if reason_code in {"UPSTREAM_UNAVAILABLE", "UPSTREAM_RATE_LIMITED"}:
        return "unavailable"
    return "invalid_source_data"


def _materialize_increment(
    previous: Mapping[str, object],
    delta: Mapping[str, object],
) -> dict[str, object]:
    canonical = dict(previous)
    append_fields = {
        "research_calendar_append": "research_calendar",
        "trading_states_append": "trading_states",
        "price_limits_append": "price_limits",
        "base_pool_append": "base_pool",
    }
    for delta_name, canonical_name in append_fields.items():
        appended = delta.get(delta_name, [])
        current = canonical.get(canonical_name)
        if not isinstance(appended, list) or not isinstance(current, list):
            raise DataSourceError(
                "invalid_source_data",
                detail_code="INVALID_CANONICAL_INCREMENT",
            )
        canonical[canonical_name] = [*current, *appended]

    replacement_fields = {
        "instruments_replace": "instruments",
        "prices_replace": "prices",
        "industry_membership_replace": "industry_membership",
    }
    for delta_name, canonical_name in replacement_fields.items():
        replacement = delta.get(delta_name)
        if not isinstance(replacement, list):
            raise DataSourceError(
                "invalid_source_data",
                detail_code="INVALID_CANONICAL_INCREMENT",
            )
        canonical[canonical_name] = list(replacement)

    universes = canonical.get("liquidity_universes")
    appended_universes = delta.get("liquidity_universes_append", {})
    replacement_universes = delta.get("liquidity_universes_replace", {})
    if not all(
        isinstance(value, dict) for value in (universes, appended_universes, replacement_universes)
    ):
        raise DataSourceError(
            "invalid_source_data",
            detail_code="INVALID_CANONICAL_INCREMENT",
        )
    assert isinstance(universes, dict)
    assert isinstance(appended_universes, dict)
    assert isinstance(replacement_universes, dict)
    universes = dict(universes)
    canonical["liquidity_universes"] = universes
    for name, rows in appended_universes.items():
        current = universes.get(name)
        if not isinstance(current, list) or not isinstance(rows, list):
            raise DataSourceError(
                "invalid_source_data",
                detail_code="INVALID_CANONICAL_INCREMENT",
            )
        universes[name] = [*current, *rows]
    for name, rows in replacement_universes.items():
        current = universes.get(name)
        if not isinstance(current, list) or not isinstance(rows, list):
            raise DataSourceError(
                "invalid_source_data",
                detail_code="INVALID_CANONICAL_INCREMENT",
            )
        replacement_by_session = {
            str(row["session"]): dict(row)
            for row in rows
            if isinstance(row, dict) and "session" in row
        }
        universes[name] = [
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
    if corrections:
        prices = [dict(row) if isinstance(row, dict) else row for row in prices]
        canonical["prices"] = prices
    price_by_position = {
        (str(row["session"]), str(row["instrument_id"])): row
        for row in prices
        if isinstance(row, dict) and "session" in row and "instrument_id" in row
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
        field = str(correction["field"])
        if field not in SOURCE_CORRECTABLE_PRICE_FIELDS:
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
        target[field] = str(correction["value"])
    return canonical


def _canonical_before_overlap(
    previous: Mapping[str, object],
    overlap_start_session: str,
) -> dict[str, object]:
    calendar = previous.get("research_calendar")
    if not isinstance(calendar, list):
        raise DataSourceError(
            "invalid_source_data",
            detail_code="INVALID_PREVIOUS_CANONICAL",
        )
    prefix_sessions = [str(value) for value in calendar if str(value) < overlap_start_session]
    if not prefix_sessions:
        cursor = date.fromisoformat(overlap_start_session) - timedelta(days=1)
        while cursor.weekday() >= 5:
            cursor -= timedelta(days=1)
        prefix_sessions = [cursor.isoformat()]
    prefix = dict(previous)
    prefix["research_calendar"] = prefix_sessions
    for table in ("prices", "trading_states", "price_limits", "base_pool"):
        rows = prefix.get(table)
        if not isinstance(rows, list):
            raise DataSourceError(
                "invalid_source_data",
                detail_code="INVALID_PREVIOUS_CANONICAL",
            )
        prefix[table] = [row for row in rows if str(row.get("session", "")) < overlap_start_session]
    universes = prefix.get("liquidity_universes")
    if not isinstance(universes, dict):
        raise DataSourceError(
            "invalid_source_data",
            detail_code="INVALID_PREVIOUS_CANONICAL",
        )
    prefix["liquidity_universes"] = {
        name: [row for row in rows if str(row.get("session", "")) < overlap_start_session]
        for name, rows in universes.items()
        if isinstance(rows, list)
    }
    return prefix


def _remove_synthetic_predecessor(
    canonical: dict[str, object],
    overlap_start_session: str,
) -> None:
    calendar = canonical.get("research_calendar")
    if not isinstance(calendar, list) or not calendar:
        raise DataSourceError(
            "invalid_source_data",
            detail_code="INVALID_CANONICAL_INCREMENT",
        )
    first = str(calendar[0])
    if first >= overlap_start_session:
        return
    if len(calendar) < 2 or str(calendar[1]) != overlap_start_session:
        return
    for table in ("prices", "trading_states", "price_limits", "base_pool"):
        rows = canonical.get(table)
        if not isinstance(rows, list):
            raise DataSourceError(
                "invalid_source_data",
                detail_code="INVALID_CANONICAL_INCREMENT",
            )
        if any(isinstance(row, dict) and str(row.get("session", "")) == first for row in rows):
            return
    canonical["research_calendar"] = calendar[1:]


def _recompute_liquidity_universes(canonical: dict[str, object]) -> None:
    calendar = canonical.get("research_calendar")
    base_pool = canonical.get("base_pool")
    prices = canonical.get("prices")
    states = canonical.get("trading_states")
    if not all(isinstance(value, list) for value in (calendar, base_pool, prices, states)):
        raise DataSourceError(
            "invalid_source_data",
            detail_code="INVALID_CANONICAL_INCREMENT",
        )
    assert isinstance(calendar, list)
    assert isinstance(base_pool, list)
    assert isinstance(prices, list)
    assert isinstance(states, list)
    canonical["liquidity_universes"] = liquidity_universes(
        [str(value) for value in calendar],
        base_pool,
        prices,
        states,
    )


def _preserve_ordinary_overlap_absence(
    snapshot: Mapping[str, list[dict[str, object]]],
    previous: Mapping[str, object],
    *,
    overlap_start_session: str,
) -> dict[str, list[dict[str, object]]]:
    supplemented = dict(snapshot)
    calendar_sse = supplemented.get("calendar_sse", [])
    calendar_szse = supplemented.get("calendar_szse", [])
    stock_basic = supplemented.get("stock_basic", [])
    daily = supplemented.get("daily", [])
    adjustments = supplemented.get("adjustments", [])
    suspensions = supplemented.get("suspensions", [])
    limits = supplemented.get("price_limits", [])
    if not all(
        isinstance(rows, list)
        for rows in (
            calendar_sse,
            calendar_szse,
            stock_basic,
            daily,
            adjustments,
            suspensions,
            limits,
        )
    ):
        raise DataSourceError(
            "invalid_source_data",
            detail_code="MALFORMED_PROVIDER_PAYLOAD",
        )
    previous_calendar = previous.get("research_calendar")
    previous_instruments = previous.get("instruments")
    if not isinstance(previous_calendar, list) or not isinstance(previous_instruments, list):
        raise DataSourceError(
            "invalid_source_data",
            detail_code="INVALID_PREVIOUS_CANONICAL",
        )
    for exchange, rows in (("SSE", calendar_sse), ("SZSE", calendar_szse)):
        returned_dates = {str(row["cal_date"]) for row in rows}
        for session in previous_calendar:
            session_text = str(session)
            if session_text < overlap_start_session:
                continue
            source_date = session_text.replace("-", "")
            if source_date not in returned_dates:
                rows.append(
                    {
                        "exchange": exchange,
                        "cal_date": source_date,
                        "is_open": "1",
                    }
                )
                returned_dates.add(source_date)
    returned_codes = {str(row["ts_code"]) for row in stock_basic}
    for instrument in previous_instruments:
        if not isinstance(instrument, dict):
            raise DataSourceError(
                "invalid_source_data",
                detail_code="INVALID_PREVIOUS_CANONICAL",
            )
        code = str(instrument["ts_code"])
        if code not in returned_codes:
            stock_basic.append(_source_instrument(instrument))
            returned_codes.add(code)
    daily_positions = {(str(row["trade_date"]), str(row["ts_code"])) for row in daily}
    suspension_positions = {(str(row["trade_date"]), str(row["ts_code"])) for row in suspensions}
    adjustment_positions = {(str(row["trade_date"]), str(row["ts_code"])) for row in adjustments}
    limit_positions = {(str(row["trade_date"]), str(row["ts_code"])) for row in limits}
    instruments = previous.get("instruments")
    prices = previous.get("prices")
    states = previous.get("trading_states")
    previous_limits = previous.get("price_limits")
    if not all(
        isinstance(rows, list)
        for rows in (instruments, prices, states, previous_limits)
    ):
        raise DataSourceError(
            "invalid_source_data",
            detail_code="INVALID_PREVIOUS_CANONICAL",
        )
    assert isinstance(instruments, list)
    assert isinstance(prices, list)
    assert isinstance(states, list)
    assert isinstance(previous_limits, list)
    code_by_instrument = {
        str(row["instrument_id"]): str(row["ts_code"])
        for row in instruments
        if isinstance(row, dict)
    }
    price_by_position = {
        (str(row["session"]), str(row["instrument_id"])): row
        for row in prices
        if isinstance(row, dict)
    }
    limit_by_position = {
        (str(row["session"]), str(row["instrument_id"])): row
        for row in previous_limits
        if isinstance(row, dict)
    }
    for state in states:
        if not isinstance(state, dict):
            continue
        session = str(state["session"])
        if session < overlap_start_session:
            continue
        instrument_id = str(state["instrument_id"])
        code = code_by_instrument[instrument_id]
        source_position = (session.replace("-", ""), code)
        price = price_by_position.get((session, instrument_id))
        prior_limit = limit_by_position.get((session, instrument_id))
        if source_position in daily_positions:
            if price is not None and source_position not in adjustment_positions:
                adjustments.append(
                    {
                        "ts_code": code,
                        "trade_date": source_position[0],
                        "adj_factor": price["adjustment_factor"],
                    }
                )
                adjustment_positions.add(source_position)
            if prior_limit is not None and source_position not in limit_positions:
                limits.append(
                    {
                        "ts_code": code,
                        "trade_date": source_position[0],
                        "pre_close": (None if price is None else price["pre_close_raw"]),
                        "up_limit": prior_limit["upper"],
                        "down_limit": prior_limit["lower"],
                    }
                )
                limit_positions.add(source_position)
            continue
        if source_position in suspension_positions:
            continue
        if state["state"] == "full_session_suspension":
            suspensions.append(
                {
                    "ts_code": code,
                    "trade_date": source_position[0],
                    "suspend_timing": "全天",
                    "suspend_type": "preserved",
                }
            )
            suspension_positions.add(source_position)
            continue
        if state["state"] == "data_unavailable":
            continue
        if price is None or prior_limit is None:
            raise DataSourceError(
                "invalid_source_data",
                detail_code="INVALID_PREVIOUS_CANONICAL",
            )
        daily.append(_source_daily(code, session, price))
        daily_positions.add(source_position)
        if source_position not in adjustment_positions:
            adjustments.append(
                {
                    "ts_code": code,
                    "trade_date": source_position[0],
                    "adj_factor": price["adjustment_factor"],
                }
            )
        if source_position not in limit_positions:
            limits.append(
                {
                    "ts_code": code,
                    "trade_date": source_position[0],
                    "pre_close": price["pre_close_raw"],
                    "up_limit": prior_limit["upper"],
                    "down_limit": prior_limit["lower"],
                }
            )
    return supplemented


def _validate_new_session_evidence(
    snapshot: Mapping[str, list[dict[str, object]]],
    current_data_through: str,
    *,
    completed_through_date: date,
) -> None:
    sse = snapshot.get("calendar_sse")
    szse = snapshot.get("calendar_szse")
    stock_basic = snapshot.get("stock_basic")
    if not isinstance(sse, list) or not isinstance(szse, list) or not isinstance(stock_basic, list):
        raise DataSourceError(
            "invalid_source_data",
            detail_code="MALFORMED_PROVIDER_PAYLOAD",
        )
    frontier_date = date.fromisoformat(current_data_through)
    expected_dates: set[str] = set()
    cursor = frontier_date + timedelta(days=1)
    while cursor <= completed_through_date:
        expected_dates.add(cursor.strftime("%Y%m%d"))
        cursor += timedelta(days=1)
    for calendar in (sse, szse):
        returned_dates = {str(row["cal_date"]) for row in calendar}
        if not expected_dates <= returned_dates:
            raise DataSourceError(
                "invalid_source_data",
                detail_code="INCOMPLETE_NEW_SESSION_CALENDAR",
            )
    known_codes = {str(row["ts_code"]) for row in stock_basic}
    frontier = current_data_through.replace("-", "")
    new_open_sessions = (
        {
            str(row["cal_date"])
            for row in sse
            if str(row.get("is_open")) == "1" and str(row["cal_date"]) > frontier
        }
        & {
            str(row["cal_date"])
            for row in szse
            if str(row.get("is_open")) == "1" and str(row["cal_date"]) > frontier
        }
    )
    for table in ("daily", "adjustments", "suspensions", "price_limits"):
        rows = snapshot.get(table)
        if not isinstance(rows, list):
            raise DataSourceError(
                "invalid_source_data",
                detail_code="MALFORMED_PROVIDER_PAYLOAD",
            )
        if any(
            str(row["trade_date"]) > frontier and str(row["ts_code"]) not in known_codes
            for row in rows
        ):
            raise DataSourceError(
                "invalid_source_data",
                detail_code="INCOMPLETE_NEW_SESSION_INSTRUMENT",
            )
        returned_sessions = {str(row["trade_date"]) for row in rows}
        if table == "daily" and not new_open_sessions <= returned_sessions:
            raise DataSourceError(
                "invalid_source_data",
                detail_code="UNEXPLAINED_DAILY_ABSENCE",
            )
        if table in {"adjustments", "price_limits"} and not new_open_sessions <= (
            returned_sessions
        ):
            raise DataSourceError(
                "invalid_source_data",
                detail_code="INCOMPLETE_REQUIRED_MARKET_FACTS",
            )


def _project_price_limits_to_stock_scope(
    snapshot: Mapping[str, list[dict[str, object]]],
) -> dict[str, list[dict[str, object]]]:
    stock_basic = snapshot.get("stock_basic")
    price_limits = snapshot.get("price_limits")
    if not isinstance(stock_basic, list) or not isinstance(price_limits, list):
        raise DataSourceError(
            "invalid_source_data",
            detail_code="MALFORMED_PROVIDER_PAYLOAD",
        )
    known_codes = {str(row["ts_code"]) for row in stock_basic}
    projected = dict(snapshot)
    projected["price_limits"] = [
        row for row in price_limits if str(row["ts_code"]) in known_codes
    ]
    return projected


def _compact_source_lineage(lineage: Mapping[str, object]) -> dict[str, object]:
    responses = lineage.get("responses")
    if not isinstance(responses, Mapping):
        return dict(lineage)
    row_counts: dict[str, int] = {}
    for name, rows in sorted(responses.items(), key=lambda item: str(item[0])):
        if not isinstance(rows, list):
            raise DataSourceError(
                "invalid_source_data",
                detail_code="MALFORMED_PROVIDER_PAYLOAD",
            )
        row_counts[str(name)] = len(rows)
    compact = {str(key): value for key, value in lineage.items() if key != "responses"}
    compact["response_row_counts"] = row_counts
    return compact


def _source_instrument(instrument: Mapping[str, object]) -> dict[str, object]:
    market_by_board = {"main": "主板", "chinext": "创业板", "star": "科创板"}
    board = str(instrument["board"])
    try:
        market = market_by_board[board]
    except KeyError as error:
        raise DataSourceError(
            "invalid_source_data",
            detail_code="INVALID_PREVIOUS_CANONICAL",
        ) from error
    listed_to = str(instrument.get("listed_to", ""))
    return {
        "ts_code": str(instrument["ts_code"]),
        "exchange": str(instrument["exchange"]),
        "market": market,
        "list_status": "D" if listed_to else "L",
        "list_date": str(instrument["listed_from"]).replace("-", ""),
        "delist_date": listed_to.replace("-", ""),
    }


def _source_daily(
    code: str,
    session: str,
    price: Mapping[str, object],
) -> dict[str, object]:
    return {
        "ts_code": code,
        "trade_date": session.replace("-", ""),
        "open": price["open_raw"],
        "high": price["high_raw"],
        "low": price["low_raw"],
        "close": price["close_raw"],
        "pre_close": price["pre_close_raw"],
        "change": price["change_raw"],
        "pct_chg": price["pct_change_raw"],
        "vol": str(Decimal(str(price["volume_shares"])) / Decimal(100)),
        "amount": str(Decimal(str(price["turnover_cny"])) / Decimal(1000)),
    }
