import hashlib
import json
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from threading import Event, Thread
from urllib.parse import quote

import httpx
import pyarrow as pa
import pyarrow.parquet as pq

from thesistrace.objects import (
    ParquetContractError,
    ParquetWriterContract,
    canonical_json_bytes,
    parquet_bytes,
    require_pinned_writer_runtime,
)

READ_TRANSPORT_ATTEMPTS = 32
READ_TRANSPORT_MAX_BACKOFF_SECONDS = 2.0


class LeaseHeartbeat:
    def __init__(
        self,
        renew: Callable[[], None],
        lease_seconds: int,
    ) -> None:
        self.renew = renew
        self.interval = max(1.0, lease_seconds / 3)
        self.stop_event = Event()
        self.failure: Exception | None = None
        self.thread = Thread(
            target=self._run,
            name="object-store-lease",
            daemon=True,
        )

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        self.thread.join()

    def _run(self) -> None:
        while not self.stop_event.wait(self.interval):
            try:
                self.renew()
            except Exception as error:
                self.failure = error
                return


class RemoteObjectStore:
    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        client: httpx.Client | None = None,
    ) -> None:
        if not base_url or not token:
            raise ValueError("private ObjectStore URL and token are required")
        self.token = token
        self.client = client or httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=120,
        )

    def probe(self) -> bool:
        try:
            self._request("POST", "/v1/probe", timeout=2)
            return True
        except ParquetContractError:
            return False

    def ready(self) -> bool:
        try:
            response = self.client.get("/ready", timeout=15)
            return response.status_code == 200
        except httpx.HTTPError:
            return False

    def put_json(self, value: object) -> dict[str, object]:
        return self._put_bytes(
            "/v1/objects/json",
            canonical_json_bytes(value),
        )

    def put_parquet_rows(
        self,
        rows: Sequence[Mapping[str, object]],
        contract: ParquetWriterContract,
    ) -> dict[str, object]:
        payload = parquet_bytes(rows, contract)
        stored = self._put_bytes("/v1/objects/parquet", payload)
        return {
            "format": "parquet",
            **stored,
            "writer_contract_id": contract.identifier,
            "writer_contract": contract.descriptor(),
        }

    def put_manifest(self, resource_id: str, value: object) -> None:
        self._request(
            "PUT",
            f"/v1/manifests/{path_segment(resource_id)}",
            content=canonical_json_bytes(value),
        )

    def stage(
        self,
        run_id: str,
        attempt_id: str,
        *,
        cleanup_uncommitted_payloads: bool = False,
    ) -> "RemoteStagedObjectStore":
        return RemoteStagedObjectStore(
            self,
            run_id=run_id,
            attempt_id=attempt_id,
            cleanup_uncommitted_payloads=(cleanup_uncommitted_payloads),
        )

    @contextmanager
    def publication_guard(self, run_id: str) -> Iterator[None]:
        response = self._request(
            "POST",
            f"/v1/guards/{path_segment(run_id)}",
            retry_conflict=True,
        )
        body = response.json()
        token = str(body["token"])
        heartbeat = LeaseHeartbeat(
            lambda: self._request(
                "POST",
                f"/v1/guards/{path_segment(token)}/lease",
            ),
            int(body["lease_seconds"]),
        )
        heartbeat.start()
        body_failed = False
        try:
            yield
        except BaseException:
            body_failed = True
            raise
        finally:
            heartbeat.stop()
            try:
                self._request(
                    "DELETE",
                    f"/v1/guards/{path_segment(token)}",
                )
            except ParquetContractError:
                if not body_failed:
                    raise
        if heartbeat.failure is not None:
            raise ParquetContractError(
                "private ObjectStore publication guard expired"
            ) from heartbeat.failure

    def recover_staged_publication(
        self,
        run_id: str,
        *,
        committed_manifest_sha256: str | None,
    ) -> bool:
        response = self._request(
            "POST",
            f"/v1/stages/{path_segment(run_id)}/recover",
            json={"committed_manifest_sha256": (committed_manifest_sha256)},
        )
        return bool(response.json()["recovered"])

    def staged_publication_ids(self, *, prefix: str) -> list[str]:
        response = self._request(
            "GET",
            "/v1/stages",
            params={"prefix": prefix},
        )
        value = response.json().get("ids")
        if not isinstance(value, list):
            raise ParquetContractError("private ObjectStore returned invalid stage IDs")
        return [str(item) for item in value]

    def wait_for_staged_publication(self, run_id: str) -> None:
        self._request(
            "POST",
            f"/v1/stages/{path_segment(run_id)}/wait",
            retry_conflict=True,
        )

    def read_json(self, digest: str) -> object:
        payload = self._request(
            "GET",
            f"/v1/objects/{digest_segment(digest)}/json",
        ).content
        if hashlib.sha256(payload).hexdigest() != digest:
            raise ParquetContractError("JSON object checksum does not match its identity")
        try:
            value = json.loads(payload)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ParquetContractError("JSON object payload is invalid") from error
        if canonical_json_bytes(value) != payload:
            raise ParquetContractError("JSON object payload is not canonical")
        return value

    def read_parquet_bytes(self, digest: str) -> bytes:
        payload = self._request(
            "GET",
            f"/v1/objects/{digest_segment(digest)}/parquet",
        ).content
        if hashlib.sha256(payload).hexdigest() != digest:
            raise ParquetContractError("Parquet object checksum does not match its identity")
        return payload

    def read_parquet(
        self,
        digest: str,
        contract: ParquetWriterContract,
    ) -> pa.Table:
        require_pinned_writer_runtime()
        payload = self.read_parquet_bytes(digest)
        table = pq.read_table(pa.BufferReader(payload))
        if not table.schema.equals(
            contract.schema,
            check_metadata=True,
        ):
            raise ParquetContractError("Parquet object schema does not match writer contract")
        metadata = pq.ParquetFile(pa.BufferReader(payload)).metadata
        if metadata.num_row_groups != 1:
            raise ParquetContractError("Parquet object must contain exactly one row group")
        return table

    def delete_storage_object(self, object_key: str) -> bool:
        response = self._request(
            "DELETE",
            "/v1/storage-objects",
            json={"object_key": object_key},
        )
        return bool(response.json()["deleted"])

    def _put_bytes(
        self,
        path: str,
        payload: bytes,
    ) -> dict[str, object]:
        response = self._request("PUT", path, content=payload)
        value = response.json()
        return {
            "sha256": str(value["sha256"]),
            "bytes": int(value["bytes"]),
        }

    def _request(self, method: str, path: str, **options) -> httpx.Response:
        retry_conflict = bool(options.pop("retry_conflict", False))
        retry_deadline = time.monotonic() + 120
        transport_attempts = READ_TRANSPORT_ATTEMPTS if method.upper() == "GET" else 1
        transport_attempt = 0
        request_headers = dict(options.pop("headers", {}))
        try:
            while True:
                headers = dict(request_headers)
                headers["Authorization"] = f"Bearer {self.token}"
                try:
                    response = self.client.request(
                        method,
                        path,
                        headers=headers,
                        **options,
                    )
                except httpx.TransportError:
                    transport_attempt += 1
                    if transport_attempt >= transport_attempts:
                        raise
                    time.sleep(
                        min(
                            0.1 * (2 ** (transport_attempt - 1)),
                            READ_TRANSPORT_MAX_BACKOFF_SECONDS,
                        )
                    )
                    continue
                if (
                    response.status_code == 409
                    and retry_conflict
                    and time.monotonic() < retry_deadline
                ):
                    response.close()
                    time.sleep(0.05)
                    continue
                response.raise_for_status()
                return response
        except httpx.HTTPError as error:
            raise ParquetContractError("private ObjectStore request failed") from error


