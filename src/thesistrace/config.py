import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    metadata_path: Path
    object_root: Path
    working_cache_root: Path | None = None
    worker_stale_after_seconds: int = 30
    tushare_token: str | None = None


def settings_from_environment() -> Settings:
    home = Path(os.environ.get("THESISTRACE_HOME", ".local"))
    return Settings(
        metadata_path=home / "metadata.sqlite3",
        object_root=home / "objects",
        working_cache_root=home / "working-cache",
        tushare_token=os.environ.get("TUSHARE_TOKEN"),
    )
