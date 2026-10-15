from decimal import Decimal

import pytest
from test_financial_indicator_series import fact, resolver

from thesistrace.data.fields import alpha_field_catalog


def test_interest_catalog_states_supplier_definition_without_claiming_gross_expense():
    field = next(field for field in alpha_field_catalog()
                 if field.field_id == "financial.indicator.interest_expense")
    assert field.alpha.identifier == "interest_expense"
    assert field.source_lineage == "tushare.fina_indicator.interst_income"
    assert field.display_name == "供应商利息指标"
    assert "may be net of interest income" in field.description
    assert "not guaranteed gross statement interest expense" in field.description
    assert "cash interest paid" in field.description


@pytest.mark.parametrize("period,session,expense,income,raw", [
    ("20180630", "2018-09-03", "32321571.00", "15859651.90", "16461919.10"),
    ("20180930", "2018-12-26", "55802941.46", "55525919.49", "277021.97"),
])
def test_600120_interest_preserves_frozen_supplier_values(period, session, expense, income, raw):
    # Frozen source generation fd4a8a3ca38b0626e8b7093681e4d9cf0ef41977204a8a526055897cc2911736.
    # Independent report reconciliation: qagentis-research-20261013/INTEREST-BURDEN-CASE-600120.md.
    # These two cases establish ambiguity; they do not define every source row as net interest.
    assert Decimal(expense) - Decimal(income) == Decimal(raw)
    field = "financial.indicator.interest_expense"
    result = resolver([fact(period, session, interst_income=raw)]).resolve_table(
        manifest_sha256="a" * 64, field_ids=(field,), sessions=(session,),
        instrument_ids=("stock-1",),
    )
    assert result[field].to_pylist() == [float(raw)]
    assert result[field][0].as_py() != float(expense)
