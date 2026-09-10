from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from thesistrace.publication.client_config import (
        PUBLICATION_REQUEST_TIMEOUT_SECONDS,
        publication_request_config,
    )
    from thesistrace.publication.maintenance import PublicationMaintenance
    from thesistrace.publication.service import (
        CompressedJsonPayload,
        JsonPayload,
        ParquetRowsPayload,
        PreparedPublication,
        Publication,
        PublicationNotFoundError,
        PublicationPreparationError,
        PublicationUnavailableError,
        PublicationVerificationError,
        PublishedRef,
        StagedPayload,
        VerifiedBundle,
        VerifiedPayload,
        decode_compressed_json,
        lock_publication_mutation,
        s3_storage_is_available,
    )

__all__ = [
    "PublicationMaintenance",
    "PUBLICATION_REQUEST_TIMEOUT_SECONDS",
    "publication_request_config",
    "CompressedJsonPayload",
    "decode_compressed_json",
    "JsonPayload",
    "lock_publication_mutation",
    "ParquetRowsPayload",
    "PreparedPublication",
    "Publication",
    "PublicationNotFoundError",
    "PublicationPreparationError",
    "PublicationUnavailableError",
    "PublicationVerificationError",
    "PublishedRef",
    "StagedPayload",
    "VerifiedBundle",
    "VerifiedPayload",
    "s3_storage_is_available",
]


def __getattr__(name: str) -> object:
    if name not in __all__:
        raise AttributeError(name)
    if name == "PublicationMaintenance":
        from thesistrace.publication.maintenance import PublicationMaintenance

        return PublicationMaintenance
    if name in {"PUBLICATION_REQUEST_TIMEOUT_SECONDS", "publication_request_config"}:
        from thesistrace.publication import client_config

        return getattr(client_config, name)
    from thesistrace.publication import service

    return getattr(service, name)
