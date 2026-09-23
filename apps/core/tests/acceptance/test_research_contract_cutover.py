import json
import subprocess
import sys
from dataclasses import replace

import pytest
from core_runtime import create_initialized_test_app as create_app
from core_runtime import drop_product_schemas
from fastapi.testclient import TestClient
from psycopg.errors import LockNotAvailable
from psycopg.types.json import Jsonb
from test_combined_strategy_recovery import combined_command
from test_core_current_head_research_run_execution import _publish_head, _stored_tracking_activation
from test_python_framework_strategy import SESSIONS

from thesistrace.entrypoints.runtime import CoreSettings, core_environment_is_configured
from thesistrace.entrypoints.schema import initialize_core
from thesistrace.migrations.research_contract_cutover import apply_cutover, preview
from thesistrace.research_run.service import SEMANTIC_VERSIONS

pytestmark = pytest.mark.skipif(
    not core_environment_is_configured(), reason="isolated Core runtime is not configured",
)
OLD = {"factor": "factor-v1", "strategy": "strategy-v3", "kernel": "kernel-v4"}


def test_preview_binds_real_cluster_and_exact_old_research_without_mutation(tmp_path):
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    _publish_head(settings, sessions=SESSIONS[:3], price_offset=0)
    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.core_runtime
        ids = []
        for request_id in ("old", "current"):
            admitted = client.post("/api/research-runs", json=combined_command(request_id))
            assert admitted.status_code == 202, admitted.text
            assert runtime.research_runs.process_next()
            ids.append(admitted.json()["id"])
        tracked = client.post(f"/api/research-runs/{ids[0]}/daily-tracks",
                              json={"request_id": "old-track"})
        assert tracked.status_code == 201, tracked.text
        track_id = tracked.json()["id"]
        with runtime.database.transaction() as tx:
            tx.execute("UPDATE research_runs.runs SET immutable_input = "
                       "jsonb_set(immutable_input, '{semantic_versions}', %s) WHERE id = %s",
                       (Jsonb(OLD), ids[0]))
            tx.execute("UPDATE daily_tracks.tracks SET origin = "
                       "jsonb_set(origin, '{immutable_input,semantic_versions}', %s) WHERE id = %s",
                       (Jsonb(OLD), track_id))
        before = _stored_tracking_activation(settings, track_id)
        result = preview(runtime.database, runtime.publication, source=OLD)
        assert result["scope"] == {"run_ids": [ids[0]], "track_ids": [track_id], "batch_ids": []}
        assert result["counts"] == {"runs": 1, "tracks": 1, "batches": 0, "items": 0}
        assert result["inventory_counts"]["daily_tracks.session_checkpoints"] == 1
        assert result["inventory_counts"]["research_runs.attempts"] == 1
        assert len(result["manifest_references"]) >= 2
        assert result["target_contract"] == SEMANTIC_VERSIONS
        assert result["source_schema"] == result["target_schema"]
        assert result["environment"]["cluster"].isdigit()
        assert result["environment"]["database"] == "thesistrace"
        assert preview(runtime.database, runtime.publication, source=OLD) == result
        source_file, output_file = tmp_path / "source.json", tmp_path / "cutover-preview.json"
        source_file.write_text(json.dumps(OLD))
        cli = subprocess.run(
            [sys.executable, "-m", "thesistrace.migrations.research_contract_cutover", "preview",
             "--source-contract", str(source_file), "--output", str(output_file)],
            text=True, capture_output=True, timeout=30, check=True,
        )
        assert json.loads(cli.stdout)["status"] == "preview"
        assert json.loads(output_file.read_text()) == result
        assert _stored_tracking_activation(settings, track_id) == before
        assert client.get(f"/api/research-runs/{ids[1]}").json()["status"] == "succeeded"
        with runtime.database.transaction() as tx:
            tx.execute("UPDATE research_runs.runs SET name = 'changed after preview' WHERE id = %s",
                       (ids[0],))
        changed = preview(runtime.database, runtime.publication, source=OLD)
        assert changed["selected_records_sha256"] != result["selected_records_sha256"]
        with runtime.database.transaction() as tx:
            copied = tx.execute("""
                INSERT INTO publication.holding_units
                    (id, researcher_id, source_kind, source_id, first_session, last_session,
                     manifest_sha256, provenance, published_at, last_read_at,
                     expires_at, expired_at)
                SELECT 'retained-cutover-unit', researcher_id, source_kind, %s,
                    first_session, last_session, manifest_sha256, provenance,
                    published_at, last_read_at, expires_at, expired_at
                FROM publication.holding_units
                WHERE source_kind = 'research_run' AND source_id = %s
                  AND manifest_sha256 IS NOT NULL LIMIT 1
                RETURNING manifest_sha256
            """, (ids[1], ids[0])).fetchone()
            assert copied is not None
        shared = preview(runtime.database, runtime.publication, source=OLD)
        retained = next(row for row in shared["manifest_references"]
                        if row["sha256"] == copied["manifest_sha256"])
        assert retained["retained"] is True
        assert {row["owner"] for row in retained["references"]} == set(ids)
        assert any(row["retained"] for row in shared["objects"])
        assert shared["selected_records_sha256"] != result["selected_records_sha256"]
        with runtime.database.transaction() as tx:
            tx.execute("UPDATE publication.holding_units SET researcher_id = "
                       "'00000000-0000-0000-0000-000000000001'::uuid "
                       "WHERE source_kind = 'research_run' AND source_id = %s", (ids[0],))
        with pytest.raises(ValueError, match="ownership"):
            preview(runtime.database, runtime.publication, source=OLD)
        with runtime.database.transaction() as tx:
            tx.execute("UPDATE publication.holding_units h SET researcher_id = r.researcher_id "
                       "FROM research_runs.runs r WHERE h.source_kind = 'research_run' "
                       "AND h.source_id = r.id AND r.id = %s", (ids[0],))
        with runtime.database.transaction() as tx:
            tx.execute("UPDATE research_runs.attempts SET status = 'running', finished_at = NULL "
                       "WHERE run_id = %s", (ids[0],))
        with pytest.raises(ValueError, match="running execution"):
            preview(runtime.database, runtime.publication, source=OLD)
        with runtime.database.transaction() as tx:
            tx.execute("UPDATE research_runs.attempts SET status = 'succeeded', "
                       "finished_at = clock_timestamp() WHERE run_id = %s", (ids[0],))
        shared = preview(runtime.database, runtime.publication, source=OLD)
        apply_plan = tmp_path / "shared-plan.json"
        apply_plan.write_text(json.dumps(shared))
        cli = subprocess.run(
            [sys.executable, "-m", "thesistrace.migrations.research_contract_cutover", "apply",
             "--plan", str(apply_plan), "--backup", str(tmp_path / "shared-backup.json")],
            text=True, capture_output=True, timeout=30, check=True,
        )
        receipt = json.loads(cli.stdout)
        assert receipt["status"] == "committed"
        cli = subprocess.run(
            [sys.executable, "-m", "thesistrace.migrations.research_contract_cutover", "resume",
             "--id", receipt["id"]], text=True, capture_output=True, timeout=30, check=True,
        )
        assert json.loads(cli.stdout)["status"] == "complete"
        with runtime.database.transaction() as tx:
            assert tx.execute("SELECT 1 FROM publication.manifests WHERE sha256 = %s",
                              (copied["manifest_sha256"],)).fetchone() is not None
            assert tx.execute("SELECT manifest_sha256 FROM publication.holding_units "
                              "WHERE id = 'retained-cutover-unit'").fetchone() == copied
            for row in shared["objects"]:
                if row["retained"]:
                    assert tx.execute("SELECT 1 FROM publication.objects WHERE sha256 = %s",
                                      (row["sha256"],)).fetchone() is not None
        assert client.get(f"/api/research-runs/{ids[1]}").json()["status"] == "succeeded"


