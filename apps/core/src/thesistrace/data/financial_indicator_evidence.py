"""Immutable indicator observations and announcement-aligned version evidence."""

from __future__ import annotations

import hashlib
import json
from bisect import bisect_right
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from thesistrace.data.financial_collection import RawFinancialBatchStore
from thesistrace.data.financial_indicator_source import FinancialIndicatorProvider
from thesistrace.data.generation_files import AddressedFileStore
from thesistrace.data.source import RawSourceResponse
from thesistrace.publication.serialization import canonical_json_bytes


class FinancialIndicatorObservationStore:
    """Retain observations using the existing immutable financial raw store."""

    def __init__(self, store: RawFinancialBatchStore) -> None:
        self._store = store

    def save(self, response: RawSourceResponse, *, observed_at: datetime) -> str:
        if observed_at.tzinfo is None:
            raise ValueError("Indicator observation requires an aware timestamp")
        payload = {
            "source": "fina_indicator",
            "observed_at": observed_at.astimezone(UTC).isoformat(),
            "fields": response.fields,
            "items": response.items,
        }
        _validate_observation(payload)
        return self._store.store(canonical_json_bytes(payload))

    def read(self, digest: str) -> dict[str, object]:
        payload = self._store.read(digest)
        _validate_observation(payload)
        return payload


def _validate_observation(payload: Mapping[str, object]) -> None:
    if set(payload) != {"source", "observed_at", "fields", "items"}:
        raise ValueError("Invalid indicator observation shape")
    if payload["source"] != "fina_indicator":
        raise ValueError("Invalid indicator observation source")
    timestamp = datetime.fromisoformat(str(payload["observed_at"]))
    if timestamp.tzinfo is None:
        raise ValueError("Indicator observation requires an aware timestamp")
    fields = payload["fields"]
    if not isinstance(fields, (list, tuple)) or not all(isinstance(f, str) for f in fields):
        raise ValueError("Invalid indicator fields")
    if len(fields) != len(set(fields)) or not {"ts_code", "end_date", "ann_date"} <= set(fields):
        raise ValueError("Invalid indicator identity columns")
    items = payload["items"]
    if not isinstance(items, (list, tuple)):
        raise ValueError("Invalid indicator rows")
    for row in items:
        if not isinstance(row, (list, tuple)) or len(row) != len(fields):
            raise ValueError("Invalid indicator row width")


def indicator_versions(
    observations: Iterable[Mapping[str, object]],
    *,
    instrument_ids: Mapping[str, str],
    sessions: Sequence[str],
) -> tuple[dict[str, object], ...]:
    """Project explicit observations, without inventing supplier revision order.

    Consecutive identical observations collapse; a reverted value is a new state
    with the content's original first-observed provenance. A first historical
    observation may be aligned to disclosure; subsequently observed changes to
    that disclosure only become available after they were observed in Shanghai.
    Conflicting simultaneous observations stay quarantined.
    """
    return IndicatorVersionProjector(sessions).project(
        observations, instrument_ids=instrument_ids,
    )


def received_indicator_reports(
    rows: Iterable[Mapping[str, object]], *, through: str,
) -> tuple[tuple[str, str, str], ...]:
    """Report presence uses the latest nonconflicting state, independently of field nulls."""
    latest = {}
    for row in rows:
        key = (row["instrument_id"], row["source_report_period"], row["source_published_date"])
        event = row["observation_event_at"]
        if key not in latest or event > latest[key][0]:
            latest[key] = (event, set(), set())
        if event == latest[key][0]:
            latest[key][1].add(row["source_row_sha256"])
            latest[key][2].add(row["availability_status"])
    reports = []
    for (instrument, period, published), (_event, hashes, statuses) in latest.items():
        if len(hashes) != 1 or not statuses <= {"available", "outside_calendar"}:
            continue
        try:
            period = datetime.strptime(str(period), "%Y%m%d").date().isoformat()
            published = datetime.strptime(str(published), "%Y%m%d").date().isoformat()
        except ValueError:
            continue
        if period <= published <= through:
            reports.append((str(instrument), period, published))
    return tuple(sorted(reports))


