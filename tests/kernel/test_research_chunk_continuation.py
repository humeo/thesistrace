from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

import numpy as np

from thesistrace.alpha_language import alpha_language
from thesistrace.publication import VerifiedBundle, VerifiedPayload
from thesistrace.publication.serialization import canonical_json_bytes, parquet_bytes
from thesistrace.research_kernel.equivalence import equivalence_bytes
from thesistrace.research_kernel.factor import evaluate_factor
from thesistrace.research_kernel.kernel_run import RunInput, run_columnar_chunk
from thesistrace.research_kernel.research_chunks import (
    advance_factor_state,
    empty_factor_state,
    empty_research_continuation,
    execute_research_chunk,
    finalize_factor_state,
)
from thesistrace.research_kernel.sha256_state import (
    empty_sha256_state,
    sha256_state_hexdigest,
    update_sha256_state,
)
from thesistrace.research_run.result import (
    RESULT_DAILY_PARTITION_PREFIX,
    RESULT_DAILY_PARTITION_SESSION_COUNT,
    STRATEGY_DAILY_OBSERVATIONS_CONTRACT,
    build_result_payload,
    read_result_bundle,
)
from thesistrace.research_series import ExecutionPrice, InstrumentProfile, PriceLimit


def test_checkpointable_sha256_matches_standard_incremental_digest() -> None:
    pieces = (b"bounded", b"-checkpoint", bytes(range(255)))
    state = empty_sha256_state()
    for piece in pieces:
        state = update_sha256_state(state, piece)

    assert sha256_state_hexdigest(state) == hashlib.sha256(b"".join(pieces)).hexdigest()


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
        assert chunked["horizons"][horizon]["summary"] == uninterrupted["horizons"][
            horizon
        ]["summary"]
        assert chunked["horizons"][horizon]["coverage"] == {
            "signal_session_count": 3,
            "ic_valid_session_count": 3,
            "rank_ic_valid_session_count": 3,
            "quantile_valid_session_count": 3,
        }
    assert "daily" not in repr(state)


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
            industries={
                key: value for key, value in self.industries.items() if key[0] in selected
            },
            execution_prices={
                key: value
                for key, value in self.execution_prices.items()
                if key[0] in selected
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


def test_chunked_composite_research_is_canonically_equal_across_real_boundaries() -> None:
    sessions = tuple(f"s{index:02d}" for index in range(80))
    instruments = tuple(f"equity:{index:03d}.SH" for index in range(40))
    profiles = {
        instrument: InstrumentProfile(board="main", listed_to="")
        for instrument in instruments
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
        industries={},
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
        "cs_rank(ts_mean(close_adj, 5)) + cs_rank(total_revenue_latest_fy)"
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
        neutralization="none",
        holdings_count=5,
        rebalance_interval=5,
        initial_cash_cny="10000000",
        commission_rate_all_in="0.0003",
        commission_min_cny="5",
        stamp_duty_sell_rate="0.0005",
        transfer_fee_rate="0.00001",
        research_start_session=sessions[20],
        research_end_session=sessions[-1],
    )
    research_sessions = sessions[20:]

    uninterrupted = execute_research_chunk(
        run_input=run_input,
        research_data=fixture,
        research_sessions=research_sessions,
        final_chunk=True,
        continuation=empty_research_continuation(),
        cancellation_check=lambda: None,
    )
    continuation = empty_research_continuation()
    chunk_results = []
    for ordinal, (start, end) in enumerate(((20, 40), (40, 60), (60, 80)), start=1):
        calculation = execute_research_chunk(
            run_input=run_input,
            research_data=fixture.slice_sessions(sessions[max(0, start - 21) : end]),
            research_sessions=sessions[start:end],
            final_chunk=ordinal == 3,
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
    assert final.continuation["alpha_checksum"] == uninterrupted.continuation[
        "alpha_checksum"
    ]
    assert equivalence_bytes(final.continuation["alpha_checksum_state"]) == (
        equivalence_bytes(uninterrupted.continuation["alpha_checksum_state"])
    )
    legacy = build_result_payload(
        run_columnar_chunk(run_input, cancellation_check=lambda: None),
        rebalance_interval=run_input.rebalance_interval,
        universe=run_input.universe,
    )
    chunked_result = _read_staged_chunk_result(
        final.final_values,
        [list(calculation.strategy_daily_observations) for calculation in chunk_results],
    )
    assert equivalence_bytes(chunked_result) == equivalence_bytes(legacy)
    strategy_state = final.continuation["strategy_state"]
    assert len(strategy_state["daily"]) == 1
    assert "daily" not in repr(final.continuation["factor_state"])


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
        )
    )
