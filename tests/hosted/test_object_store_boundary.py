import time
from pathlib import Path

import pyarrow as pa
import pytest
from fastapi.testclient import TestClient

from thesistrace.hosted import object_store_service
from thesistrace.hosted.object_store import RemoteObjectStore
from thesistrace.hosted.object_store_service import (
    create_object_store_app,
)
from thesistrace.objects import (
    ParquetContractError,
    ParquetWriterContract,
)

TOKENS = {
    "api": "api-object-token",
    "compute": "compute-object-token",
    "data": "data-object-token",
}


def remote(
    tmp_path: Path,
    *,
    role: str,
) -> tuple[RemoteObjectStore, TestClient]:
    client = TestClient(
        create_object_store_app(tmp_path / "objects", TOKENS)
    )
    return (
        RemoteObjectStore(
            "http://object-store",
            TOKENS[role],
            client=client,
        ),
        client,
    )


def contract() -> ParquetWriterContract:
    return ParquetWriterContract(
        name="hosted.object-store-probe",
        version=1,
        schema=pa.schema(
            [
                pa.field("session", pa.string(), nullable=False),
                pa.field("value", pa.int64(), nullable=False),
            ]
        ),
        sort_keys=("session",),
    )


def test_private_object_store_preserves_typed_object_contract(
    tmp_path: Path,
) -> None:
    objects, client = remote(tmp_path, role="compute")
    try:
        json_object = objects.put_json({"value": "canonical"})
        parquet_object = objects.put_parquet_rows(
            [
                {"session": "2026-07-02", "value": 2},
                {"session": "2026-07-01", "value": 1},
            ],
            contract(),
        )

        assert objects.read_json(str(json_object["sha256"])) == {
            "value": "canonical"
        }
        table = objects.read_parquet(
            str(parquet_object["sha256"]),
            contract(),
        )
        assert table.to_pylist() == [
            {"session": "2026-07-01", "value": 1},
            {"session": "2026-07-02", "value": 2},
        ]
    finally:
        client.close()


def test_remote_stage_promotes_and_recovers_atomically(
    tmp_path: Path,
) -> None:
    objects, client = remote(tmp_path, role="compute")
    try:
        with objects.publication_guard("run_success"):
            with objects.stage(
                "run_success",
                "attempt-1",
                cleanup_uncommitted_payloads=True,
            ) as stage:
                candidate = stage.put_json({"result": "committed"})
                manifest = stage.put_json(
                    {"candidate": candidate["sha256"]}
                )
                stage.put_manifest(
                    "result_success",
                    {"candidate": candidate},
                )
                with stage.publication(
                    manifest_sha256=str(manifest["sha256"])
                ):
                    pass

        assert objects.read_json(str(candidate["sha256"])) == {
            "result": "committed"
        }
        assert objects.staged_publication_ids(prefix="run_") == []

        with pytest.raises(RuntimeError, match="database commit"):
            with objects.stage(
                "run_failure",
                "attempt-1",
                cleanup_uncommitted_payloads=True,
            ) as stage:
                abandoned = stage.put_json({"result": "abandoned"})
                manifest = stage.put_json(
                    {"candidate": abandoned["sha256"]}
                )
                stage.put_manifest(
                    "result_failure",
                    {"candidate": abandoned},
                )
                with stage.publication(
                    manifest_sha256=str(manifest["sha256"])
                ):
                    raise RuntimeError("database commit failed")

        assert objects.staged_publication_ids(prefix="run_") == [
            "run_failure"
        ]
        assert objects.recover_staged_publication(
            "run_failure",
            committed_manifest_sha256=None,
        )
        assert objects.staged_publication_ids(prefix="run_") == []
        with pytest.raises(ParquetContractError):
            objects.read_json(str(abandoned["sha256"]))
    finally:
        client.close()


def test_object_store_tokens_are_role_scoped_and_non_interchangeable(
    tmp_path: Path,
) -> None:
    api_objects, api_client = remote(tmp_path, role="api")
    compute_objects = RemoteObjectStore(
        "http://object-store",
        TOKENS["compute"],
        client=api_client,
    )
    try:
        assert api_objects.probe()
        assert not RemoteObjectStore(
            "http://object-store",
            "wrong-token",
            client=api_client,
        ).probe()
        stored = compute_objects.put_json({"visible": True})
        assert api_objects.read_json(str(stored["sha256"])) == {
            "visible": True
        }
        with api_objects.publication_guard("run_api_cancel"):
            pass
        with pytest.raises(ParquetContractError):
            api_objects.put_json({"forbidden": True})

        with api_objects.stage(
            "track_activation",
            "activation_attempt",
            cleanup_uncommitted_payloads=True,
        ) as stage:
            activation = stage.put_json({"kind": "activation"})
            observations = stage.put_parquet_rows(
                [{"session": "2026-07-01", "value": 1}],
                contract(),
            )
            checkpoint = stage.put_json(
                {
                    "activation": activation,
                    "observations": observations,
                }
            )
            stage.put_manifest(
                "checkpoint_activation",
                {"checkpoint": checkpoint},
            )
            with stage.publication(
                manifest_sha256=str(checkpoint["sha256"])
            ):
                pass
        assert api_objects.read_json(str(activation["sha256"])) == {
            "kind": "activation"
        }
        assert api_objects.read_parquet(
            str(observations["sha256"]),
            contract(),
        ).to_pylist() == [
            {"session": "2026-07-01", "value": 1}
        ]
        with pytest.raises(RuntimeError, match="cancelled"):
            with compute_objects.stage(
                "run_cancelled",
                "attempt_cancelled",
                cleanup_uncommitted_payloads=True,
            ) as stage:
                candidate = stage.put_json({"status": "abandoned"})
                manifest = stage.put_json(
                    {"candidate": candidate}
                )
                with stage.publication(
                    manifest_sha256=str(manifest["sha256"])
                ):
                    raise RuntimeError("cancelled")
        assert api_objects.recover_staged_publication(
            "run_cancelled",
            committed_manifest_sha256=None,
        )
        with pytest.raises(ParquetContractError):
            api_objects.staged_publication_ids(prefix="run_")
    finally:
        api_client.close()


