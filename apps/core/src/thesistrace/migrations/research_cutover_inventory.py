"""Current-schema metadata and Publication references for an explicit cutover."""

from psycopg import sql

DEPENDENTS = (
    ("research_runs.attempts", "run_id", "run_ids"),
    ("research_runs.progress", "run_id", "run_ids"),
    ("research_runs.execution_checkpoints", "run_id", "run_ids"),
    ("research_runs.admission_requests", "run_id", "run_ids"),
    ("research_runs.cancel_receipts", "run_id", "run_ids"),
    ("daily_tracks.session_checkpoints", "track_id", "track_ids"),
    ("daily_tracks.session_tracking_states", "track_id", "track_ids"),
    ("daily_tracks.session_progressions", "track_id", "track_ids"),
    ("daily_tracks.session_progression_attempts", "track_id", "track_ids"),
    ("daily_tracks.refresh_receipts", "track_id", "track_ids"),
    ("daily_tracks.retry_receipts", "track_id", "track_ids"),
    ("daily_tracks.stop_receipts", "track_id", "track_ids"),
    ("research_batches.items", "batch_id", "batch_ids"),
    ("research_batches.attempts", "batch_id", "batch_ids"),
    ("research_batches.starting_claims", "batch_id", "batch_ids"),
    ("research_batches.task_attempts", "batch_id", "batch_ids"),
    ("research_batches.private_alpha_factor_artifacts", "batch_id", "batch_ids"),
    ("research_batches.progress", "batch_id", "batch_ids"),
    ("research_batches.admission_receipts", "batch_id", "batch_ids"),
    ("research_batches.cancel_receipts", "batch_id", "batch_ids"),
)


def read_rows(tx, table, predicate, parameters):
    query = sql.SQL("SELECT to_jsonb(r) AS record FROM {} r WHERE {} ORDER BY to_jsonb(r)::text")
    return [row["record"] for row in tx.execute(
        query.format(sql.Identifier(*table.split(".")), sql.SQL(predicate)), parameters,
    )]


def read_inventory(tx, scope, roots):
    rows = {"research_runs.runs": roots["runs"], "daily_tracks.tracks": roots["tracks"],
            "research_batches.batches": roots["batches"]}
    for table, column, key in DEPENDENTS:
        rows[table] = read_rows(tx, table, f"{column} = ANY(%s)", (scope[key],))
    rows["research_runs.start_tracking_receipts"] = read_rows(
        tx, "research_runs.start_tracking_receipts", "seed_run_id = ANY(%s) OR track_id = ANY(%s)",
        (scope["run_ids"], scope["track_ids"]),
    )
    rows["publication.holding_units"] = read_rows(
        tx, "publication.holding_units",
        "(source_kind = 'research_run' AND source_id = ANY(%s)) OR "
        "(source_kind = 'daily_track' AND source_id = ANY(%s))",
        (scope["run_ids"], scope["track_ids"]),
    )
    owners = {(kind, row["id"]): row["researcher_id"]
              for kind, key in (("research_run", "runs"), ("daily_track", "tracks"))
              for row in roots[key]}
    if any(row["researcher_id"] != owners[(row["source_kind"], row["source_id"])]
           for row in rows["publication.holding_units"]):
        raise ValueError("Holding evidence ownership does not match selected research")
    pins = sorted({row["generation_pin_id"] for table_rows in rows.values() for row in table_rows
                   if row.get("generation_pin_id")})
    rows["data.generation_pins"] = read_rows(tx, "data.generation_pins", "id = ANY(%s)", (pins,))
    if rows["research_batches.starting_claims"] or any(
        row.get("status") in {"running", "stopping", "cancelling"}
        for table_rows in rows.values() for row in table_rows
    ) or any(row["status"] == "active" for row in rows["data.generation_pins"]):
        raise ValueError("Stop running execution and release its pins before cutover")

    # All current product roots that can own a Publication manifest. Dataset generations
    # use their separate mounted store and are never part of Publication retirement.
    references = [dict(row) for row in tx.execute("""
        SELECT result_manifest_sha256 AS manifest, 'research_run' AS kind, id AS owner
        FROM research_runs.runs WHERE result_manifest_sha256 IS NOT NULL
        UNION ALL SELECT checkpoint_manifest_sha256, 'research_run', run_id
        FROM research_runs.execution_checkpoints
        UNION ALL SELECT origin->'verified_result'->>'result_manifest_sha256', 'daily_track', id
        FROM daily_tracks.tracks
        UNION ALL SELECT manifest_sha256, 'daily_track', track_id
        FROM daily_tracks.session_checkpoints
        UNION ALL SELECT manifest_sha256, 'research_batch', batch_id
        FROM research_batches.private_alpha_factor_artifacts
        UNION ALL SELECT manifest_sha256, source_kind, source_id
        FROM publication.holding_units WHERE manifest_sha256 IS NOT NULL
        ORDER BY manifest, kind, owner
    """)]
    selected = {"research_run": set(scope["run_ids"]), "daily_track": set(scope["track_ids"]),
                "research_batch": set(scope["batch_ids"])}
    candidates = sorted({r["manifest"] for r in references
                         if r["manifest"] and r["owner"] in selected[r["kind"]]})
    manifest_plan = []
    for digest in candidates:
        uses = [r for r in references if r["manifest"] == digest]
        retained = [r for r in uses if r["owner"] not in selected[r["kind"]]]
        manifest_plan.append({"sha256": digest, "retained": bool(retained), "references": uses})
    for table, column in (("publication.manifests", "sha256"),
                          ("publication.manifest_objects", "manifest_sha256"),
                          ("publication.payload_retention", "manifest_sha256"),
                          ("publication.expired_payloads", "manifest_sha256")):
        rows[table] = read_rows(tx, table, f"{column} = ANY(%s)", (candidates,))
    present = {row["sha256"] for row in rows["publication.manifests"]}
    if present != set(candidates):
        raise ValueError("Research references a missing Publication manifest")
    objects = sorted({row["object_sha256"] for row in rows["publication.manifest_objects"]})
    rows["publication.objects"] = read_rows(tx, "publication.objects", "sha256 = ANY(%s)",
                                            (objects,))
    if {row["sha256"] for row in rows["publication.objects"]} != set(objects):
        raise ValueError("Publication manifest references a missing object")
    links = read_rows(tx, "publication.manifest_objects", "object_sha256 = ANY(%s)", (objects,))
    retiring = {entry["sha256"] for entry in manifest_plan if not entry["retained"]}
    object_plan = [{"sha256": digest, "retained": any(
        link["manifest_sha256"] not in retiring for link in links if link["object_sha256"] == digest
    )} for digest in objects]
    return rows, manifest_plan, object_plan
