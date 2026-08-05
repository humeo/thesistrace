from dataclasses import dataclass

from thesistrace.config import Settings
from thesistrace.objects import ImmutableObjectStore
from thesistrace.ports import (
    ControlMetadataPort,
    ExecutionDispatchPort,
    LocalWorkerDispatch,
    ObjectStorePort,
    WorkingCachePort,
)
from thesistrace.storage import MetadataStore
from thesistrace.working_cache import WorkingCacheStore


@dataclass(frozen=True)
class RuntimePorts:
    control_metadata: ControlMetadataPort
    objects: ObjectStorePort
    working_cache: WorkingCachePort
    execution_dispatch: ExecutionDispatchPort


def build_runtime(settings: Settings) -> RuntimePorts:
    metadata = MetadataStore(settings.metadata_path)
    metadata.initialize()
    return RuntimePorts(
        control_metadata=metadata,
        objects=ImmutableObjectStore(settings.object_root),
        working_cache=WorkingCacheStore(
            settings.working_cache_root or settings.metadata_path.parent / "working-cache"
        ),
        execution_dispatch=LocalWorkerDispatch(),
    )
