import hashlib
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pyarrow as pa
import pytest
from botocore.client import BaseClient
from botocore.exceptions import ClientError, ResponseStreamingError

from thesistrace.entrypoints.runtime import CoreSettings, open_core_runtime
from thesistrace.publication import (
    JsonPayload,
    ParquetRowsPayload,
    Publication,
    PublicationPreparationError,
    PublicationUnavailableError,
    PublicationVerificationError,
)
from thesistrace.publication.serialization import (
    ParquetWriterContract,
    canonical_json_bytes,
)

ROWS_CONTRACT = ParquetWriterContract(
    name="ticket-05-rows",
    version=1,
    schema=pa.schema(
        [
            pa.field("session", pa.string(), nullable=False),
            pa.field("value", pa.float64(), nullable=False),
        ]
    ),
    sort_keys=("session",),
)


@pytest.fixture(autouse=True)
def clean_publication_objects(
    core_settings: CoreSettings,
    rustfs_admin: BaseClient,
) -> Iterator[None]:
    _clear_bucket(rustfs_admin, core_settings.s3_bucket)
    yield
    _clear_bucket(rustfs_admin, core_settings.s3_bucket)


def test_prepare_is_canonical_idempotent_and_verified(core_settings: CoreSettings) -> None:
    payloads = {
        "metadata": JsonPayload({"z": 3, "alpha": "量化"}),
        "rows": ParquetRowsPayload(
            rows=(
                {"session": "2026-01-06", "value": 2.0},
                {"session": "2026-01-05", "value": 1.0},
            ),
            contract=ROWS_CONTRACT,
        ),
    }
    provenance = {"source": "fixture", "sessions": ["2026-01-05", "2026-01-06"]}

    with open_core_runtime(core_settings) as runtime:
        first = runtime.publication.prepare(
            kind="dataset.fixture",
            payloads=payloads,
            provenance=provenance,
        )
        second = runtime.publication.prepare(
            kind="dataset.fixture",
            payloads={
                "rows": ParquetRowsPayload(
                    rows=tuple(reversed(payloads["rows"].rows)),
                    contract=ROWS_CONTRACT,
                ),
                "metadata": JsonPayload({"alpha": "量化", "z": 3}),
            },
            provenance={"sessions": ["2026-01-05", "2026-01-06"], "source": "fixture"},
        )

        assert first.manifest_sha256 == second.manifest_sha256
        assert first.object_count == second.object_count == 2
        assert "key" not in repr(first).lower()

        verified = runtime.publication.verify_prepared(second)
        assert verified.kind == "dataset.fixture"
        assert verified.manifest_sha256 == first.manifest_sha256
        assert verified.provenance == provenance
        assert verified.payloads["metadata"].content == canonical_json_bytes(
            {"alpha": "量化", "z": 3}
        )
        assert verified.payloads["rows"].media_type == "application/vnd.apache.parquet"


def test_all_payloads_are_serialized_before_any_upload(
    core_settings: CoreSettings,
    rustfs_admin: BaseClient,
) -> None:
    valid_content = canonical_json_bytes({"must_not_upload": "ticket-05"})

    with open_core_runtime(core_settings) as runtime:
        with pytest.raises(PublicationPreparationError) as captured:
            runtime.publication.prepare(
                kind="serialization.atomicity",
                payloads={
                    "a_valid": JsonPayload({"must_not_upload": "ticket-05"}),
                    "z_invalid": ParquetRowsPayload(
                        rows=({"session": "2026-01-05", "value": "not-a-float"},),
                        contract=ROWS_CONTRACT,
                    ),
                },
                provenance={"ticket": 5},
            )

    assert str(captured.value) == "Parquet payload violates its contract"
    assert not _bucket_contains_content(rustfs_admin, core_settings.s3_bucket, valid_content)


