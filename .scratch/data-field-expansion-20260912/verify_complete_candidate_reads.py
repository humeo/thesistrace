"""Exercise the actual composed candidate and DSL offline, without publishing Head."""
import argparse
import json
from pathlib import Path
from unittest.mock import patch

import numpy as np

from thesistrace.data.fields import alpha_field_catalog
from thesistrace.data.generation_store import MountedGenerationStore
from thesistrace.data.head_store import MountedDatasetHeadStore
from thesistrace.data.io_metrics import cold_file_reads, measure_data_io
from thesistrace.research_kernel.alpha import evaluate_columnar_alpha_matrix, validate_alpha

parser = argparse.ArgumentParser()
parser.add_argument('--root', type=Path, required=True)
parser.add_argument('--candidate', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
prepared = json.loads(args.candidate.read_text())
digest = prepared['candidate']['manifest_sha256']
store = MountedGenerationStore(args.root)
head = MountedDatasetHeadStore(args.root).current_pointer()
descriptor = store.inspect_root(digest)
calendar = descriptor.research_sessions
middle = len(calendar) // 2
sessions = sorted(set((*calendar[:3], *calendar[middle:middle + 3], *calendar[-3:])))
fields = alpha_field_catalog()
bindings = {field.field_id: field.alpha.identifier for field in fields}
assert len(bindings) == 226
pe = 'market.valuation.pe'
roe = 'financial.indicator.roe'
revenue = 'financial.income.total_revenue.latest_fy'
profit = 'financial.income.net_profit_parent.latest_fy'
close = 'price.close.raw'


def read(selected):
    with cold_file_reads(), measure_data_io() as measured:
        data = MountedGenerationStore(args.root).read_columnar_slice(
            digest, sessions=sessions, universe_name='top3000', neutralization='none',
            field_bindings=selected, fact_instrument_ids=frozenset(),
        )
        instruments = tuple(sorted(data.instruments))
        matrices = data.numeric_field_matrices(tuple(selected), instruments)
    return data, matrices, instruments, measured.snapshot()


def field(identifier):
    return {'kind': 'field', 'field_id': identifier}


def binary(operator, left, right):
    return {'kind': 'binary', 'operator': operator, 'left': left, 'right': right}


expression = binary('multiply', binary('divide', field(close), field(pe)),
                    binary('multiply', field(roe), binary('divide', field(profit), field(revenue))))
with patch('socket.socket.connect', side_effect=AssertionError('Research must remain offline')):
    _, one, instruments, one_io = read({pe: bindings[pe]})
    data, many, all_instruments, all_io = read(bindings)
    assert instruments == all_instruments
    assert all(matrix.shape == (len(instruments), len(sessions)) for matrix in many.values())
    assert np.array_equal(one[pe], many[pe], equal_nan=True)
    assert one_io['columns_scanned'] < all_io['columns_scanned']
    result = evaluate_columnar_alpha_matrix(
        data, compiled_alpha=validate_alpha(expression, field_bindings=bindings),
        neutralization='none', cancellation_check=lambda: None,
    )
    with np.errstate(divide='ignore', invalid='ignore'):
        expected = many[close] / many[pe] * (many[roe] * (many[profit] / many[revenue]))
    positions = {instrument: index for index, instrument in enumerate(instruments)}
    checked = 0
    for index, session_result in enumerate(result['sessions']):
        actual = {row['instrument_id']: row['value'] for row in session_result['values']}
        wanted = {instrument: float(expected[positions[instrument], index])
                  for instrument in data.universe_members[sessions[index]]
                  if np.isfinite(expected[positions[instrument], index])}
        assert actual.keys() == wanted.keys()
        for instrument, value in actual.items():
            assert np.isclose(value, wanted[instrument], rtol=1e-12, atol=1e-12)
        checked += len(actual)
    assert checked > 0
assert MountedDatasetHeadStore(args.root).current_pointer() == head
report = {
    'source_generation': prepared['source_generation'], 'candidate': digest,
    'status': 'offline_complete_candidate_reads_passed', 'author_field_count': len(bindings),
    'sessions': sessions, 'instrument_count': len(instruments), 'universe': 'top3000',
    'one_field_io': one_io, 'all_fields_io': all_io,
    'single_multi_pe_equal': True, 'network_connect_forbidden': True, 'head_unchanged': True,
    'mixed_source_expression': expression, 'dsl_checked_coordinates': checked,
    'dsl_checksum': result['checksum'],
    'scope': 'Actual composed candidate and DSL at nine boundary/middle dates; full coverage is separately qualified.',
}
args.output.write_text(json.dumps(report, indent=2) + '\n')
print('Complete candidate offline DSL verified', checked, 'coordinates', flush=True)
