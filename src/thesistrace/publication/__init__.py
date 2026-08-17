from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from thesistrace.publication.service import (
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
        lock_publication_mutation,
    )

__all__ = [
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
]


def __getattr__(name: str) -> object:
    if name not in __all__:
        raise AttributeError(name)
    from thesistrace.publication import service

    return getattr(service, name)