@pytest.mark.parametrize(
    ("code", "status", "expected_type"),
    [
        ("ServiceUnavailable", 503, PublicationUnavailableError),
        ("AccessDenied", 403, PublicationPreparationError),
    ],
)
def test_bucket_failures_distinguish_transient_from_deterministic_errors(
    core_settings: CoreSettings,
    monkeypatch: pytest.MonkeyPatch,
    code: str,
    status: int,
    expected_type: type[Exception],
) -> None:
    def fail_head_bucket(**_arguments: object) -> None:
        raise ClientError(
            {
                "Error": {"Code": code},
                "ResponseMetadata": {"HTTPStatusCode": status},
            },
            "HeadBucket",
        )

    with open_core_runtime(core_settings) as runtime:
        monkeypatch.setattr(runtime.publication._s3, "head_bucket", fail_head_bucket)
        with pytest.raises(expected_type) as captured:
            runtime.publication.prepare(
                kind="classification.probe",
                payloads={"only": JsonPayload({"valid": True})},
                provenance={"ticket": 23},
            )

    assert isinstance(captured.value, PublicationUnavailableError) is (status >= 500)


@pytest.mark.parametrize("damage", ["missing", "truncated", "substituted"])
def test_verification_rejects_damaged_object_without_a_bundle(
    core_settings: CoreSettings,
    rustfs_admin: BaseClient,
    damage: str,
) -> None:
    expected = canonical_json_bytes({"case": damage, "value": "0123456789"})

    with open_core_runtime(core_settings) as runtime:
        prepared = runtime.publication.prepare(
            kind=f"verification.{damage}",
            payloads={"only": JsonPayload({"case": damage, "value": "0123456789"})},
            provenance={"ticket": 5},
        )
        target_key = _find_key_with_content(rustfs_admin, core_settings.s3_bucket, expected)
        if damage == "missing":
            rustfs_admin.delete_object(Bucket=core_settings.s3_bucket, Key=target_key)
        elif damage == "truncated":
            rustfs_admin.put_object(
                Bucket=core_settings.s3_bucket,
                Key=target_key,
                Body=expected[:-1],
            )
        else:
            rustfs_admin.put_object(
                Bucket=core_settings.s3_bucket,
                Key=target_key,
                Body=b"x" * len(expected),
            )

        with pytest.raises(PublicationVerificationError):
            runtime.publication.verify_prepared(prepared)


def test_prepare_never_overwrites_a_conflicting_content_address(
    core_settings: CoreSettings,
    rustfs_admin: BaseClient,
) -> None:
    expected = canonical_json_bytes({"immutable": True})

    with open_core_runtime(core_settings) as runtime:
        prepared = runtime.publication.prepare(
            kind="immutability.probe",
            payloads={"only": JsonPayload({"immutable": True})},
            provenance={"ticket": 5},
        )
        target_key = _find_key_with_content(rustfs_admin, core_settings.s3_bucket, expected)
        substitute = b"!" * len(expected)
        rustfs_admin.put_object(
            Bucket=core_settings.s3_bucket,
            Key=target_key,
            Body=substitute,
        )

        with pytest.raises(PublicationVerificationError):
            runtime.publication.prepare(
                kind="immutability.probe",
                payloads={"only": JsonPayload({"immutable": True})},
                provenance={"ticket": 5},
            )
        stored = rustfs_admin.get_object(
            Bucket=core_settings.s3_bucket,
            Key=target_key,
        )["Body"].read()
        assert stored == substitute
        assert hashlib.sha256(stored).hexdigest() != prepared.payload_sha256s["only"]


def test_concurrent_prepare_uses_conditional_create_without_overwrite(
    core_settings: CoreSettings,
    rustfs_admin: BaseClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = canonical_json_bytes({"race": "ticket-05"})
    digest = hashlib.sha256(expected).hexdigest()
    barrier = Barrier(2)
    original_object_exists = Publication._object_exists

    def synchronize_absence(self: Publication, candidate_digest: str) -> bool:
        if candidate_digest == digest:
            barrier.wait(timeout=5)
            return False
        return original_object_exists(self, candidate_digest)

    with open_core_runtime(core_settings) as runtime:
        runtime.publication.prepare(
            kind="race.bucket.warmup",
            payloads={"warmup": JsonPayload({"warmup": True})},
            provenance={"ticket": 5},
        )
        monkeypatch.setattr(Publication, "_object_exists", synchronize_absence)

        def prepare_once() -> str:
            return runtime.publication.prepare(
                kind="race.concurrent",
                payloads={"only": JsonPayload({"race": "ticket-05"})},
                provenance={"ticket": 5},
            ).manifest_sha256

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _index: prepare_once(), range(2)))

    assert results[0] == results[1]
    target_key = _find_key_with_content(rustfs_admin, core_settings.s3_bucket, expected)
    stored = rustfs_admin.get_object(
        Bucket=core_settings.s3_bucket,
        Key=target_key,
    )["Body"].read()
    assert stored == expected


