from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient

from thesistrace.api import create_app
from thesistrace.config import Settings


def test_release_exposes_complete_canonical_market_and_research_contract(tmp_path: Path) -> None:
    settings = Settings(
        metadata_path=tmp_path / "metadata.sqlite3",
        object_root=tmp_path / "objects",
    )
    with TestClient(create_app(settings)) as client:
        release = client.post(
            "/api/v1/dataset-releases/bootstrap",
            headers={"Idempotency-Key": "contract-fixture"},
            json={"fixture": "v1"},
        ).json()["release"]

        contract_response = client.get(f"/api/v1/dataset-releases/{release['id']}/data-contract")
        assert contract_response.status_code == 200
        contract = contract_response.json()
        assert contract["calendar"] == {
            "session_count": 756,
            "start": release["appended_session_range"]["start"],
            "end": release["appended_session_range"]["end"],
            "rule": "SSE_SZSE_OPEN_DAY_INTERSECTION",
        }
        assert contract["alpha_authorable_fields"] == [
            "open_adj",
            "high_adj",
            "low_adj",
            "close_adj",
            "volume",
            "amount",
        ]
        assert set(contract["universes"]) == {"top300", "top1000", "top2000", "top3000"}
        assert contract["industry_levels"] == ["SW2021_L1", "SW2021_L2", "SW2021_L3"]
        assert contract["trading_state_counts"]["full_session_suspension"] == 1
        assert contract["trading_state_counts"]["partial_opening_suspension"] == 1
        assert contract["trading_state_counts"]["after_open_suspension"] == 1
        assert all("tushare" not in field["name"].lower() for field in contract["fields"])

        objects = {item["kind"]: item for item in release["objects"]}
        source = client.get(f"/api/v1/objects/{objects['source_fixture']['sha256']}").json()
        canonical = client.get(f"/api/v1/objects/{objects['canonical_fixture']['sha256']}").json()

    assert canonical["research_calendar"] == sorted(
        set(source["sse_open_days"]) & set(source["szse_open_days"])
    )
    assert set(source["daily"][0]) == {
        "ts_code",
        "trade_date",
        "open",
        "high",
        "low",
        "close",
        "pre_close",
        "change",
        "pct_chg",
        "vol",
        "amount",
    }
    assert all(
        isinstance(value, str)
        for row in source["daily"][:100]
        for key, value in row.items()
        if key not in {"ts_code", "trade_date"}
    )

    states = {item["state"] for item in canonical["trading_states"]}
    assert states == {
        "normal",
        "partial_opening_suspension",
        "after_open_suspension",
        "full_session_suspension",
    }
    full_suspension = next(
        item for item in canonical["trading_states"] if item["state"] == "full_session_suspension"
    )
    assert not any(
        row["session"] == full_suspension["session"]
        and row["instrument_id"] == full_suspension["instrument_id"]
        for row in canonical["prices"]
    )

    sample = canonical["prices"][0]
    expected_adjusted_open = (
        Decimal(sample["open_raw"])
        * Decimal(sample["adjustment_factor"])
        / Decimal(sample["adjustment_anchor_factor"])
    )
    assert Decimal(sample["open_adj"]) == expected_adjusted_open.quantize(Decimal("0.00000001"))
    assert all(isinstance(sample[field], str) for field in sample if field != "trading_state")

    assert canonical["price_limits"]
    assert all({"upper", "lower"} <= set(item) for item in canonical["price_limits"][:100])
    assert all(item["asset_type"] == "ordinary_a_share" for item in canonical["instruments"])
    assert all(
        snapshot["instrument_ids"] == []
        for snapshot in canonical["liquidity_universes"]["top300"][:19]
    )
    assert len(canonical["liquidity_universes"]["top300"][19]["instrument_ids"]) == 35
    assert set(canonical["liquidity_universes"]["top300"][19]["instrument_ids"]) <= set(
        canonical["liquidity_universes"]["top1000"][19]["instrument_ids"]
    )
    assert all(
        membership["active_from"] < release["appended_session_range"]["end"]
        and membership["active_to"] == ""
        for membership in canonical["industry_membership"]
    )
