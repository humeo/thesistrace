import asyncio
from pathlib import Path

import pytest

from thesistrace.api import public_result_view
from thesistrace.hosted.execution_relay import relay_once
from thesistrace.hosted.research_workflow import (
    RESEARCH_TASK_QUEUE,
    research_workflow_id,
)
from thesistrace.storage import MetadataStore


class RecordingOutboxStore(MetadataStore):
    def __init__(self, path: Path, *, fail: bool = False) -> None:
        super().__init__(path)
        self.fail = fail
        self.enqueued: list[tuple[str, str]] = []

    def _enqueue_research_run(
        self,
        connection,
        *,
        run_id: str,
        created_at: str,
    ) -> None:
        del connection
        if self.fail:
            raise RuntimeError("outbox unavailable")
        self.enqueued.append((run_id, created_at))


def create_run(store: MetadataStore, key: str) -> tuple[dict[str, object], bool]:
    draft = store.create_research_draft({"title": "test"})
    _frozen, run, created = store.freeze_definition_and_create_run(
        draft_id=str(draft["id"]),
        frozen_content={"title": "test"},
        content_hash="frozen-content-hash",
        dataset_release_id="release-1",
        idempotency_key=key,
    )
    return run, created


def prepare_store(store: MetadataStore) -> None:
    store.initialize()
    with store.connect() as connection:
        connection.execute(
            """
            INSERT INTO dataset_releases (id, manifest_json, created_at)
            VALUES (?, '{}', '2026-07-31T00:00:00+00:00')
            """,
            ("release-1",),
        )


def test_new_run_enqueues_once_and_idempotent_replay_consumes_no_capacity(
    tmp_path: Path,
) -> None:
    store = RecordingOutboxStore(tmp_path / "metadata.sqlite3")
    prepare_store(store)

    first, first_created = create_run(store, "same-request")
    second, second_created = create_run(store, "same-request")

    assert first_created is True
    assert second_created is False
    assert second["id"] == first["id"]
    assert [run_id for run_id, _created_at in store.enqueued] == [first["id"]]


def test_outbox_failure_rolls_back_frozen_definition_and_run(tmp_path: Path) -> None:
    store = RecordingOutboxStore(tmp_path / "metadata.sqlite3", fail=True)
    prepare_store(store)

    with pytest.raises(RuntimeError, match="outbox unavailable"):
        create_run(store, "failed-request")

    assert store.list_frozen_research_definitions() == []
    assert store.list_research_runs() == []


class FakeTemporalClient:
    def __init__(self) -> None:
        self.starts: list[dict[str, object]] = []

    async def start_workflow(self, workflow, request, **options):
        self.starts.append(
            {
                "workflow": workflow,
                "request": request,
                "options": options,
            }
        )


class FakeOutbox:
    def __init__(self) -> None:
        self.dispatched: list[str] = []

    def pending(self, *, limit: int) -> list[dict[str, str]]:
        assert limit == 25
        return [
            {
                "outbox_id": "outbox-run-1",
                "workspace_id": "workspace-1",
                "resource_kind": "research_run",
                "resource_id": "run-1",
            }
        ]

    def mark_dispatched(self, outbox_id: str) -> bool:
        self.dispatched.append(outbox_id)
        return True


def test_relay_uses_stable_domain_identity_and_only_opaque_payload() -> None:
    client = FakeTemporalClient()
    outbox = FakeOutbox()

    assert asyncio.run(relay_once(client, outbox)) == 1

    assert outbox.dispatched == ["outbox-run-1"]
    assert len(client.starts) == 1
    start = client.starts[0]
    assert start["request"] == {
        "workspace_id": "workspace-1",
        "run_id": "run-1",
    }
    assert start["options"]["id"] == research_workflow_id("run-1")
    assert start["options"]["task_queue"] == RESEARCH_TASK_QUEUE


def test_hosted_result_projection_hides_storage_and_transient_artifacts() -> None:
    result = {
        "manifest": {
            "research_run_id": "run-1",
            "manifest_sha256": "secret",
            "dataset_release": {
                "id": "release-1",
                "manifest_sha256": "secret",
            },
            "objects": {"factor_summary": {"sha256": "secret"}},
        },
        "factor_evaluation": {
            "horizons": {
                "1": {
                    "alpha_checksum": "alpha",
                    "label_checksum": "label",
                    "source_checksum": "source",
                    "summary": {"ic": 0.1},
                }
            }
        },
        "strategy_backtest": {
            "alpha_checksum": "alpha",
            "metrics": {"sharpe": 1.2},
            "daily": [{"session": str(index)} for index in range(5)],
            "rebalance_aggregates": [{"session": "1"}],
            "execution_aggregates": [{"session": "1"}],
        },
        "terminal_strategy_state": {
            "positions": [{"instrument_id": str(index)} for index in range(4)]
        },
    }

    view = public_result_view(
        result,
        daily_offset=1,
        daily_limit=2,
        position_offset=2,
        position_limit=1,
    )

    assert set(view["manifest"]) == {"research_run_id", "dataset_release"}
    assert view["manifest"]["dataset_release"] == {"id": "release-1"}
    assert view["factor_evaluation"]["horizons"]["1"] == {
        "summary": {"ic": 0.1}
    }
    assert view["strategy_backtest"]["daily"] == [
        {"session": "1"},
        {"session": "2"},
    ]
    assert "rebalance_aggregates" not in view["strategy_backtest"]
    assert "execution_aggregates" not in view["strategy_backtest"]
    assert view["terminal_strategy_state"]["positions"] == [{"instrument_id": "2"}]
