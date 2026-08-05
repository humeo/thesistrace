from dataclasses import dataclass

from thesistrace.config import Settings
from thesistrace.objects import ImmutableObjectStore
from thesistrace.ports import (
    ControlMetadataPort,
    ExecutionDispatchPort,
    LocalWorkerDispatch,
    ObjectStorePort,
)
from thesistrace.storage import MetadataStore


@dataclass(frozen=True)
class RuntimePorts:
    control_metadata: ControlMetadataPort
    objects: ObjectStorePort
    execution_dispatch: ExecutionDispatchPort


def build_runtime(settings: Settings) -> RuntimePorts:
    metadata = MetadataStore(settings.metadata_path)
    metadata.initialize()
    return RuntimePorts(
        control_metadata=metadata,
        objects=ImmutableObjectStore(settings.object_root),
        execution_dispatch=LocalWorkerDispatch(),
    )
