import hashlib
import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime

from thesistrace.activity_contract import (
    MAX_AUTOMATIC_ACTIVITY_EXECUTIONS,
    CooperativeActivityCancellation,
    is_resource_exhaustion,
    should_retry_resource_exhaustion,
)
from thesistrace.alpha import evaluate_alpha_matrix
from thesistrace.datasets import DatasetPublisher
from thesistrace.factor import build_forward_labels, evaluate_factor
from thesistrace.objects import canonical_json_bytes
from thesistrace.ports import ControlMetadataPort, ObjectStorePort, ObjectWriterPort
from thesistrace.result_objects import (
    CompactResultError,
    publish_compact_result_objects,
    reconstruct_result_view,
)
from thesistrace.strategy import run_strategy

RUNTIME_BUILD = {"package": "thesistrace", "version": "0.1.0"}
MAX_RESULT_BUNDLE_BYTES = 1_048_576
logger = logging.getLogger(__name__)
Calculator = Callable[
    [dict[str, object], dict[str, object]],
    dict[str, dict[str, object]],
]
Progress = Callable[[str], None]


class TransientResearchRunError(RuntimeError):
    pass


class ResearchPublicationFenced(RuntimeError):
    pass


def recover_staged_research_run(
    metadata: ControlMetadataPort,
    objects: ObjectStorePort,
    run_id: str,
) -> dict[str, object]:
    with objects.publication_guard(run_id):
        current = metadata.research_run(run_id)
        if current is None:
            raise KeyError(run_id)
        digest = current.get("result_manifest_sha256")
        objects.recover_staged_publication(
            run_id,
            committed_manifest_sha256=(
                str(digest)
                if current["status"] == "succeeded" and isinstance(digest, str)
                else None
            ),
        )
        return current


