from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal

import numpy as np
import pytest

from thesistrace.alpha_language import alpha_language
from thesistrace.publication import VerifiedBundle, VerifiedPayload
from thesistrace.publication.serialization import canonical_json_bytes, parquet_bytes
from thesistrace.research_kernel.equivalence import equivalence_bytes
from thesistrace.research_kernel.factor import evaluate_factor
from thesistrace.research_kernel.kernel_run import (
    RunInput,
    StrategyRunInput,
    run_columnar_chunk,
)
from thesistrace.research_kernel.research_chunks import (
    advance_factor_state,
    empty_factor_state,
    empty_research_continuation,
    execute_research_chunk,
    finalize_factor_state,
    validated_research_continuation,
)
from thesistrace.research_run.result import (
    RESULT_DAILY_PARTITION_PREFIX,
    RESULT_DAILY_PARTITION_SESSION_COUNT,
    STRATEGY_DAILY_OBSERVATIONS_CONTRACT,
    build_result_payload,
    read_result_bundle,
)
from thesistrace.research_series import ExecutionPrice, InstrumentProfile, PriceLimit


def _label_session(session: str, offset: float) -> dict[str, object]:
    samples = [
        {
            "instrument_id": f"instrument_{index:03d}",
            "alpha": float(index),
            "label": float(index) / 100 + offset,
        }
        for index in range(40)
    ]
    return {
        "session": session,
        "signal_session": session,
        "alpha_values": [],
        "samples": samples,
        "resolutions": [],
        "unavailable": {},
    }


def _labels(rows: list[dict[str, object]]) -> dict[str, object]:
    return {
        "alpha_checksum": "a" * 64,
        "report_session_count": len(rows),
        "horizons": {
            str(horizon): {
                "horizon": horizon,
                "sessions": rows,
                "checksum": f"{horizon}" * 64,
            }
            for horizon in (1, 5, 20)
        },
    }


def test_factor_observations_fold_into_chunk_invariant_bounded_aggregate_state() -> None:
    rows = [
        _label_session("2026-08-03", 0.0),
        _label_session("2026-08-04", 0.1),
        _label_session("2026-08-05", -0.2),
    ]
    uninterrupted = evaluate_factor(_labels(rows))

    state = empty_factor_state()
    state = advance_factor_state(state, _labels(rows[:2]))
    state = advance_factor_state(state, _labels(rows[2:]))
    chunked = finalize_factor_state(state, alpha_checksum="a" * 64)

    for horizon in ("1", "5", "20"):
        assert (
            chunked["horizons"][horizon]["summary"] == uninterrupted["horizons"][horizon]["summary"]
        )
        assert chunked["horizons"][horizon]["coverage"] == {
            "signal_session_count": 3,
            "ic_valid_session_count": 3,
            "rank_ic_valid_session_count": 3,
            "quantile_valid_session_count": 3,
        }
    assert "daily" not in repr(state)


def test_research_continuation_requires_the_exact_frozen_kind_shape() -> None:
    factor = empty_research_continuation("factor_evaluation")
    strategy = empty_research_continuation("strategy_backtest")

    assert validated_research_continuation(
        factor,
        research_kind="factor_evaluation",
    ) == factor
    assert validated_research_continuation(
        strategy,
        research_kind="strategy_backtest",
    ) == strategy

    with pytest.raises(ValueError, match="continuation is invalid"):
        validated_research_continuation(
            {**factor, "strategy_state": None},
            research_kind="factor_evaluation",
        )
    with pytest.raises(ValueError, match="continuation is invalid"):
        validated_research_continuation(
            {name: value for name, value in strategy.items() if name != "strategy_checksum"},
            research_kind="strategy_backtest",
        )


