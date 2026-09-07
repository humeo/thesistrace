from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path


@dataclass
class DataIOMeasurement:
    manifest_opens: int = 0
    parquet_object_opens: int = 0
    raw_financial_batch_opens: int = 0
    market_parquet_scans: int = 0
    financial_parquet_scans: int = 0
    bytes_read: int = 0
    rows_scanned: int = 0
    columns_scanned: int = 0

    def snapshot(self) -> dict[str, int]:
        return {
            "manifest_opens": self.manifest_opens,
            "parquet_object_opens": self.parquet_object_opens,
            "raw_financial_batch_opens": self.raw_financial_batch_opens,
            "market_parquet_scans": self.market_parquet_scans,
            "financial_parquet_scans": self.financial_parquet_scans,
            "bytes_read": self.bytes_read,
            "rows_scanned": self.rows_scanned,
            "columns_scanned": self.columns_scanned,
        }


_ACTIVE: ContextVar[DataIOMeasurement | None] = ContextVar(
    "thesistrace_data_io_measurement",
    default=None,
)
_COLD_FILE_READS: ContextVar[bool] = ContextVar(
    "thesistrace_cold_file_reads",
    default=False,
)


@contextmanager
def measure_data_io() -> Iterator[DataIOMeasurement]:
    if _ACTIVE.get() is not None:
        raise RuntimeError("Data I/O measurement is already active")
    measurement = DataIOMeasurement()
    token = _ACTIVE.set(measurement)
    try:
        yield measurement
    finally:
        _ACTIVE.reset(token)


@contextmanager
def cold_file_reads() -> Iterator[None]:
    if _COLD_FILE_READS.get():
        raise RuntimeError("Cold file reads are already active")
    token = _COLD_FILE_READS.set(True)
    try:
        yield
    finally:
        _COLD_FILE_READS.reset(token)


def cold_file_reads_are_active() -> bool:
    return _COLD_FILE_READS.get()


def record_addressed_read(path: Path, byte_count: int) -> None:
    measurement = _ACTIVE.get()
    if measurement is None:
        return
    if byte_count < 0:
        raise ValueError("Data I/O byte count is invalid")
    parts = path.parts
    if path.suffix == ".parquet":
        measurement.parquet_object_opens += 1
    elif "financial" in parts and "raw" in parts:
        measurement.raw_financial_batch_opens += 1
    else:
        measurement.manifest_opens += 1
    measurement.bytes_read += byte_count


def record_parquet_scan(
    *,
    source: str,
    row_count: int,
    column_count: int,
) -> None:
    measurement = _ACTIVE.get()
    if measurement is None:
        return
    if row_count < 0 or column_count < 0:
        raise ValueError("Parquet scan counts are invalid")
    if source == "market":
        measurement.market_parquet_scans += 1
    elif source == "financial":
        measurement.financial_parquet_scans += 1
    else:
        raise ValueError("Parquet scan source is invalid")
    measurement.rows_scanned += row_count
    measurement.columns_scanned += column_count


__all__ = (
    "DataIOMeasurement",
    "cold_file_reads",
    "cold_file_reads_are_active",
    "measure_data_io",
    "record_parquet_scan",
)
