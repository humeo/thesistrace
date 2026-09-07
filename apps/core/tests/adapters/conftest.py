import pytest

from thesistrace.adapters.fixture_data import FixtureDataSource
from thesistrace.data import CanonicalSourceBatch, CollectionPlan


@pytest.fixture(scope="session")
def fixture_bootstrap_batch() -> CanonicalSourceBatch:
    return FixtureDataSource().collect(CollectionPlan.bootstrap())