@pytest.mark.parametrize("operation", ["prepare", "verify"])
def test_transient_response_stream_failure_is_retried_at_read_boundary(
    core_settings: CoreSettings,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    payloads = {"only": JsonPayload({"stream": "retry"})}

    with open_core_runtime(core_settings) as runtime:
        prepared = runtime.publication.prepare(
            kind="stream.retry",
            payloads=payloads,
            provenance={"ticket": 49},
        )
        original_get_object = runtime.publication._s3.get_object
        calls = 0
        failed_body = _FailingResponseBody()

        def fail_first_read(**arguments: object) -> object:
            nonlocal calls
            calls += 1
            if calls == 1:
                return {"Body": failed_body}
            return original_get_object(**arguments)

        monkeypatch.setattr(runtime.publication._s3, "get_object", fail_first_read)
        if operation == "prepare":
            runtime.publication.prepare(
                kind="stream.retry",
                payloads=payloads,
                provenance={"ticket": 49},
            )
        else:
            runtime.publication.verify_prepared(prepared)

    assert calls == 2
    assert failed_body.closed is True


def test_transient_response_stream_retries_are_bounded(
    core_settings: CoreSettings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with open_core_runtime(core_settings) as runtime:
        prepared = runtime.publication.prepare(
            kind="stream.exhaustion",
            payloads={"only": JsonPayload({"stream": "exhaustion"})},
            provenance={"ticket": 49},
        )
        calls = 0
        failed_bodies: list[_FailingResponseBody] = []

        def fail_every_read(**_arguments: object) -> object:
            nonlocal calls
            calls += 1
            body = _FailingResponseBody()
            failed_bodies.append(body)
            return {"Body": body}

        monkeypatch.setattr(runtime.publication._s3, "get_object", fail_every_read)
        with pytest.raises(PublicationUnavailableError) as captured:
            runtime.publication.verify_prepared(prepared)

    assert calls == 3
    assert all(body.closed for body in failed_bodies)
    assert str(captured.value) == "Publication object read is temporarily unavailable"


class _FailingResponseBody:
    def __init__(self) -> None:
        self.closed = False

    def read(self) -> bytes:
        raise ResponseStreamingError(error=RuntimeError("incomplete response stream"))

    def close(self) -> None:
        self.closed = True


def _find_key_with_content(s3: BaseClient, bucket: str, expected: bytes) -> str:
    response = s3.list_objects_v2(Bucket=bucket)
    for item in response.get("Contents", []):
        key = item["Key"]
        body = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
        if body == expected:
            return str(key)
    raise AssertionError("test object was not uploaded")


def _bucket_contains_content(s3: BaseClient, bucket: str, expected: bytes) -> bool:
    response = s3.list_objects_v2(Bucket=bucket)
    return any(
        s3.get_object(Bucket=bucket, Key=item["Key"])["Body"].read() == expected
        for item in response.get("Contents", [])
    )


def _clear_bucket(s3: BaseClient, bucket: str) -> None:
    try:
        response = s3.list_objects_v2(Bucket=bucket)
    except ClientError as error:
        if str(error.response.get("Error", {}).get("Code", "")) in {
            "404",
            "NoSuchBucket",
            "NotFound",
        }:
            return
        raise
    objects = [{"Key": item["Key"]} for item in response.get("Contents", [])]
    if objects:
        s3.delete_objects(Bucket=bucket, Delete={"Objects": objects})
