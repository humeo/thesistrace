from __future__ import annotations

from datetime import datetime

from thesistrace.data.financial_candidate import FinancialCandidateStore
from thesistrace.data.financial_indicator_candidate import FinancialIndicatorCandidateStore
from thesistrace.data.generation_family import MountedFamilyGenerationDescriptor
from thesistrace.data.generation_store import GenerationStoreError, MountedGenerationStore


class FinancialComposition:
    """Verify current task evidence and bytes before composing against an accepted Head.

    The caller retains its mutation lock, receipt, protection lease and CAS. The
    candidate store must be the one that built this task's proof; proof is never
    persisted or replaced with a trusted flag on the composed manifest.
    """

    def __init__(
        self,
        generations: MountedGenerationStore,
        candidates: FinancialCandidateStore,
    ) -> None:
        self._generations = generations
        self._candidates = candidates

    def compose(
        self,
        market_manifest_sha256: str,
        candidate_manifest_sha256: str,
        *,
        financial_predecessor: str | None,
        prepared_at: datetime,
        publication_coordinate: str,
        indicator_manifest_sha256: str | None = None,
        indicator_store: FinancialIndicatorCandidateStore | None = None,
    ) -> MountedFamilyGenerationDescriptor:
        market = self._generations.inspect_root(market_manifest_sha256)
        if market.financial_candidate_manifest_sha256 != financial_predecessor:
            raise GenerationStoreError("Financial composition predecessor differs from Head")
        self._candidates.verify_for_publication(candidate_manifest_sha256)
        self._candidates.reopen_against_prevalidated_market_generation(
            candidate_manifest_sha256,
            market_manifest_sha256,
        )
        composed = self._generations._compose_prevalidated_financial_candidate(
            market_manifest_sha256,
            candidate_manifest_sha256,
            prepared_at=prepared_at,
            publication_coordinate=publication_coordinate,
        )
        if indicator_manifest_sha256 is not None:
            if indicator_store is None:
                raise GenerationStoreError(
                    "Indicator composition requires the task validation store"
                )
            composed = self._generations._compose_incremental_indicator_candidate(
                composed.manifest_sha256,
                indicator_manifest_sha256,
                published_generation_sha256=market_manifest_sha256,
                prepared_at=prepared_at,
                indicator_store=indicator_store,
            )
        return composed

    def verify_persisted(
        self,
        composed_manifest_sha256: str,
        market_manifest_sha256: str,
        candidate_manifest_sha256: str,
        *,
        financial_predecessor: str | None,
        prepared_at: datetime,
        publication_coordinate: str,
    ) -> None:
        # Restart lost the task-local proof. Re-establish it without changing the
        # recorded preparation/coordinate or the immutable publication identity.
        checked = self.compose(
            market_manifest_sha256,
            candidate_manifest_sha256,
            financial_predecessor=financial_predecessor,
            prepared_at=prepared_at,
            publication_coordinate=publication_coordinate,
        )
        if checked.manifest_sha256 != composed_manifest_sha256:
            raise GenerationStoreError("Persisted Financial composition identity is invalid")
