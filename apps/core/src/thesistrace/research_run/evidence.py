"""Result evidence scope, bounded staging and assembly for ordinary and Batch Runs."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from thesistrace.daily_holding_evidence import (
    HoldingEvidencePublication,
    merge_verified_holding_segment,
    stage_holding_evidence,
)
from thesistrace.publication import ParquetRowsPayload, StagedPayload, VerifiedBundle
from thesistrace.research_kernel.common_inputs import common_input_references
from thesistrace.research_kernel.factor_evidence import (
    factor_resolution_coordinates,
    validate_factor_observations,
)
from thesistrace.research_run.factor_result import (
    FACTOR_DAILY_CONTRACT,
    FactorEvidencePublication,
    factor_daily_payload,
    read_factor_daily_partition,
)
from thesistrace.research_run.models import ImmutableRunInput
from thesistrace.research_run.result import (
    COMMON_INPUT_OBSERVATIONS_CONTRACT,
    RESULT_DAILY_PARTITION_SESSION_COUNT,
    STRATEGY_DAILY_OBSERVATIONS_CONTRACT,
    ResearchResultError,
    common_input_observation_payload,
    enforce_result_bundle_budget,
    read_common_input_observation_partition,
    result_publication_payloads_from_staged,
    validate_common_chunk_observations,
)
from thesistrace.strategy_evidence import (
    StrategyEvidencePublication,
    append_staged_strategy_evidence,
    stage_strategy_evidence,
    strategy_event_record_count,
    verified_event_partitions,
)

Partition = tuple[StagedPayload, int, str, str]


class ResearchCheckpointIntegrityError(RuntimeError):
    pass


class EvidenceScope:
    def __init__(self, immutable_input: ImmutableRunInput) -> None:
        self.input = immutable_input
        self.plan = immutable_input.execution_plan
        self.sessions = tuple(
            day.isoformat()
            for day in self.plan.calculation_sessions[self.plan.research_session_offset :]
        )
        self.common_input_count = len(common_input_references(*immutable_input.expression_trees))

    def checkpoint_sessions(self, ordinal: int) -> tuple[str, ...]:
        if type(ordinal) is not int or not 1 <= ordinal <= len(self.plan.chunks):
            raise ResearchResultError("Research Chunk ordinal is invalid")
        chunk = self.plan.chunks[ordinal - 1]
        return tuple(
            session
            for session in self.sessions
            if chunk.first_session.isoformat() <= session <= chunk.last_session.isoformat()
        )

    def batch_sessions(self, ordinal: int) -> tuple[str, ...]:
        if type(ordinal) is not int or ordinal < 1:
            raise ResearchResultError("Batch evidence ordinal is invalid")
        offset = (ordinal - 1) * self.plan.chunk_session_count
        sessions = self.sessions[offset : offset + self.plan.chunk_session_count]
        if not sessions:
            raise ResearchResultError("Batch evidence scope is invalid")
        return sessions

    def validate_common(self, rows: object, sessions: tuple[str, ...]) -> None:
        if not isinstance(rows, list) or any(not isinstance(row, Mapping) for row in rows):
            raise ResearchResultError("Common Chunk observations are invalid")
        validate_common_chunk_observations(
            rows, expressions=self.input.expression_trees, sessions=sessions
        )

    def validate_checkpoint_factor(self, ordinal: int, rows: object) -> None:
        self.checkpoint_sessions(ordinal)
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ResearchResultError("Factor Chunk observations are invalid")
        try:
            values = validate_factor_observations(rows)
            before = sum(chunk.research_session_count for chunk in self.plan.chunks[: ordinal - 1])
            after = before + self.plan.chunks[ordinal - 1].research_session_count
            expected = (
                factor_resolution_coordinates(
                    self.sessions,
                    before=before,
                    after=after,
                    final=ordinal == len(self.plan.chunks),
                )
                if self.input.research_kind == "factor_evaluation"
                else []
            )
            if [(row["horizon"], row["session"]) for row in values] != expected:
                raise ValueError("Factor Chunk signal coverage is incomplete")
        except ValueError as error:
            raise ResearchResultError("Factor Chunk evidence is invalid") from error

    def common_partition(self, payload: StagedPayload, sessions: tuple[str, ...]) -> Partition:
        if not sessions or not self.common_input_count:
            raise ResearchResultError("Unexpected common observation checkpoint partition")
        return payload, len(sessions) * self.common_input_count, sessions[0], sessions[-1]

    def validate_complete_common(self, partitions: Sequence[Partition], *, batch: bool) -> None:
        windows = (
            (
                self.batch_sessions(ordinal)
                for ordinal in range(
                    1,
                    (len(self.sessions) + self.plan.chunk_session_count - 1)
                    // self.plan.chunk_session_count
                    + 1,
                )
            )
            if batch
            else (
                self.checkpoint_sessions(ordinal) for ordinal in range(1, len(self.plan.chunks) + 1)
            )
        )
        expected = [
            (len(sessions) * self.common_input_count, sessions[0], sessions[-1])
            for sessions in windows
            if sessions and self.common_input_count
        ]
        if [(count, first, last) for _payload, count, first, last in partitions] != expected:
            raise ResearchResultError("Common observation partitions are incomplete")


@dataclass(frozen=True)
class CheckpointEvidencePayloads:
    observation: StagedPayload | None
    common: StagedPayload | None
    factor: StagedPayload | None
    events: dict[str, StagedPayload]
    holdings: dict[str, StagedPayload]


@dataclass(frozen=True)
class AssembledResultEvidence:
    payloads: dict
    holding_payloads: dict | None
    sessions: tuple[str, ...]

    def enforce_budget(self, exact_bytes: int) -> None:
        enforce_result_bundle_budget(
            exact_bytes,
            len(self.sessions),
            strategy_event_count=strategy_event_record_count(self.payloads),
            strategy_target_count=strategy_event_record_count(
                self.payloads, section="strategy_targets"
            ),
            strategy_framework_count=strategy_event_record_count(
                self.payloads, section="strategy_framework"
            ),
        )


def staged_payload(value: object) -> StagedPayload:
    if not isinstance(value, Mapping) or not isinstance(value.get("serialization"), Mapping):
        raise ResearchResultError("Staged Result payload reference is invalid")
    return StagedPayload(
        sha256=str(value["sha256"]),
        byte_size=int(value["byte_size"]),
        media_type=str(value["media_type"]),
        serialization=dict(value["serialization"]),
    )


def checkpoint_evidence_names(row: Mapping[str, object]) -> frozenset[str]:
    names = set(row["strategy_event_payloads"]) | set(row["holding_payloads"])
    for field, name in (
        ("observation_payload", "strategy_daily_observations"),
        ("common_observation_payload", "common_input_observations"),
        ("factor_observation_payload", "factor_daily_observations"),
    ):
        if row[field] is not None:
            names.add(name)
    return frozenset(names)


class ResultEvidence:
    """Keep only staged descriptors and aggregates between bounded evidence segments."""

    def __init__(self, immutable_input: ImmutableRunInput) -> None:
        self.scope = EvidenceScope(immutable_input)
        self._common: list[Partition] = []
        self._observations: list[Partition] = []
        self._holdings = HoldingEvidencePublication()
        self._strategy = StrategyEvidencePublication()
        self._factor = FactorEvidencePublication()
        self._factor_chunks = 0
        self._checkpoint_count = 0

    def stage_checkpoint(
        self, ordinal: int, chunk: Mapping[str, object], publication, *, staging_authority
    ) -> CheckpointEvidencePayloads:
        sessions = self.scope.checkpoint_sessions(ordinal)
        common = chunk.get("common_input_observations")
        factor = chunk.get("factor_daily_observations")
        self.scope.validate_common(common, sessions)
        self.scope.validate_checkpoint_factor(ordinal, factor)
        collect_strategy = self.scope.input.research_kind == "strategy_backtest" and bool(sessions)
        events = chunk.get("strategy_events")
        if not isinstance(events, dict) or (not collect_strategy and events != {}):
            raise ResearchResultError("Research Chunk event evidence is invalid")
        holding_rows = chunk.get("holding_observations")
        if chunk.get("holding_sessions") != (
            list(sessions) if collect_strategy else []
        ) or not isinstance(holding_rows, Sequence):
            raise ResearchResultError("Research Chunk holding coverage is invalid")
        if not collect_strategy and holding_rows:
            raise ResearchResultError("Non-Strategy Chunk cannot contain holdings")

        def stage(payload):
            return publication.stage(payload, staging_authority=staging_authority)

        observations = chunk["strategy_daily_observations"]
        return CheckpointEvidencePayloads(
            observation=stage(
                ParquetRowsPayload(
                    rows=tuple(dict(value) for value in observations),
                    contract=STRATEGY_DAILY_OBSERVATIONS_CONTRACT,
                )
            )
            if observations
            else None,
            common=stage(common_input_observation_payload(common)) if common else None,
            factor=stage(factor_daily_payload(factor)) if factor else None,
            events=stage_strategy_evidence(
                publication, events, sessions=sessions, staging_authority=staging_authority
            )
            if collect_strategy
            else {},
            holdings=stage_holding_evidence(
                publication, list(sessions), holding_rows, staging_authority=staging_authority
            )
            if collect_strategy
            else {},
        )

    def append_batch_chunk(
        self, message: Mapping[str, object], publication, *, staging_authority
    ) -> None:
        status = message.get("status")
        ordinal = message.get("chunk_ordinal")

        def stage(payload):
            return publication.stage(payload, staging_authority=staging_authority)

        if status == "item_factor_evidence_succeeded":
            if (
                self.scope.input.research_kind != "factor_evaluation"
                or type(ordinal) is not int
                or ordinal != self._factor_chunks + 1
            ):
                raise ResearchResultError("Factor Batch evidence order is invalid")
            sessions = self.scope.batch_sessions(ordinal)
            rows = message.get("factor_daily_observations")
            if not isinstance(rows, list):
                raise ResearchResultError("Factor Batch observations are invalid")
            values = validate_factor_observations(rows)
            before = (ordinal - 1) * self.scope.plan.chunk_session_count
            after = before + len(sessions)
            expected = factor_resolution_coordinates(
                self.scope.sessions,
                before=before,
                after=after,
                final=after == len(self.scope.sessions),
            )
            if [(row["horizon"], row["session"]) for row in values] != expected:
                raise ResearchResultError("Factor Batch evidence coverage is incomplete")
            if values:
                self._factor.add(stage(factor_daily_payload(values)), values)
            self._factor_chunks = ordinal
        elif status == "item_common_input_chunk_succeeded":
            if type(ordinal) is not int or ordinal != len(self._common) + 1:
                raise ResearchResultError("Common Batch partition order is invalid")
            sessions = self.scope.batch_sessions(ordinal)
            rows = message.get("common_input_observations")
            self.scope.validate_common(rows, sessions)
            if not rows:
                raise ResearchResultError("Unexpected empty Common Batch partition")
            self._common.append(
                self.scope.common_partition(stage(common_input_observation_payload(rows)), sessions)
            )
        elif status == "item_strategy_chunk_succeeded":
            if self.scope.input.research_kind != "strategy_backtest":
                raise ResearchResultError("Strategy evidence requires a Strategy Run")
            partition = message["strategy_partition"]
            sessions = tuple(
                session
                for session in self.scope.sessions
                if partition["first_session"] <= session <= partition["last_session"]
            )
            events = message.get("strategy_events")
            if not isinstance(events, dict) or message.get("holding_sessions") != list(sessions):
                raise ResearchResultError("Strategy Batch evidence scope is invalid")
            self._holdings.add_segment(list(sessions), message["holding_observations"], stage=stage)
            append_staged_strategy_evidence(
                self._strategy,
                publication,
                events,
                sessions=sessions,
                staging_authority=staging_authority,
            )
        else:
            raise ResearchResultError("Batch evidence Kind is invalid")

    def bind_strategy_partitions(
        self,
        partitions: Sequence[tuple[int, StagedPayload, int, str, str]],
    ) -> None:
        if self.scope.input.research_kind != "strategy_backtest":
            raise ResearchResultError("Strategy partitions require a Strategy Run")
        observations = []
        offset = 0
        for expected_ordinal, (ordinal, payload, count, first, last) in enumerate(
            partitions,
            start=1,
        ):
            sessions = self.scope.sessions[offset : offset + count]
            if (
                type(ordinal) is not int
                or type(count) is not int
                or ordinal != expected_ordinal
                or not 1 <= count <= RESULT_DAILY_PARTITION_SESSION_COUNT
                or len(sessions) != count
                or (first, last) != (sessions[0], sessions[-1])
            ):
                raise ResearchResultError("Strategy observation partition scope is invalid")
            observations.append((payload, count, first, last))
            offset += count
        if offset != len(self.scope.sessions):
            raise ResearchResultError("Strategy observation partitions are incomplete")
        self._observations = observations

    def append_verified_checkpoint(self, row: Mapping[str, object], bundle: VerifiedBundle) -> None:
        ordinal = int(row["ordinal"])
        if ordinal != self._checkpoint_count + 1 or set(
            bundle.payloads
        ) != checkpoint_evidence_names(row):
            raise ResearchCheckpointIntegrityError(
                "Checkpoint evidence ordering or inventory is invalid"
            )
        sessions = self.scope.checkpoint_sessions(ordinal)
        bound_payloads: dict[str, StagedPayload] = {}

        def verified(name: str, descriptor: object, contract=None) -> StagedPayload:
            staged = staged_payload(descriptor)
            payload = bundle.payloads[name]
            if name not in bound_payloads and (
                hashlib.sha256(payload.content).hexdigest() != staged.sha256
                or len(payload.content) != staged.byte_size
                or payload.media_type != staged.media_type
                or payload.serialization != staged.serialization
            ):
                raise ResearchCheckpointIntegrityError(
                    "Checkpoint evidence bytes differ from its binding"
                )
            bound_payloads[name] = staged
            if contract is not None and (
                payload.media_type != "application/vnd.apache.parquet"
                or payload.serialization
                != {
                    "format": "canonical-parquet",
                    "writer_contract": contract.descriptor(),
                }
            ):
                raise ResearchCheckpointIntegrityError("Checkpoint evidence contract is invalid")
            return staged

        # Verify every binding before parsing bytes or mutating aggregate builders.
        for name, descriptor in {
            **row["strategy_event_payloads"],
            **row["holding_payloads"],
            **(
                {"strategy_daily_observations": row["observation_payload"]}
                if row["observation_payload"] is not None
                else {}
            ),
            **(
                {"common_input_observations": row["common_observation_payload"]}
                if row["common_observation_payload"] is not None
                else {}
            ),
            **(
                {"factor_daily_observations": row["factor_observation_payload"]}
                if row["factor_observation_payload"] is not None
                else {}
            ),
        }.items():
            verified(name, descriptor)
        common = []
        if row["common_observation_payload"] is not None:
            staged = verified(
                "common_input_observations",
                row["common_observation_payload"],
                COMMON_INPUT_OBSERVATIONS_CONTRACT,
            )
            common = read_common_input_observation_partition(
                bundle.payloads["common_input_observations"].content
            )
            self._common.append(self.scope.common_partition(staged, sessions))
        self.scope.validate_common(common, sessions)
        factor = []
        if row["factor_observation_payload"] is not None:
            staged = verified(
                "factor_daily_observations",
                row["factor_observation_payload"],
                FACTOR_DAILY_CONTRACT,
            )
            factor = read_factor_daily_partition(
                bundle.payloads["factor_daily_observations"].content
            )
            self._factor.add(staged, factor)
        self.scope.validate_checkpoint_factor(ordinal, factor)
        if row["observation_payload"] is not None:
            staged = verified(
                "strategy_daily_observations",
                row["observation_payload"],
                STRATEGY_DAILY_OBSERVATIONS_CONTRACT,
            )
            if (
                not sessions
                or int(row["observation_row_count"]) != len(sessions)
                or row["observation_first_session"].isoformat() != sessions[0]
                or row["observation_last_session"].isoformat() != sessions[-1]
            ):
                raise ResearchCheckpointIntegrityError("Checkpoint observation scope is invalid")
            self._observations.append((staged, len(sessions), sessions[0], sessions[-1]))
        if sessions and self.scope.input.research_kind == "strategy_backtest":
            references = {
                name: verified(name, value) for name, value in row["holding_payloads"].items()
            }
            merge_verified_holding_segment(
                self._holdings, bundle, references, sessions=list(sessions)
            )
            descriptors = row["strategy_event_payloads"]
            if not descriptors:
                raise ResearchCheckpointIntegrityError("Strategy checkpoint evidence is missing")
            for section, name, event_rows in verified_event_partitions(bundle, sessions=sessions):
                self._strategy.add(section, verified(name, descriptors[name]), event_rows)
        elif row["holding_payloads"] or row["strategy_event_payloads"]:
            raise ResearchCheckpointIntegrityError(
                "Non-Strategy checkpoint contains Strategy evidence"
            )
        self._checkpoint_count = ordinal

    def finish(self, final_values: Mapping[str, object], *, batch: bool) -> AssembledResultEvidence:
        self.scope.validate_complete_common(self._common, batch=batch)
        if not batch and self._checkpoint_count != len(self.scope.plan.chunks):
            raise ResearchCheckpointIntegrityError(
                "Result evidence checkpoint coverage is incomplete"
            )
        kind = self.scope.input.research_kind
        holdings = None
        if kind == "strategy_backtest":
            if (
                not self._observations
                or sum(part[1] for part in self._observations) != len(self.scope.sessions)
                or self._observations[0][2] != self.scope.sessions[0]
                or self._observations[-1][3] != self.scope.sessions[-1]
            ):
                raise ResearchResultError("Strategy observation partitions are incomplete")
            holdings = self._holdings.finish()
            if holdings["daily_holdings"].value["sessions"] != list(self.scope.sessions):
                raise ResearchResultError("Strategy holding coverage is incomplete")
        payloads = result_publication_payloads_from_staged(
            final_values, self._observations, research_kind=kind, common_partitions=self._common
        )
        if kind == "factor_evaluation":
            if (
                batch
                and self._factor_chunks
                != (len(self.scope.sessions) + self.scope.plan.chunk_session_count - 1)
                // self.scope.plan.chunk_session_count
            ):
                raise ResearchResultError("Factor Batch evidence coverage is incomplete")
            payloads.update(self._factor.finish(summary=final_values["factor_summary"]))
        else:
            payloads.update(self._strategy.finish())
        return AssembledResultEvidence(payloads, holdings, self.scope.sessions)
