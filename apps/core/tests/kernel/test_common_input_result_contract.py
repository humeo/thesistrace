from __future__ import annotations

import pytest
from pydantic import ValidationError

from thesistrace.research_kernel.common_observations import CommonInputObservation


def observation(**changes):
    return {
        "session": "2026-01-06",
        "identifier": "universe_return",
        "industry_code": None,
        "value": 0.04,
        "member_count": 3,
        "valid_count": 2,
        "exclusions": {"invalid_current_close": 1},
        **changes,
    }


def test_common_observation_preserves_actual_scope_counts_and_missing_values():
    assert CommonInputObservation.model_validate(observation()).model_dump() == observation()
    empty = observation(value=None, member_count=0, valid_count=0, exclusions={})
    assert CommonInputObservation.model_validate(empty).value is None
    industry = observation(identifier="industry_return", industry_code="801010")
    assert CommonInputObservation.model_validate(industry).industry_code == "801010"


@pytest.mark.parametrize(
    "changes",
    [
        {"valid_count": 4},
        {"exclusions": {}},
        {"exclusions": {"invented": 1}},
        {"valid_count": True},
        {"value": float("nan")},
        {"value": float("inf")},
        {"value": None},
        {"identifier": "universe_advancing_fraction", "value": 1.2},
        {"industry_code": "801010"},
        {"identifier": "industry_return", "industry_code": "801020"},
        {"value": 0.0, "valid_count": 0, "exclusions": {"insufficient_history": 3}},
    ],
)
def test_common_observation_rejects_inconsistent_or_ambiguous_evidence(changes):
    with pytest.raises(ValidationError):
        CommonInputObservation.model_validate(observation(**changes))


def test_result_rows_keep_only_requested_sessions_and_reject_duplicate_metrics():
    from thesistrace.research_kernel.common_observations import (
        CommonInputObservationError,
        common_input_observation_rows,
    )

    value = observation()
    metric = {key: item for key, item in value.items() if key != "session"}
    matrix = {
        "sessions": [
            {"session": "2026-01-05", "common_inputs": [metric]},
            {"session": "2026-01-06", "common_inputs": [metric]},
        ]
    }
    assert common_input_observation_rows(matrix, sessions=("2026-01-06",)) == [value]
    matrix["sessions"][1]["common_inputs"].append(metric)
    with pytest.raises(CommonInputObservationError):
        common_input_observation_rows(matrix, sessions=("2026-01-06",))


def test_common_observations_round_trip_through_canonical_parquet():
    from thesistrace.publication.serialization import parquet_bytes
    from thesistrace.research_run.result import (
        common_input_observation_payload,
        read_common_input_observation_partition,
    )

    values = [
        observation(),
        observation(
            session="2026-01-07",
            identifier="industry_advancing_fraction",
            industry_code="801010",
            value=None,
            member_count=0,
            valid_count=0,
            exclusions={},
        ),
    ]
    payload = common_input_observation_payload(values)
    data = parquet_bytes(payload.rows, contract=payload.contract)
    assert read_common_input_observation_partition(data) == values


@pytest.mark.parametrize("change", [{"valid_count": 9}, {"industry_code": "801020"}])
def test_common_partition_reader_rejects_invalid_stored_evidence(change):
    from thesistrace.publication.serialization import parquet_bytes
    from thesistrace.research_run.result import (
        ResearchResultError,
        common_input_observation_payload,
        read_common_input_observation_partition,
    )

    payload = common_input_observation_payload([observation()])
    rows = [{**payload.rows[0], **change}]
    with pytest.raises(ResearchResultError):
        read_common_input_observation_partition(parquet_bytes(rows, payload.contract))


def test_common_partition_bytes_are_order_independent_and_duplicates_are_rejected():
    from thesistrace.publication.serialization import parquet_bytes
    from thesistrace.research_run.result import (
        ResearchResultError,
        common_input_observation_payload,
    )

    values = [observation(), observation(session="2026-01-07")]
    forward = common_input_observation_payload(values)
    reverse = common_input_observation_payload(list(reversed(values)))
    assert parquet_bytes(forward.rows, forward.contract) == parquet_bytes(
        reverse.rows, reverse.contract
    )
    with pytest.raises(ResearchResultError):
        common_input_observation_payload([values[0], values[0]])


