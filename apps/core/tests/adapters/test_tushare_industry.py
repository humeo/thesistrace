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
        return [row for row in self.memberships if row["is_new"] == params.get("is_new", "Y")]


def test_industry_source_preserves_history_changes_and_delisted_members() -> None:
    old = {
        "l1_code": "801010", "l2_code": "801011", "l3_code": "850111",
        "ts_code": "000001.SZ", "in_date": "20000101", "out_date": "20201231",
        "is_new": "N",
    }
    current = {**old, "l1_code": "801780", "l2_code": "801783", "l3_code": "851911",
               "in_date": "20210101", "out_date": "", "is_new": "Y"}
    delisted = {**old, "ts_code": "000005.SZ", "out_date": "20200101"}
    snapshot = TushareIndustrySource(RecordingProvider([current, old, delisted])).collect(
        allowed_codes={"000001.SZ", "000005.SZ"},
    )

    assert [(row["instrument_id"], row["active_from"], row["active_to"], row["sw2021_l1"])
            for row in snapshot.memberships] == [
        ("equity:000001.SZ", "2000-01-01", "2021-01-01", "801010"),
        ("equity:000001.SZ", "2021-01-01", "", "801780"),
        ("equity:000005.SZ", "2000-01-01", "2020-01-02", "801010"),
    ]
    assert {row["is_new"] for row in snapshot.raw_memberships} == {"Y", "N"}


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
        "index_member_all",
    ]
    assert [request[1] for request in provider.requests[1:]] == [
        {"is_new": "Y"}, {"is_new": "N"},
    ]
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


@pytest.mark.parametrize("historical", [False, True])
def test_industry_source_fails_closed_on_overlapping_primary_classification(historical) -> None:
    provider = RecordingProvider(
        [
            {
                "l1_code": "801010",
                "l2_code": "801011",
                "l3_code": "850111",
                "ts_code": "000001.SZ",
                "in_date": "20210101",
                "out_date": "20230101" if historical else "",
                "is_new": "N" if historical else "Y",
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
    replay = (
        Path(__file__).resolve().parents[4] / "tests/fixtures" / "tushare-bootstrap-replay-v2.json"
    )

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
        TushareIndustrySource(DeniedProvider([])).collect(allowed_codes={"600000.SH"})


def test_empty_industry_membership_fails_the_independent_capability_gate() -> None:
    with pytest.raises(IndustrySourceError, match="INDUSTRY_CAPABILITY_UNAVAILABLE"):
        TushareIndustrySource(RecordingProvider([])).collect(allowed_codes={"600000.SH"})
