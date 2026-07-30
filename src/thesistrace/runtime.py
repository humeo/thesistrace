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


class RuntimeConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True)
class RuntimePorts:
    control_metadata: ControlMetadataPort
    objects: ObjectStorePort
    working_cache: WorkingCachePort
    execution_dispatch: ExecutionDispatchPort


def build_runtime(settings: Settings) -> RuntimePorts:
    if settings.runtime_mode == "local":
        metadata = MetadataStore(settings.metadata_path)
        metadata.initialize()
        return RuntimePorts(
            control_metadata=metadata,
            objects=ImmutableObjectStore(settings.object_root),
            working_cache=WorkingCacheStore(
                settings.working_cache_root
                or settings.metadata_path.parent / "working-cache"
            ),
            execution_dispatch=LocalWorkerDispatch(),
        )
    if settings.runtime_mode == "hosted":
        try:
            from thesistrace.hosted.runtime import build_hosted_runtime
        except ImportError as error:
            raise RuntimeConfigurationError(
                "hosted runtime adapters are unavailable"
            ) from error
        return build_hosted_runtime(settings)
    raise RuntimeConfigurationError(
        f"unsupported THESISTRACE_RUNTIME_MODE: {settings.runtime_mode}"
    )