def test_active_stage_is_locked_and_owned_by_its_role(
    tmp_path: Path,
) -> None:
    compute_objects, client = remote(tmp_path, role="compute")
    data_objects = RemoteObjectStore(
        "http://object-store",
        TOKENS["data"],
        client=client,
    )
    try:
        with compute_objects.stage(
            "run_active",
            "attempt_active",
            cleanup_uncommitted_payloads=True,
        ) as stage:
            candidate = stage.put_json({"status": "writing"})
            assert not compute_objects.recover_staged_publication(
                "run_active",
                committed_manifest_sha256=None,
            )
            assert compute_objects.staged_publication_ids(
                prefix="run_"
            ) == ["run_active"]
            with pytest.raises(ParquetContractError):
                data_objects.recover_staged_publication(
                    "run_active",
                    committed_manifest_sha256=None,
                )
            with pytest.raises(ParquetContractError):
                data_objects.staged_publication_ids(prefix="run_")
            with pytest.raises(ParquetContractError):
                data_objects.wait_for_staged_publication("run_active")
            with pytest.raises(ParquetContractError):
                data_objects.stage(
                    "run_active",
                    "attempt_active",
                ).__enter__()
            with pytest.raises(ParquetContractError):
                compute_objects.stage(
                    "run_active",
                    "attempt_active",
                ).__enter__()
            stage.put_json({"status": "still-writing"})
        with pytest.raises(ParquetContractError):
            compute_objects.read_json(str(candidate["sha256"]))
    finally:
        client.close()


def test_manifest_namespaces_are_role_scoped(
    tmp_path: Path,
) -> None:
    compute_objects, client = remote(tmp_path, role="compute")
    data_objects = RemoteObjectStore(
        "http://object-store",
        TOKENS["data"],
        client=client,
    )
    try:
        with pytest.raises(ParquetContractError):
            compute_objects.put_manifest(
                "dsr_poison",
                {"role": "compute"},
            )
        with pytest.raises(ParquetContractError):
            data_objects.put_manifest(
                "result_poison",
                {"role": "data"},
            )
        with compute_objects.stage(
            "run_manifest",
            "attempt_manifest",
        ) as stage:
            with pytest.raises(ParquetContractError):
                stage.put_manifest(
                    "dsr_staged_poison",
                    {"role": "compute"},
                )

        with data_objects.stage(
            "dsp_publication",
            "dpa_publication",
        ) as stage:
            payload = stage.put_json({"kind": "dataset"})
            manifest = stage.put_json({"payload": payload})
            stage.put_manifest(
                "dsr_release",
                {"payload": payload},
            )
            with stage.publication(
                manifest_sha256=str(manifest["sha256"])
            ):
                pass
        assert data_objects.read_json(str(payload["sha256"])) == {
            "kind": "dataset"
        }
    finally:
        client.close()


def test_crashed_stage_lease_expires_and_becomes_recoverable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        object_store_service,
        "LEASE_SECONDS",
        0.05,
    )
    client = TestClient(
        create_object_store_app(tmp_path / "objects", TOKENS)
    )
    headers = {"Authorization": f"Bearer {TOKENS['compute']}"}
    try:
        opened = client.post(
            "/v1/stages/run_crashed/attempts/attempt_crashed",
            headers=headers,
            json={"cleanup_uncommitted_payloads": True},
        )
        assert opened.status_code == 200
        crashed_objects = RemoteObjectStore(
            "http://object-store",
            TOKENS["compute"],
            client=client,
        )
        crashed_objects.wait_for_staged_publication("run_crashed")
        recovered = client.post(
            "/v1/stages/run_crashed/recover",
            headers=headers,
            json={"committed_manifest_sha256": None},
        )
        assert recovered.status_code == 200
        assert recovered.json() == {"recovered": True}
        first_guard = client.post(
            "/v1/guards/run_guard_crashed",
            headers=headers,
        )
        assert first_guard.status_code == 200
        time.sleep(0.1)
        monkeypatch.setattr(
            object_store_service,
            "LEASE_SECONDS",
            30.0,
        )
        second_guard = client.post(
            "/v1/guards/run_guard_crashed",
            headers=headers,
        )
        assert second_guard.status_code == 200
        released = client.delete(
            f"/v1/guards/{second_guard.json()['token']}",
            headers=headers,
        )
        assert released.status_code == 200
    finally:
        client.close()