class ResearchRunService:
    def __init__(
        self,
        metadata: ControlMetadataPort,
        datasets: DatasetPublisher,
        objects: ObjectStorePort,
        *,
        calculator: Calculator | None = None,
        progress: Progress | None = None,
    ) -> None:
        self.metadata = metadata
        self.datasets = datasets
        self.objects = objects
        self.calculator = calculator or calculate_research
        self.progress = progress or (lambda _stage: None)

    def execute_next(self) -> dict[str, object] | None:
        run_id = self.metadata.next_queued_research_run_id()
        return None if run_id is None else self.execute(run_id)

    def execute(self, run_id: str) -> dict[str, object]:
        current = recover_staged_research_run(
            self.metadata,
            self.objects,
            run_id,
        )
        if current["status"] in {"succeeded", "failed", "cancelled"}:
            return current
        claimed = self.metadata.claim_research_run(run_id)
        if claimed is None:
            latest = self.metadata.research_run(run_id)
            if latest is None:
                raise KeyError(run_id)
            return latest
        run, attempt = claimed
        attempt_id = str(attempt["id"])
        ordinal = int(attempt["ordinal"])
        try:
            self.progress("claimed")
            frozen = self.metadata.frozen_research_definition(str(run["definition_version_id"]))
            release = self.metadata.dataset_release(str(run["dataset_release_id"]))
            if frozen is None or release is None:
                raise RuntimeError("ResearchRun input metadata is missing")
            canonical = research_input_history(self.datasets.materialize_canonical(release))
            self.progress("inputs_loaded")
            content = frozen["content"]
            if not isinstance(content, dict):
                raise RuntimeError("frozen Research Definition is invalid")
            artifacts = self.calculator(canonical, content)
            self.progress("calculated")
            with self.objects.publication_guard(run_id):
                latest = self.metadata.research_run(run_id)
                if latest is None:
                    raise KeyError(run_id)
                if latest["status"] != "running":
                    return latest
                try:
                    with self.objects.stage(run_id, attempt_id) as staged_objects:
                        manifest, manifest_object = self.publish_result_objects(
                            objects=staged_objects,
                            run=run,
                            frozen=frozen,
                            release=release,
                            artifacts=artifacts,
                        )
                        staged_objects.put_manifest(str(manifest["id"]), manifest)
                        with staged_objects.publication(
                            manifest_sha256=str(manifest_object["sha256"])
                        ):
                            published = self.metadata.publish_research_run_success(
                                run_id=run_id,
                                attempt_id=attempt_id,
                                result_bundle_id=str(manifest["id"]),
                                result_manifest_sha256=str(
                                    manifest_object["sha256"]
                                ),
                            )
                            if not published:
                                raise ResearchPublicationFenced
                except ResearchPublicationFenced:
                    self.objects.recover_staged_publication(
                        run_id,
                        committed_manifest_sha256=None,
                    )
                    latest = self.metadata.research_run(run_id)
                    if latest is None:
                        raise KeyError(run_id) from None
                    return latest
        except CooperativeActivityCancellation:
            self.metadata.acknowledge_research_run_cancellation(
                run_id=run_id,
                attempt_id=attempt_id,
            )
            return self._recover_staged_for_run(run_id)
        except TransientResearchRunError as error:
            logger.warning(
                "Research Activity transient failure run_id=%s attempt_id=%s error_type=%s",
                run_id,
                attempt_id,
                type(error).__name__,
            )
            self.metadata.finish_research_run_attempt(
                run_id=run_id,
                attempt_id=attempt_id,
                retryable=ordinal < MAX_AUTOMATIC_ACTIVITY_EXECUTIONS,
                diagnostic={
                    "reason_code": "TRANSIENT_FAILURE",
                    "message": "temporary research infrastructure failure",
                    "correlation_id": attempt_id,
                },
            )
            return self._recover_staged_for_run(run_id)
        except Exception as error:
            latest = self.metadata.research_run(run_id)
            if latest is not None and latest["status"] == "succeeded":
                return self._recover_staged_for_run(run_id)
            resource_exhausted = is_resource_exhaustion(error)
            reason_code = (
                "RESOURCE_EXHAUSTED"
                if resource_exhausted
                else "CALCULATION_FAILED"
            )
            retryable = resource_exhausted and should_retry_resource_exhaustion(
                ordinal
            )
            logger.error(
                "Research Activity failed run_id=%s attempt_id=%s error_type=%s reason_code=%s",
                run_id,
                attempt_id,
                type(error).__name__,
                reason_code,
            )
            self.metadata.finish_research_run_attempt(
                run_id=run_id,
                attempt_id=attempt_id,
                retryable=retryable,
                diagnostic={
                    "reason_code": reason_code,
                    "message": (
                        "accepted activity resource envelope was exhausted"
                        if resource_exhausted
                        else "research calculation failed"
                    ),
                    "correlation_id": attempt_id,
                },
            )
            return self._recover_staged_for_run(run_id)
        completed = self.metadata.research_run(run_id)
        if completed is None:
            raise KeyError(run_id)
        return completed

    def _recover_staged_for_run(
        self,
        run_id: str,
    ) -> dict[str, object]:
        return recover_staged_research_run(self.metadata, self.objects, run_id)

    def publish_result_objects(
        self,
        *,
        objects: ObjectWriterPort,
        run: dict[str, object],
        frozen: dict[str, object],
        release: dict[str, object],
        artifacts: dict[str, dict[str, object]],
    ) -> tuple[dict[str, object], dict[str, object]]:
        required = {
            "alpha_matrix",
            "forward_labels",
            "factor_evaluation",
            "strategy_backtest",
            "strategy_time_series",
            "strategy_events",
            "diagnostics",
        }
        if set(artifacts) != required:
            raise RuntimeError("calculation did not produce the complete Result Bundle")
        content = frozen["content"]
        if not isinstance(content, dict):
            raise RuntimeError("frozen Research Definition is invalid")
        object_entries = publish_compact_result_objects(
            objects,
            artifacts,
            content,
        )
        semantics = content.get("semantic_versions")
        if not isinstance(semantics, dict):
            raise RuntimeError("Research semantics are missing")
        manifest_core: dict[str, object] = {
            "research_run_id": run["id"],
            "definition": {
                "id": frozen["id"],
                "content_hash": frozen["content_hash"],
            },
            "dataset_release": {
                "id": release["id"],
                "manifest_sha256": release["manifest_sha256"],
            },
            "research_semantics": semantics,
            "numeric_execution_contract": content["numeric_execution_contract"],
            "calculation_kernel": semantics["kernel"],
            "runtime_build": RUNTIME_BUILD,
            "input_sessions": {"total": 756, "warmup": 252, "report": 504},
            "objects": object_entries,
            "created_at": datetime.now(UTC).isoformat(),
        }
        digest = hashlib.sha256(canonical_json_bytes(manifest_core)).hexdigest()
        manifest = {
            "id": f"result_{digest[:20]}",
            **manifest_core,
            "manifest_sha256": digest,
        }
        payload_bytes = sum(int(entry["bytes"]) for entry in object_entries.values())
        logical_bytes: dict[str, int] = {
            "payloads": payload_bytes,
            "manifest": 0,
            "total": payload_bytes,
            "limit": MAX_RESULT_BUNDLE_BYTES,
        }
        for _ in range(10):
            manifest["logical_bytes"] = logical_bytes
            manifest_bytes = len(canonical_json_bytes(manifest))
            next_logical_bytes = {
                "payloads": payload_bytes,
                "manifest": manifest_bytes,
                "total": payload_bytes + manifest_bytes,
                "limit": MAX_RESULT_BUNDLE_BYTES,
            }
            if next_logical_bytes == logical_bytes:
                break
            logical_bytes = next_logical_bytes
        manifest["logical_bytes"] = logical_bytes
        if len(canonical_json_bytes(manifest)) != logical_bytes["manifest"]:
            raise RuntimeError("Result Bundle byte accounting did not converge")
        if logical_bytes["total"] > MAX_RESULT_BUNDLE_BYTES:
            raise RuntimeError(
                "complete Result Bundle exceeds the 1,048,576 byte limit"
            )
        manifest_object = objects.put_json(manifest)
        return manifest, manifest_object

    def result_view(self, run_id: str) -> dict[str, object] | None:
        run = recover_staged_research_run(
            self.metadata,
            self.objects,
            run_id,
        )
        digest = run.get("result_manifest_sha256")
        if run["status"] != "succeeded":
            return None
        if not isinstance(digest, str):
            raise RuntimeError("successful ResearchRun has no Result Manifest")
        manifest = self.objects.read_json(digest)
        if not isinstance(manifest, dict):
            raise RuntimeError("Result Manifest is invalid")
        entries = manifest.get("objects")
        if not isinstance(entries, dict):
            raise RuntimeError("Result Manifest object index is invalid")
        try:
            return reconstruct_result_view(self.objects, manifest)
        except CompactResultError as error:
            raise RuntimeError(str(error)) from error


