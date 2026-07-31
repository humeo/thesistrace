from thesistrace.config import Settings
from thesistrace.hosted.control import PostgresControlMetadataStore
from thesistrace.hosted.object_store import RemoteObjectStore
from thesistrace.ports import LocalWorkerDispatch
from thesistrace.runtime import RuntimePorts
from thesistrace.working_cache import WorkingCacheStore


def build_hosted_runtime(settings: Settings) -> RuntimePorts:
    if not settings.database_url:
        raise RuntimeError("THESISTRACE_DATABASE_URL is required in hosted runtime mode")
    if not settings.object_store_url or not settings.object_store_token:
        raise RuntimeError(
            "private ObjectStore URL and token are required in hosted runtime mode"
        )
    metadata = PostgresControlMetadataStore(
        settings.database_url,
        database_role=settings.database_role,
    )
    return RuntimePorts(
        control_metadata=metadata,
        objects=RemoteObjectStore(
            settings.object_store_url,
            settings.object_store_token,
        ),
        working_cache=WorkingCacheStore(
            settings.working_cache_root
            or settings.object_root.parent / "working-cache"
        ),
        execution_dispatch=LocalWorkerDispatch(),
    )
