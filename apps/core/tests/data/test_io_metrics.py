from pathlib import Path

from thesistrace.data.generation_files import AddressedFileStore
from thesistrace.data.io_metrics import cold_file_reads, measure_data_io, record_parquet_scan


def test_data_io_measurement_classifies_immutable_reads_and_rows(tmp_path: Path) -> None:
    store = AddressedFileStore(tmp_path)
    manifest = b"manifest"
    parquet = b"parquet"
    raw = b"raw"
    manifest_sha = _store(store, tmp_path / "manifests/sha256/aa/manifest.json", manifest)
    parquet_sha = _store(store, tmp_path / "objects/sha256/bb/object.parquet", parquet)
    raw_sha = _store(store, tmp_path / "financial/raw/sha256/cc/batch.json", raw)

    with measure_data_io() as measurement:
        store.read(tmp_path / "manifests/sha256/aa/manifest.json", manifest_sha)
        store.read(tmp_path / "objects/sha256/bb/object.parquet", parquet_sha)
        store.read(tmp_path / "financial/raw/sha256/cc/batch.json", raw_sha)
        record_parquet_scan(source="financial", row_count=7, column_count=3)

    assert measurement.snapshot() == {
        "manifest_opens": 1,
        "parquet_object_opens": 1,
        "raw_financial_batch_opens": 1,
        "market_parquet_scans": 0,
        "financial_parquet_scans": 1,
        "bytes_read": len(manifest) + len(parquet) + len(raw),
        "rows_scanned": 7,
        "columns_scanned": 3,
    }


def test_nested_measurement_is_rejected_instead_of_double_counting() -> None:
    with measure_data_io():
        try:
            with measure_data_io():
                raise AssertionError("unreachable")
        except RuntimeError as error:
            assert str(error) == "Data I/O measurement is already active"
        else:
            raise AssertionError("nested measurement was accepted")


def test_cold_file_read_mode_reads_and_verifies_the_same_addressed_content(
    tmp_path: Path,
) -> None:
    store = AddressedFileStore(tmp_path)
    content = b"cold-content"
    sha256 = _store(store, tmp_path / "objects/sha256/aa/object.parquet", content)

    with cold_file_reads():
        assert store.read(tmp_path / "objects/sha256/aa/object.parquet", sha256) == content


def _store(store: AddressedFileStore, path: Path, content: bytes) -> str:
    import hashlib

    sha256 = hashlib.sha256(content).hexdigest()
    store.store(path, sha256, content)
    return sha256
