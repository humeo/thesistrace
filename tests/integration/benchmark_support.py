from datetime import date, timedelta
from pathlib import Path

from thesistrace.benchmark import BenchmarkLevel


class FixtureBenchmarkSource:
    def __init__(self) -> None:
        self.requests: list[tuple[str, str]] = []

    def collect_open_levels(
        self,
        *,
        start_session: str,
        end_session: str,
    ) -> tuple[BenchmarkLevel, ...]:
        self.requests.append((start_session, end_session))
        current = date.fromisoformat(start_session)
        end = date.fromisoformat(end_session)
        levels: list[BenchmarkLevel] = []
        while current <= end:
            if current.weekday() < 5:
                levels.append(
                    BenchmarkLevel(
                        session=current.isoformat(),
                        open_level=f"{current.toordinal()}.1",
                    )
                )
            current += timedelta(days=1)
        return tuple(levels)


def benchmark_mount_for_data_mount(data_mount: Path) -> Path:
    resolved = data_mount.resolve()
    return resolved.parent / f"{resolved.name}-benchmark-data"


__all__ = ("FixtureBenchmarkSource", "benchmark_mount_for_data_mount")