class IndicatorVersionProjector:
    """One validated calendar shared by independent security projections."""

    def __init__(self, sessions: Sequence[str]) -> None:
        calendar = tuple(sessions)
        if calendar != tuple(sorted(set(calendar))):
            raise ValueError("Indicator calendar must be unique and ordered")
        for session in calendar:
            if date.fromisoformat(session).isoformat() != session:
                raise ValueError("Invalid indicator session")
        self._calendar = calendar

    def project(
        self,
        observations: Iterable[Mapping[str, object]],
        *,
        instrument_ids: Mapping[str, str],
    ) -> tuple[dict[str, object], ...]:
        calendar = self._calendar
        grouped = defaultdict(lambda: defaultdict(set))
        rows_by_digest = {}
        for observation in observations:
            _validate_observation(observation)
            observed = datetime.fromisoformat(str(observation["observed_at"])).astimezone(UTC)
            for item in observation["items"]:
                row = dict(zip(observation["fields"], item, strict=True))
                code = row["ts_code"]
                if code not in instrument_ids:
                    raise ValueError("Indicator instrument is absent from historical identity")
                period = str(row["end_date"])
                if datetime.strptime(period, "%Y%m%d").strftime("%Y%m%d") != period:
                    raise ValueError("Invalid indicator report period")
                digest = hashlib.sha256(canonical_json_bytes(row)).hexdigest()
                key = (code, period, row["ann_date"])
                rows_by_digest.setdefault(digest, row)
                grouped[key][observed].add(digest)
        result = []
        for (code, period, announcement), by_time in grouped.items():
            earliest = {}
            previous_state = None
            for index, observed in enumerate(sorted(by_time)):
                values = by_time[observed]
                for digest in values:
                    earliest.setdefault(digest, observed)
                state = frozenset(values)
                if state == previous_state:
                    continue
                previous_state = state
                status = "available"
                try:
                    published = datetime.strptime(str(announcement), "%Y%m%d").date()
                    if published.strftime("%Y%m%d") != announcement:
                        raise ValueError("Invalid source announcement")
                    if published < datetime.strptime(period, "%Y%m%d").date():
                        status = "invalid_announcement"
                except ValueError:
                    status = "missing_announcement"
                if len(values) > 1 and status == "available":
                    status = "conflicting_observation"
                effective = None
                if status in {"available", "conflicting_observation"}:
                    cutoff = published
                    if index:
                        cutoff = max(cutoff, observed.astimezone(ZoneInfo("Asia/Shanghai")).date())
                    position = bisect_right(calendar, cutoff.isoformat())
                    if position < len(calendar):
                        effective = calendar[position]
                    else:
                        status = "outside_calendar"
                for digest in values:
                    row = rows_by_digest[digest]
                    result.append(
                        {
                            **row,
                            "instrument_id": instrument_ids[code],
                            "source_report_period": period,
                            "source_published_date": announcement,
                            "source_row_sha256": digest,
                            "first_observed_at": earliest[digest].isoformat(),
                            "observation_event_at": observed.isoformat(),
                            "state_effective_session": effective,
                            "effective_available_session": (
                                effective if status == "available" else None
                            ),
                            "availability_status": status,
                        }
                    )
        return tuple(
            sorted(
                result,
                key=lambda row: (
                    row["instrument_id"],
                    row["source_report_period"],
                    row["observation_event_at"],
                    row["source_row_sha256"],
                ),
            )
        )


