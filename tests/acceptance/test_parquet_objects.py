import base64
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pyarrow as pa
import pytest

from thesistrace.objects import (
    ImmutableObjectStore,
    ParquetContractError,
    ParquetWriterContract,
)


def test_parquet_object_round_trips_with_one_exact_content_identity(tmp_path: Path) -> None:
    store = ImmutableObjectStore(tmp_path / "objects")
    contract = parquet_contract()

    entry = store.put_parquet_rows(
        [
            {"instrument_id": "equity:000002.SZ", "session": "2026-07-30", "value": 2.0},
            {"instrument_id": "equity:000001.SZ", "session": "2026-07-30", "value": 1.0},
        ],
        contract,
    )

    payload = store.read_parquet_bytes(str(entry["sha256"]))
    table = store.read_parquet(str(entry["sha256"]), contract)

    assert entry["format"] == "parquet"
    assert entry["bytes"] == len(payload)
    assert entry["sha256"] == hashlib.sha256(payload).hexdigest()
    assert entry["writer_contract_id"] == contract.identifier
    assert entry["writer_contract"] == contract.descriptor()
    assert entry["writer_contract"]["writer"] == {
        "implementation": "pyarrow",
        "implementation_version": "25.0.0",
        "arrow_cpp_version": "25.0.0",
    }
    assert entry["writer_contract"]["compression"] == {
        "codec": "zstd",
        "codec_version": "1.5.7",
        "level": 9,
    }
    assert table.schema == contract.schema
    assert table.to_pylist() == [
        {"instrument_id": "equity:000001.SZ", "session": "2026-07-30", "value": 1.0},
        {"instrument_id": "equity:000002.SZ", "session": "2026-07-30", "value": 2.0},
    ]


def test_parquet_object_is_byte_exact_across_fresh_processes(tmp_path: Path) -> None:
    first = write_in_fresh_process(tmp_path / "first", reverse=False)
    second = write_in_fresh_process(tmp_path / "second", reverse=True)

    assert first["entry"]["sha256"] == second["entry"]["sha256"]
    assert first["entry"]["writer_contract_id"] == second["entry"]["writer_contract_id"]
    assert first["payload"] == second["payload"]


def test_parquet_contract_rejects_rows_without_a_canonical_unique_order(
    tmp_path: Path,
) -> None:
    store = ImmutableObjectStore(tmp_path / "objects")

    with pytest.raises(ParquetContractError, match="unique"):
        store.put_parquet_rows(
            [
                {"instrument_id": "equity:000001.SZ", "session": "2026-07-30", "value": 1.0},
                {"instrument_id": "equity:000001.SZ", "session": "2026-07-30", "value": 2.0},
            ],
            parquet_contract(),
        )


def test_contract_upgrade_keeps_prior_objects_readable(tmp_path: Path) -> None:
    store = ImmutableObjectStore(tmp_path / "objects")
    baseline = parquet_contract()
    changed = ParquetWriterContract(
        name=baseline.name,
        version=baseline.version,
        schema=baseline.schema,
        sort_keys=baseline.sort_keys,
        compression_level=10,
    )

    assert baseline.identifier != changed.identifier
    assert baseline.descriptor() != changed.descriptor()
    baseline_entry = store.put_parquet_rows(
        [{"instrument_id": "equity:000001.SZ", "session": "2026-07-30", "value": 1.0}],
        baseline,
    )
    changed_entry = store.put_parquet_rows(
        [{"instrument_id": "equity:000001.SZ", "session": "2026-07-30", "value": 1.0}],
        changed,
    )

    assert store.read_parquet(str(baseline_entry["sha256"]), baseline).num_rows == 1
    assert store.read_parquet(str(changed_entry["sha256"]), changed).num_rows == 1


def test_parquet_read_rejects_bytes_that_do_not_match_the_content_identity(
    tmp_path: Path,
) -> None:
    store = ImmutableObjectStore(tmp_path / "objects")
    entry = store.put_parquet_rows(
        [{"instrument_id": "equity:000001.SZ", "session": "2026-07-30", "value": 1.0}],
        parquet_contract(),
    )
    path = store.parquet_path_for(str(entry["sha256"]))
    path.write_bytes(path.read_bytes() + b"corrupt")

    with pytest.raises(ParquetContractError, match="checksum"):
        store.read_parquet(str(entry["sha256"]), parquet_contract())


def test_empty_declared_table_still_has_one_deterministic_row_group(
    tmp_path: Path,
) -> None:
    store = ImmutableObjectStore(tmp_path / "objects")
    contract = parquet_contract()

    entry = store.put_parquet_rows([], contract)
    table = store.read_parquet(str(entry["sha256"]), contract)

    assert table.num_rows == 0
    assert table.schema == contract.schema


def parquet_contract() -> ParquetWriterContract:
    return ParquetWriterContract(
        name="test.equity_observation",
        version=1,
        schema=pa.schema(
            [
                pa.field("instrument_id", pa.string(), nullable=False),
                pa.field("session", pa.string(), nullable=False),
                pa.field("value", pa.float64(), nullable=True),
            ]
        ),
        sort_keys=("session", "instrument_id"),
    )


def write_in_fresh_process(root: Path, *, reverse: bool) -> dict[str, object]:
    script = """
import base64
import json
import sys
from pathlib import Path

import pyarrow as pa

from thesistrace.objects import ImmutableObjectStore, ParquetWriterContract

rows = [
    {"instrument_id": "equity:000001.SZ", "session": "2026-07-30", "value": 1.0},
    {"instrument_id": "equity:000002.SZ", "session": "2026-07-30", "value": 2.0},
]
if sys.argv[2] == "reverse":
    rows = [
        dict(reversed(tuple(row.items())))
        for row in reversed(rows)
    ]
contract = ParquetWriterContract(
    name="test.equity_observation",
    version=1,
    schema=pa.schema(
        [
            pa.field("instrument_id", pa.string(), nullable=False),
            pa.field("session", pa.string(), nullable=False),
            pa.field("value", pa.float64(), nullable=True),
        ]
    ),
    sort_keys=("session", "instrument_id"),
)
store = ImmutableObjectStore(Path(sys.argv[1]))
entry = store.put_parquet_rows(rows, contract)
payload = store.read_parquet_bytes(str(entry["sha256"]))
print(json.dumps({"entry": entry, "payload": base64.b64encode(payload).decode("ascii")}))
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(root), "reverse" if reverse else "forward"],
        check=True,
        capture_output=True,
        text=True,
    )
    value = json.loads(result.stdout)
    assert isinstance(value, dict)
    assert base64.b64decode(value["payload"])
    return value