def calculate_research(
    canonical: dict[str, object],
    definition: dict[str, object],
) -> dict[str, dict[str, object]]:
    alpha = definition["alpha"]
    if not isinstance(alpha, dict):
        raise RuntimeError("Alpha definition is invalid")
    matrix = evaluate_alpha_matrix(
        canonical,
        expression=str(alpha["expression"]),
        universe_name=str(definition["universe"]),
        neutralization=str(definition["neutralization"]),
    )
    labels = build_forward_labels(canonical, matrix)
    factor = evaluate_factor(labels)
    strategy = run_strategy(canonical, matrix, definition)
    return {
        "alpha_matrix": matrix,
        "forward_labels": labels,
        "factor_evaluation": factor,
        "strategy_backtest": strategy,
        "strategy_time_series": {"daily": strategy["daily"]},
        "strategy_events": {
            "orders": strategy["orders"],
            "child_orders": strategy["child_orders"],
            "fills": strategy["fills"],
            "rebalance_events": strategy["rebalance_events"],
            "rejections": strategy["rejections"],
        },
        "diagnostics": {
            "alpha_coverage": [
                {
                    "session": item["session"],
                    "coverage_loss": item["coverage_loss"],
                }
                for item in matrix["sessions"]
            ],
            "strategy": strategy["diagnostics"],
        },
    }


def research_input_history(canonical: dict[str, object]) -> dict[str, object]:
    copied = json.loads(json.dumps(canonical, ensure_ascii=False, allow_nan=False))
    if not isinstance(copied, dict):
        raise RuntimeError("canonical Dataset Release is invalid")
    calendar = copied.get("research_calendar")
    if not isinstance(calendar, list) or len(calendar) < 756:
        raise RuntimeError("ResearchRun requires at least 756 completed sessions")
    selected = [str(session) for session in calendar[-756:]]
    selected_set = set(selected)
    copied["research_calendar"] = selected
    for key in (
        "prices",
        "trading_states",
        "price_limits",
        "base_pool",
        "st_designations",
    ):
        rows = copied.get(key)
        if isinstance(rows, list):
            copied[key] = [
                row
                for row in rows
                if isinstance(row, dict)
                and str(row.get("session") or row.get("trade_date")) in selected_set
            ]
    universes = copied.get("liquidity_universes")
    if not isinstance(universes, dict):
        raise RuntimeError("canonical Dataset Release has no Liquidity Universes")
    copied["liquidity_universes"] = {
        name: [
            row for row in rows if isinstance(row, dict) and str(row.get("session")) in selected_set
        ]
        for name, rows in universes.items()
        if isinstance(rows, list)
    }
    return copied