def test_cutover_backs_up_before_atomic_retirement_and_rejects_stale_preview(
    tmp_path, monkeypatch,
):
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    _publish_head(settings, sessions=SESSIONS[:3], price_offset=0)
    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.core_runtime
        ids = []
        for request_id in ("retire", "preserve"):
            admitted = client.post("/api/research-runs", json=combined_command(request_id))
            assert admitted.status_code == 202, admitted.text
            assert runtime.research_runs.process_next()
            ids.append(admitted.json()["id"])
        tracked = client.post(f"/api/research-runs/{ids[0]}/daily-tracks",
                              json={"request_id": "retire-track"})
        assert tracked.status_code == 201, tracked.text
        track_id = tracked.json()["id"]
        with runtime.database.transaction() as tx:
            tx.execute("UPDATE research_runs.runs SET immutable_input = "
                       "jsonb_set(immutable_input, '{semantic_versions}', %s) WHERE id = %s",
                       (Jsonb(OLD), ids[0]))
            tx.execute("UPDATE daily_tracks.tracks SET origin = "
                       "jsonb_set(origin, '{immutable_input,semantic_versions}', %s) WHERE id = %s",
                       (Jsonb(OLD), track_id))
        plan = preview(runtime.database, runtime.publication, source=OLD)
        preserved = client.get(f"/api/research-runs/{ids[1]}").json()["result"]
        with runtime.database.transaction() as tx:
            tx.execute("UPDATE research_runs.runs SET name = 'changed' WHERE id = %s", (ids[0],))
        with pytest.raises(ValueError, match="stale"):
            apply_cutover(runtime.database, runtime.publication, plan=plan,
                          backup_path=tmp_path / "stale.json")
        assert not (tmp_path / "stale.json").exists()
        plan = preview(runtime.database, runtime.publication, source=OLD)
        failed_backup = tmp_path / "failed-backup.json"
        release = runtime.publication.release_manifest_in_transaction

        def fail_after_release(*args, **kwargs):
            with pytest.raises(LockNotAvailable):
                with runtime.database.transaction() as writer:
                    writer.execute("SET LOCAL lock_timeout = '100ms'")
                    writer.execute("UPDATE research_runs.runs SET name = 'concurrent writer' "
                                   "WHERE id = %s", (ids[0],))
            release(*args, **kwargs)
            raise RuntimeError("injected authority failure")

        with monkeypatch.context() as patch:
            patch.setattr(runtime.publication, "release_manifest_in_transaction",
                          fail_after_release)
            with pytest.raises(RuntimeError, match="injected authority"):
                apply_cutover(runtime.database, runtime.publication, plan=plan,
                              backup_path=failed_backup)
        assert json.loads(failed_backup.read_text())["plan"] == plan
        assert preview(runtime.database, runtime.publication, source=OLD) == plan
        assert client.get(f"/api/research-runs/{ids[1]}").json()["result"] == preserved
        import hashlib

        from thesistrace.migrations.research_contract_cutover import cutover_status
        from thesistrace.research_kernel.serialization import canonical_json_bytes

        cutover_id = hashlib.sha256(canonical_json_bytes(plan)).hexdigest()
        status = cutover_status(runtime.database, runtime.publication, cutover_id=cutover_id)
        assert status["status"] == "not_committed"
        backup = failed_backup
        receipt = apply_cutover(runtime.database, runtime.publication,
                                plan=plan, backup_path=backup)
        assert receipt["status"] == "committed"
        _assert_other_storage_rejected(runtime, settings, plan, backup, receipt)
        assert cutover_status(runtime.database, runtime.publication,
                              cutover_id=cutover_id) == receipt
        archived = json.loads(backup.read_text())
        assert archived["plan"] == plan
        assert archived["rows"]["research_runs.runs"][0]["id"] == ids[0]
        assert archived["rows"]["daily_tracks.session_checkpoints"][0]["track_id"] == track_id
        with runtime.database.transaction() as tx:
            assert tx.execute("SELECT 1 FROM research_runs.runs WHERE id = %s",
                              (ids[0],)).fetchone() is None
            assert tx.execute("SELECT 1 FROM daily_tracks.tracks WHERE id = %s",
                              (track_id,)).fetchone() is None
            assert tx.execute(
                "SELECT count(*) AS n FROM publication.object_deletions",
            ).fetchone()["n"] > 0
        assert client.get(f"/api/research-runs/{ids[1]}").json()["result"] == preserved
        assert apply_cutover(runtime.database, runtime.publication, plan=plan,
                             backup_path=backup) == receipt
        from thesistrace.migrations.research_contract_cutover import resume_cutover
        from thesistrace.publication import JsonPayload

        unrelated = runtime.publication.prepare(
            kind="publication.probe", payloads={"canonical": JsonPayload({"unrelated": True})},
            provenance={"owner": "outside-cutover"},
        )
        with runtime.database.transaction() as tx:
            ref = runtime.publication.record(tx, unrelated)
            runtime.publication.release_manifest_in_transaction(
                tx, ref.manifest_sha256, still_referenced=False,
            )
        unrelated_sha = unrelated.payload_sha256s["canonical"]
        assert unrelated_sha not in receipt["pending_objects"]
        collect = runtime.publication.collect_pending_deletion_in_transaction
        assert len(receipt["pending_objects"]) >= 2
        interrupted_digest = receipt["pending_objects"][1]

        def fail_after_bytes(tx, **kwargs):
            result = collect(tx, **kwargs)
            if kwargs.get("object_sha256") == interrupted_digest:
                raise RuntimeError("injected collection interruption")
            return result

        with monkeypatch.context() as patch:
            patch.setattr(runtime.publication, "collect_pending_deletion_in_transaction",
                          fail_after_bytes)
            with pytest.raises(RuntimeError, match="collection interruption"):
                resume_cutover(runtime.database, runtime.publication, cutover_id=receipt["id"])
        with runtime.database.transaction() as tx:
            interrupted = tx.execute("SELECT receipt FROM thesistrace_meta.research_cutovers "
                                     "WHERE id = %s", (receipt["id"],)).fetchone()["receipt"]
        assert interrupted["status"] == "collecting"
        assert interrupted["pending_objects"] == receipt["pending_objects"][1:]
        assert interrupted["object_results"] == {receipt["pending_objects"][0]: "deleted"}
        collected = resume_cutover(runtime.database, runtime.publication, cutover_id=receipt["id"])
        assert collected["status"] == "complete"
        assert collected["pending_objects"] == []
        assert set(collected["object_results"]) == set(receipt["pending_objects"])
        with runtime.database.transaction() as tx:
            assert tx.execute("SELECT 1 FROM publication.object_deletions "
                              "WHERE object_sha256 = %s", (unrelated_sha,)).fetchone() is not None
        assert client.get(f"/api/research-runs/{ids[1]}").json()["result"] == preserved
        assert resume_cutover(runtime.database, runtime.publication,
                              cutover_id=receipt["id"]) == collected
        cli = subprocess.run(
            [sys.executable, "-m", "thesistrace.migrations.research_contract_cutover", "status",
             "--id", receipt["id"]], text=True, capture_output=True, timeout=30, check=True,
        )
        assert json.loads(cli.stdout) == collected
        with runtime.database.transaction() as tx:
            assert runtime.publication.collect_pending_deletion_in_transaction(
                tx, object_sha256=unrelated_sha,
            ) == "deleted"


