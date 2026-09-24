from copy import deepcopy

import pytest

from thesistrace.migrations.research_contract_cutover import select_scope, write_record

OLD = {"factor": "factor-v1", "strategy": "strategy-v3", "kernel": "kernel-v4"}
CURRENT = {"factor": "factor-v1", "strategy": "strategy-v10", "kernel": "kernel-v14"}


def records():
    return {
        "runs": [{"id": "old", "researcher_id": "owner", "immutable_input": {
            "semantic_versions": OLD,
        }}, {"id": "new", "researcher_id": "owner", "immutable_input": {
            "semantic_versions": CURRENT,
        }}],
        "tracks": [{"id": "track-old", "seed_run_id": "old", "researcher_id": "owner",
                    "origin": {"immutable_input": {"semantic_versions": OLD}}},
                   {"id": "track-new", "seed_run_id": "new", "researcher_id": "owner",
                    "origin": {"immutable_input": {"semantic_versions": CURRENT}}}],
        "batches": [{"id": "batch-old", "researcher_id": "owner"}],
        "items": [{"batch_id": "batch-old", "research_run_id": "old", "researcher_id": "owner"}],
    }


def test_scope_selects_exact_source_contract_and_preserves_input():
    value = records()
    before = deepcopy(value)
    selected = select_scope(**value, source=OLD, target=CURRENT)
    assert selected == {"run_ids": ["old"], "track_ids": ["track-old"], "batch_ids": ["batch-old"]}
    assert value == before


def test_track_with_deleted_seed_is_selected_from_its_own_frozen_contract():
    value = records()
    value["tracks"].append({"id": "orphan-origin", "seed_run_id": "deleted",
                            "researcher_id": "owner",
                            "origin": {"immutable_input": {"semantic_versions": OLD}}})
    assert select_scope(**value, source=OLD, target=CURRENT)["track_ids"] == [
        "orphan-origin", "track-old",
    ]


def test_mixed_batch_cannot_expand_cutover_to_current_research():
    value = records()
    value["items"].append({"batch_id": "batch-old", "research_run_id": "new",
                           "researcher_id": "owner"})
    with pytest.raises(ValueError, match="retained research"):
        select_scope(**value, source=OLD, target=CURRENT)


@pytest.mark.parametrize("contract", [CURRENT, {}, {"kernel": "kernel-v4"}])
def test_current_or_incomplete_source_contract_is_rejected(contract):
    with pytest.raises(ValueError, match="source contract"):
        select_scope(**records(), source=contract, target=CURRENT)


def test_other_legacy_versions_are_not_implicitly_authorized():
    value = records()
    value["runs"].append({"id": "unrelated", "researcher_id": "owner", "immutable_input": {
        "semantic_versions": {**OLD, "kernel": "kernel-v2"},
    }})
    assert select_scope(**value, source=OLD, target=CURRENT)["run_ids"] == ["old"]


@pytest.mark.parametrize("relation", ["tracks", "items", "batches"])
def test_cross_owner_associations_fail_closed(relation):
    value = records()
    value[relation][0]["researcher_id"] = "another-owner"
    with pytest.raises(ValueError, match="ownership"):
        select_scope(**value, source=OLD, target=CURRENT)


def test_retained_track_prevents_removal_of_its_selected_seed():
    value = records()
    value["tracks"][0]["origin"]["immutable_input"]["semantic_versions"] = CURRENT
    with pytest.raises(ValueError, match="retained Track"):
        select_scope(**value, source=OLD, target=CURRENT)


def test_deleted_batch_item_requires_frozen_source_contract_and_deletion_receipt():
    value = records()
    value["items"].append({"batch_id": "batch-old", "research_run_id": "deleted",
                           "researcher_id": "owner", "run_deleted_at": "2026-09-24T00:00:00Z"})
    with pytest.raises(ValueError, match="unverified deleted Run"):
        select_scope(**value, source=OLD, target=CURRENT)
    value["batches"][0]["scope"] = {"semantic_versions": OLD}
    assert select_scope(**value, source=OLD, target=CURRENT)["batch_ids"] == ["batch-old"]
    value["items"][-1]["run_deleted_at"] = None
    with pytest.raises(ValueError, match="unverified deleted Run"):
        select_scope(**value, source=OLD, target=CURRENT)


def test_all_deleted_batch_can_be_selected_without_guessing_contract_from_absent_runs():
    value = records()
    value["runs"] = [value["runs"][1]]
    value["tracks"] = []
    value["items"][0]["run_deleted_at"] = "2026-09-24T00:00:00Z"
    value["batches"][0]["scope"] = {"semantic_versions": OLD}
    assert select_scope(**value, source=OLD, target=CURRENT) == {
        "run_ids": [], "track_ids": [], "batch_ids": ["batch-old"],
    }


def test_operator_record_is_private_durable_and_never_overwrites_existing_evidence(tmp_path):
    import hashlib
    import json
    import stat

    path = tmp_path / "preview.json"
    digest = write_record(path, {"status": "preview", "source_contract": OLD})
    assert json.loads(path.read_bytes())["source_contract"] == OLD
    assert hashlib.sha256(path.read_bytes()).hexdigest() == digest
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    with pytest.raises(FileExistsError):
        write_record(path, {"status": "changed"})
    assert hashlib.sha256(path.read_bytes()).hexdigest() == digest


def test_backup_retry_requires_identical_bytes(tmp_path):
    path = tmp_path / "backup.json"
    original = {"records": ["only-authorized"]}
    digest = write_record(path, original)
    assert write_record(path, original, reuse_identical=True) == digest
    with pytest.raises(ValueError, match="differs"):
        write_record(path, {"records": ["expanded"]}, reuse_identical=True)
    assert write_record(path, original, reuse_identical=True) == digest