@dataclass(frozen=True)
class _ColumnarFixture:
    sessions: tuple[str, ...]
    instruments: dict[str, InstrumentProfile]
    universe_members: dict[str, tuple[str, ...]]
    industries: dict[tuple[str, str], str]
    execution_prices: dict[tuple[str, str], ExecutionPrice]
    trading_states: dict[tuple[str, str], str]
    price_limits: dict[tuple[str, str], PriceLimit]
    matrices: dict[str, np.ndarray]

    def snapshot(self) -> _ColumnarFixture:
        return self

    def slice_sessions(self, sessions: tuple[str, ...]) -> _ColumnarFixture:
        positions = [self.sessions.index(session) for session in sessions]
        selected = set(sessions)
        return _ColumnarFixture(
            sessions=sessions,
            instruments=self.instruments,
            universe_members={session: self.universe_members[session] for session in sessions},
            industries={key: value for key, value in self.industries.items() if key[0] in selected},
            execution_prices={
                key: value for key, value in self.execution_prices.items() if key[0] in selected
            },
            trading_states={
                key: value for key, value in self.trading_states.items() if key[0] in selected
            },
            price_limits={
                key: value for key, value in self.price_limits.items() if key[0] in selected
            },
            matrices={name: value[:, positions] for name, value in self.matrices.items()},
        )

    def numeric_field_matrices(
        self,
        field_ids: tuple[str, ...],
        instruments: tuple[str, ...],
    ) -> dict[str, np.ndarray]:
        positions = [tuple(self.instruments).index(instrument) for instrument in instruments]
        return {field_id: self.matrices[field_id][positions] for field_id in field_ids}

    def adjusted_open_matrix(self, instruments: tuple[str, ...]) -> np.ndarray:
        return np.asarray(
            [
                [
                    float(self.execution_prices[(session, instrument_id)].adjusted_open)
                    for session in self.sessions
                ]
                for instrument_id in instruments
            ],
            dtype=np.float64,
        )

    def adjusted_open_decimal_matrix(self, instruments: tuple[str, ...]) -> np.ndarray:
        return np.asarray(
            [
                [
                    Decimal(
                        self.execution_prices[(session, instrument_id)].adjusted_open
                    )
                    for session in self.sessions
                ]
                for instrument_id in instruments
            ],
            dtype=object,
        )