@pytest.mark.parametrize("mode", ["framework", "direct"])
def test_cutover_preserves_dataset_identity_then_current_product_loop(tmp_path, mode):
    from test_python_direct_strategy import command as direct_command

    from thesistrace.migrations.research_contract_cutover import resume_cutover

    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    head = _publish_head(settings, sessions=SESSIONS[:3], price_offset=0)
    strategy = combined_command("seed") if mode == "framework" else direct_command("seed")
    excluded = {"request_id", "folder_id", "name", "research_kind", "start_date", "end_date",
                "universe", "formula", "neutralization"}
    payload = {
        "batch_kind": "strategy_sweep", "request_id": "retire-batch",
        "start_date": SESSIONS[0], "end_date": SESSIONS[2], "universe": "top300",
        "strategies": [{"item_key": "selected",
                        **{k: v for k, v in strategy.items() if k not in excluded}}],
    }
    if mode == "framework":
        payload.update(alpha={"formula": strategy["formula"]}, neutralization="none")
    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.core_runtime
        batch = client.post("/api/research-batches", json=payload)
        assert batch.status_code == 202, batch.text
        assert runtime.research_batches.process_next()
        batch_id = batch.json()["id"]
        detail = client.get(f"/api/research-batches/{batch_id}").json()
        assert detail["status"] == "succeeded", detail
        run_id = detail["items"][0]["research_run_id"]
        track = client.post(f"/api/research-runs/{run_id}/daily-tracks",
                            json={"request_id": "retire-batch-track"})
        assert track.status_code == 201, track.text
        track_id = track.json()["id"]
        from thesistrace.publication import JsonPayload

        # Explicit historical fixture: an old Batch's still-owned private artifact.
        private = runtime.publication.prepare(
            kind="publication.probe", payloads={"canonical": JsonPayload({"legacy": mode})},
            provenance={"owner": batch_id},
        )
        with runtime.database.transaction() as tx:
            private_ref = runtime.publication.record(tx, private)
            tx.execute("""
                INSERT INTO research_batches.private_alpha_factor_artifacts
                    (batch_id, manifest_sha256, binding_checksum, binding, content_sha256,
                     byte_size, created_by_attempt_id, created_by_fence)
                SELECT batch_id, %s, %s, '{}'::jsonb, %s, 1, id, fence
                FROM research_batches.attempts WHERE batch_id = %s
                ORDER BY fence DESC LIMIT 1
            """, (private_ref.manifest_sha256, "a" * 64,
                  private.payload_sha256s["canonical"], batch_id))
            identities = tx.execute("SELECT * FROM researchers.researchers ORDER BY id").fetchall()
            generations = tx.execute("SELECT to_jsonb(g) AS row FROM data.current_dataset_state g "
                                     "ORDER BY to_jsonb(g)::text").fetchall()
            tx.execute("UPDATE research_runs.runs SET immutable_input = "
                       "jsonb_set(immutable_input, '{semantic_versions}', %s) WHERE id = %s",
                       (Jsonb(OLD), run_id))
            tx.execute("UPDATE daily_tracks.tracks SET origin = "
                       "jsonb_set(origin, '{immutable_input,semantic_versions}', %s) WHERE id = %s",
                       (Jsonb(OLD), track_id))
            tx.execute("UPDATE research_batches.batches SET scope = "
                       "jsonb_set(scope, '{semantic_versions}', %s) WHERE id = %s",
                       (Jsonb(OLD), batch_id))
        import hashlib

        dataset_files = {path: hashlib.sha256(path.read_bytes()).hexdigest()
                         for path in tmp_path.rglob("*") if path.is_file()}
        assert dataset_files
        plan = preview(runtime.database, runtime.publication, source=OLD)
        assert plan["scope"] == {"run_ids": [run_id], "track_ids": [track_id],
                                 "batch_ids": [batch_id]}
        assert plan["inventory_counts"]["research_batches.items"] == 1
        assert plan["inventory_counts"]["research_batches.private_alpha_factor_artifacts"] == 1
        assert any(entry["sha256"] == private_ref.manifest_sha256 and not entry["retained"]
                   for entry in plan["manifest_references"])
        receipt = apply_cutover(runtime.database, runtime.publication, plan=plan,
                                backup_path=tmp_path / f"{mode}-backup.json")
        assert resume_cutover(runtime.database, runtime.publication,
                              cutover_id=receipt["id"])["status"] == "complete"
        with runtime.database.transaction() as tx:
            assert tx.execute("SELECT 1 FROM research_batches.batches WHERE id = %s",
                              (batch_id,)).fetchone() is None
            assert tx.execute("SELECT 1 FROM publication.manifests WHERE sha256 = %s",
                              (private_ref.manifest_sha256,)).fetchone() is None
            assert tx.execute("SELECT 1 FROM publication.objects WHERE sha256 = %s",
                              (private.payload_sha256s["canonical"],)).fetchone() is None
            assert tx.execute("SELECT * FROM researchers.researchers ORDER BY id").fetchall() == (
                identities
            )
            assert tx.execute("SELECT to_jsonb(g) AS row FROM data.current_dataset_state g "
                              "ORDER BY to_jsonb(g)::text").fetchall() == generations
        assert {path: hashlib.sha256(path.read_bytes()).hexdigest()
                for path in dataset_files} == dataset_files
        admitted = client.post("/api/research-runs", json=strategy)
        assert admitted.status_code == 202, admitted.text
        assert runtime.research_runs.process_next()
        result = client.get(f"/api/research-runs/{admitted.json()['id']}").json()
        assert result["status"] == "succeeded", result
        payload["request_id"] = "current-batch"
        current_batch = client.post("/api/research-batches", json=payload)
        assert current_batch.status_code == 202, current_batch.text
        assert runtime.research_batches.process_next()
        current = client.get(f"/api/research-batches/{current_batch.json()['id']}").json()
        assert current["status"] == "succeeded", current
        new_track = client.post(f"/api/research-runs/{admitted.json()['id']}/daily-tracks",
                                json={"request_id": "current-track"})
        assert new_track.status_code == 201, new_track.text
        _publish_head(settings, sessions=SESSIONS[:4], price_offset=0, expected_manifest=head)
        refresh = client.post(f"/api/daily-tracks/{new_track.json()['id']}/refresh",
                              json={"request_id": "current-refresh"})
        assert refresh.status_code == 202, refresh.text
        assert runtime.daily_tracks.process_next()
        state = _stored_tracking_activation(settings, new_track.json()["id"])
        assert state["current_checkpoint_session"].isoformat() == SESSIONS[3]


