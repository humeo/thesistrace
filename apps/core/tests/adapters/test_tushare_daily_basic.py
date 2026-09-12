from collections.abc import Mapping, Sequence

import pytest

from thesistrace.adapters.tushare_daily_basic import (
    DAILY_BASIC_SOURCE_FIELDS,
    TushareDailyBasicSource,
)
from thesistrace.data.source import DataSourceError, RawSourceResponse


def response(codes: tuple[str, ...], *, session: str = "20260909") -> RawSourceResponse:
    return RawSourceResponse(
        fields=DAILY_BASIC_SOURCE_FIELDS,
        items=tuple(tuple(
            code if field == "ts_code" else session if field == "trade_date" else None
            for field in DAILY_BASIC_SOURCE_FIELDS
        ) for code in codes),
    )


class Provider:
    def __init__(self, pages: list[RawSourceResponse]) -> None:
        self.pages = iter(pages)
        self.requests: list[dict[str, object]] = []

    def query_raw(self, api_name: str, *, params: Mapping[str, object],
                  fields: Sequence[str]) -> RawSourceResponse:
        assert api_name == "daily_basic"
        assert tuple(fields) == DAILY_BASIC_SOURCE_FIELDS
        self.requests.append(dict(params))
        return next(self.pages)


def test_collect_session_retains_raw_nulls_and_exact_source_contract() -> None:
    raw = response(("600519.SH",))
    provider = Provider([raw])
    collected = TushareDailyBasicSource(provider).collect_session(
        session="2026-09-09", instrument_codes=("600519.SH", "000001.SZ"),
    )
    assert len(DAILY_BASIC_SOURCE_FIELDS) == 19
    assert collected == raw
    assert provider.requests == [{"trade_date": "20260909"}]


def test_full_day_is_split_by_historical_security_without_offset() -> None:
    codes = tuple(f"{number:06}.SZ" for number in range(6000))
    provider = Provider([response(codes), *[response((code,)) for code in codes]])
    collected = TushareDailyBasicSource(provider).collect_session(
        session="2026-09-09", instrument_codes=codes,
    )
    assert collected == response(codes)
    assert provider.requests[1:] == [
        {"trade_date": "20260909", "ts_code": code} for code in codes
    ]


@pytest.mark.parametrize("raw", [
    response(("600519.SH",), session="20260908"),
    response(("600519.SH", "600519.SH")),
    response(("000001.SZ",)),
    RawSourceResponse(fields=("ts_code", "trade_date"), items=()),
])
def test_wrong_scope_duplicates_or_missing_columns_fail_closed(raw: RawSourceResponse) -> None:
    with pytest.raises(DataSourceError):
        TushareDailyBasicSource(Provider([raw])).collect_session(
            session="2026-09-09", instrument_codes=("600519.SH",),
        )


def test_retry_reopens_completed_session_without_provider_network(tmp_path) -> None:
    from thesistrace.adapters.tushare_daily_basic import DailyBasicCheckpoint

    raw = response(("600519.SH",))
    first = TushareDailyBasicSource(Provider([raw]))
    checkpoint = DailyBasicCheckpoint(tmp_path, collection_key="refresh-a")
    first.collect_session(session="2026-09-09", instrument_codes=("600519.SH",),
                          checkpoint=checkpoint)
    second = TushareDailyBasicSource(Provider([]))
    assert second.collect_session(
        session="2026-09-09", instrument_codes=("600519.SH",),
        checkpoint=DailyBasicCheckpoint(tmp_path, collection_key="refresh-a"),
    ) == raw
    assert len(checkpoint.evidence()) == 1


def test_next_refresh_collects_new_observation_of_same_session(tmp_path) -> None:
    from thesistrace.adapters.tushare_daily_basic import DailyBasicCheckpoint

    first = TushareDailyBasicSource(Provider([response(("600519.SH",))]))
    first.collect_session(
        session="2026-09-09", instrument_codes=("600519.SH",),
        checkpoint=DailyBasicCheckpoint(tmp_path, collection_key="refresh-a"),
    )
    provider = Provider([response(())])
    assert TushareDailyBasicSource(provider).collect_session(
        session="2026-09-09", instrument_codes=("600519.SH",),
        checkpoint=DailyBasicCheckpoint(tmp_path, collection_key="refresh-b"),
    ).items == ()
    assert provider.requests == [{"trade_date": "20260909"}]


def test_failed_session_remains_pending_while_previous_session_is_reusable(tmp_path) -> None:
    from thesistrace.adapters.tushare_daily_basic import DailyBasicCheckpoint

    checkpoint = DailyBasicCheckpoint(tmp_path, collection_key="bootstrap")
    first = TushareDailyBasicSource(Provider([
        response(("600519.SH",)), response(("600519.SH",), session="20260911"),
    ]))
    first.collect_session(session="2026-09-09", instrument_codes=("600519.SH",),
                          checkpoint=checkpoint)
    with pytest.raises(DataSourceError):
        first.collect_session(session="2026-09-10", instrument_codes=("600519.SH",),
                              checkpoint=checkpoint)
    assert len(checkpoint.evidence()) == 1
    provider = Provider([response(("600519.SH",), session="20260910")])
    resumed = TushareDailyBasicSource(provider)
    for session in ("2026-09-09", "2026-09-10"):
        resumed.collect_session(session=session, instrument_codes=("600519.SH",),
                                checkpoint=DailyBasicCheckpoint(
                                    tmp_path, collection_key="bootstrap",
                                ))
    assert provider.requests == [{"trade_date": "20260910"}]