def test_chunked_composite_research_is_canonically_equal_across_real_boundaries() -> None:
    sessions = tuple(f"s{index:02d}" for index in range(80))
    instruments = tuple(f"equity:{index:03d}.SH" for index in range(40))
    profiles = {
        instrument: InstrumentProfile(board="main", listed_to="") for instrument in instruments
    }
    prices = {
        (session, instrument): ExecutionPrice(
            raw_open=str(10 + instrument_index + session_index / 10),
            adjusted_open=str(10 + instrument_index + session_index / 10),
        )
        for session_index, session in enumerate(sessions)
        for instrument_index, instrument in enumerate(instruments)
    }
    close = np.asarray(
        [
            [10 + instrument_index + session_index / 10 for session_index in range(80)]
            for instrument_index in range(40)
        ],
        dtype=np.float64,
    )
    revenue = np.asarray(
        [
            [
                1000 + instrument_index * 7 + (session_index // 20) * 13
                for session_index in range(80)
            ]
            for instrument_index in range(40)
        ],
        dtype=np.float64,
    )
    for instrument_index in range(40):
        for session_index in range(80):
            if (instrument_index * 3 + session_index) % 29 == 0:
                close[instrument_index, session_index] = np.nan
            if (instrument_index + session_index * 2) % 31 == 0:
                revenue[instrument_index, session_index] = np.nan
    fixture = _ColumnarFixture(
        sessions=sessions,
        instruments=profiles,
        universe_members={
            session: (
                instruments[5:]
                if session_index % 3 == 0
                else instruments[:-5]
                if session_index % 3 == 1
                else instruments
            )
            for session_index, session in enumerate(sessions)
        },
        industries={
            (session, instrument): f"industry:{instrument_index % 5}"
            for session in sessions
            for instrument_index, instrument in enumerate(instruments)
        },
        execution_prices=prices,
        trading_states={},
        price_limits={
            coordinate: PriceLimit(upper="100000", lower="0.01") for coordinate in prices
        },
        matrices={
            "price.close.adjusted": close,
            "financial.income.total_revenue.latest_fy": revenue,
        },
    )
    compiled = alpha_language.compile(
        "rank(ts_mean(close, 5)) + rank(revenue)"
    )
    run_input = RunInput(
        research_data=fixture,
        alpha_expression=compiled.expression,
        field_bindings={
            field_id: identifier
            for identifier, field_id in compiled.field_ids_by_identifier.items()
        },
        effective_alpha_lookback=compiled.effective_lookback,
        universe="top300",
        neutralization="industry",
        research_kind="strategy_backtest",
        strategy=StrategyRunInput(
            holdings_count=5,
            rebalance_interval=5,
            initial_cash_cny="10000000",
            commission_rate_all_in="0.0003",
            commission_min_cny="5",
            stamp_duty_sell_rate="0.0005",
            transfer_fee_rate="0.00001",
        ),
        research_start_session=sessions[20],
        research_end_session=sessions[-1],
    )
    research_sessions = sessions[20:]

    uninterrupted = execute_research_chunk(
        run_input=run_input,
        research_data=fixture,
        research_sessions=research_sessions,
        final_chunk=True,
        continuation=empty_research_continuation("strategy_backtest"),
        cancellation_check=lambda: None,
    )
    legacy = build_result_payload(
        run_columnar_chunk(run_input, cancellation_check=lambda: None),
        research_kind="strategy_backtest",
        rebalance_interval=5,
        universe=run_input.universe,
    )
    for boundaries in (
        ((20, 40), (40, 60), (60, 80)),
        ((20, 63), (63, 80)),
        ((20, 64), (64, 80)),
    ):
        continuation = empty_research_continuation("strategy_backtest")
        chunk_results = []
        for ordinal, (start, end) in enumerate(boundaries, start=1):
            calculation = execute_research_chunk(
                run_input=run_input,
                research_data=fixture.slice_sessions(sessions[max(0, start - 21) : end]),
                research_sessions=sessions[start:end],
                final_chunk=ordinal == len(boundaries),
                continuation=continuation,
                cancellation_check=lambda: None,
            )
            chunk_results.append(calculation)
            continuation = calculation.continuation

        final = chunk_results[-1]
        assembled_observations = [
            observation
            for calculation in chunk_results
            for observation in calculation.strategy_daily_observations
        ]
        assert equivalence_bytes(final.final_values) == equivalence_bytes(
            uninterrupted.final_values
        )
        assert equivalence_bytes(assembled_observations) == equivalence_bytes(
            list(uninterrupted.strategy_daily_observations)
        )
        assert final.continuation["alpha_checksum"] == uninterrupted.continuation["alpha_checksum"]
        assert "alpha_checksum_state" not in final.continuation
        assert final.continuation["schema_version"] == "research-chunk-continuation-v2"
        chunked_result = _read_staged_chunk_result(
            final.final_values,
            [list(calculation.strategy_daily_observations) for calculation in chunk_results],
        )
        assert equivalence_bytes(chunked_result) == equivalence_bytes(legacy)
        strategy_state = final.continuation["strategy_state"]
        assert len(strategy_state["daily"]) == 1
        assert "daily" not in repr(final.continuation["factor_state"])

    factor_run_input = RunInput(
        research_data=fixture,
        alpha_expression=compiled.expression,
        field_bindings={
            field_id: identifier
            for identifier, field_id in compiled.field_ids_by_identifier.items()
        },
        effective_alpha_lookback=compiled.effective_lookback,
        universe="top300",
        neutralization="industry",
        research_kind="factor_evaluation",
        strategy=None,
        research_start_session=sessions[20],
        research_end_session=sessions[-1],
    )
    factor_uninterrupted = execute_research_chunk(
        run_input=factor_run_input,
        research_data=fixture,
        research_sessions=research_sessions,
        final_chunk=True,
        continuation=empty_research_continuation("factor_evaluation"),
        cancellation_check=lambda: None,
    )
    for boundaries in (
        ((20, 40), (40, 60), (60, 80)),
        ((20, 63), (63, 80)),
        ((20, 64), (64, 80)),
    ):
        factor_continuation = empty_research_continuation("factor_evaluation")
        factor_results = []
        for ordinal, (start, end) in enumerate(boundaries, start=1):
            calculation = execute_research_chunk(
                run_input=factor_run_input,
                research_data=fixture.slice_sessions(sessions[max(0, start - 21) : end]),
                research_sessions=sessions[start:end],
                final_chunk=ordinal == len(boundaries),
                continuation=factor_continuation,
                cancellation_check=lambda: None,
            )
            factor_results.append(calculation)
            factor_continuation = json.loads(canonical_json_bytes(calculation.continuation))

        factor_final = factor_results[-1]
        assert all(result.phase_seconds["strategy"] == 0.0 for result in factor_results)
        assert all(not result.strategy_daily_observations for result in factor_results)
        assert "strategy_state" not in factor_final.continuation
        assert "strategy_checksum" not in factor_final.continuation
        assert set(factor_final.final_values or {}) == {"factor_summary"}
        assert equivalence_bytes(
            (factor_final.final_values or {})["factor_summary"]
        ) == equivalence_bytes(factor_uninterrupted.final_values["factor_summary"])
        assert equivalence_bytes(
            (factor_final.final_values or {})["factor_summary"]
        ) == equivalence_bytes(uninterrupted.final_values["factor_summary"])
        for horizon in ("1", "5", "20"):
            chunked_horizon = (factor_final.final_values or {})["factor_summary"][
                "horizons"
            ][horizon]
            reference_horizon = legacy["factor_summary"]["horizons"][horizon]
            assert chunked_horizon["coverage"] == reference_horizon["coverage"]
            assert chunked_horizon["alpha_checksum"] == reference_horizon["alpha_checksum"]
            assert chunked_horizon["label_checksum"] == reference_horizon["label_checksum"]
            assert chunked_horizon["source_checksum"] == reference_horizon["source_checksum"]


def _read_staged_chunk_result(
    final_values: dict[str, object] | None,
    observation_partitions: list[list[dict[str, object]]],
) -> dict[str, object]:
    assert final_values is not None
    payloads = {
        name: VerifiedPayload(
            media_type="application/json",
            content=canonical_json_bytes(value),
            serialization={"format": "canonical-json", "version": 1},
        )
        for name, value in final_values.items()
    }
    descriptors = []
    for index, rows in enumerate(observation_partitions):
        name = f"{RESULT_DAILY_PARTITION_PREFIX}{index:06d}"
        content = parquet_bytes(rows, STRATEGY_DAILY_OBSERVATIONS_CONTRACT)
        assert content == parquet_bytes(rows, STRATEGY_DAILY_OBSERVATIONS_CONTRACT)
        payloads[name] = VerifiedPayload(
            media_type="application/vnd.apache.parquet",
            content=content,
            serialization={
                "format": "canonical-parquet",
                "writer_contract": STRATEGY_DAILY_OBSERVATIONS_CONTRACT.descriptor(),
            },
        )
        descriptors.append(
            {
                "name": name,
                "row_count": len(rows),
                "first_session": rows[0]["session"],
                "last_session": rows[-1]["session"],
            }
        )
    descriptor = {
        "format": "partitioned-parquet",
        "version": 1,
        "partition_session_count": RESULT_DAILY_PARTITION_SESSION_COUNT,
        "writer_contract": STRATEGY_DAILY_OBSERVATIONS_CONTRACT.descriptor(),
        "partitions": descriptors,
    }
    payloads["strategy_daily_observations"] = VerifiedPayload(
        media_type="application/json",
        content=json.dumps(
            descriptor,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode(),
        serialization={"format": "canonical-json", "version": 1},
    )
    return read_result_bundle(
        VerifiedBundle(
            kind="research.result",
            manifest_sha256="f" * 64,
            provenance={},
            payloads=payloads,
        ),
        research_kind="strategy_backtest",
    )
