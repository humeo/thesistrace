"""Offline comparison of saved Financial Refresh inputs in an owned scratch directory.

Run with the baseline or proposed source tree on PYTHONPATH. No database, Head,
supplier or network entry point is used. Existing addressed inputs are hard-linked;
the store only creates new addressed files beneath the fresh scratch root.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import resource
import shutil
import sys
from collections import defaultdict
from contextlib import nullcontext
from dataclasses import replace
from pathlib import Path
from time import perf_counter

import pyarrow as pa
import pyarrow.parquet as pq

from thesistrace.data.financial_candidate import (
    FinancialCandidateStore,
    FinancialDiscoveryPublication,
)
from thesistrace.data.financial_collection import (
    CompletedFinancialCollection,
    FinancialCollectionContract,
    FinancialShardCheckpoint,
)
from thesistrace.data.io_metrics import cold_file_reads, measure_data_io
from thesistrace.publication.serialization import canonical_json_bytes


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--requirements", type=Path, required=True)
    parser.add_argument("--scratch-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--implementation", choices=("baseline", "prepared"), required=True)
    parser.add_argument("--cold", action="store_true")
    args = parser.parse_args()
    evidence = json.loads(args.evidence.read_bytes())
    args.scratch_root.mkdir(parents=True, exist_ok=False)
    try:
        for name in ("manifests", "objects", "financial"):
            shutil.copytree(args.input_root / name, args.scratch_root / name, copy_function=os.link)
        result = replay(args, evidence)
        args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    finally:
        shutil.rmtree(args.scratch_root)


def replay(args, evidence):
    operation = evidence["financial"]
    family = evidence["manifests"]["financial_candidate"]["content"]
    checkpoints = tuple(
        replace(FinancialShardCheckpoint(**item), ordinal=ordinal)
        for ordinal, item in enumerate(
            item for attempt in sorted(evidence["attempts"], key=lambda row: row["instrument_id"])
            if attempt["status"] == "accepted" for item in attempt["checkpoints"]
        )
    )
    collection = CompletedFinancialCollection(
        idempotency_key=operation["idempotency_key"],
        generation_manifest_sha256=operation["source_generation_manifest_sha256"],
        contract=FinancialCollectionContract.from_descriptor(family["source_collection"]["contract"]),
        finished_at=family["source_collection"]["finished_at"],
        target_count=len(checkpoints), shards=checkpoints,
    )
    coverage = family["dataset_coverage"]
    discovery = FinancialDiscoveryPublication(
        baseline_session=coverage["discovery_baseline_session"],
        attempted_through_session=coverage["discovery_attempted_through_session"],
        complete_through_session=coverage["discovery_complete_through_session"],
        source_lineage_sha256=coverage["source_lineage_sha256"],
        readiness_status=coverage["readiness_status"],
        pending_instrument_count=coverage["pending_instrument_count"],
        discovery_gap_count=coverage["discovery_gap_count"],
        earliest_unresolved_date=coverage["earliest_unresolved_date"],
    )
    requirements = json.loads(args.requirements.read_bytes())["reports"]

    def reconcile(reports):
        pending = sorted({
            "equity:" + item["ts_code"] for item in requirements
            if any(("equity:" + item["ts_code"], item["report_period"]) not in reports[endpoint]
                   for endpoint in ("income", "balancesheet", "cashflow"))
        })
        assert len(pending) == discovery.pending_instrument_count, pending
        return pending
    store = FinancialCandidateStore(args.scratch_root)
    prior = operation["prior_financial_manifest_sha256"]
    target = operation["target_session"]
    phases = []
    worksets = []
    validation_seconds = 0.0
    sqlite_peak_bytes = 0
    decoded = {"tables": 0, "rows": 0, "cells": 0}
    original_read_table = pq.read_table
    original_index = store._published_rows
    original_validate = store.validate

    def index(*values, **kwargs):
        nonlocal sqlite_peak_bytes
        previous = store._published_index
        result = original_index(*values, **kwargs)
        if result is not previous:
            worksets.append(values[0])
        sqlite_peak_bytes = max(sqlite_peak_bytes, sum(
            p.stat().st_size for p in Path(result._temporary.name).iterdir() if p.is_file()
        ))
        return result

    def validate(*values, **kwargs):
        nonlocal validation_seconds
        start = perf_counter()
        try:
            return original_validate(*values, **kwargs)
        finally:
            validation_seconds += perf_counter() - start

    def read_table(*values, **kwargs):
        table = original_read_table(*values, **kwargs)
        decoded["tables"] += 1
        decoded["rows"] += table.num_rows
        decoded["cells"] += table.num_rows * table.num_columns
        return table

    # Diagnostics surround existing implementations equally in both source trees.
    store._published_rows = index
    store.validate = validate
    pq.read_table = read_table
    with cold_file_reads() if args.cold else nullcontext(), measure_data_io() as io:
        start = perf_counter()

        def stage(name, action):
            started = perf_counter()
            before = io.snapshot()
            result = action()
            phases.append({"name": name, "seconds": perf_counter() - started,
                           "io": {key: value - before[key]
                                  for key, value in io.snapshot().items()}})
            print(json.dumps(phases[-1]), flush=True)
            return result

        stage("published_inventory", lambda: store.report_inventory(prior, through=target))
        grouped = defaultdict(list)
        for checkpoint in checkpoints:
            grouped[checkpoint.instrument_id].append(checkpoint)
        if args.implementation == "prepared":
            stage("selected_values", lambda: store.prepare_instruments(
                prior_candidate_manifest_sha256=prior,
                generation_manifest_sha256=collection.generation_manifest_sha256,
                observation_through_session=target, instrument_ids=frozenset(grouped),
            ))

        def project_companies():
            for items in grouped.values():
                subset = tuple(replace(item, ordinal=i) for i, item in enumerate(items))
                store.validate_daily_instrument(
                    replace(collection, target_count=len(subset), shards=subset),
                    prior_candidate_manifest_sha256=prior, observation_through_session=target,
                )

        stage("company_projection", project_companies)
        if args.implementation == "prepared":
            prepared = stage("candidate_prepare", lambda: store.prepare_daily(
                collection, prior_candidate_manifest_sha256=prior, discovery=discovery,
            ))
            reports = stage("reconciliation_inventory", lambda: prepared.received_reports)
            pending = stage("report_reconciliation", lambda: reconcile(reports))
            candidate = stage("candidate_finalize", lambda: store.finalize_daily(
                prepared, discovery=discovery,
            ))
            assert stage("verified_inventory", lambda: store.report_inventory(
                candidate.manifest_sha256, through=target,
            )) == reports
            stage("publication_check", lambda: store.verify_for_publication(
                candidate.manifest_sha256,
            ))
        else:
            candidate = stage("candidate_build", lambda: store.rebuild_daily(
                collection, prior_candidate_manifest_sha256=prior, discovery=discovery,
            ))
            reports = stage("reconciliation_inventory", lambda: store.report_inventory(
                candidate.manifest_sha256, through=target,
            ))
            pending = stage("report_reconciliation", lambda: reconcile(reports))
        duration = perf_counter() - start
        summary = io.snapshot()
    manifest = json.loads((args.scratch_root / "manifests/sha256" /
                           candidate.manifest_sha256[:2] /
                           f"{candidate.manifest_sha256}.json").read_bytes())
    # Equal table references bind every immutable physical row and overlay ordinal,
    # proving identical final logical rows without materializing the entire market.
    facts = {key: manifest[key] for key in ("tables", "quarantine", "dataset_coverage")}
    facts["inventory"] = {key: sorted(values) for key, values in reports.items()}
    facts_sha256 = hashlib.sha256(canonical_json_bytes(facts)).hexdigest()
    result = {
        "implementation": args.implementation, "cold": args.cold,
        "runtime": {"python": sys.version.split()[0], "pyarrow": pa.__version__,
                    "platform": sys.platform, "arrow_threads": pa.cpu_count()},
        "candidate_implementation_sha256": hashlib.sha256(Path(
            sys.modules[FinancialCandidateStore.__module__].__file__,
        ).read_bytes()).hexdigest(),
        "evidence_sha256": hashlib.sha256(args.evidence.read_bytes()).hexdigest(),
        "requirements_sha256": hashlib.sha256(args.requirements.read_bytes()).hexdigest(),
        "source_generation": collection.generation_manifest_sha256,
        "prior_financial": prior, "checkpoint_count": len(checkpoints),
        "company_count": len(grouped), "duration_seconds": duration,
        "validation_seconds_included": validation_seconds, "phases": phases, "io": summary,
        "workset_families": worksets, "sqlite_peak_bytes": sqlite_peak_bytes,
        "parquet_decoded": decoded,
        "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (
            1 if sys.platform == "darwin" else 1024
        ),
        "facts_sha256": facts_sha256,
        "table_references": manifest["tables"], "coverage": manifest["dataset_coverage"],
        "quarantine": manifest["quarantine"],
        "pending_instruments": pending,
        "inventory_report_counts": {key: len(values) for key, values in reports.items()},
    }
    store.close()
    pq.read_table = original_read_table
    return result


if __name__ == "__main__":
    main()
