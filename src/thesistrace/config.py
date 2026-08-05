import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    metadata_path: Path
    object_root: Path
    worker_stale_after_seconds: int = 30
    tushare_token: str | None = None


def environment_value(name: str) -> str | None:
    file_name = os.environ.get(f"{name}_FILE")
    if file_name:
        value = Path(file_name).read_text().rstrip("\n")
        return value or None
    return os.environ.get(name)


def settings_from_environment() -> Settings:
    home = Path(os.environ.get("THESISTRACE_HOME", ".local"))
    return Settings(
        metadata_path=home / "metadata.sqlite3",
        object_root=home / "objects",
        tushare_token=environment_value("TUSHARE_TOKEN"),
    )
