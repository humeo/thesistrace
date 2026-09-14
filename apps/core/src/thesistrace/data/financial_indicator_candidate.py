"""Immutable sparse indicator candidates; collection readiness is verified separately."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from thesistrace.data.fields import FINANCIAL_INDICATOR_FIELDS
from thesistrace.data.financial_announcements import FINANCIAL_ANNOUNCEMENT_CATEGORIES
from thesistrace.data.financial_collection import (
    FINANCIAL_HISTORY_FLOOR,
    FinancialCollectionError,
    RawFinancialBatchStore,
)
from thesistrace.data.financial_indicator_evidence import (
    FinancialIndicatorObservationStore,
    indicator_versions,
    validate_indicator_collection_evidence,
)
from thesistrace.data.financial_indicator_series import normalize_indicator_value
from thesistrace.data.financial_indicator_source import FINANCIAL_INDICATOR_SOURCE_FIELDS
from thesistrace.data.generation_files import AddressedFileError, AddressedFileStore
from thesistrace.publication.serialization import (
    ParquetWriterContract,
    canonical_json_bytes,
    parquet_bytes,
)

_METADATA = (
    "instrument_id",
    "source_report_period",
    "source_published_date",
    "source_row_sha256",
    "first_observed_at",
    "observation_event_at",
    "state_effective_session",
    "effective_available_session",
    "availability_status",
)
_SORT_KEYS = ("instrument_id", "source_report_period", "observation_event_at", "source_row_sha256")
_SCHEMA = pa.schema(
    [
        pa.field(name, pa.string(), nullable=name not in _SORT_KEYS)
        for name in (*FINANCIAL_INDICATOR_SOURCE_FIELDS, *_METADATA)
    ]
)
_WRITER = ParquetWriterContract("financial-indicator-versions", 1, _SCHEMA, _SORT_KEYS)


class FinancialIndicatorCandidateStore:
    def __init__(self, root: Path) -> None:
        self._root = root
        self._files = AddressedFileStore(root)
        self._raw = RawFinancialBatchStore(root)
        self._observations = FinancialIndicatorObservationStore(self._raw)

    def _path(self, digest: str, suffix: str) -> Path:
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ValueError("Invalid indicator candidate address")
        directory = {"json": "manifests", "parquet": "objects"}[suffix]
        return self._root / directory / "sha256" / digest[:2] / f"{digest}.{suffix}"

    def _store(self, content: bytes, suffix: str) -> str:
        digest = hashlib.sha256(content).hexdigest()
        self._files.store(self._path(digest, suffix), digest, content)
        return digest

    def build(
        self,
        *,
        collection_evidence_sha256s: Sequence[str],
        instrument_ids: Mapping[str, str],
        sessions: Sequence[str],
        unresolved_sources: Mapping[str, str] | None = None,
        discovery_evidence_sha256s: Sequence[str] = (),
    ) -> str:
        if not sessions or not collection_evidence_sha256s:
            raise ValueError("Indicator candidate requires observations and a calendar")
        if len(set(instrument_ids.values())) != len(instrument_ids):
            raise ValueError("Indicator identities must be unique")
        unresolved = _validated_unresolved_sources(
            {} if unresolved_sources is None else dict(unresolved_sources),
            instrument_ids,
        )
        collections = sorted(set(collection_evidence_sha256s))
        discoveries = sorted(set(discovery_evidence_sha256s))
        by_security = self._collection_observations(
            collections, instrument_ids, sessions, discoveries,
        )
        references = sorted({digest for values in by_security.values() for digest in values})
        partitions = []
        for instrument, row_count, content in _project_partition_contents(
            self._observations,
            by_security,
            instrument_ids,
            sessions,
        ):
            partitions.append(
                {
                    "instrument_id": instrument,
                    "sha256": self._store(content, "parquet"),
                    "row_count": row_count,
                    "byte_count": len(content),
                }
            )
        for instrument, since in self._discovery_unresolved(
            discoveries, instrument_ids, partitions,
        ).items():
            unresolved[instrument] = min(unresolved.get(instrument, since), since)
        return self._store(
            canonical_json_bytes(
                {
                    "family_id": "equity.financial_indicator",
                    "schema_contract": "financial-indicator-wide",
                    "research_sessions": list(sessions),
                    "observation_sha256s": references,
                    "collection_evidence_sha256s": collections,
                    "discovery_evidence_sha256s": discoveries,
                    "instrument_ids": dict(instrument_ids),
                    "unresolved_sources": unresolved,
                    "partitions": partitions,
                    "writer": _WRITER.descriptor(),
                    "field_ids": sorted(field.field_id for field in FINANCIAL_INDICATOR_FIELDS),
                }
            ),
            "json",
        )

    def reopen(self, digest: str) -> dict[str, object]:
        manifest = json.loads(
            self._files.read(self._path(digest, "json"), digest, max_byte_count=64 * 1024 * 1024)
        )
        if (
            set(manifest)
            != {
                "family_id",
                "schema_contract",
                "research_sessions",
                "observation_sha256s",
                "collection_evidence_sha256s",
                "discovery_evidence_sha256s",
                "instrument_ids",
                "unresolved_sources",
                "partitions",
                "writer",
                "field_ids",
            }
            or manifest["family_id"] != "equity.financial_indicator"
            or manifest["schema_contract"] != "financial-indicator-wide"
            or manifest["writer"] != _WRITER.descriptor()
            or not manifest["research_sessions"]
            or manifest["research_sessions"] != sorted(set(manifest["research_sessions"]))
        ):
            raise ValueError("Invalid indicator candidate manifest")
        fields = manifest["field_ids"]
        if (
            not isinstance(fields, list)
            or not fields
            or fields != sorted(set(fields))
            or not set(fields) <= {field.field_id for field in FINANCIAL_INDICATOR_FIELDS}
        ):
            raise ValueError("Invalid indicator candidate field declarations")
        identities = manifest["instrument_ids"]
        if (
            not isinstance(identities, dict)
            or not identities
            or not all(
                isinstance(k, str) and k and isinstance(v, str) and v for k, v in identities.items()
            )
            or len(set(identities.values())) != len(identities)
        ):
            raise ValueError("Invalid indicator candidate identities")
        _validated_unresolved_sources(manifest["unresolved_sources"], identities)
        for session in manifest["research_sessions"]:
            if date.fromisoformat(session).isoformat() != session:
                raise ValueError("Invalid indicator candidate calendar")
        references = manifest["observation_sha256s"]
        if (
            not isinstance(references, list)
            or not references
            or references != sorted(set(references))
        ):
            raise ValueError("Invalid indicator observation references")
        for reference in references:
            self._path(reference, "json")
        partitions = manifest["partitions"]
        if not isinstance(partitions, list):
            raise ValueError("Invalid indicator partitions")
        seen = set()
        for partition in partitions:
            if (
                not isinstance(partition, dict)
                or set(partition) != {"instrument_id", "sha256", "row_count", "byte_count"}
                or partition["instrument_id"] not in identities.values()
                or type(partition["row_count"]) is not int
                or not 1 <= partition["row_count"] <= 4096
                or type(partition["byte_count"]) is not int
                or not 0 < partition["byte_count"] <= 256 * 1024 * 1024
            ):
                raise ValueError("Invalid indicator partition reference")
            self._path(partition["sha256"], "parquet")
            if partition["sha256"] in seen:
                raise ValueError("Duplicate indicator partition")
            seen.add(partition["sha256"])
        return manifest

    def _collection_ranges(self, references, instrument_ids):
        if (
            not isinstance(references, list)
            or not references
            or references != sorted(set(references))
        ):
            raise ValueError("Invalid indicator collection evidence references")
        observations = {code: set() for code in instrument_ids}
        ranges = {code: [] for code in instrument_ids}
        for digest in references:
            evidence = validate_indicator_collection_evidence(self._raw, digest)
            if instrument_ids.get(evidence["ts_code"]) != evidence["instrument_id"]:
                raise ValueError("Indicator collection identity differs from candidate")
            ranges[evidence["ts_code"]].append(
                (
                    datetime.strptime(evidence["start_date"], "%Y%m%d").date(),
                    datetime.strptime(evidence["end_date"], "%Y%m%d").date(),
                )
            )
            observations[evidence["ts_code"]].update(
                receipt["observation_sha256"] for receipt in evidence["completed_requests"]
            )
        return observations, ranges

    def canonical_projection_sha256(self, digest: str) -> str:
        """Identify sparse version facts independently of collection and readiness metadata."""
        manifest = self.reopen(digest)
        return hashlib.sha256(
            canonical_json_bytes(
                {
                    "field_ids": manifest["field_ids"],
                    "partitions": manifest["partitions"],
                }
            )
        ).hexdigest()

    def available_sessions(
        self,
        *,
        collection_evidence_sha256s: Sequence[str],
        instrument_ids: Mapping[str, str],
        sessions: Sequence[str],
        discovery_evidence_sha256s: Sequence[str] = (),
    ) -> tuple[str, ...]:
        """Return only the continuous research prefix supported for every identity."""
        if tuple(sessions) != tuple(sorted(set(sessions))) or not instrument_ids:
            raise ValueError("Invalid indicator coverage scope")
        if not collection_evidence_sha256s:
            return ()
        _observations, ranges = self._collection_ranges(
            sorted(set(collection_evidence_sha256s)),
            instrument_ids,
        )
        discovery_ranges = self._discovery_ranges(discovery_evidence_sha256s, instrument_ids)
        through = []
        for code, intervals in ranges.items():
            # Discovery can extend existing history, never replace its initial collection.
            intervals = list(intervals)
            if any(lower == date(1990, 1, 1) for lower, _upper in intervals):
                intervals.extend(discovery_ranges[code])
            next_day = datetime.strptime(FINANCIAL_HISTORY_FLOOR, "%Y%m%d").date()
            for lower, upper in sorted(intervals):
                if lower > next_day:
                    break
                next_day = max(next_day, upper + timedelta(days=1))
            through.append(next_day - timedelta(days=1))
        end = min(through)
        return tuple(session for session in sessions if date.fromisoformat(session) <= end)

    def _discovery_ranges(self, references, instrument_ids):
        ranges = {code: [] for code in instrument_ids}
        if list(references) != sorted(set(references)):
            raise ValueError("Invalid indicator discovery references")
        for digest in references:
            evidence = self._raw.read(digest)
            if (
                not isinstance(evidence, dict)
                or set(evidence) != {
                    "source", "instrument_ids", "discovery", "source_lineage_sha256",
                }
                or evidence["source"] != "indicator-announcement-discovery"
                or not isinstance(evidence["instrument_ids"], dict)
            ):
                raise ValueError("Invalid indicator discovery evidence")
            self._path(evidence["source_lineage_sha256"], "json")
            scope = evidence["instrument_ids"]
            if any(instrument_ids.get(code) != identity for code, identity in scope.items()):
                raise ValueError("Indicator discovery identity differs from candidate")
            discovery = evidence["discovery"]
            if not isinstance(discovery, dict) or set(discovery) != {
                "start_date", "end_date", "completed_categories", "announcements", "gaps",
            }:
                raise ValueError("Invalid indicator discovery record")
            lower, upper = (date.fromisoformat(discovery[key])
                            for key in ("start_date", "end_date"))
            if lower > upper or not isinstance(discovery["announcements"], list):
                raise ValueError("Invalid indicator discovery interval")
            for item in discovery["announcements"]:
                if (
                    item["ts_code"] not in scope
                    or item["category"] not in FINANCIAL_ANNOUNCEMENT_CATEGORIES
                    or not lower <= date.fromisoformat(item["source_published_date"]) <= upper
                ):
                    raise ValueError("Invalid indicator discovered announcement")
            if (
                discovery["completed_categories"] != list(FINANCIAL_ANNOUNCEMENT_CATEGORIES)
                or discovery["gaps"] != []
            ):
                continue
            for code in scope:
                ranges[code].append((lower, upper))
        return ranges

    def _discovery_unresolved(self, references, instrument_ids, partitions):
        targets = set()
        for digest in references:
            for item in self._raw.read(digest)["discovery"]["announcements"]:
                targets.add((
                    instrument_ids[item["ts_code"]],
                    (None if item["report_period"] is None
                     else item["report_period"].replace("-", "")),
                    item["source_published_date"].replace("-", ""),
                ))
        if not targets:
            return {}
        instruments = {instrument for instrument, _period, _announced in targets}
        columns = (
            "instrument_id", "source_report_period", "source_published_date",
            "observation_event_at", "source_row_sha256", "availability_status",
        )
        latest = {}
        for partition in partitions:
            if partition["instrument_id"] not in instruments:
                continue
            for row in self._read_partition(partition, columns).to_pylist():
                key = (row["instrument_id"], row["source_report_period"],
                       row["source_published_date"])
                if key not in targets:
                    continue
                event = row["observation_event_at"]
                if key not in latest or event > latest[key][0]:
                    latest[key] = (event, set(), set())
                if event == latest[key][0]:
                    latest[key][1].add(row["source_row_sha256"])
                    latest[key][2].add(row["availability_status"])
        unresolved = {}
        for key in targets:
            instrument, period, announced = key
            state = latest.get(key)
            if (
                period is not None and period <= announced and state is not None
                and len(state[1]) == 1
                and state[2] <= {"available", "outside_calendar"}
            ):
                continue
            since = datetime.strptime(announced, "%Y%m%d").date().isoformat()
            unresolved[instrument] = min(unresolved.get(instrument, since), since)
        return unresolved

    def _collection_observations(
        self, references, instrument_ids, sessions, discoveries
    ) -> dict[str, list[str]]:
        observations, ranges = self._collection_ranges(references, instrument_ids)
        if any(not intervals for intervals in ranges.values()):
            raise ValueError("Indicator collection does not cover all candidate identities")
        verified = self.available_sessions(
            collection_evidence_sha256s=references,
            instrument_ids=instrument_ids,
            sessions=sessions,
            discovery_evidence_sha256s=discoveries,
        )
        if verified != tuple(sessions):
            raise ValueError("Indicator collection coverage has a history gap or ends early")
        return {code: sorted(values) for code, values in observations.items()}

    def validate(self, digest: str) -> dict[str, object]:
        """Verify retained references and full partition structure before publishing."""
        try:
            manifest = self.reopen(digest)
            by_security = self._collection_observations(
                manifest["collection_evidence_sha256s"],
                manifest["instrument_ids"],
                manifest["research_sessions"],
                manifest["discovery_evidence_sha256s"],
            )
            references = sorted({digest for values in by_security.values() for digest in values})
            if references != manifest["observation_sha256s"]:
                raise ValueError("Indicator observations differ from collection evidence")
            expected = [
                {
                    "instrument_id": instrument,
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "row_count": row_count,
                    "byte_count": len(content),
                }
                for instrument, row_count, content in _project_partition_contents(
                    self._observations,
                    by_security,
                    manifest["instrument_ids"],
                    manifest["research_sessions"],
                )
            ]
            if expected != manifest["partitions"]:
                raise ValueError("Indicator partitions differ from source observation projection")
            for partition in manifest["partitions"]:
                self._read_partition(partition, _SCHEMA.names)
            inferred = self._discovery_unresolved(
                manifest["discovery_evidence_sha256s"],
                manifest["instrument_ids"], manifest["partitions"],
            )
            if any(
                instrument not in manifest["unresolved_sources"]
                or manifest["unresolved_sources"][instrument] > since
                for instrument, since in inferred.items()
            ):
                raise ValueError("Indicator candidate omits unresolved discovery targets")
            return manifest
        except (AddressedFileError, FinancialCollectionError, KeyError, TypeError) as error:
            raise ValueError("Invalid indicator candidate evidence or partition") from error

    def family_reference(self, digest: str) -> dict[str, object]:
        manifest = self.validate(digest)
        content = self._files.read(
            self._path(digest, "json"), digest, max_byte_count=64 * 1024 * 1024
        )
        return {
            "family_id": "equity.financial_indicator",
            "schema_contract": "financial-indicator-wide",
            "dataset_coverage": {
                "kind": "financial-indicator-observation-range",
                "start": manifest["research_sessions"][0],
                "end": manifest["research_sessions"][-1],
                "revision_coverage": "announcement-aligned-with-observed-revisions",
                "instrument_count": len(manifest["instrument_ids"]),
                "pending_instrument_count": len(manifest["unresolved_sources"]),
                "readiness_status": (
                    "ready_with_pending" if manifest["unresolved_sources"] else "ready"
                ),
                "complete_through_session": max(
                    (
                        day
                        for day in manifest["research_sessions"]
                        if not manifest["unresolved_sources"]
                        or day <= min(manifest["unresolved_sources"].values())
                    ),
                    default=None,
                ),
            },
            "validation_summary": {
                "status": "validated",
                "table_count": 1,
                "row_count": sum(part["row_count"] for part in manifest["partitions"]),
                "object_count": len(manifest["partitions"]),
            },
            "manifest_sha256": digest,
            "manifest_byte_count": len(content),
            "table_names": ["financial_indicator_versions"],
            "field_ids": manifest["field_ids"],
        }

    def _read_partition(self, partition: Mapping[str, object], columns: Sequence[str]) -> pa.Table:
        content = self._files.read(
            self._path(partition["sha256"], "parquet"),
            partition["sha256"],
            expected_byte_count=partition["byte_count"],
            max_byte_count=256 * 1024 * 1024,
        )
        parquet = pq.ParquetFile(pa.BufferReader(content))
        if parquet.schema_arrow != _SCHEMA or parquet.metadata.num_rows != partition["row_count"]:
            raise ValueError("Indicator partition schema or row count differs")
        selected = sorted(set(columns) | {"instrument_id"})
        table = parquet.read(columns=selected)
        if pc.any(pc.not_equal(table["instrument_id"], partition["instrument_id"])).as_py():
            raise ValueError("Indicator partition contains another identity")
        if table["instrument_id"].null_count:
            raise ValueError("Indicator partition contains a missing identity")
        return table.select(columns)

    def read_table(
        self,
        digest: str,
        *,
        columns: set[str],
        instrument_ids: frozenset[str],
        through: str,
    ) -> pa.Table:
        if columns - set(_SCHEMA.names):
            raise ValueError("Unknown indicator source columns")
        manifest = self.reopen(digest)
        tables = []
        selected_columns = sorted(columns | {"state_effective_session"})
        for partition in manifest["partitions"]:
            if partition["instrument_id"] not in instrument_ids:
                continue
            table = self._read_partition(partition, selected_columns)
            table = table.filter(pc.less_equal(table["state_effective_session"], through))
            tables.append(table.select(sorted(columns)))
        if tables:
            return pa.concat_tables(tables)
        return pa.Table.from_pylist(
            [], schema=pa.schema([_SCHEMA.field(c) for c in sorted(columns)])
        )


def _project_partition_contents(observation_store, by_security, instrument_ids, sessions):
    for code, instrument in sorted(instrument_ids.items()):
        # The delegated generator releases this security's decoded payloads before
        # the next security is loaded. Only addresses span the whole universe.
        yield from _project_security_partitions(
            (observation_store.read(digest) for digest in by_security[code]),
            code,
            instrument,
            sessions,
        )


def _project_security_partitions(observations, code, instrument, sessions):
    def validated_observations():
        for observation in observations:
            if set(observation["fields"]) != set(FINANCIAL_INDICATOR_SOURCE_FIELDS):
                raise ValueError("Indicator candidate requires all source columns")
            code_index = observation["fields"].index("ts_code")
            if any(row[code_index] != code for row in observation["items"]):
                raise ValueError("Indicator source identity differs from its collection")
            for row in observation["items"]:
                for field in FINANCIAL_INDICATOR_FIELDS:
                    normalize_indicator_value(
                        row[observation["fields"].index(field.source_column)],
                        source_unit=field.source_unit,
                    )
            yield observation

    versions = indicator_versions(
        validated_observations(),
        instrument_ids={code: instrument},
        sessions=sessions,
    )
    for offset in range(0, len(versions), 4096):
        rows = [
            {name: None if row[name] is None else str(row[name]) for name in _SCHEMA.names}
            for row in versions[offset : offset + 4096]
        ]
        content = parquet_bytes(rows, _WRITER)
        yield instrument, len(rows), content


def _validated_unresolved_sources(value, instrument_ids) -> dict[str, str]:
    if not isinstance(value, dict) or not set(value) <= set(instrument_ids.values()):
        raise ValueError("Invalid unresolved indicator identities")
    for day in value.values():
        if not isinstance(day, str) or date.fromisoformat(day).isoformat() != day:
            raise ValueError("Invalid unresolved indicator date")
    return dict(value)
