from dataclasses import replace

import pytest

from thesistrace.adapters.fixture_data import FixtureDataSource
from thesistrace.data import CollectionPlan
from thesistrace.data.validation import validate_bootstrap_batch


def test_data_rejects_provider_output_that_breaks_canonical_coverage() -> None:
    batch = FixtureDataSource().collect(CollectionPlan.bootstrap())
    invalid = replace(
        batch,
        covered_session_range=(batch.covered_session_range[0], "2099-01-01"),
    )

    with pytest.raises(ValueError, match="calendar or three-year coverage"):
        validate_bootstrap_batch(invalid)
