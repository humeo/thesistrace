"""Profile immutable income reads on the explicitly authorized local snapshot."""
import collections
import gc
import hashlib
import json
import pathlib
import statistics
import sys
import time
from unittest.mock import patch

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from thesistrace.data import financial_candidate as fc
from thesistrace.data.financial_series import FinancialSeriesResolver
from thesistrace.data.generation_files import AddressedFileStore
from thesistrace.data.io_metrics import measure_data_io

directory = pathlib.Path(__file__).resolve().parent
root = directory / 'income-fixture'
sha = 'cea82fc459da39fd7757f6e700dbf23d28d09ae6825b8ca9c48ecc62cc4a0d0f'
def manifest(digest):
    return json.loads((root/'manifests/sha256'/digest[:2]/(digest+'.json')).read_text())
family = manifest(sha)
source = manifest(family['source_generation_manifest_sha256'])
income = manifest(next(t['manifest_sha256'] for t in family['tables'] if t['name']=='income_statement_versions'))
instruments = set()
for obj in income['objects']:
    digest = obj['sha256']
    instruments.update(pq.read_table(root/'objects/sha256'/digest[:2]/(digest+'.parquet'), columns=['instrument_id'])['instrument_id'].to_pylist())
selected_instruments = tuple(sorted(instruments)[:3000])
calendar = source['research_sessions']
first = next(i for i, session in enumerate(calendar) if session >= '2018-01-01')
windows = [calendar[first:first+64], calendar[first+64:first+128], calendar[-64:]]
original_overlay = fc._overlay_financial_table

def columnar_overlay(table, schema):
    if table.num_rows == 0:
        return pa.Table.from_batches([], schema=schema)
    valid = pc.fill_null(pc.match_substring_regex(table['source_row_sha256'], '^[0-9a-f]{64}$'), False)
    if not pc.all(valid).as_py():
        raise fc.FinancialCandidateError('FINANCIAL_SHA256_INVALID')
    indexed = table.select(['source_row_sha256']).append_column('_ordinal', pa.array(np.arange(table.num_rows, dtype=np.int64)))
    groups = indexed.group_by('source_row_sha256', use_threads=False).aggregate([('_ordinal','min'),('_ordinal','max')])
    groups = groups.sort_by([('_ordinal_min','ascending')])
    return table.take(groups['_ordinal_max'])

if '--check-semantics' in sys.argv:
    table = pa.table({'source_row_sha256':['a'*64,'b'*64,'a'*64,'c'*64], 'value':['old','second','new','third']})
    assert original_overlay(table,table.schema).equals(columnar_overlay(table,table.schema))
    for bad in [None, 'A'*64, 'g'*64, 'a'*63, 'a'*65]:
        malformed = pa.table({'source_row_sha256':pa.array([bad], type=pa.string()),'value':['test']})
        codes = []
        for implementation in [original_overlay,columnar_overlay]:
            try:
                implementation(malformed,malformed.schema)
            except fc.FinancialCandidateError as error:
                codes.append(str(error))
        assert codes==['FINANCIAL_SHA256_INVALID']*2
    print(json.dumps({'duplicate_order_and_last_value_equal':True,'invalid_hash_cases_rejected_equally':5}))
    raise SystemExit(0)

all_results = []
baseline_tables = {}
repeat_latest = '--repeat-latest' in sys.argv
cases = [('baseline',2),('columnar_probe',2),('columnar_probe',2),('baseline',2),('baseline',2),('columnar_probe',2)] if repeat_latest else [('baseline',0),('baseline',1),('baseline',2),('columnar_probe',0),('columnar_probe',1),('columnar_probe',2)]
for variant, window_index in cases:
    durations = collections.Counter()
    counts = collections.Counter()
    paths = []
    sessions = tuple(windows[window_index])
    original_file_read = AddressedFileStore.read
    original_parquet_read = pq.read_table
    original_compact = fc._compact_financial_history
    pool = pa.default_memory_pool()
    class PoolProxy:
        def release_unused(self):
            started = time.perf_counter()
            pool.release_unused()
            durations['release_unused'] += time.perf_counter()-started
            counts['release_unused'] += 1
    class ArrowProxy:
        def __getattr__(self, name):
            return getattr(pa, name)
        def default_memory_pool(self):
            return PoolProxy()
    def file_read(self, path, *args, **kwargs):
        started = time.perf_counter()
        value = original_file_read(self,path,*args,**kwargs)
        durations['addressed_read_and_sha256'] += time.perf_counter()-started
        if path.suffix == '.parquet':
            paths.append(path.stem)
        return value
    def parquet_read(*args,**kwargs):
        started = time.perf_counter()
        value = original_parquet_read(*args,**kwargs)
        durations['parquet_read'] += time.perf_counter()-started
        return value
    def overlay(table,schema):
        started = time.perf_counter()
        value = (original_overlay if variant=='baseline' else columnar_overlay)(table,schema)
        durations['overlay'] += time.perf_counter()-started
        counts['overlay_input_rows'] += table.num_rows
        counts['overlay_output_rows'] += value.num_rows
        return value
    def compact(table,start):
        started = time.perf_counter()
        value = original_compact(table,start)
        durations['compact_history'] += time.perf_counter()-started
        return value
    with patch.object(fc,'pa',ArrowProxy()), patch.object(AddressedFileStore,'read',file_read), patch.object(pq,'read_table',parquet_read), patch.object(fc,'_overlay_financial_table',overlay), patch.object(fc,'_compact_financial_history',compact), measure_data_io() as io:
        started = time.perf_counter()
        values = FinancialSeriesResolver(fc.FinancialCandidateStore(root)).resolve_table(manifest_sha256=sha,field_ids=('financial.income.total_revenue.latest_fy',),sessions=sessions,instrument_ids=selected_instruments)
        total = time.perf_counter()-started
    equal = None
    if variant=='baseline':
        baseline_tables[window_index] = values
    else:
        equal = values.equals(baseline_tables[window_index])
        assert equal, 'diagnostic columnar probe changed output'
    result = {'variant':variant,'window':window_index,'first_session':sessions[0],'last_session':sessions[-1],'instrument_count':len(selected_instruments),'total_seconds':total,'timing_seconds':dict(durations),'counts':dict(counts),'io':io.snapshot(),'output_rows':values.num_rows,'equals_baseline':equal,'object_hashes':paths}
    all_results.append(result)
    print(json.dumps({k:v for k,v in result.items() if k!='object_hashes'}),flush=True)
    gc.collect()
    pool.release_unused()

baseline = [r for r in all_results if r['variant']=='baseline']
common = set(baseline[0]['object_hashes']) & set(baseline[1]['object_hashes'])
summary = {'mode':'repeat_latest' if repeat_latest else 'three_windows','repeated_objects_between_first_two_baselines':len(common),'first_window_objects':len(baseline[0]['object_hashes']),'second_window_objects':len(baseline[1]['object_hashes']),'median_seconds':{v:statistics.median(r['total_seconds'] for r in all_results if r['variant']==v) for v in ('baseline','columnar_probe')},'snapshots':all_results}
(directory/('financial-read-repeat.json' if repeat_latest else 'financial-read-profile.json')).write_text(json.dumps(summary,indent=2))
print(json.dumps({k:v for k,v in summary.items() if k!='snapshots'}),flush=True)
