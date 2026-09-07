from typing import TYPE_CHECKING

if TYPE_CHECKING:
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
    from thesistrace.publication import service

    return getattr(service, name)
