"""Count the unchanged seven physical price fields by year, without publishing."""
import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from thesistrace.data.fields import MARKET_FIELDS
from thesistrace.data.generation_store import MountedGenerationStore
from thesistrace.data.market_series import market_field_column_bindings

parser = argparse.ArgumentParser()
parser.add_argument('--root', type=Path, required=True)
parser.add_argument('--source-integrity', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
verified = json.loads(args.source_integrity.read_text())
head = verified['source_head']['generation_manifest_sha256']
store = MountedGenerationStore(args.root)
source = store.inspect_root(head)
family = next(item for item in source.families if item.family_id == 'equity.eod_price')


def manifest(digest):
    return json.loads((args.root / 'manifests' / 'sha256' / digest[:2] / (digest + '.json')).read_text())


family_manifest = manifest(family.manifest_sha256)
reference = next(item for item in family_manifest['tables'] if item['name'] == 'eod_prices')
table_manifest = manifest(reference['manifest_sha256'])
bindings = market_field_column_bindings({field.field_id: field.alpha.identifier for field in MARKET_FIELDS})
assert len(bindings) == 7
counts = defaultdict(Counter)
observed = 0
for obj in table_manifest['objects']:
    path = args.root / 'objects' / 'sha256' / obj['sha256'][:2] / (obj['sha256'] + '.parquet')
    for batch in pq.ParquetFile(path).iter_batches(batch_size=65536, columns=['session_date', *bindings.values()]):
        years = pc.cast(pc.year(batch['session_date']), pa.string())
        for year in pc.unique(years).to_pylist():
            rows = batch.filter(pc.equal(years, year))
            observed += rows.num_rows
            for field_id, column in bindings.items():
                raw = rows[column]
                if pa.types.is_string(raw.type):
                    raw = pc.if_else(pc.equal(raw, ''), None, raw)
                numbers = pc.cast(raw, pa.float64())
                finite = pc.fill_null(pc.is_finite(numbers), False)
                total = counts[(field_id, year)]
                total['observed_price_rows'] += rows.num_rows
                total['non_null_finite'] += pc.sum(pc.cast(finite, pa.int64())).as_py()
                total['missing'] += numbers.null_count
                total['non_finite'] += pc.sum(pc.cast(pc.and_(pc.is_valid(numbers), pc.invert(finite)), pa.int64())).as_py()
assert observed == reference['row_count']
assert all(values['non_finite'] == 0 for values in counts.values())
assert store.inspect_root(head) == source
csv_path = args.output.with_suffix('.csv')
with csv_path.open('w', newline='') as output:
    writer = csv.DictWriter(output, fieldnames=['field_id', 'year', 'company_type', 'observed_price_rows', 'non_null_finite', 'missing', 'non_finite'])
    writer.writeheader()
    for (field_id, year), values in sorted(counts.items()):
        writer.writerow({'field_id': field_id, 'year': year, 'company_type': 'not_applicable', **values})
report = {'source_generation': head, 'price_family': family.manifest_sha256,
          'status': 'price_source_statistics_complete', 'field_count': len(bindings),
          'observed_price_rows': observed, 'csv': str(csv_path), 'source_requests': 0,
          'scope': 'All retained physical price rows by year; listing lifecycle denominator is separate.'}
args.output.write_text(json.dumps(report, indent=2) + '\n')
print('Price history qualified', observed, 'rows', flush=True)