def test_chunk_statistics_must_exactly_cover_frozen_inputs_and_new_sessions():
    from thesistrace.alpha_language import alpha_language
    from thesistrace.research_run.result import (
        ResearchResultError,
        validate_common_chunk_observations,
    )

    expression = alpha_language.compile("close * universe_return()").expression
    values = [observation()]
    validate_common_chunk_observations(values, expression=expression, sessions=("2026-01-06",))
    for invalid in ([], values * 2, [observation(session="2026-01-05")]):
        with pytest.raises(ResearchResultError):
            validate_common_chunk_observations(
                invalid, expression=expression, sessions=("2026-01-06",)
            )


def test_common_pages_preserve_same_session_metrics_and_skip_completed_partitions():
    from thesistrace.publication import VerifiedBundle, VerifiedPayload
    from thesistrace.publication.serialization import canonical_json_bytes, parquet_bytes
    from thesistrace.research_run.result import (
        COMMON_INPUT_OBSERVATIONS_CONTRACT,
        COMMON_INPUT_PARTITION_PREFIX,
        common_input_observation_payload,
        read_common_input_observation_page,
    )

    groups = [
        [
            observation(identifier="industry_return", industry_code=code)
            for code in ("801010", "801030")
        ],
        [observation(session="2026-01-07")],
        [observation(session="2026-01-08")],
    ]
    payloads = {}
    parts = []
    for index, rows in enumerate(groups):
        name = f"{COMMON_INPUT_PARTITION_PREFIX}{index:06d}"
        payload = common_input_observation_payload(rows)
        payloads[name] = VerifiedPayload(
            media_type="application/vnd.apache.parquet",
            content=parquet_bytes(payload.rows, payload.contract),
            serialization={
                "format": "canonical-parquet",
                "writer_contract": payload.contract.descriptor(),
            },
        )
        parts.append(
            {
                "name": name,
                "row_count": len(rows),
                "first_session": rows[0]["session"],
                "last_session": rows[-1]["session"],
            }
        )
    payloads["common_input_observations"] = VerifiedPayload(
        media_type="application/json",
        content=canonical_json_bytes(
            {
                "format": "partitioned-parquet",
                "writer_contract": COMMON_INPUT_OBSERVATIONS_CONTRACT.descriptor(),
                "partitions": parts,
            }
        ),
        serialization={"format": "canonical-json", "version": 1},
    )

    class PublicationReader:
        def __init__(self):
            self.loaded = []

        def read_selected(self, ref, names):
            self.loaded.append(names)
            return VerifiedBundle(
                kind="research.result",
                manifest_sha256="0" * 64,
                provenance={},
                payloads={name: payloads[name] for name in names},
            )

    reader = PublicationReader()
    first = read_common_input_observation_page(reader, None, limit=1)
    assert first.value == groups[0][:1]
    second = read_common_input_observation_page(reader, None, after=first.next_after, limit=1)
    assert second.value == groups[0][1:]
    third = read_common_input_observation_page(reader, None, after=second.next_after, limit=1)
    assert third.value == groups[1]
    reader.loaded.clear()
    last = read_common_input_observation_page(reader, None, after=third.next_after, limit=1)
    assert last.value == groups[2]
    assert last.next_after is None
    assert all(parts[0]["name"] not in names for names in reader.loaded)


@pytest.mark.parametrize("arguments", [{"limit": 0}, {"limit": True}, {"after": "2026-01-06"}])
def test_common_page_rejects_invalid_boundary_before_reading_publication(arguments):
    from thesistrace.research_run.result import (
        ResearchResultError,
        read_common_input_observation_page,
    )

    with pytest.raises(ResearchResultError):
        read_common_input_observation_page(None, None, **arguments)
