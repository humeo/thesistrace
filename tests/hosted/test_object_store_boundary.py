import time
from pathlib import Path

import httpx
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
}


def remote(
    tmp_path: Path,
    *,
    role: str,
) -> tuple[RemoteObjectStore, TestClient]:
    client = TestClient(
        create_object_store_app(
            tmp_path / "objects",
            TOKENS,
        )
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


def test_remote_readiness_covers_the_constrained_cpu_budget() -> None:
    requested: list[tuple[str, int]] = []

    class Response:
        status_code = 200

    class Client:
        def get(self, path: str, *, timeout: int) -> Response:
            requested.append((path, timeout))
            return Response()

    objects = RemoteObjectStore(
        "http://object-store",
        TOKENS["api"],
        client=Client(),
    )

    assert objects.ready() is True
    assert requested == [("/ready", 15)]


def test_private_object_store_retries_transient_read_disconnects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = b'{"value":"canonical"}'
    requested: list[tuple[str, str]] = []
    sleeps: list[float] = []

    class Client:
        def request(
            self,
            method: str,
            path: str,
            **_options: object,
        ) -> httpx.Response:
            requested.append((method, path))
            if len(requested) == 1:
                raise httpx.RemoteProtocolError(
                    "server disconnected without sending a response"
                )
            return httpx.Response(
                200,
                content=payload,
                request=httpx.Request(method, f"http://object-store{path}"),
            )

    monkeypatch.setattr(time, "sleep", sleeps.append)
    objects = RemoteObjectStore(
        "http://object-store",
        TOKENS["api"],
        client=Client(),
    )

    digest = (
        "31b824660c304dcb39024ba5a6df5dd5cddb2dd6f00b2f3b4ce3dd3a7f77eb01"
    )

    assert objects.read_json(digest) == {"value": "canonical"}
    assert requested == [
        ("GET", f"/v1/objects/{digest}/json"),
        ("GET", f"/v1/objects/{digest}/json"),
    ]
    assert sleeps == [0.1]


def test_private_object_store_bounds_persistent_read_disconnects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = 0
    sleeps: list[float] = []

    class Client:
        def request(self, *_args: object, **_options: object) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            raise httpx.RemoteProtocolError("persistent disconnect")

    monkeypatch.setattr(time, "sleep", sleeps.append)
    objects = RemoteObjectStore(
        "http://object-store",
        TOKENS["api"],
        client=Client(),
    )

    with pytest.raises(ParquetContractError):
        objects.read_json("0" * 64)

    assert attempts == 32
    assert sleeps[:5] == [0.1, 0.2, 0.4, 0.8, 1.6]
    assert sleeps[-1] == 2.0


def test_private_object_store_preserves_typed_object_contract(
    tmp_path: Path,
) -> None:
    objects, client = remote(tmp_path, role="api")
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
    objects, client = remote(tmp_path, role="api")
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
        create_object_store_app(
            tmp_path / "objects",
            TOKENS,
        )
    )
    headers = {"Authorization": f"Bearer {TOKENS['api']}"}
    try:
        opened = client.post(
            "/v1/stages/run_crashed/attempts/attempt_crashed",
            headers=headers,
            json={"cleanup_uncommitted_payloads": True},
        )
        assert opened.status_code == 200
        crashed_objects = RemoteObjectStore(
            "http://object-store",
            TOKENS["api"],
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
