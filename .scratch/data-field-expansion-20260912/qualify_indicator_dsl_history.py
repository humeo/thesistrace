"""Count every listed research date using exact constant-state intervals."""
import argparse
import csv
import json
import time
from bisect import bisect_left
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc

from thesistrace.data.fields import FINANCIAL_INDICATOR_FIELDS
from thesistrace.data.financial_indicator_candidate import FinancialIndicatorCandidateStore
from thesistrace.data.financial_indicator_series import FinancialIndicatorSeriesResolver
from thesistrace.data.generation_store import MountedGenerationStore

parser = argparse.ArgumentParser()
parser.add_argument('--root', type=Path, required=True)
parser.add_argument('--candidate', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
started = time.monotonic()
prepared = json.loads(args.candidate.read_text())
head, digest = prepared['source_generation'], prepared['indicator_candidate']
market = MountedGenerationStore(args.root)
source = market.inspect_root(head)
lifecycles = market.read_historical_ordinary_a_share_lifecycles(head)
store = FinancialIndicatorCandidateStore(args.root)
manifest = store.reopen(digest)
assert manifest['research_sessions'] == list(source.research_sessions)
partitions = defaultdict(list)
for part in manifest['partitions']:
    partitions[part['instrument_id']].append(part)
assert manifest['instrument_ids'] == {item.ts_code: item.instrument_id for item in lifecycles}
field_ids = tuple(field.field_id for field in FINANCIAL_INDICATOR_FIELDS)
columns = sorted({
    'instrument_id', 'source_report_period', 'source_published_date',
    'state_effective_session', 'availability_status', 'observation_event_at',
    *(field.source_column for field in FINANCIAL_INDICATOR_FIELDS),
})
counts = defaultdict(Counter)
examples = {}
dense_verified = []
interval_count = 0
listed_coordinate_count = 0
for ordinal, identity in enumerate(lifecycles, 1):
    instrument = identity.instrument_id
    active = tuple(day for day in source.research_sessions if day >= identity.listed_from
                   and (not identity.listed_to or day <= identity.listed_to))
    if not active:
        continue
    parts = partitions[instrument]
    table = (pa.concat_tables([store._read_partition(part, columns) for part in parts])
             if parts else store.read_table(digest, columns=set(columns),
                 instrument_ids=frozenset({instrument}), through=active[-1]))
    positions = {0}
    for day in table['state_effective_session'].to_pylist():
        if day is not None:
            position = bisect_left(active, day)
            if position < len(active):
                positions.add(position)
    positions.update(index for index in range(1, len(active))
                     if active[index][:4] != active[index - 1][:4])
    starts = sorted(positions)
    ends = starts[1:] + [len(active)]
    boundary_sessions = tuple(active[index] for index in starts)
    weights = np.asarray([end - start for start, end in zip(starts, ends, strict=True)])
    assert int(weights.sum()) == len(active)

    def read_table(requested_columns, requested_ids, through):
        assert requested_ids == frozenset({instrument})
        return table.filter(pc.less_equal(table['state_effective_session'], through)).select(
            sorted(requested_columns)
        )

    resolver = FinancialIndicatorSeriesResolver(digest, read_table)
    resolved = resolver.resolve_table(manifest_sha256=digest, field_ids=field_ids,
                                      sessions=boundary_sessions, instrument_ids=(instrument,))
    values_by_field = {field: resolved[field].to_numpy(zero_copy_only=False) for field in field_ids}
    # All input state changes and year boundaries are included. Between adjacent
    # boundaries the public resolver has no event that can change a value.
    # Verify the interval expansion against dense daily evaluation on real data.
    if table.num_rows and len(dense_verified) < 5:
        dense = resolver.resolve_table(manifest_sha256=digest, field_ids=field_ids,
                                       sessions=active, instrument_ids=(instrument,))
        for field in field_ids:
            assert np.array_equal(np.repeat(values_by_field[field], weights),
                                  dense[field].to_numpy(zero_copy_only=False), equal_nan=True), {
                'interval_daily_mismatch': field, 'instrument': instrument,
            }
        dense_verified.append(instrument)
    for position, weight, day in zip(range(len(starts)), weights.tolist(), boundary_sessions, strict=True):
        for field in field_ids:
            values = values_by_field[field]
            valid = bool(np.isfinite(values[position]))
            count = counts[(field, day[:4])]
            count['listed_security_sessions'] += weight
            count['dsl_non_null' if valid else 'dsl_missing'] += weight
            if valid:
                examples.setdefault(field, {'instrument_id': instrument, 'session': day,
                                             'value': float(values[position])})
    interval_count += len(starts)
    listed_coordinate_count += len(active)
    if ordinal % 100 == 0:
        print('Qualified indicator DSL history', ordinal, '/', len(lifecycles), flush=True)

csv_path = args.output.with_suffix('.csv')
with csv_path.open('w', newline='') as destination:
    names = ['field_id', 'year', 'company_type', 'listed_security_sessions', 'dsl_non_null', 'dsl_missing']
    writer = csv.DictWriter(destination, fieldnames=names)
    writer.writeheader()
    for (field, year), values in sorted(counts.items()):
        writer.writerow({'field_id': field, 'year': year, 'company_type': 'not_provided_by_source',
                         **{name: values[name] for name in names[3:]}})
for field in field_ids:
    assert sum(values['listed_security_sessions'] for (field_id, _), values in counts.items()
               if field_id == field) == listed_coordinate_count
report = {
    'source_generation': head, 'indicator_candidate': digest,
    'status': 'indicator_dsl_statistics_complete', 'instrument_count': len(lifecycles),
    'field_count': len(field_ids), 'listed_security_sessions': listed_coordinate_count,
    'evaluated_state_intervals': interval_count, 'dense_daily_verified_instruments': dense_verified,
    'counting_basis': 'Every listed research date, weighted from all state changes and calendar-year boundaries.',
    'company_type': 'not_provided_by_source', 'csv': str(csv_path),
    'fields_without_non_null_dsl_values': [field.alpha.identifier for field in FINANCIAL_INDICATOR_FIELDS
                                          if field.field_id not in examples],
    'examples': examples, 'source_requests': 0, 'elapsed_seconds': time.monotonic() - started,
}
args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
print('Indicator DSL statistics complete', len(examples), '/', len(field_ids), flush=True)
