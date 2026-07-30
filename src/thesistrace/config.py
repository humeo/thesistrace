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
    runtime_mode: str = "local"
    database_url: str | None = None
    database_role: str = "api"
    auth_mode: str = "disabled"
    insforge_jwks_url: str = "http://insforge:7130/.well-known/jwks.json"
    insforge_jwt_issuer: str = "insforge"
    insforge_jwt_audience: str = "thesistrace"
    temporal_address: str = "temporal:7233"
    temporal_namespace: str = "thesistrace"


def settings_from_environment() -> Settings:
    home = Path(os.environ.get("THESISTRACE_HOME", ".local"))
    return Settings(
        metadata_path=home / "metadata.sqlite3",
        object_root=home / "objects",
        working_cache_root=home / "working-cache",
        tushare_token=os.environ.get("TUSHARE_TOKEN"),
        runtime_mode=os.environ.get("THESISTRACE_RUNTIME_MODE", "local"),
        database_url=os.environ.get("THESISTRACE_DATABASE_URL"),
        database_role=os.environ.get("THESISTRACE_DATABASE_ROLE", "api"),
        auth_mode=os.environ.get("THESISTRACE_AUTH_MODE", "disabled"),
        insforge_jwks_url=os.environ.get(
            "THESISTRACE_INSFORGE_JWKS_URL",
            "http://insforge:7130/.well-known/jwks.json",
        ),
        insforge_jwt_issuer=os.environ.get(
            "THESISTRACE_INSFORGE_JWT_ISSUER",
            "insforge",
        ),
        insforge_jwt_audience=os.environ.get(
            "THESISTRACE_INSFORGE_JWT_AUDIENCE",
            "thesistrace",
        ),
        temporal_address=os.environ.get(
            "THESISTRACE_TEMPORAL_ADDRESS",
            "temporal:7233",
        ),
        temporal_namespace=os.environ.get(
            "THESISTRACE_TEMPORAL_NAMESPACE",
            "thesistrace",
        ),
    )
