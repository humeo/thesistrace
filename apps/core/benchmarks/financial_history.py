"""Fixed offline financial-reader comparison against the checkout's committed base."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import resource
import subprocess
import sys
import tarfile
from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / "apps/core/tests/data"), str(ROOT / "apps/core/tests/support")]


def prepare(root):
    import pyarrow as pa
    from test_financial_candidate import FIELDS, _materialized_candidate
    from test_financial_indicator_candidate import _read_candidate

    from thesistrace.data.financial_indicator_candidate import (
        _SCHEMA,
        _WRITER,
        FinancialIndicatorCandidateStore,
    )
    from thesistrace.data.generation_files import AddressedFileStore
    from thesistrace.publication.serialization import canonical_json_bytes, parquet_table_bytes

    # Real current-schema immutable Parquet, with synthetic source revisions.
    # This measures reader amplification, not end-to-end production throughput.
    indicators = root / "indicators"
    store = FinancialIndicatorCandidateStore(indicators)
    manifest = store.reopen(_read_candidate(indicators))
    template = store.read_table(
        hashlib.sha256(canonical_json_bytes(manifest)).hexdigest(), columns=set(_SCHEMA.names),
        instrument_ids=frozenset({"stock-1"}), through="2020-05-04",
    ).to_pylist()[0]
    sessions = [(date(2020, 4, 21) + timedelta(days=day)).isoformat() for day in range(90)]
    files, partitions, identities = AddressedFileStore(indicators), [], {}
    for index in range(3004):
        instrument, code = f"stock-{index:04}", f"{index:06}.SZ"
        identities[code] = instrument
        rows = [{
            **template, "instrument_id": instrument, "ts_code": code,
            "state_effective_session": session, "effective_available_session": session,
            "observation_event_at": session + "T00:00:00+00:00",
            "roe": str(10 + index % 7 + ordinal / 10),
            "debt_to_assets": str(30 + index % 11 + ordinal / 10),
        } for ordinal, session in enumerate(sessions[:60:2])]
        content = parquet_table_bytes(pa.Table.from_pylist(rows, schema=_SCHEMA), _WRITER)
        digest = hashlib.sha256(content).hexdigest()
        files.store(indicators / "objects/sha256" / digest[:2] / f"{digest}.parquet",
                    digest, content)
        partitions.append({**manifest["partitions"][0], "sha256": digest,
                           "byte_count": len(content), "row_count": len(rows),
                           "instrument_id": instrument})
    manifest.update(partitions=partitions, instrument_ids=identities, research_sessions=sessions)
    content = canonical_json_bytes(manifest)
    digest = hashlib.sha256(content).hexdigest()
    files.store(indicators / "manifests/sha256" / digest[:2] / f"{digest}.json", digest, content)
    store.reopen(digest)

    import test_financial_candidate as fixtures

    fixtures.FIELDS = tuple("n_cashflow_act" if name == "revenue" else name for name in FIELDS)
    _, statement, _, _ = _materialized_candidate(root / "statements", quarterly_cash_seed=True)
    return {"indicator": digest, "statement": statement.manifest_sha256,
            "statement_start": statement.coverage_start, "sessions": sessions,
            "instrument_count": 3000, "source_revisions_per_security": 30}


def sample(root, mode):
    import pyarrow as pa
    from test_financial_candidate import SESSIONS

    import thesistrace
    from thesistrace.data.financial_candidate import FinancialCandidateStore
    from thesistrace.data.financial_indicator_candidate import FinancialIndicatorCandidateStore
    from thesistrace.data.financial_indicator_series import FinancialIndicatorSeriesResolver
    from thesistrace.data.financial_series import FinancialSeriesResolver
    from thesistrace.data.history_projection import HistoryProjectionCache
    from thesistrace.data.io_metrics import measure_data_io

    fixture = json.loads((root / "fixture.json").read_text())
    cache, result = HistoryProjectionCache(), hashlib.sha256()
    instruments = tuple(f"stock-{index:04}" for index in range(3004))
    phases = []

    def consume(table):
        buffer = pa.BufferOutputStream()
        with pa.ipc.new_stream(buffer, table.schema) as writer:
            writer.write_table(table.combine_chunks())
        result.update(buffer.getvalue().to_pybytes())

    for window in range(4):
        started = perf_counter()
        with measure_data_io() as metrics:
            for count in (5, 1, 2):
                sessions = tuple(fixture["sessions"][60 + window * 5:60 + window * 5 + count])
                for field in ("roe", "debt_to_assets"):
                    store = FinancialIndicatorCandidateStore(
                        root / "indicators", **({"projection_cache": cache}
                                               if mode == "baseline" else {}),
                    )
                    reader = FinancialIndicatorSeriesResolver(
                        fixture["indicator"],
                        lambda cols, ids, through, store=store: store.read_table(
                            fixture["indicator"], columns=cols, instrument_ids=ids, through=through,
                        ), **({"projection_cache": cache, "history_end": fixture["sessions"][-1]}
                              if mode == "current" else {}),
                    )
                    consume(reader.resolve_table(
                        manifest_sha256=fixture["indicator"],
                        field_ids=(f"financial.indicator.{field}",), sessions=sessions,
                        instrument_ids=instruments[window:window + 3000],
                    ))
                reader = FinancialSeriesResolver(
                    FinancialCandidateStore(root / "statements"), **({
                        "projection_cache": cache,
                        "history_sessions": tuple(day for day in SESSIONS
                                                  if day >= fixture["statement_start"]),
                    } if mode == "current" else {}),
                )
                consume(reader.resolve_table(
                    manifest_sha256=fixture["statement"],
                    field_ids=("financial.cashflow.operating_cash_flow.ttm",),
                    sessions=SESSIONS[-2:], instrument_ids=("equity:000001.SZ", "equity:000002.SZ"),
                ))
        phases.append({"seconds": perf_counter() - started, "io": vars(metrics),
                       "retained_bytes": cache.retained_bytes})
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return {"mode": mode, "module_path": str(thesistrace.__file__), "phases": phases,
            "result_sha256": result.hexdigest(), "peak_rss_bytes": peak if sys.platform == "darwin"
            else peak * 1024, "seconds": sum(phase["seconds"] for phase in phases),
            "parquet_object_opens": sum(p["io"]["parquet_object_opens"] for p in phases),
            "bytes_read": sum(p["io"]["bytes_read"] for p in phases)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--baseline-ref", help="Committed revision before the reader changes")
    parser.add_argument("--sample", choices=("baseline", "current"))
    parser.add_argument("--fixture", type=Path)
    args = parser.parse_args()
    if args.sample:
        print(json.dumps(sample(args.fixture, args.sample)))
        return
    if args.output is None:
        parser.error("--output is required")
    if args.baseline_ref is None:
        parser.error("--baseline-ref is required")
    revision = subprocess.check_output([
        "git", "rev-parse", "--verify", "--end-of-options", f"{args.baseline_ref}^{{commit}}",
    ], cwd=ROOT, text=True).strip()
    current_revision = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True,
    ).strip()
    with TemporaryDirectory(prefix="thesistrace-financial-history-") as temporary:
        folder = Path(temporary)
        fixture = prepare(folder)
        (folder / "fixture.json").write_text(json.dumps(fixture))
        archive = subprocess.check_output(["git", "archive", revision, "apps/core/src"], cwd=ROOT)
        baseline = folder / "baseline"
        with tarfile.open(fileobj=io.BytesIO(archive)) as source:
            source.extractall(baseline, filter="data")
        results = []
        for mode, code in (("baseline", baseline), ("current", ROOT)):
            env = {**os.environ, "PYTHONPATH": str(code / "apps/core/src")}
            print(
                f"financial history: {mode}, 3000 securities, four windows + prefixes", flush=True,
            )
            output = subprocess.check_output([
                sys.executable, str(Path(__file__).resolve()), "--sample", mode,
                "--fixture", str(folder),
            ], cwd=ROOT, env=env, text=True)
            results.append(json.loads(output))
        original, current = results
        evidence = {"baseline_revision": revision, "current_revision": current_revision,
                    "fixture": fixture, "samples": results,
                    "result_identical": original["result_sha256"] == current["result_sha256"],
                    "scope": "offline reader benchmark; application reads include OS cache hits"}
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(evidence, indent=2) + "\n")
        print(json.dumps({key: current[key] for key in
                          ("seconds", "parquet_object_opens", "bytes_read", "peak_rss_bytes")}))
        assert evidence["result_identical"], "Cached financial values changed"
        assert current["parquet_object_opens"] < original["parquet_object_opens"] * 0.2
        assert current["seconds"] < original["seconds"]
        assert max(p["retained_bytes"] for p in current["phases"]) <= 32 * 1024**2


if __name__ == "__main__":
    main()
