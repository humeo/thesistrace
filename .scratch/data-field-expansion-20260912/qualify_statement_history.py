"""Audit retained statement scope and resolve every listed research coordinate offline."""
import argparse
import csv
import json
import time
from collections import Counter, defaultdict
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from thesistrace.data.fields import alpha_field_catalog
from thesistrace.data.financial_candidate import FinancialCandidateStore
from thesistrace.data.financial_collection import FINANCIAL_ENDPOINTS
from thesistrace.data.financial_series import FinancialSeriesResolver
from thesistrace.data.generation_store import MountedGenerationStore

parser = argparse.ArgumentParser()
parser.add_argument('--root', type=Path, required=True)
parser.add_argument('--candidate', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
started = time.monotonic()
prepared = json.loads(args.candidate.read_text())
head = prepared['source_generation']
digest = prepared['statement_candidate']['manifest_sha256']
market = MountedGenerationStore(args.root)
source = market.inspect_root(head)
lifecycles = market.read_historical_ordinary_a_share_lifecycles(head)
identities = frozenset(item.instrument_id for item in lifecycles)
sessions = source.research_sessions
fields = tuple(field for field in alpha_field_catalog() if field.family_id == 'equity.financial_pit')
assert len(fields) == 41
metadata = ('instrument_id', 'source_report_period', 'source_report_type', 'source_company_type',
            'effective_available_session', 'availability_status', 'first_observed_at',
            'source_published_date', 'source_row_sha256', 'update_flag')
store = FinancialCandidateStore(args.root)
tables = {}
indices = {}
old_tables = {}
old_indices = {}
old_digest = prepared['source_statement_candidate']
original_ids = {
    'financial.income.total_revenue.latest_fy',
    'financial.income.net_profit_parent.latest_fy',
    'financial.cashflow.operating_cash_flow.latest_fy',
    'financial.balance_sheet.total_assets.latest_reported',
    'financial.balance_sheet.total_liabilities.latest_reported',
    'financial.balance_sheet.equity_parent.latest_reported',
}
original_fields = tuple(field for field in fields if field.field_id in original_ids)
assert len(original_fields) == 6
gap_path = args.candidate.with_name('issue07-statement-gap-collection.json')
gap_receipts = json.loads(gap_path.read_text())
assert gap_receipts['source_head'] == head
supplemented_instruments = {item['instrument_id'] for item in gap_receipts['checkpoints']}
source_counts = defaultdict(Counter)
family = store._read_family(digest)

def retained_source_rows(endpoint, columns):
    table_name = {"income": "income_statement_versions", "balancesheet": "balance_sheet_versions",
                  "cashflow": "cash_flow_statement_versions"}[endpoint]
    reference = next(item for item in family["tables"] if item["name"] == table_name)
    table_digest = reference["manifest_sha256"]
    manifest = json.loads(store._manifest_path(table_digest).read_text())
    for obj in manifest["objects"]:
        parquet = pq.ParquetFile(store._object_path(obj["sha256"]))
        for batch in parquet.iter_batches(batch_size=4096, columns=list(columns)):
            yield from batch.to_pylist()

for endpoint in FINANCIAL_ENDPOINTS:
    selected = tuple(field for field in fields if field.source_endpoint == endpoint)
    columns = tuple(dict.fromkeys((*metadata, *(field.source_column for field in selected))))
    print('Reading retained statement columns', endpoint, len(columns), flush=True)
    table = store.read_financial_table(digest, endpoint, columns, tuple(sessions), identities)
    tables[endpoint] = table
    positions = defaultdict(list)
    for index, instrument in enumerate(table['instrument_id'].to_pylist()):
        positions[instrument].append(index)
    for row in retained_source_rows(endpoint, columns):
        year = str(row['source_report_period'])[:4]
        company = str(row['source_company_type'])
        for field in selected:
            counts = source_counts[(field.field_id, year, company)]
            counts['retained_observation_rows'] += 1
            if row['availability_status'] != 'available':
                counts['unavailable_source_fact'] += 1
            elif row['source_report_type'] != '1':
                counts['out_of_reporting_scope'] += 1
            elif company not in field.applicable_company_types:
                counts['inapplicable_company_type'] += 1
            elif field.report_period_selection == 'latest_visible_full_year' and not str(
                row['source_report_period']
            ).endswith('1231'):
                counts['out_of_period_scope'] += 1
            elif field.report_period_selection == 'latest_visible_ttm' and not str(
                row['source_report_period']
            ).endswith(('0331', '0630', '0930', '1231')):
                counts['out_of_period_scope'] += 1
            elif row[field.source_column] is None:
                counts['eligible_source_null'] += 1
            else:
                counts['eligible_source_non_null'] += 1
    indices[endpoint] = positions
    old_columns = tuple(dict.fromkeys((*metadata, *(field.source_column for field in original_fields
                                                    if field.source_endpoint == endpoint))))
    old_table = store.read_financial_table(old_digest, endpoint, old_columns, tuple(sessions), identities)
    old_tables[endpoint] = old_table
    old_positions = defaultdict(list)
    for index, instrument in enumerate(old_table['instrument_id'].to_pylist()):
        old_positions[instrument].append(index)
    old_indices[endpoint] = old_positions

daily_counts = defaultdict(Counter)
examples = {}
completed = 0
compared_original_coordinates = 0
original_differences = []
for identity in lifecycles:
    instrument = identity.instrument_id
    active = tuple(day for day in sessions if day >= identity.listed_from
                   and (not identity.listed_to or day <= identity.listed_to))
    if not active:
        completed += 1
        continue
    selected_tables = {
        endpoint: table.take(pa.array(indices[endpoint].get(instrument, []), type=pa.int64()))
        for endpoint, table in tables.items()
    }

    class RetainedProjectionReader:
        def read_financial_table(self, manifest, endpoint, columns, requested_sessions, requested_ids):
            assert manifest == digest and requested_ids == frozenset({instrument})
            assert requested_sessions == active
            return selected_tables[endpoint].select(columns)

    resolved = FinancialSeriesResolver(RetainedProjectionReader()).resolve_table(
        manifest_sha256=digest, field_ids=tuple(field.field_id for field in fields),
        sessions=active, instrument_ids=(instrument,),
    )
    assert resolved.num_rows == len(active)
    if instrument not in supplemented_instruments:
        selected_old = {
            endpoint: table.take(pa.array(old_indices[endpoint].get(instrument, []), type=pa.int64()))
            for endpoint, table in old_tables.items()
        }

        class OriginalProjectionReader:
            def read_financial_table(self, manifest, endpoint, columns, requested_sessions, requested_ids):
                assert manifest == old_digest and requested_ids == frozenset({instrument})
                assert requested_sessions == active
                return selected_old[endpoint].select(columns)

        old_resolved = FinancialSeriesResolver(OriginalProjectionReader()).resolve_table(
            manifest_sha256=old_digest, field_ids=tuple(field.field_id for field in original_fields),
            sessions=active, instrument_ids=(instrument,),
        )
        for field in original_fields:
            old_column = old_resolved[field.field_id].combine_chunks()
            new_column = resolved[field.field_id].combine_chunks()
            if not old_column.equals(new_column):
                differences = [
                    {'session': day, 'old': before, 'new': after}
                    for day, before, after in zip(
                        active, old_column.to_pylist(), new_column.to_pylist(), strict=True,
                    ) if before != after
                ]
                original_differences.append({
                    'field_id': field.field_id, 'instrument_id': instrument,
                    'coordinate_count': len(differences),
                    'first': differences[:3], 'last': differences[-3:],
                    'coordinates': differences,
                })
        compared_original_coordinates += len(active)
    start = 0
    while start < len(active):
        year = active[start][:4]
        end = start + 1
        while end < len(active) and active[end][:4] == year:
            end += 1
        block = resolved.slice(start, end - start)
        for field in fields:
            column = block[field.field_id]
            counts = daily_counts[(field.field_id, year)]
            counts['listed_security_sessions'] += len(column)
            counts['dsl_non_null'] += len(column) - column.null_count
            counts['dsl_missing'] += column.null_count
            if field.field_id not in examples and column.null_count < len(column):
                for offset, value in enumerate(column.to_pylist()):
                    if value is not None:
                        examples[field.field_id] = {
                            'instrument_id': instrument, 'session': active[start + offset],
                            'value': value,
                        }
                        break
        start = end
    completed += 1
    if completed % 100 == 0:
        print('Resolved all statement research sessions', completed, '/', len(lifecycles), flush=True)

def write_counts(path, labels, counts, value_names):
    with path.open('w', newline='') as destination:
        writer = csv.DictWriter(destination, fieldnames=[*labels, *value_names])
        writer.writeheader()
        for key, values in sorted(counts.items()):
            writer.writerow({**dict(zip(labels, key, strict=True)),
                             **{name: values[name] for name in value_names}})

source_csv = args.output.with_name(args.output.stem + '-source.csv')
daily_csv = args.output.with_name(args.output.stem + '-dsl.csv')
write_counts(source_csv, ['field_id', 'report_year', 'company_type'], source_counts,
             ['retained_observation_rows', 'unavailable_source_fact', 'out_of_reporting_scope',
              'inapplicable_company_type', 'out_of_period_scope', 'eligible_source_null',
              'eligible_source_non_null'])
write_counts(daily_csv, ['field_id', 'year'], daily_counts,
             ['listed_security_sessions', 'dsl_non_null', 'dsl_missing'])
report = {
    'source_generation': head, 'statement_candidate': digest,
    'status': ('statement_statistics_with_original_differences' if original_differences
               else 'statement_statistics_complete'), 'expected_instruments': len(lifecycles),
    'completed_instruments': completed, 'field_count': len(fields),
    'original_financial_fields_compared': sorted(original_ids),
    'original_security_sessions_compared': compared_original_coordinates,
    'original_differences': original_differences,
    'original_value_acceptance': 'pending' if original_differences else 'equal',
    'supplemented_instruments_with_new_source_inputs': sorted(supplemented_instruments),
    'source_csv': str(source_csv), 'dsl_csv': str(daily_csv),
    'source_counting_basis': 'Retained source facts by report year and source company type.',
    'dsl_counting_basis': 'Every pinned research session inside each retained listing lifecycle.',
    'projection_missingness': 'Current resolver enforces visibility, scope and complete matching TTM components; no filling.',
    'fields_without_non_null_dsl_values': [field.alpha.identifier for field in fields
                                          if field.field_id not in examples],
    'examples': examples, 'source_requests': 0,
    'elapsed_seconds': time.monotonic() - started,
}
args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
print('Statement source and DSL statistics complete', len(examples), '/', 41, flush=True)
