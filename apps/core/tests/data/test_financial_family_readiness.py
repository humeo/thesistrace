import pytest

from thesistrace.data.models import FieldFamilyAvailability
from thesistrace.data.overview import financial_family_readiness


def family(name, readiness, available=True, category='financial'):
    return FieldFamilyAvailability(
        family_id=name,
        research_category=category,
        source_endpoints=[name],
        supported_field_ids=[name + '.value'],
        available_field_ids=[name + '.value'] if available else [],
        coverage_start=None,
        coverage_end=None,
        readiness=readiness,
    )


@pytest.mark.parametrize(
    ('states', 'expected'),
    [
        ([], 'not_ready'),
        ([('not_ready', False)], 'not_ready'),
        ([('ready', True), ('not_ready', False)], 'ready_with_gaps'),
        ([('ready', True), ('partial', True)], 'ready_with_gaps'),
        ([('ready', True), ('ready_with_pending', True)], 'ready_with_pending'),
        ([('ready_with_pending', True), ('ready_with_gaps', True)], 'ready_with_gaps'),
        ([('ready', True), ('ready', True)], 'ready'),
    ],
)
def test_financial_readiness_aggregates_available_families(states, expected):
    families = [family(str(i), state, available) for i, (state, available) in enumerate(states)]
    families.append(family('price', 'partial', category='market'))
    assert financial_family_readiness(families) == expected
