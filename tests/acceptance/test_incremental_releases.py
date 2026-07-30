from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from thesistrace.api import create_app
from thesistrace.config import Settings
from thesistrace.datasets import DatasetPublisher
from thesistrace.objects import ImmutableObjectStore
from thesistrace.storage import DatasetPublicationConflict, MetadataStore


def test_incremental_catchup_and_correction_releases_form_one_immutable_chain(
    tmp_path: Path,
) -> None:
    settings = Settings(
        metadata_path=tmp_path / "metadata.sqlite3",
        object_root=tmp_path / "objects",
    )
    with TestClient(create_app(settings)) as client:
        root = client.post(
            "/api/v1/dataset-releases/bootstrap",
            headers={"Idempotency-Key": "root"},
            json={"fixture": "v1"},
        ).json()["release"]

        daily_response = client.post(
            "/api/v1/dataset-releases/publish-fixture",
            headers={"Idempotency-Key": "daily-1"},
            json={"new_sessions": 1, "corrections": []},
        )
        assert daily_response.status_code == 201
        daily = daily_response.json()["release"]
        assert daily["predecessor_id"] == root["id"]
        assert daily["session_count"] == 757
        assert daily["appended_session_range"]["start"] == daily["appended_session_range"]["end"]
        assert daily["correction_change_set"] == []
        root_hashes = {item["sha256"] for item in root["objects"]}
        daily_hashes = {item["sha256"] for item in daily["objects"]}
        assert root_hashes < daily_hashes
        assert {item["kind"] for item in daily["objects"]} >= {
            "source_delta",
            "canonical_partition",
        }

        invalid = client.post(
            "/api/v1/dataset-releases/publish-fixture",
            headers={"Idempotency-Key": "correction-only"},
            json={
                "new_sessions": 0,
                "corrections": [
                    {
                        "session": root["appended_session_range"]["start"],
                        "instrument_id": "equity:600000.SH",
                        "field": "close_raw",
                        "value": "9.9900",
                    }
                ],
            },
        )
        assert invalid.status_code == 422
        assert client.get("/api/v1/workspace").json()["latest_dataset_release"]["id"] == daily["id"]

        catchup = client.post(
            "/api/v1/dataset-releases/publish-fixture",
            headers={"Idempotency-Key": "catchup-3"},
            json={"new_sessions": 3, "corrections": []},
        ).json()["release"]
        assert catchup["predecessor_id"] == daily["id"]
        assert catchup["session_count"] == 760
        assert catchup["appended_session_range"]["start"] < catchup["appended_session_range"]["end"]
        assert client.get("/api/v1/workspace").json()["resource_counts"]["dataset_releases"] == 3

        correction = {
            "session": root["appended_session_range"]["start"],
            "instrument_id": "equity:600000.SH",
            "field": "close_raw",
            "value": "8.0500",
        }
        turnover_correction = {
            "session": root["appended_session_range"]["start"],
            "instrument_id": "equity:600000.SH",
            "field": "turnover_cny",
            "value": "123456.78",
        }
        derived_field_response = client.post(
            "/api/v1/dataset-releases/publish-fixture",
            headers={"Idempotency-Key": "derived-field-correction"},
            json={
                "new_sessions": 1,
                "corrections": [{**correction, "field": "close_adj"}],
            },
        )
        assert derived_field_response.status_code == 422
        invalid_row_response = client.post(
            "/api/v1/dataset-releases/publish-fixture",
            headers={"Idempotency-Key": "invalid-price-row-correction"},
            json={
                "new_sessions": 1,
                "corrections": [{**correction, "value": "99.0000"}],
            },
        )
        assert invalid_row_response.status_code == 422
        corrected_response = client.post(
            "/api/v1/dataset-releases/publish-fixture",
            headers={"Idempotency-Key": "daily-with-correction"},
            json={"new_sessions": 1, "corrections": [correction, turnover_correction]},
        )
        assert corrected_response.status_code == 201
        corrected = corrected_response.json()["release"]
        assert corrected["predecessor_id"] == catchup["id"]
        assert corrected["session_count"] == 761
        assert corrected["correction_change_set"] == [correction, turnover_correction]

        repeated = client.post(
            "/api/v1/dataset-releases/publish-fixture",
            headers={"Idempotency-Key": "daily-with-correction"},
            json={"new_sessions": 1, "corrections": [correction, turnover_correction]},
        )
        assert repeated.status_code == 200
        assert repeated.json()["release"]["id"] == corrected["id"]

        latest_contract = client.get(
            f"/api/v1/dataset-releases/{corrected['id']}/data-contract"
        ).json()
        assert latest_contract["calendar"]["session_count"] == 761
        assert [
            release["id"] for release in client.get("/api/v1/dataset-releases").json()["items"]
        ] == [root["id"], daily["id"], catchup["id"], corrected["id"]]
        assert client.get("/api/v1/dataset-releases/root-does-not-exist").status_code == 404
        assert client.get(f"/api/v1/dataset-releases/{root['id']}").json() == root

        publisher = DatasetPublisher(
            MetadataStore(settings.metadata_path),
            ImmutableObjectStore(settings.object_root),
        )
        materialized = publisher.materialize_canonical(corrected)
        price = next(
            row
            for row in materialized["prices"]
            if row["session"] == correction["session"]
            and row["instrument_id"] == correction["instrument_id"]
        )
        expected_close_adj = (
            Decimal(price["close_raw"])
            * Decimal(price["adjustment_factor"])
            / Decimal(price["adjustment_anchor_factor"])
        ).quantize(Decimal("0.00000001"))
        assert Decimal(price["close_adj"]) == expected_close_adj
        assert Decimal(price["change_raw"]) == (
            Decimal(price["close_raw"]) - Decimal(price["pre_close_raw"])
        )
        for snapshots in materialized["liquidity_universes"].values():
            assert len(snapshots) == corrected["session_count"]
            assert len({snapshot["session"] for snapshot in snapshots}) == len(snapshots)


def test_release_commit_rejects_a_stale_predecessor_and_replays_idempotently(
    tmp_path: Path,
) -> None:
    settings = Settings(
        metadata_path=tmp_path / "metadata.sqlite3",
        object_root=tmp_path / "objects",
    )
    with TestClient(create_app(settings)) as client:
        root = client.post(
            "/api/v1/dataset-releases/bootstrap",
            headers={"Idempotency-Key": "root"},
            json={"fixture": "v1"},
        ).json()["release"]

    store = MetadataStore(settings.metadata_path)
    first = {
        **root,
        "id": "dsr_first",
        "predecessor_id": root["id"],
        "created_at": "2026-07-30T00:00:00+00:00",
    }
    second = {
        **root,
        "id": "dsr_second",
        "predecessor_id": root["id"],
        "created_at": "2026-07-30T00:00:01+00:00",
    }
    assert store.publish_dataset_release(first, "first") == (first, True)
    assert store.publish_dataset_release(second, "first") == (first, False)
    with pytest.raises(DatasetPublicationConflict, match="latest Dataset Release changed"):
        store.publish_dataset_release(second, "second")