def _assert_other_storage_rejected(runtime, settings, plan, backup, receipt):
    from uuid import uuid4

    import boto3

    from thesistrace.migrations.research_contract_cutover import resume_cutover
    from thesistrace.publication import Publication

    s3 = boto3.client("s3", endpoint_url=settings.s3_endpoint_url,
                      aws_access_key_id=settings.s3_access_key_id,
                      aws_secret_access_key=settings.s3_secret_access_key,
                      region_name=settings.s3_region)
    bucket = "cutover-other-" + uuid4().hex
    s3.create_bucket(Bucket=bucket)
    original = s3.list_objects_v2(Bucket=settings.s3_bucket).get("Contents", [])
    digest = receipt["pending_objects"][0]
    key = next(row["Key"] for row in original if digest in row["Key"])
    s3.copy_object(Bucket=bucket, Key=key,
                   CopySource={"Bucket": settings.s3_bucket, "Key": key})
    try:
        other = s3.list_objects_v2(Bucket=bucket)["Contents"]
        publication = Publication(runtime.database, s3, bucket=bucket)
        with pytest.raises(ValueError, match="environment"):
            apply_cutover(runtime.database, publication, plan=plan, backup_path=backup)
        with pytest.raises(ValueError, match="environment"):
            resume_cutover(runtime.database, publication, cutover_id=receipt["id"])
        wrong_endpoint = boto3.client(
            "s3", endpoint_url="http://127.0.0.1:1",
            aws_access_key_id=settings.s3_access_key_id,
            aws_secret_access_key=settings.s3_secret_access_key,
            region_name=settings.s3_region,
        )
        try:
            publication = Publication(runtime.database, wrong_endpoint, bucket=settings.s3_bucket)
            with pytest.raises(ValueError, match="environment"):
                resume_cutover(runtime.database, publication, cutover_id=receipt["id"])
        finally:
            wrong_endpoint.close()
        assert s3.list_objects_v2(Bucket=settings.s3_bucket)["Contents"] == original
        assert s3.list_objects_v2(Bucket=bucket)["Contents"] == other
    finally:
        s3.delete_object(Bucket=bucket, Key=key)
        s3.delete_bucket(Bucket=bucket)
        s3.close()
