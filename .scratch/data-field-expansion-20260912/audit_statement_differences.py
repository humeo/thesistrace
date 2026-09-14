"""Attribute every changed original-field coordinate to retained source evidence."""
import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from thesistrace.data.fields import alpha_field_catalog
from thesistrace.data.financial_candidate import FinancialCandidateStore
from thesistrace.data.generation_store import MountedGenerationStore

parser = argparse.ArgumentParser()
parser.add_argument('--root', type=Path, required=True)
parser.add_argument('--qualification', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
qualification = json.loads(args.qualification.read_text())
differences = qualification['original_differences']
assert all(len(item['coordinates']) == item['coordinate_count'] for item in differences)
new_digest = qualification['statement_candidate']
market = MountedGenerationStore(args.root)
source = market.inspect_root(qualification['source_generation'])
old_digest = source.financial_candidate_manifest_sha256
store = FinancialCandidateStore(args.root)
fields = {item.field_id: item for item in alpha_field_catalog()}
metadata = ('instrument_id', 'source_report_period', 'source_report_type', 'source_company_type',
            'effective_available_session', 'availability_status', 'first_observed_at',
            'source_published_date', 'source_row_sha256', 'update_flag',
            'logical_revision_group_sha256')
queries = {}
pending = defaultdict(list)
conflicts = defaultdict(list)


def group_key(row):
    return (row['logical_revision_group_sha256'], row['source_published_date'],
            row['first_observed_at'])


def raw_rows(digest, endpoint, columns, identities, status):
    names = {'income': 'income_statement_versions', 'balancesheet': 'balance_sheet_versions',
             'cashflow': 'cash_flow_statement_versions'}
    family = store._read_family(digest)
    reference = next(item for item in family['tables'] if item['name'] == names[endpoint])
    manifest = json.loads(store._manifest_path(reference['manifest_sha256']).read_text())
    for obj in manifest['objects']:
        parquet = pq.ParquetFile(store._object_path(obj['sha256']))
        for batch in parquet.iter_batches(batch_size=4096, columns=list(columns)):
            selected = batch.filter(pc.and_(
                pc.is_in(batch['instrument_id'], value_set=pa.array(sorted(identities))),
                pc.equal(batch['availability_status'], status),
            ))
            yield from selected.to_pylist()


for endpoint in ('income', 'balancesheet', 'cashflow'):
    affected = [item for item in differences if fields[item['field_id']].source_endpoint == endpoint]
    identities = frozenset(item['instrument_id'] for item in affected)
    if not identities:
        continue
    columns = tuple(dict.fromkeys((*metadata, *(fields[item['field_id']].source_column
                                               for item in affected))))
    table = store.read_financial_table(new_digest, endpoint, columns,
                                      tuple(source.research_sessions), identities)
    groups = defaultdict(list)
    for batch in table.to_batches(max_chunksize=4096):
        for row in batch.to_pylist():
            if row['availability_status'] == 'available':
                groups[row['instrument_id']].append(row)
    queries[endpoint] = groups
    for row in raw_rows(old_digest, endpoint, columns, identities, 'pending_calendar'):
        pending[(endpoint, row['logical_revision_group_sha256'], row['source_published_date'])].append(row)
    for row in raw_rows(new_digest, endpoint, columns, identities, 'quarantined'):
        conflicts[(endpoint, *group_key(row))].append(row)
    print('Loaded difference evidence', endpoint, len(identities), flush=True)

ledger = []
for difference in differences:
    field = fields[difference['field_id']]
    endpoint = field.source_endpoint
    instrument = difference['instrument_id']
    for coordinate in difference['coordinates']:
        day = coordinate['session']
        rows = [row for row in queries[endpoint][instrument]
                if row['effective_available_session'] <= day
                and row['source_report_type'] == '1'
                and row['source_company_type'] in {'1', '2', '3', '4'}
                and (field.report_period_selection != 'latest_visible_full_year'
                     or row['source_report_period'].endswith('1231'))]
        selected = max(rows, key=lambda row: (
            row['source_report_period'], row['effective_available_session'],
            row['update_flag'] == '1', row['source_published_date'], row['first_observed_at'],
            row['source_row_sha256'],
        )) if rows else None
        cause = 'unexplained'
        hashes = []
        if selected is not None and selected[field.source_column] == coordinate['new']:
            if coordinate['new'] is None:
                evidence = conflicts[(endpoint, *group_key(selected))]
                if len({row[field.source_column] for row in evidence}) > 1:
                    cause = 'conflicting_field_projects_to_missing'
                    hashes = sorted({row['source_row_sha256'] for row in evidence})
            else:
                evidence = pending[(endpoint, selected['logical_revision_group_sha256'],
                                    selected['source_published_date'])]
                evidence = [row for row in evidence
                            if row[field.source_column] == coordinate['new']]
                if evidence:
                    cause = 'retained_pending_report_activated_by_calendar'
                    hashes = sorted({row['source_row_sha256'] for row in evidence})
        ledger.append({
            'field_id': field.field_id, 'instrument_id': instrument, **coordinate,
            'cause': cause, 'source_row_sha256s': hashes,
            'selected_report_period': selected['source_report_period'] if selected else None,
            'effective_available_session': selected['effective_available_session'] if selected else None,
        })
summary = Counter(row['cause'] for row in ledger)
report = {
    'source_generation': qualification['source_generation'], 'statement_candidate': new_digest,
    'status': 'difference_evidence_audited' if not summary['unexplained'] else 'unexplained_differences',
    'coordinate_count': len(ledger), 'causes': dict(summary), 'ledger': ledger,
    'acceptance': 'pending_user_decision',
    'scope': 'Evidence attribution only; no original-value requirement is relaxed by this report.',
}
args.output.write_text(json.dumps(report, indent=2) + '\n')
print('Difference evidence audit', dict(summary), flush=True)
