import hashlib

import pyarrow as pa
import pytest
from thesistrace.publication import (
    JsonPayload,
    ParquetRowsPayload,
    PublicationVerificationError,
)

from thesistrace.entrypoints.runtime import CoreSettings, open_core_runtime
from thesistrace.objects import ParquetWriterContract, canonical_json_bytes

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


@pytest.mark.parametrize("damage", ["missing", "truncated", "substituted"])
def test_verification_rejects_damaged_object_without_a_bundle(
    core_settings: CoreSettings,
    damage: str,
) -> None:
    expected = canonical_json_bytes({"case": damage, "value": "0123456789"})

    with open_core_runtime(core_settings) as runtime:
        prepared = runtime.publication.prepare(
            kind=f"verification.{damage}",
            payloads={"only": JsonPayload({"case": damage, "value": "0123456789"})},
            provenance={"ticket": 5},
        )
        target_key = _find_key_with_content(runtime.s3, core_settings.s3_bucket, expected)
        if damage == "missing":
            runtime.s3.delete_object(Bucket=core_settings.s3_bucket, Key=target_key)
        elif damage == "truncated":
            runtime.s3.put_object(
                Bucket=core_settings.s3_bucket,
                Key=target_key,
                Body=expected[:-1],
            )
        else:
            runtime.s3.put_object(
                Bucket=core_settings.s3_bucket,
                Key=target_key,
                Body=b"x" * len(expected),
            )

        with pytest.raises(PublicationVerificationError):
            runtime.publication.verify_prepared(prepared)


def test_prepare_never_overwrites_a_conflicting_content_address(
    core_settings: CoreSettings,
) -> None:
    expected = canonical_json_bytes({"immutable": True})

    with open_core_runtime(core_settings) as runtime:
        prepared = runtime.publication.prepare(
            kind="immutability.probe",
            payloads={"only": JsonPayload({"immutable": True})},
            provenance={"ticket": 5},
        )
        target_key = _find_key_with_content(runtime.s3, core_settings.s3_bucket, expected)
        substitute = b"!" * len(expected)
        runtime.s3.put_object(
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
        stored = runtime.s3.get_object(
            Bucket=core_settings.s3_bucket,
            Key=target_key,
        )["Body"].read()
        assert stored == substitute
        assert hashlib.sha256(stored).hexdigest() != prepared.payload_sha256s["only"]


def _find_key_with_content(s3: object, bucket: str, expected: bytes) -> str:
    response = s3.list_objects_v2(Bucket=bucket)
    for item in response.get("Contents", []):
        key = item["Key"]
        body = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
        if body == expected:
            return str(key)
    raise AssertionError("test object was not uploaded")
