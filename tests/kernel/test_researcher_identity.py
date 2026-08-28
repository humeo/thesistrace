from uuid import UUID

import pytest
from pydantic import ValidationError

from thesistrace.researcher import ResearcherIdentity


def test_researcher_identity_is_an_exact_canonical_auth_value() -> None:
    identity = ResearcherIdentity.model_validate(
        {
            "researcher_id": "9061bab0-c600-4013-9065-89b65dd28d99",
            "email": "researcher@example.com",
            "display_label": "researcher",
        }
    )

    assert identity.researcher_id == UUID("9061bab0-c600-4013-9065-89b65dd28d99")
    assert identity.model_dump(mode="json") == {
        "researcher_id": "9061bab0-c600-4013-9065-89b65dd28d99",
        "email": "researcher@example.com",
        "display_label": "researcher",
    }

    for invalid in (
        {
            "researcher_id": "9061bab0-c600-4013-9065-89b65dd28d99",
            "email": " Researcher@Example.COM ",
            "display_label": "researcher",
        },
        {
            "researcher_id": "9061bab0-c600-4013-9065-89b65dd28d99",
            "email": "researcher@example.com",
            "display_label": " researcher ",
        },
        {
            "researcher_id": "9061bab0-c600-4013-9065-89b65dd28d99",
            "email": "researcher@example.com",
            "display_label": "researcher",
            "active": True,
        },
    ):
        with pytest.raises(ValidationError):
            ResearcherIdentity.model_validate(invalid)
