"""Durable, typed Factor daily evidence partitions."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from datetime import date

import pyarrow as pa
import pyarrow.parquet as pq
from pyarrow import ArrowException

from thesistrace.publication import (
    JsonPayload,
    ParquetRowsPayload,
    Publication,
    PublishedRef,
    StagedPayload,
    VerifiedBundle,
)
from thesistrace.publication.serialization import ParquetWriterContract
from thesistrace.research_kernel.factor_evidence import validate_factor_observations
from thesistrace.research_kernel.factor_periods import FactorPeriodAccumulator
from thesistrace.research_run.result_schema import FactorPeriodStatistic, FactorSummaryValue

_ALPHA_REASONS = ("missing_expression", "missing_industry", "industry_group_too_small")
_LABEL_REASONS = (
    "confirmed_market_open_unavailable",
    "data_unavailable",
    "right_censored_by_research_period_end",
)
_QUANTILES = ("q1", "q2", "q3", "q4", "q5")

FACTOR_DAILY_CONTRACT = ParquetWriterContract(
    name="research-result-factor-daily-observations",
    version=1,
    schema=pa.schema(
        [
            pa.field("horizon", pa.int64(), nullable=False),
            pa.field("session", pa.string(), nullable=False),
            pa.field("label_entry_session", pa.string()),
            pa.field("label_exit_session", pa.string()),
            pa.field("label_status", pa.string(), nullable=False),
            *(
                pa.field(name, pa.int64(), nullable=False)
                for name in (
                    "alpha_candidate_count",
                    "alpha_sample_count",
                    "sample_count",
                )
            ),
            *(pa.field("alpha_" + reason, pa.int64(), nullable=False) for reason in _ALPHA_REASONS),
            *(pa.field("label_" + reason, pa.int64(), nullable=False) for reason in _LABEL_REASONS),
            pa.field("ic", pa.float64()),
            pa.field("rank_ic", pa.float64()),
            pa.field("correlation_reason", pa.string()),
            *(pa.field(name + "_return", pa.float64()) for name in _QUANTILES),
            *(pa.field(name + "_count", pa.int64(), nullable=False) for name in _QUANTILES),
            pa.field("top_bottom_return", pa.float64()),
            pa.field("quantile_reason", pa.string()),
        ]
    ),
    sort_keys=("horizon", "session"),
)


def factor_daily_payload(rows: Sequence[Mapping[str, object]]) -> ParquetRowsPayload:
    values = validate_factor_observations([dict(row) for row in rows])
    encoded = []
    for value in values:
        alpha = value.pop("alpha_exclusions")
        labels = value.pop("label_exclusions")
        returns = value.pop("quantile_returns")
        counts = value.pop("quantile_counts")
        encoded.append(
            {
                **value,
                **{"alpha_" + reason: alpha.get(reason, 0) for reason in _ALPHA_REASONS},
                **{"label_" + reason: labels.get(reason, 0) for reason in _LABEL_REASONS},
                **{name + "_return": returns[name] for name in _QUANTILES},
                **{name + "_count": counts[name] for name in _QUANTILES},
            }
        )
    return ParquetRowsPayload(rows=tuple(encoded), contract=FACTOR_DAILY_CONTRACT)


def read_factor_daily_partition(data: bytes) -> list[dict[str, object]]:
    try:
        table = pq.read_table(pa.BufferReader(data))
    except ArrowException as error:
        raise ValueError("Factor daily partition is unreadable") from error
    if not table.schema.equals(FACTOR_DAILY_CONTRACT.schema, check_metadata=False):
        raise ValueError("Factor daily partition schema is invalid")
    if any(table[field.name].null_count for field in table.schema if not field.nullable):
        raise ValueError("Factor daily partition is missing required values")
    rows = []
    for row in table.to_pylist():
        alpha = {reason: row.pop("alpha_" + reason) for reason in _ALPHA_REASONS}
        labels = {reason: row.pop("label_" + reason) for reason in _LABEL_REASONS}
        rows.append(
            {
                "alpha_exclusions": {reason: count for reason, count in alpha.items() if count},
                "label_exclusions": {reason: count for reason, count in labels.items() if count},
                "quantile_returns": {name: row.pop(name + "_return") for name in _QUANTILES},
                "quantile_counts": {name: row.pop(name + "_count") for name in _QUANTILES},
                **row,
            }
        )
    return validate_factor_observations(rows)


FACTOR_DAILY_PARTITION_PREFIX = "factor_daily_observations.part-"


class FactorEvidencePublication:
    """Accumulate verified descriptors and statistics without retaining daily rows."""

    def __init__(self) -> None:
        self._accumulator = FactorPeriodAccumulator()
        self._descriptors: list[dict[str, object]] = []
        self._payloads: dict[str, StagedPayload | ParquetRowsPayload] = {}

    def add(
        self, payload: StagedPayload | ParquetRowsPayload, rows: list[dict[str, object]]
    ) -> None:
        if isinstance(payload, ParquetRowsPayload):
            valid_payload = payload == factor_daily_payload(rows)
        else:
            valid_payload = (
                payload.media_type == "application/vnd.apache.parquet"
                and payload.serialization == {
                    "format": "canonical-parquet",
                    "writer_contract": FACTOR_DAILY_CONTRACT.descriptor(),
                }
            )
        if not rows or not valid_payload:
            raise ValueError("Factor daily partition is invalid")
        self._accumulator.add(rows)
        name = f"{FACTOR_DAILY_PARTITION_PREFIX}{len(self._descriptors):06d}"
        self._payloads[name] = payload
        ranges = []
        for horizon in (1, 5, 20):
            sessions = [row["session"] for row in rows if row["horizon"] == horizon]
            if sessions:
                ranges.append(
                    {
                        "horizon": horizon,
                        "row_count": len(sessions),
                        "first_session": sessions[0],
                        "last_session": sessions[-1],
                    }
                )
        self._descriptors.append({"name": name, "row_count": len(rows), "horizons": ranges})

    def finish(
        self, *, summary: Mapping[str, object]
    ) -> dict[str, JsonPayload | StagedPayload | ParquetRowsPayload]:
        expected = FactorSummaryValue.model_validate(summary).model_dump(mode="json", by_alias=True)
        payloads: dict[str, JsonPayload | StagedPayload | ParquetRowsPayload] = dict(self._payloads)
        actual = self._accumulator.full_summary(
            alpha_checksums={h: expected["horizons"][str(h)]["alpha_checksum"] for h in (1, 5, 20)}
        )
        if actual != expected:
            raise ValueError("Factor daily evidence does not match its summary")
        payloads["factor_daily_observations"] = JsonPayload(
            {
                "format": "partitioned-parquet",
                "writer_contract": FACTOR_DAILY_CONTRACT.descriptor(),
                "partitions": list(self._descriptors),
            }
        )
        payloads["factor_period_statistics"] = JsonPayload(self._accumulator.finish())
        return payloads


def factor_evidence_publication_payloads(
    partitions: Iterable[tuple[StagedPayload, list[dict[str, object]]]],
    *,
    summary: Mapping[str, object],
) -> dict[str, JsonPayload | StagedPayload]:
    builder = FactorEvidencePublication()
    for payload, rows in partitions:
        builder.add(payload, rows)
    return builder.finish(summary=summary)


def factor_partition_descriptors(bundle: VerifiedBundle) -> list[dict[str, object]]:
    if bundle.kind != "research.result":
        raise ValueError("Factor evidence requires a Research Result")
    payload = bundle.payloads.get("factor_daily_observations")
    if payload is None or payload.media_type != "application/json":
        raise ValueError("Factor daily descriptor is missing")
    value = json.loads(payload.content)
    if (
        not isinstance(value, dict)
        or set(value) != {"format", "writer_contract", "partitions"}
        or value["format"] != "partitioned-parquet"
        or value["writer_contract"] != FACTOR_DAILY_CONTRACT.descriptor()
        or not isinstance(value["partitions"], list)
        or not value["partitions"]
    ):
        raise ValueError("Factor daily descriptor is invalid")
    previous = {}
    for index, part in enumerate(value["partitions"]):
        if (
            not isinstance(part, dict)
            or set(part) != {"name", "row_count", "horizons"}
            or part["name"] != f"{FACTOR_DAILY_PARTITION_PREFIX}{index:06d}"
            or type(part["row_count"]) is not int
            or part["row_count"] < 1
            or not isinstance(part["horizons"], list)
            or not part["horizons"]
        ):
            raise ValueError("Factor partition descriptor is invalid")
        seen = []
        total = 0
        for span in part["horizons"]:
            if (
                not isinstance(span, dict)
                or set(span) != {"horizon", "row_count", "first_session", "last_session"}
                or type(span["horizon"]) is not int
                or span["horizon"] not in (1, 5, 20)
                or type(span["row_count"]) is not int
                or span["row_count"] < 1
            ):
                raise ValueError("Factor horizon descriptor is invalid")
            first, last = span["first_session"], span["last_session"]
            _require_session(first)
            _require_session(last)
            h = span["horizon"]
            if first > last or first <= previous.get(h, ""):
                raise ValueError("Factor partition dates are not ordered")
            previous[h] = last
            total += span["row_count"]
            seen.append(h)
        if seen != sorted(set(seen)) or total != part["row_count"]:
            raise ValueError("Factor partition counts are inconsistent")
    if set(previous) != {1, 5, 20}:
        raise ValueError("Factor descriptor is missing horizons")
    return value["partitions"]


def read_factor_described_partition(
    bundle: VerifiedBundle,
    part: Mapping[str, object],
) -> list[dict[str, object]]:
    payload = bundle.payloads.get(part["name"])
    if (
        bundle.kind != "research.result"
        or payload is None
        or payload.media_type != "application/vnd.apache.parquet"
        or payload.serialization
        != {
            "format": "canonical-parquet",
            "writer_contract": FACTOR_DAILY_CONTRACT.descriptor(),
        }
    ):
        raise ValueError("Factor partition encoding is invalid")
    rows = read_factor_daily_partition(payload.content)
    ranges = []
    for horizon in (1, 5, 20):
        sessions = [row["session"] for row in rows if row["horizon"] == horizon]
        if sessions:
            ranges.append(
                {
                    "horizon": horizon,
                    "row_count": len(sessions),
                    "first_session": sessions[0],
                    "last_session": sessions[-1],
                }
            )
    if len(rows) != part["row_count"] or ranges != part["horizons"]:
        raise ValueError("Factor partition evidence does not match descriptor")
    return rows


def _require_session(value: object) -> None:
    if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
        raise ValueError("Factor signal date is invalid")


def read_factor_daily_page(
    publication: Publication,
    published_ref: PublishedRef,
    *,
    horizon: int,
    start_session: str | None = None,
    end_session: str | None = None,
    after: str | None = None,
    limit: int = 20,
) -> tuple[list[dict[str, object]], str | None]:
    if type(horizon) is not int or horizon not in (1, 5, 20):
        raise ValueError("Factor horizon is invalid")
    if type(limit) is not int or not 1 <= limit <= 50:
        raise ValueError("Factor page limit must be between 1 and 50")
    for value in (start_session, end_session, after):
        if value is not None:
            _require_session(value)
    if start_session is not None and end_session is not None and start_session > end_session:
        raise ValueError("Factor signal date range is invalid")
    descriptor = publication.read_selected(published_ref, frozenset({"factor_daily_observations"}))
    parts = factor_partition_descriptors(descriptor)
    selected = []
    for part in parts:
        span = next((span for span in part["horizons"] if span["horizon"] == horizon), None)
        if span is None:
            continue
        if (
            (after is not None and span["last_session"] <= after)
            or (start_session is not None and span["last_session"] < start_session)
            or (end_session is not None and span["first_session"] > end_session)
        ):
            continue
        bundle = publication.read_selected(published_ref, frozenset({part["name"]}))
        rows = read_factor_described_partition(bundle, part)
        for row in rows:
            session = row["session"]
            if (
                row["horizon"] == horizon
                and (after is None or session > after)
                and (start_session is None or session >= start_session)
                and (end_session is None or session <= end_session)
            ):
                selected.append(row)
                if len(selected) > limit:
                    return selected[:limit], selected[limit - 1]["session"]
    return selected, None


FACTOR_SUMMARY_PAYLOAD_NAMES = frozenset(
    {
        "factor_summary",
        "factor_daily_observations",
        "factor_period_statistics",
    }
)


def read_factor_summary_bundle(bundle: VerifiedBundle) -> dict[str, object]:
    """Read the current summary and its coverage inventory without opening daily partitions."""
    parts = factor_partition_descriptors(bundle)
    summaries = {}
    for name in ("factor_summary", "factor_period_statistics"):
        payload = bundle.payloads.get(name)
        if payload is None or payload.media_type != "application/json":
            raise ValueError("Required Factor summary evidence is missing")
        summaries[name] = json.loads(payload.content)
    summary = FactorSummaryValue.model_validate(summaries["factor_summary"]).model_dump(
        mode="json",
        by_alias=True,
    )
    raw_periods = summaries["factor_period_statistics"]
    if not isinstance(raw_periods, list) or not raw_periods:
        raise ValueError("Factor period statistics are missing")
    periods = [
        FactorPeriodStatistic.model_validate(row).model_dump(mode="json") for row in raw_periods
    ]
    keys = [(row["horizon"], row["granularity"], row["period"]) for row in periods]
    if keys != sorted(set(keys)):
        raise ValueError("Factor period statistics are not uniquely ordered")
    for h in (1, 5, 20):
        spans = [span for part in parts for span in part["horizons"] if span["horizon"] == h]
        full = [row for row in periods if row["horizon"] == h and row["granularity"] == "all"]
        expected = summary["horizons"][str(h)]
        if (
            len(full) != 1
            or full[0]["period"] != "all"
            or full[0]["summary"] != expected["summary"]
            or sum(span["row_count"] for span in spans)
            != expected["coverage"]["signal_session_count"]
            or any(full[0]["coverage"][key] != value for key, value in expected["coverage"].items())
            or full[0]["coverage"]["first_signal_session"] != spans[0]["first_session"]
            or full[0]["coverage"]["last_signal_session"] != spans[-1]["last_session"]
        ):
            raise ValueError("Factor summary and evidence coverage are inconsistent")
    return summary


def read_factor_period_page(
    publication: Publication,
    published_ref: PublishedRef,
    *,
    horizon: int,
    granularity: str,
    after: str | None = None,
    limit: int = 20,
) -> tuple[list[dict[str, object]], str | None]:
    if type(horizon) is not int or horizon not in (1, 5, 20):
        raise ValueError("Factor horizon is invalid")
    if granularity not in ("all", "month", "year"):
        raise ValueError("Factor period granularity is invalid")
    if type(limit) is not int or not 1 <= limit <= 50:
        raise ValueError("Factor page limit must be between 1 and 50")
    if after is not None:
        if granularity == "all":
            valid = after == "all"
        else:
            suffix = "-01" if granularity == "month" else "-01-01"
            try:
                _require_session(after + suffix)
                valid = True
            except (ValueError, TypeError):
                valid = False
        if not valid:
            raise ValueError("Factor period continuation is invalid")
    bundle = publication.read_selected(published_ref, FACTOR_SUMMARY_PAYLOAD_NAMES)
    read_factor_summary_bundle(bundle)
    periods = json.loads(bundle.payloads["factor_period_statistics"].content)
    selected = [
        row
        for row in periods
        if row["horizon"] == horizon
        and row["granularity"] == granularity
        and (after is None or row["period"] > after)
    ]
    return selected[:limit], selected[limit - 1]["period"] if len(selected) > limit else None
