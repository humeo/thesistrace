from __future__ import annotations

from pathlib import Path

import pytest

from thesistrace.adapters.tushare_industry import (
    IndustrySourceError,
    TushareIndustrySource,
)
from thesistrace.adapters.tushare_provider import TushareSourceError
from thesistrace.adapters.tushare_replay import ReplayTushareProvider


class RecordingProvider:
    def __init__(self, memberships: list[dict[str, object]]) -> None:
        self.memberships = memberships
        self.requests: list[tuple[str, dict[str, object], tuple[str, ...]]] = []

    def query_paginated(
        self,
        api_name: str,
        *,
        params: dict[str, object],
        fields: tuple[str, ...],
        primary_key: tuple[str, ...],
    ) -> list[dict[str, object]]:
        del primary_key
        self.requests.append((api_name, params, fields))
        if api_name == "index_classify":
            return [
                {
                    "index_code": "801780",
                    "industry_name": "银行",
                    "level": "L1",
                    "src": "SW2021",
                }
            ]
        assert api_name == "index_member_all"
        return self.memberships


def test_industry_source_requests_and_retains_complete_primary_classification() -> None:
    raw = {
        "l1_code": "801780",
        "l2_code": "801783",
        "l3_code": "851911",
        "ts_code": "000001.SZ",
        "in_date": "20210101",
        "out_date": "",
        "is_new": "Y",
    }
    provider = RecordingProvider([raw])

    snapshot = TushareIndustrySource(provider).collect(
        allowed_codes={"000001.SZ"},
    )

    assert [request[0] for request in provider.requests] == [
        "index_classify",
        "index_member_all",
    ]
    assert provider.requests[1][1] == {}
    assert provider.requests[1][2] == (
        "l1_code",
        "l2_code",
        "l3_code",
        "ts_code",
        "in_date",
        "out_date",
        "is_new",
    )
    assert snapshot.raw_memberships == (raw,)
    assert snapshot.memberships[0]["active_to"] == ""


def test_industry_source_fails_closed_on_overlapping_primary_classification() -> None:
    provider = RecordingProvider(
        [
            {
                "l1_code": "801010",
                "l2_code": "801011",
                "l3_code": "850111",
                "ts_code": "000001.SZ",
                "in_date": "20210101",
                "out_date": "",
                "is_new": "Y",
            },
            {
                "l1_code": "801780",
                "l2_code": "801783",
                "l3_code": "851911",
                "ts_code": "000001.SZ",
                "in_date": "20220101",
                "out_date": "",
                "is_new": "Y",
            },
        ]
    )

    with pytest.raises(
        IndustrySourceError,
        match="OVERLAPPING_PRIMARY_INDUSTRY_CLASSIFICATION",
    ) as captured:
        TushareIndustrySource(provider).collect(allowed_codes={"000001.SZ"})

    assert captured.value.diagnostic["instrument_id"] == "equity:000001.SZ"
    assert captured.value.diagnostic["overlap_count"] == 1


def test_industry_source_supports_explicit_replay_contract() -> None:
    replay = Path(__file__).parents[1] / "fixtures" / "tushare-bootstrap-replay-v2.json"

    snapshot = TushareIndustrySource(ReplayTushareProvider(replay)).collect(
        allowed_codes={"600000.SH"}
    )

    assert snapshot.raw_memberships[0]["is_new"] == "Y"
    assert snapshot.memberships[0]["instrument_id"] == "equity:600000.SH"


def test_industry_capability_failure_is_independent_from_market_gate() -> None:
    class DeniedProvider(RecordingProvider):
        def query_paginated(
            self,
            api_name: str,
            *,
            params: dict[str, object],
            fields: tuple[str, ...],
            primary_key: tuple[str, ...],
        ) -> list[dict[str, object]]:
            if api_name == "index_member_all":
                raise TushareSourceError("PERMISSION_DENIED", source_code=40203)
            return super().query_paginated(
                api_name,
                params=params,
                fields=fields,
                primary_key=primary_key,
            )

    with pytest.raises(IndustrySourceError, match="PERMISSION_DENIED"):
        TushareIndustrySource(DeniedProvider([])).collect(
            allowed_codes={"600000.SH"}
        )


def test_empty_industry_membership_fails_the_independent_capability_gate() -> None:
    with pytest.raises(IndustrySourceError, match="INDUSTRY_CAPABILITY_UNAVAILABLE"):
        TushareIndustrySource(RecordingProvider([])).collect(
            allowed_codes={"600000.SH"}
        )
