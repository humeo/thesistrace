"""Collect one historical security's indicator range with durable progress."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from thesistrace._postgres import PostgresDatabase
from thesistrace.data.financial_collection import RawFinancialBatchStore
from thesistrace.data.financial_indicator_evidence import (
    FinancialIndicatorCheckpoint,
    indicator_versions,
    received_indicator_reports,
    validate_indicator_collection_evidence,
)
from thesistrace.data.financial_indicator_progress import FinancialIndicatorProgressStore
from thesistrace.data.financial_indicator_source import (
    FinancialIndicatorProvider,
    FinancialIndicatorSource,
)
from thesistrace.data.generation_store import HistoricalInstrumentIdentity
from thesistrace.data.lifecycle import mounted_data_mutation_lock
from thesistrace.publication.serialization import canonical_json_bytes


@dataclass(frozen=True)
class CompletedIndicatorCollection:
    evidence_sha256: str
    observation_sha256s: tuple[str, ...]
    pending_reports: tuple[tuple[str, str], ...]


class FinancialIndicatorCollector:
    def __init__(
        self,
        database: PostgresDatabase,
        root: Path,
        provider: FinancialIndicatorProvider,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._database, self._root, self._provider, self._clock = database, root, provider, clock
        self._progress = FinancialIndicatorProgressStore(database)
        self._raw = RawFinancialBatchStore(root)

    def collect(
        self,
        *,
        collection_key: str,
        identity: HistoricalInstrumentIdentity,
        start_date: str,
        end_date: str,
        checked_through: str,
        required_reports: Sequence[tuple[str, str]],
    ) -> CompletedIndicatorCollection:
        start = datetime.strptime(start_date, "%Y%m%d").date()
        end = datetime.strptime(end_date, "%Y%m%d").date()
        checked = date.fromisoformat(checked_through)
        if start > end or end > checked:
            raise ValueError("Invalid indicator collection range")
        for period, announced in required_reports:
            if (not start <= date.fromisoformat(period) <= end) or date.fromisoformat(
                announced
            ) > checked:
                raise ValueError("Indicator target falls outside collection scope")
        with mounted_data_mutation_lock(
            self._database,
            exclusive_name="indicator-collection:" + identity.instrument_id,
        ):
            for period, announced in required_reports:
                self._progress.require_report(
                    identity.instrument_id, report_period=period, announced_on=announced
                )
            checkpoint = FinancialIndicatorCheckpoint(
                self._root,
                collection_key=collection_key,
                provider=self._provider,
                clock=self._clock,
            )
            source = FinancialIndicatorSource(checkpoint)
            for _shard in source.collect_report_range(
                ts_code=identity.ts_code, start_date=start_date, end_date=end_date
            ):
                pass
            observations = checkpoint.observations()
            references = tuple(
                sorted(
                    {
                        hashlib.sha256(canonical_json_bytes(observation)).hexdigest()
                        for observation in observations
                    }
                )
            )
            evidence = self._raw.store(
                canonical_json_bytes(
                    {
                        "source": "fina_indicator",
                        "collection_key": collection_key,
                        "instrument_id": identity.instrument_id,
                        "ts_code": identity.ts_code,
                        "start_date": start_date,
                        "end_date": end_date,
                        "checked_through": checked_through,
                        "completed_requests": checkpoint.completed_requests(),
                    }
                )
            )
            validate_indicator_collection_evidence(self._raw, evidence)
            # Receipt does not require a later research session. The same version rules
            # still reject conflicting observations, including those outside the calendar.
            reports = received_indicator_reports(
                indicator_versions(
                    observations, instrument_ids={identity.ts_code: identity.instrument_id},
                    sessions=(),
                ),
                through=checked_through,
            )
            self._progress.record_reconciliation(
                identity.instrument_id,
                checked_through=checked_through,
                observed_reports=tuple((period, published) for _id, period, published in reports),
                observation_sha256=evidence,
            )
            return CompletedIndicatorCollection(
                evidence, references, self._progress.pending(identity.instrument_id)
            )


@dataclass(frozen=True)
class DailyIndicatorCollection:
    scheduled_instrument_ids: tuple[str, ...]
    collection_evidence_sha256s: tuple[str, ...]
    failures: tuple[tuple[str, str], ...]
    pending_instrument_ids: tuple[str, ...]

    @property
    def failed_instrument_ids(self) -> tuple[str, ...]:
        return tuple(instrument for instrument, _code in self.failures)


class FinancialIndicatorDailyCollector:
    """Resume a frozen pending/rotating dispatch plan through the ordinary source."""

    def __init__(
        self,
        database: PostgresDatabase,
        root: Path,
        provider: FinancialIndicatorProvider,
        *,
        reconciliation_limit: int = 64,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        ownership_guard: Callable[[], None] = lambda: None,
    ) -> None:
        if type(reconciliation_limit) is not int or reconciliation_limit <= 0:
            raise ValueError("Indicator reconciliation limit must be positive")
        self._database, self._root = database, root
        self._clock = clock
        self._limit = reconciliation_limit
        self._guard = ownership_guard
        self._progress = FinancialIndicatorProgressStore(database)
        self._collector = FinancialIndicatorCollector(database, root, provider, clock=clock)

    def collect(
        self,
        *,
        operation_key: str,
        identities: Sequence[HistoricalInstrumentIdentity],
        checked_through: str,
        research_session_index: int,
        initial_instrument_ids: Sequence[str],
    ) -> DailyIndicatorCollection:
        from thesistrace.data.financial_collection import FINANCIAL_HISTORY_FLOOR
        from thesistrace.data.source import DataSourceError

        target = date.fromisoformat(checked_through)
        if (
            not operation_key
            or not identities
            or type(research_session_index) is not int
            or research_session_index < 0
        ):
            raise ValueError("Invalid indicator dispatch scope")
        by_id = {item.instrument_id: item for item in identities}
        if len(by_id) != len(identities) or len({item.ts_code for item in identities}) != len(
            identities
        ):
            raise ValueError("Indicator dispatch requires unique historical identities")
        initial = tuple(sorted(initial_instrument_ids))
        if len(initial) != len(set(initial)) or not set(initial) <= set(by_id):
            raise ValueError("Initial indicator identities fall outside dispatch scope")
        with mounted_data_mutation_lock(
            self._database,
            exclusive_name="indicator-daily-dispatch",
        ):
            self._guard()
            plan = self._plan(
                operation_key,
                by_id,
                checked_through,
                research_session_index,
                initial,
            )
        completed, failures, pending = [], [], []
        for instrument in plan["selected"]:
            self._guard()
            targets = tuple(
                (period, announced)
                for period, announced in self._progress.pending(instrument)
                if announced <= checked_through
            )
            try:
                result = self._collector.collect(
                    collection_key=hashlib.sha256(
                        canonical_json_bytes(
                            {
                                "operation": operation_key,
                                "instrument": instrument,
                            }
                        )
                    ).hexdigest(),
                    identity=by_id[instrument],
                    start_date=FINANCIAL_HISTORY_FLOOR,
                    end_date=target.strftime("%Y%m%d"),
                    checked_through=checked_through,
                    required_reports=targets,
                )
            except DataSourceError as error:
                failures.append((instrument, error.detail_code))
            else:
                completed.append(result.evidence_sha256)
            if any(
                announced <= checked_through
                for _period, announced in self._progress.pending(instrument)
            ):
                pending.append(instrument)
            from thesistrace.data.financial_report_progress import record_recheck

            with self._database.transaction() as tx:
                record_recheck(
                    tx,
                    instrument,
                    "fina_indicator",
                    next((code for item, code in failures if item == instrument), None),
                )
            self._guard()
        return DailyIndicatorCollection(
            tuple(plan["selected"]),
            tuple(sorted(completed)),
            tuple(failures),
            tuple(pending),
        )

    def _plan(
        self,
        operation_key: str,
        by_id: Mapping[str, HistoricalInstrumentIdentity],
        target: str,
        session_index: int,
        initial_instrument_ids: tuple[str, ...],
    ) -> dict[str, object]:
        import json

        from thesistrace.data.generation_files import AddressedFileStore

        scope = {
            "operation_key": operation_key,
            "checked_through": target,
            "research_session_index": session_index,
            "reconciliation_limit": self._limit,
            "identities": {key: by_id[key].ts_code for key in sorted(by_id)},
            "initial_instrument_ids": list(initial_instrument_ids),
        }
        directory = (
            self._root
            / ".operator"
            / "indicator-dispatch"
            / hashlib.sha256(operation_key.encode()).hexdigest()
        )
        files = AddressedFileStore(self._root)
        receipts = tuple(directory.glob("*.json"))
        if len(receipts) > 1:
            raise ValueError("Conflicting indicator dispatch plans")
        if receipts:
            path = receipts[0]
            plan = json.loads(files.read(path, path.stem, max_byte_count=16 * 1024 * 1024))
            if (
                not isinstance(plan, dict)
                or set(plan) != {"scope", "selected"}
                or plan["scope"] != scope
                or not isinstance(plan["selected"], list)
                or not plan["selected"]
                or not all(isinstance(item, str) and item in by_id for item in plan["selected"])
                or len(set(plan["selected"])) != len(plan["selected"])
            ):
                raise ValueError("Indicator dispatch scope differs")
            return plan
        with self._database.transaction() as tx:
            rows = tx.execute(
                """SELECT DISTINCT instrument_id FROM data.financial_report_targets
                   WHERE endpoint='fina_indicator' AND instrument_id = ANY(%s::text[])
                     AND actual_date <= %s
                     AND resolved_evidence_sha256 IS NULL ORDER BY instrument_id""",
                (list(by_id), date.fromisoformat(target)),
            ).fetchall()
        pending = [str(row["instrument_id"]) for row in rows]
        from thesistrace.data.financial_report_progress import reconciliation_ids

        with self._database.transaction() as tx:
            rotated = reconciliation_ids(
                tx, by_id, "fina_indicator", limit=self._limit, exclude=set(pending)
            )
        selected = list(dict.fromkeys([*initial_instrument_ids, *pending, *rotated]))
        plan = {"scope": scope, "selected": selected}
        content = canonical_json_bytes(plan)
        digest = hashlib.sha256(content).hexdigest()
        files.store(directory / f"{digest}.json", digest, content)
        return plan