class FinancialIndicatorCheckpoint:
    """Request receipts scoped to one collection; writers hold the mounted-data lock.

    The collection owner exhausts the adapter's shards and verifies all targets
    before publishing. Individual successful requests are not global coverage.
    """

    def __init__(
        self,
        root: Path,
        *,
        collection_key: str,
        provider: FinancialIndicatorProvider,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if not collection_key:
            raise ValueError("Indicator checkpoint requires a collection key")
        self._root = root
        self._key = collection_key
        self._provider = provider
        self._clock = clock
        self._files = AddressedFileStore(root)
        self._store = FinancialIndicatorObservationStore(RawFinancialBatchStore(root))
        self._directory = (
            root
            / ".operator"
            / "indicator-requests"
            / hashlib.sha256(collection_key.encode()).hexdigest()
        )
        self._used: dict[str, dict[str, object]] = {}

    def query_raw(
        self,
        api_name: str,
        *,
        params: Mapping[str, object],
        fields: Sequence[str],
    ) -> RawSourceResponse:
        if api_name != "fina_indicator" or set(params) != {"ts_code", "start_date", "end_date"}:
            raise ValueError("Invalid indicator checkpoint request")
        request = {"api_name": api_name, "params": dict(params), "fields": list(fields)}
        request_id = hashlib.sha256(canonical_json_bytes(request)).hexdigest()
        directory = self._directory / request_id
        paths = tuple(directory.glob("*.json"))
        if len(paths) > 1:
            raise ValueError("Conflicting indicator request receipts")
        if paths:
            path = paths[0]
            receipt = json.loads(self._files.read(path, path.stem, max_byte_count=1024 * 1024))
            if (
                set(receipt) != {"collection_key", "request", "observation_sha256"}
                or receipt["collection_key"] != self._key
                or receipt["request"] != request
            ):
                raise ValueError("Indicator receipt scope differs")
            observation = self._store.read(receipt["observation_sha256"])
            response = RawSourceResponse(
                fields=tuple(observation["fields"]),
                items=tuple(tuple(row) for row in observation["items"]),
            )
        else:
            response = self._provider.query_raw(api_name, params=params, fields=fields)
            digest = self._store.save(response, observed_at=self._clock())
            receipt = {
                "collection_key": self._key,
                "request": request,
                "observation_sha256": digest,
            }
            content = canonical_json_bytes(receipt)
            checksum = hashlib.sha256(content).hexdigest()
            self._files.store(directory / f"{checksum}.json", checksum, content)
            observation = self._store.read(digest)
        self._used[request_id] = {"request": request, "observation": observation}
        return response

    def observations(self) -> tuple[dict[str, object], ...]:
        """Return validated leaf observations, excluding ambiguous capped parents."""
        observations = []
        for item in self._used.values():
            request, observation = item["request"], item["observation"]
            fields = observation["fields"]
            if not set(request["fields"]) <= set(fields):
                raise ValueError("Indicator receipt lacks requested columns")
            for row in observation["items"]:
                source = dict(zip(fields, row, strict=True))
                period = str(source["end_date"])
                if (
                    source["ts_code"] != request["params"]["ts_code"]
                    or datetime.strptime(period, "%Y%m%d").strftime("%Y%m%d") != period
                    or not request["params"]["start_date"]
                    <= period
                    <= request["params"]["end_date"]
                ):
                    raise ValueError("Indicator receipt contains unrelated source rows")
            if len(observation["items"]) < 100:
                observations.append(observation)
        return tuple(observations)

    def completed_requests(self) -> tuple[dict[str, object], ...]:
        """Bind each validated leaf's request coordinates to its raw observation."""
        self.observations()
        return tuple(
            {
                "request": item["request"],
                "observation_sha256": hashlib.sha256(
                    canonical_json_bytes(item["observation"])
                ).hexdigest(),
            }
            for item in self._used.values()
            if len(item["observation"]["items"]) < 100
        )


def validate_indicator_collection_evidence(
    store: RawFinancialBatchStore,
    digest: str,
) -> dict[str, object]:
    """Prove that complete leaves cover exactly the declared report-date interval."""
    from thesistrace.data.financial_indicator_source import FINANCIAL_INDICATOR_SOURCE_FIELDS

    evidence = store.read(digest)
    if (
        set(evidence)
        != {
            "source",
            "collection_key",
            "instrument_id",
            "ts_code",
            "start_date",
            "end_date",
            "checked_through",
            "completed_requests",
        }
        or evidence["source"] != "fina_indicator"
        or any(
            not isinstance(evidence[key], str) or not evidence[key]
            for key in ("collection_key", "instrument_id", "ts_code")
        )
    ):
        raise ValueError("Invalid indicator collection evidence")
    start = datetime.strptime(evidence["start_date"], "%Y%m%d").date()
    end = datetime.strptime(evidence["end_date"], "%Y%m%d").date()
    if start > end or end > date.fromisoformat(evidence["checked_through"]):
        raise ValueError("Invalid indicator collection dates")
    receipts = evidence["completed_requests"]
    if not isinstance(receipts, list) or not receipts:
        raise ValueError("Indicator collection has no completed requests")
    intervals = []
    observations = FinancialIndicatorObservationStore(store)
    for receipt in receipts:
        if not isinstance(receipt, dict) or set(receipt) != {"request", "observation_sha256"}:
            raise ValueError("Invalid completed indicator request")
        request = receipt["request"]
        if (
            not isinstance(request, dict)
            or set(request) != {"api_name", "params", "fields"}
            or request["api_name"] != "fina_indicator"
            or request["fields"] != list(FINANCIAL_INDICATOR_SOURCE_FIELDS)
        ):
            raise ValueError("Invalid indicator request source contract")
        params = request["params"]
        if (
            not isinstance(params, dict)
            or set(params) != {"ts_code", "start_date", "end_date"}
            or params["ts_code"] != evidence["ts_code"]
        ):
            raise ValueError("Invalid indicator request identity")
        lower = datetime.strptime(params["start_date"], "%Y%m%d").date()
        upper = datetime.strptime(params["end_date"], "%Y%m%d").date()
        if not start <= lower <= upper <= end:
            raise ValueError("Indicator leaf lies outside collection interval")
        observation = observations.read(receipt["observation_sha256"])
        if (
            set(observation["fields"]) != set(FINANCIAL_INDICATOR_SOURCE_FIELDS)
            or len(observation["items"]) >= 100
        ):
            raise ValueError("Indicator leaf lacks columns or may be truncated")
        for item in observation["items"]:
            row = dict(zip(observation["fields"], item, strict=True))
            period = datetime.strptime(str(row["end_date"]), "%Y%m%d").date()
            if row["ts_code"] != evidence["ts_code"] or not lower <= period <= upper:
                raise ValueError("Indicator source row lies outside its request")
        intervals.append((lower, upper))
    next_day = start
    for lower, upper in sorted(intervals):
        if lower != next_day:
            raise ValueError("Indicator collection intervals overlap or have gaps")
        next_day = upper + timedelta(days=1)
    if next_day != end + timedelta(days=1):
        raise ValueError("Indicator collection interval is incomplete")
    return evidence
