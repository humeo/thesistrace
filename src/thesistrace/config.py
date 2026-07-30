from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    metadata_path: Path
    object_root: Path
    worker_stale_after_seconds: int = 30
