import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote


@dataclass(frozen=True)
class Settings:
    metadata_path: Path
    object_root: Path
    working_cache_root: Path | None = None
    worker_stale_after_seconds: int = 30
    tushare_token: str | None = None
    runtime_mode: str = "local"
    database_url: str | None = None
    database_role: str = "api"
    object_store_url: str | None = None
    object_store_token: str | None = None


def environment_value(name: str) -> str | None:
    file_name = os.environ.get(f"{name}_FILE")
    if file_name:
        value = Path(file_name).read_text().rstrip("\n")
        return value or None
    return os.environ.get(name)


def database_url_from_environment() -> str | None:
    configured = environment_value("THESISTRACE_DATABASE_URL")
    if configured:
        return configured
    password = environment_value("THESISTRACE_DATABASE_PASSWORD")
    user = os.environ.get("THESISTRACE_DATABASE_USER")
    if not password or not user:
        return None
    host = os.environ.get("THESISTRACE_DATABASE_HOST", "postgres")
    port = os.environ.get("THESISTRACE_DATABASE_PORT", "5432")
    database = os.environ.get("THESISTRACE_DATABASE_NAME", "thesistrace")
    return (
        f"postgresql://{quote(user, safe='')}:{quote(password, safe='')}"
        f"@{host}:{port}/{quote(database, safe='')}"
    )


def settings_from_environment() -> Settings:
    home = Path(os.environ.get("THESISTRACE_HOME", ".local"))
    return Settings(
        metadata_path=home / "metadata.sqlite3",
        object_root=home / "objects",
        working_cache_root=home / "working-cache",
        tushare_token=environment_value("TUSHARE_TOKEN"),
        runtime_mode=os.environ.get("THESISTRACE_RUNTIME_MODE", "local"),
        database_url=database_url_from_environment(),
        database_role=os.environ.get("THESISTRACE_DATABASE_ROLE", "api"),
        object_store_url=os.environ.get("THESISTRACE_OBJECT_STORE_URL"),
        object_store_token=environment_value("THESISTRACE_OBJECT_STORE_TOKEN"),
    )
