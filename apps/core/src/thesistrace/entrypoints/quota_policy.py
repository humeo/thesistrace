"""Read effective quotas from Auth without duplicating policy or role knowledge."""

from uuid import UUID

import httpx

from thesistrace.researcher.quota import QuotaPolicy, QuotaPolicyLookup, QuotaPolicyUnavailable


def quota_policy_lookup(auth_origin: str | None) -> QuotaPolicyLookup:
    def lookup(researcher_id: UUID) -> QuotaPolicy:
        if not auth_origin:
            raise QuotaPolicyUnavailable("Quota policy is not configured")
        try:
            response = httpx.get(
                f"{auth_origin}/internal/researchers/{researcher_id}/quota-policy",
                timeout=2.0,
                follow_redirects=False,
            )
            response.raise_for_status()
            return QuotaPolicy.model_validate(response.json())
        except (httpx.HTTPError, ValueError) as error:
            raise QuotaPolicyUnavailable("Quota policy is temporarily unavailable") from error

    return lookup
