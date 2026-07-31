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
    auth_mode: str = "disabled"
    insforge_jwks_url: str = "http://insforge:7130/.well-known/jwks.json"
    insforge_jwt_issuer: str = "insforge"
    insforge_jwt_audience: str = "thesistrace"
    temporal_address: str = "temporal:7233"
    temporal_namespace: str = "thesistrace"
    compute_slot_preference: str = "p1"
    compute_workflow_poller: bool = True
    object_store_url: str | None = None
    object_store_token: str | None = None
    api_rate_limit_window_seconds: int = 60
    api_user_request_limit: int = 120
    api_workspace_request_limit: int = 240
    api_mutation_request_limit: int = 30


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
    database = os.environ.get("THESISTRACE_DATABASE_NAME", "insforge")
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
        compute_slot_preference=os.environ.get(
            "THESISTRACE_COMPUTE_SLOT_PREFERENCE",
            "p1",
        ),
        compute_workflow_poller=os.environ.get(
            "THESISTRACE_COMPUTE_WORKFLOW_POLLER",
            "true",
        ).lower()
        in {"1", "true", "yes"},
        object_store_url=os.environ.get(
            "THESISTRACE_OBJECT_STORE_URL"
        ),
        object_store_token=environment_value("THESISTRACE_OBJECT_STORE_TOKEN"),
        api_rate_limit_window_seconds=int(
            os.environ.get(
                "THESISTRACE_API_RATE_LIMIT_WINDOW_SECONDS",
                "60",
            )
        ),
        api_user_request_limit=int(
            os.environ.get("THESISTRACE_API_USER_REQUEST_LIMIT", "120")
        ),
        api_workspace_request_limit=int(
            os.environ.get(
                "THESISTRACE_API_WORKSPACE_REQUEST_LIMIT",
                "240",
            )
        ),
        api_mutation_request_limit=int(
            os.environ.get(
                "THESISTRACE_API_MUTATION_REQUEST_LIMIT",
                "30",
            )
        ),
    )