def test_checkpoint_corruption_is_not_silently_refetched(tmp_path) -> None:
    from thesistrace.adapters.tushare_daily_basic import DailyBasicCheckpoint

    checkpoint = DailyBasicCheckpoint(tmp_path, collection_key="refresh-a")
    TushareDailyBasicSource(Provider([response(("600519.SH",))])).collect_session(
        session="2026-09-09", instrument_codes=("600519.SH",), checkpoint=checkpoint,
    )
    path = next(tmp_path.rglob('*.json'))
    path.write_text('{}')
    with pytest.raises(DataSourceError) as failed:
        TushareDailyBasicSource(Provider([])).collect_session(
            session="2026-09-09", instrument_codes=("600519.SH",), checkpoint=checkpoint,
        )
    assert failed.value.detail_code == "DAILY_BASIC_CHECKPOINT_INVALID"


def test_normalization_uses_decimal_units_without_filling_missing_values() -> None:
    from thesistrace.adapters.tushare_daily_basic import normalize_daily_basic

    values = dict(zip(DAILY_BASIC_SOURCE_FIELDS, response(("600519.SH",)).items[0], strict=True))
    values.update(close='12.3', total_mv='1.5', circ_mv='0', total_share='2.3',
                  float_share='1.2', free_share='0.5', turnover_rate='1.25',
                  turnover_rate_f='2.5', volume_ratio='1.7', pe='15', pe_ttm=None,
                  pb='2', ps='3', ps_ttm='3.2', dv_ratio='4.5', dv_ttm='5')
    raw = RawSourceResponse(DAILY_BASIC_SOURCE_FIELDS,
                            (tuple(values[field] for field in DAILY_BASIC_SOURCE_FIELDS),))
    assert normalize_daily_basic(raw, instrument_ids={'600519.SH': 'stock-a'}) == ({
        'instrument_id': 'stock-a', 'session': '2026-09-09', 'source_close': '12.3',
        'total_mv': '15000', 'circ_mv': '0', 'total_share': '23000',
        'float_share': '12000', 'free_share': '5000', 'turnover_rate': '0.0125',
        'turnover_rate_f': '0.025', 'volume_ratio': '1.7', 'pe': '15', 'pe_ttm': None,
        'pb': '2', 'ps': '3', 'ps_ttm': '3.2', 'dv_ratio': '0.045', 'dv_ttm': '0.05',
    },)
    assert normalize_daily_basic(response(()), instrument_ids={'600519.SH': 'stock-a'}) == ()


@pytest.mark.parametrize('invalid', ['NaN', 'Infinity', 'bad', True])
def test_normalization_rejects_invalid_numbers(invalid: object) -> None:
    from thesistrace.adapters.tushare_daily_basic import normalize_daily_basic

    values = list(response(("600519.SH",)).items[0])
    values[DAILY_BASIC_SOURCE_FIELDS.index('pe')] = invalid
    with pytest.raises(DataSourceError):
        normalize_daily_basic(RawSourceResponse(DAILY_BASIC_SOURCE_FIELDS, (tuple(values),)),
                              instrument_ids={'600519.SH': 'stock-a'})


def test_sealed_daily_evidence_requires_completed_dates_and_verifies_raw_receipts(tmp_path) -> None:
    from thesistrace.adapters.tushare_daily_basic import DailyBasicCheckpoint

    checkpoint = DailyBasicCheckpoint(tmp_path, collection_key="sealed-refresh")
    source = TushareDailyBasicSource(Provider([response(("600519.SH",))]))
    source.collect_session(
        session="2026-09-09", instrument_codes=("600519.SH",), checkpoint=checkpoint,
    )
    with pytest.raises(DataSourceError):
        checkpoint.seal(("2026-09-09", "2026-09-10"))
    sealed = checkpoint.seal(("2026-09-09",))
    reopened = DailyBasicCheckpoint(tmp_path, collection_key="sealed-refresh")
    assert reopened.verify_evidence(sealed) == ("2026-09-09",)
    assert checkpoint.seal(("2026-09-09",)) == sealed
    raw = tmp_path / checkpoint.evidence()[0]["path"]
    raw.unlink()
    with pytest.raises(DataSourceError):
        reopened.verify_evidence(sealed)


def test_capped_day_cannot_lose_an_observed_security_during_splitting(tmp_path) -> None:
    from thesistrace.data.daily_basic_evidence import DailyBasicCheckpoint

    codes = tuple(f"{number:06}.SZ" for number in range(6000))
    provider = Provider([
        response(codes), *[response((code,)) for code in codes[:-1]], response(()),
    ])
    with pytest.raises(DataSourceError) as failed:
        TushareDailyBasicSource(provider).collect_session(
            session="2026-09-09", instrument_codes=codes,
            checkpoint=DailyBasicCheckpoint(tmp_path, collection_key="split"),
        )
    assert failed.value.detail_code == "DAILY_BASIC_SPLIT_INCOMPLETE"
    retry = Provider([response((codes[-1],))])
    collected = TushareDailyBasicSource(retry).collect_session(
        session="2026-09-09", instrument_codes=codes,
        checkpoint=DailyBasicCheckpoint(tmp_path, collection_key="split"),
    )
    assert len(collected.items) == 6000
    assert retry.requests == [{"trade_date": "20260909", "ts_code": codes[-1]}]