class RemoteStagedObjectStore:
    def __init__(
        self,
        destination: RemoteObjectStore,
        *,
        run_id: str,
        attempt_id: str,
        cleanup_uncommitted_payloads: bool,
    ) -> None:
        self.destination = destination
        self.run_id = run_id
        self.attempt_id = attempt_id
        self.cleanup_uncommitted_payloads = cleanup_uncommitted_payloads
        self.promotion_started = False
        self.promotion_resolved = False
        self.stage_token: str | None = None
        self.heartbeat: LeaseHeartbeat | None = None

    @property
    def path(self) -> str:
        return f"/v1/stages/{path_segment(self.run_id)}/attempts/{path_segment(self.attempt_id)}"

    def __enter__(self) -> "RemoteStagedObjectStore":
        response = self.destination._request(
            "POST",
            self.path,
            json={"cleanup_uncommitted_payloads": (self.cleanup_uncommitted_payloads)},
        )
        body = response.json()
        self.stage_token = str(body["stage_token"])
        self.heartbeat = LeaseHeartbeat(
            lambda: self._stage_request("POST", "lease"),
            int(body["lease_seconds"]),
        )
        self.heartbeat.start()
        return self

    def __exit__(self, _type, _value, _traceback) -> None:
        if self.heartbeat is not None:
            self.heartbeat.stop()
        if not self.promotion_started:
            self._stage_request("DELETE")
        elif not self.promotion_resolved:
            self._stage_request("POST", "release")

    def put_json(self, value: object) -> dict[str, object]:
        return self._put_bytes(
            "json",
            canonical_json_bytes(value),
        )

    def put_parquet_rows(
        self,
        rows: Sequence[Mapping[str, object]],
        contract: ParquetWriterContract,
    ) -> dict[str, object]:
        stored = self._put_bytes(
            "parquet",
            parquet_bytes(rows, contract),
        )
        return {
            "format": "parquet",
            **stored,
            "writer_contract_id": contract.identifier,
            "writer_contract": contract.descriptor(),
        }

    def put_manifest(self, resource_id: str, value: object) -> None:
        self.destination._request(
            "PUT",
            f"{self.path}/manifests/{path_segment(resource_id)}",
            headers=self._stage_headers(),
            content=canonical_json_bytes(value),
        )

    def read_json(self, digest: str) -> object:
        return self.destination.read_json(digest)

    def read_parquet_bytes(self, digest: str) -> bytes:
        return self.destination.read_parquet_bytes(digest)

    def read_parquet(
        self,
        digest: str,
        contract: ParquetWriterContract,
    ) -> pa.Table:
        return self.destination.read_parquet(digest, contract)

    @contextmanager
    def publication(self, *, manifest_sha256: str) -> Iterator[None]:
        self._stage_request(
            "POST",
            "promote",
            json={"manifest_sha256": manifest_sha256},
        )
        self.promotion_started = True
        yield
        self._stage_request("POST", "resolve")
        self.promotion_resolved = True

    def _put_bytes(
        self,
        object_format: str,
        payload: bytes,
    ) -> dict[str, object]:
        response = self._stage_request(
            "PUT",
            f"objects/{object_format}",
            content=payload,
        )
        value = response.json()
        return {
            "sha256": str(value["sha256"]),
            "bytes": int(value["bytes"]),
        }

    def _stage_request(
        self,
        method: str,
        suffix: str = "",
        **options,
    ) -> httpx.Response:
        path = self.path if not suffix else f"{self.path}/{suffix}"
        headers = dict(options.pop("headers", {}))
        headers.update(self._stage_headers())
        return self.destination._request(
            method,
            path,
            headers=headers,
            **options,
        )

    def _stage_headers(self) -> dict[str, str]:
        if self.stage_token is None:
            raise ParquetContractError("private ObjectStore stage is not open")
        return {"X-Stage-Token": self.stage_token}


def path_segment(value: str) -> str:
    if not value or "/" in value or value in {".", ".."}:
        raise ValueError("private ObjectStore identity is not path-safe")
    return quote(value, safe="")


def digest_segment(value: str) -> str:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError("private ObjectStore digest is invalid")
    return value
