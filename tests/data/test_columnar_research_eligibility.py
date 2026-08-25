from __future__ import annotations

from decimal import Decimal

import pyarrow as pa

from thesistrace.data.columnar_series import ColumnarResearchData
from thesistrace.research_kernel.numeric import canonical_binary64_bytes
from thesistrace.research_kernel.strategy import columnar_equal_weight_benchmark_return
from thesistrace.research_series import decimal_to_binary64


def _empty_table() -> pa.Table:
    return pa.table({"instrument_id": pa.array([], type=pa.string())})


def test_research_universe_excludes_members_without_positive_turnover_observations() -> None:
    session = "2010-02-09"
    positive = "equity:000001.SZ"
    zero = "equity:000002.SZ"
    absent = "equity:000004.SZ"
    series = ColumnarResearchData(
        sessions=(session,),
        _instruments=pa.table(
            {
                "instrument_id": [positive, zero, absent],
                "board": ["main", "main", "main"],
                "listed_to": ["", "", ""],
            }
        ),
        _eod_prices=pa.table(
            {
                "session_date": [session, session],
                "instrument_id": [positive, zero],
                "open_raw": [Decimal("10"), Decimal("20")],
                "open_adj": [Decimal("10"), Decimal("20")],
                "close_adj": [Decimal("10"), Decimal("20")],
                "turnover_amount_cny": [Decimal("1000"), Decimal("0")],
            }
        ),
        _universes=pa.table(
            {
                "session": [session],
                "instrument_ids": [[positive, zero, absent]],
            }
        ),
        _trading_states=_empty_table(),
        _price_limits=_empty_table(),
        _industries=_empty_table(),
        _financial_values=None,
        _field_columns={"price.close.adjusted": "close_adj"},
    )

    assert series.universe_members[session] == (positive,)


def test_decimal_fields_follow_the_numeric_execution_contract_bit_exactly() -> None:
    session = "2026-08-13"
    instrument_id = "equity:000001.SZ"
    value = Decimal("0.35")
    series = ColumnarResearchData(
        sessions=(session,),
        _instruments=pa.table(
            {
                "instrument_id": [instrument_id],
                "board": ["main"],
                "listed_to": [""],
            }
        ),
        _eod_prices=pa.table(
            {
                "session_date": [session],
                "instrument_id": [instrument_id],
                "open_raw": [value],
                "open_adj": [value],
                "close_adj": [value],
                "turnover_amount_cny": [Decimal("1")],
            }
        ),
        _universes=pa.table(
            {
                "session": [session],
                "instrument_ids": [[instrument_id]],
            }
        ),
        _trading_states=_empty_table(),
        _price_limits=_empty_table(),
        _industries=_empty_table(),
        _financial_values=None,
        _field_columns={"price.close.adjusted": "close_adj"},
    )

    actual = float(
        series.numeric_field_matrices(
            ("price.close.adjusted",),
            (instrument_id,),
        )["price.close.adjusted"][0, 0]
    )

    assert canonical_binary64_bytes(actual) == canonical_binary64_bytes(
        decimal_to_binary64(value)
    )


def test_decimal_fields_keep_correct_rounding_when_arrow_cast_selects_adjacent_float() -> None:
    session = "2026-08-13"
    instrument_id = "equity:000001.SZ"
    value = Decimal("3944830730744934695645.63507900")
    series = ColumnarResearchData(
        sessions=(session,),
        _instruments=pa.table(
            {
                "instrument_id": [instrument_id],
                "board": ["main"],
                "listed_to": [""],
            }
        ),
        _eod_prices=pa.table(
            {
                "session_date": [session],
                "instrument_id": [instrument_id],
                "open_raw": [value],
                "open_adj": [value],
                "close_adj": [value],
                "turnover_amount_cny": [Decimal("1")],
            }
        ),
        _universes=pa.table(
            {
                "session": [session],
                "instrument_ids": [[instrument_id]],
            }
        ),
        _trading_states=_empty_table(),
        _price_limits=_empty_table(),
        _industries=_empty_table(),
        _financial_values=None,
        _field_columns={"price.close.adjusted": "close_adj"},
    )

    field_value = float(
        series.numeric_field_matrices(
            ("price.close.adjusted",),
            (instrument_id,),
        )["price.close.adjusted"][0, 0]
    )
    adjusted_open = float(series.adjusted_open_matrix((instrument_id,))[0, 0])

    expected = canonical_binary64_bytes(decimal_to_binary64(value))
    assert canonical_binary64_bytes(field_value) == expected
    assert canonical_binary64_bytes(adjusted_open) == expected


def test_zero_turnover_member_cannot_fail_the_columnar_benchmark() -> None:
    signal, entry, exit_session = ("2010-02-09", "2010-02-10", "2010-02-11")
    active = "equity:000001.SZ"
    suspended_from_coverage_start = "equity:000004.SZ"
    series = ColumnarResearchData(
        sessions=(signal, entry, exit_session),
        _instruments=pa.table(
            {
                "instrument_id": [active, suspended_from_coverage_start],
                "board": ["main", "main"],
                "listed_to": ["", ""],
            }
        ),
        _eod_prices=pa.table(
            {
                "session_date": [signal, entry, exit_session, exit_session],
                "instrument_id": [active, active, active, suspended_from_coverage_start],
                "open_raw": [
                    Decimal("10"),
                    Decimal("11"),
                    Decimal("12"),
                    Decimal("38.608"),
                ],
                "open_adj": [
                    Decimal("10"),
                    Decimal("11"),
                    Decimal("12"),
                    Decimal("38.608"),
                ],
                "turnover_amount_cny": [
                    Decimal("1000"),
                    Decimal("1000"),
                    Decimal("1000"),
                    Decimal("1000"),
                ],
            }
        ),
        _universes=pa.table(
            {
                "session": [signal],
                "instrument_ids": [[active, suspended_from_coverage_start]],
            }
        ),
        _trading_states=_empty_table(),
        _price_limits=_empty_table(),
        _industries=_empty_table(),
        _financial_values=None,
        _field_columns={},
    )
    instruments = tuple(sorted(series.instruments))

    result = columnar_equal_weight_benchmark_return(
        signal,
        entry,
        exit_session,
        series.universe_members,
        {(entry, suspended_from_coverage_start): "full_session_suspension"},
        series.instruments,
        {instrument_id: index for index, instrument_id in enumerate(instruments)},
        {session: index for index, session in enumerate(series.sessions)},
        series.adjusted_open_decimal_matrix(instruments),
        series.adjusted_open_matrix(instruments),
    )

    assert result == Decimal(12) / Decimal(11) - Decimal(1)
