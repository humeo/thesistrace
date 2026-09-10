"""Compare the implemented public financial read against the captured Git base."""
import ast
import gc
import json
import statistics
import subprocess
import time
from pathlib import Path
from unittest.mock import patch

import pyarrow as pa
import pyarrow.parquet as pq

from thesistrace._memory import release_unused_memory
from thesistrace.data import financial_candidate as fc
from thesistrace.data.financial_series import FinancialSeriesResolver
from thesistrace.data.io_metrics import measure_data_io

base_revision = "ad16ea9bd8e369c20270d187499cb089b7b7069e"
source = subprocess.check_output([
    "git", "show", f"{base_revision}:apps/core/src/thesistrace/data/financial_candidate.py",
], text=True)
node = next(node for node in ast.parse(source).body if isinstance(node, ast.FunctionDef) and node.name == "_overlay_financial_table")
namespace = dict(vars(fc))
exec(compile(ast.Module(body=[node], type_ignores=[]), "baseline-overlay", "exec"), namespace)
implementations = {"before": namespace["_overlay_financial_table"], "after": fc._overlay_financial_table}

sample = pa.table({"source_row_sha256": ["a" * 64, "b" * 64, "a" * 64, "c" * 64], "value": ["old", "second", "new", "third"]})
assert implementations["before"](sample, sample.schema).equals(implementations["after"](sample, sample.schema))
invalid = [None, "A" * 64, "g" * 64, "a" * 63, "a" * 65, "a" * 64 + "\n"]
for value in invalid:
    table = pa.table({"source_row_sha256": pa.array([value], type=pa.string()), "value": ["invalid"]})
    for implementation in implementations.values():
        try:
            implementation(table, table.schema)
        except fc.FinancialCandidateError as error:
            assert str(error) == "FINANCIAL_SHA256_INVALID"
        else:
            raise AssertionError("invalid hash accepted")

root = Path("/Users/koltenluca/code-github/thesistrace/.scratch/server-performance-diagnosis-20260910/income-fixture")
family_id = "cea82fc459da39fd7757f6e700dbf23d28d09ae6825b8ca9c48ecc62cc4a0d0f"
def manifest(digest):
    return json.loads((root / "manifests/sha256" / digest[:2] / f"{digest}.json").read_text())
family = manifest(family_id)
calendar = manifest(family["source_generation_manifest_sha256"])["research_sessions"]
income = manifest(next(table["manifest_sha256"] for table in family["tables"] if table["name"] == "income_statement_versions"))
instruments = set()
for item in income["objects"]:
    digest = item["sha256"]
    instruments.update(pq.read_table(root / "objects/sha256" / digest[:2] / f"{digest}.parquet", columns=["instrument_id"])["instrument_id"].to_pylist())
selected = tuple(sorted(instruments)[:3000])
first = next(index for index, session in enumerate(calendar) if session >= "2018-01-01")
windows = [calendar[first:first + 64], calendar[first + 64:first + 128], calendar[-64:]]
references = {}
results = []
cases = [(kind, window) for window in range(3) for kind in ("before", "after")]
cases += [(kind, 2) for kind in ("after", "before", "before", "after")]
for kind, window in cases:
    release_unused_memory()
    with patch.object(fc, "_overlay_financial_table", implementations[kind]), measure_data_io() as io:
        started = time.perf_counter()
        values = FinancialSeriesResolver(fc.FinancialCandidateStore(root)).resolve_table(
            manifest_sha256=family_id, field_ids=("financial.income.total_revenue.latest_fy",),
            sessions=tuple(windows[window]), instrument_ids=selected,
        )
        elapsed = time.perf_counter() - started
    if kind == "before":
        references[window] = values
    else:
        assert values.equals(references[window]), "financial values changed"
    result = {"variant": kind, "window": window, "seconds": elapsed, "rows": values.num_rows, "io": io.snapshot()}
    results.append(result)
    print(json.dumps(result), flush=True)
    del values
    gc.collect()
summary = {
    "base_revision": base_revision, "family_manifest": family_id,
    "instruments": len(selected), "sessions_per_window": 64,
    "three_windows_equal": True, "duplicate_order_equal": True,
    "invalid_hash_cases_rejected": len(invalid),
    "latest_window_median_seconds": {
        kind: statistics.median(row["seconds"] for row in results if row["variant"] == kind and row["window"] == 2)
        for kind in implementations
    }, "samples": results,
}
Path(".local/financial-read-comparison.json").write_text(json.dumps(summary, indent=2))
print(json.dumps({key: value for key, value in summary.items() if key != "samples"}))
