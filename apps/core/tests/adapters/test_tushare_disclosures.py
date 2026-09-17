from thesistrace.adapters.tushare_disclosures import TushareDisclosureSource
from thesistrace.data.source import RawSourceResponse


class Provider:
    def query_raw(self, api_name, *, params, fields):
        assert api_name == "disclosure_date"
        rows = [] if params["end_date"] != "20260630" else [
            ("000001.SZ", "20260905", "20260630", "20260828", "20260829", "20260905"),
            ("000002.SZ", "20260820", "20260630", "20260830", None, None),
            ("000003.SZ", "20260901", "20260630", "20260912", "20260912", None),
        ]
        return RawSourceResponse(tuple(fields), tuple(rows))


def test_only_actual_disclosures_due_by_target_create_report_requirements():
    result = TushareDisclosureSource(Provider()).discover(
        start_date="2026-09-01", end_date="2026-09-11",
        allowed_ts_codes={"000001.SZ", "000002.SZ", "000003.SZ"},
    )
    assert result.completed_periods == ("2025-12-31", "2026-03-31", "2026-06-30")
    assert [(r.ts_code, r.report_period, r.actual_date) for r in result.reports] == [
        ("000001.SZ", "2026-06-30", "2026-08-29"),
    ]
    assert result.gaps == ()


def test_capped_disclosure_list_is_a_gap_not_a_complete_check():
    class CappedProvider(Provider):
        def query_raw(self, api_name, *, params, fields):
            row = ("000001.SZ", "20260829", params["end_date"], None, "20260829", None)
            return RawSourceResponse(tuple(fields), (row,) * 6000)

    result = TushareDisclosureSource(CappedProvider()).discover(
        start_date="2026-09-01", end_date="2026-09-11", allowed_ts_codes={"000001.SZ"},
    )
    assert result.completed_periods == ()
    assert len(result.gaps) == 3
    assert result.reports == ()
