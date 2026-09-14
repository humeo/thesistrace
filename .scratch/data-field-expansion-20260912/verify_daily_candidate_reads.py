"""Reopen the real daily candidate without networking and compare projected reads."""
import argparse
import json
from pathlib import Path
from unittest.mock import patch

import numpy as np

from thesistrace.data.fields import DAILY_BASIC_FIELDS, MARKET_FIELDS
from thesistrace.data.generation_store import GenerationStoreError, MountedGenerationStore
from thesistrace.data.head_store import MountedDatasetHeadStore
from thesistrace.data.io_metrics import cold_file_reads, measure_data_io

parser = argparse.ArgumentParser()
parser.add_argument('--root', type=Path, required=True)
parser.add_argument('--candidate', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
prepared = json.loads(args.candidate.read_text())
digest = prepared['candidate']['manifest_sha256']
source = prepared['source_generation']
store = MountedGenerationStore(args.root)
head = MountedDatasetHeadStore(args.root).current_pointer()
descriptor = store.inspect_root(digest)
calendar = descriptor.research_sessions
middle = len(calendar) // 2
sessions = sorted(set((*calendar[:3], *calendar[middle:middle + 3], *calendar[-3:])))
pe = next(field.field_id for field in DAILY_BASIC_FIELDS if field.alpha.identifier == 'pe')
all_fields = (*MARKET_FIELDS, *DAILY_BASIC_FIELDS)
all_bindings = {field.field_id: field.alpha.identifier for field in all_fields}


def read(root, bindings):
    with cold_file_reads(), measure_data_io() as measurement:
        data = MountedGenerationStore(args.root).read_columnar_slice(
            root, sessions=sessions, universe_name='top3000', neutralization='none',
            field_bindings=bindings, fact_instrument_ids=frozenset(),
        )
        instruments = tuple(sorted(data.instruments))
        matrices = data.numeric_field_matrices(tuple(bindings), instruments)
    return matrices, instruments, measurement.snapshot()


with patch('socket.socket.connect', side_effect=AssertionError('Offline reads must not network')):
    one, instruments, one_io = read(digest, {pe: 'pe'})
    many, many_instruments, many_io = read(digest, all_bindings)
    assert instruments == many_instruments
    assert np.array_equal(one[pe], many[pe], equal_nan=True)
    assert one_io['columns_scanned'] < many_io['columns_scanned']
    original_bindings = {field.field_id: field.alpha.identifier for field in MARKET_FIELDS}
    old_prices, old_instruments, old_io = read(source, original_bindings)
    assert old_instruments == instruments
    for field_id in original_bindings:
        assert np.array_equal(old_prices[field_id], many[field_id], equal_nan=True), field_id
    try:
        read(source, {pe: 'pe'})
    except GenerationStoreError:
        pass
    else:
        raise AssertionError('Source Generation unexpectedly admitted the absent daily family')
    with np.errstate(divide='ignore', invalid='ignore'):
        mixed = many['price.close.raw'] / many[pe]
    assert np.isfinite(mixed).any()

assert MountedDatasetHeadStore(args.root).current_pointer() == head
report = {
    'source_generation': source, 'candidate': digest, 'status': 'offline_daily_reads_passed',
    'sessions': sessions, 'universe': 'top3000', 'instrument_count': len(instruments),
    'fields_read': sorted(all_bindings), 'one_field_io': one_io, 'all_market_fields_io': many_io,
    'original_price_io': old_io, 'original_price_fields_equal': sorted(original_bindings),
    'pe_single_and_multi_equal': True, 'source_rejects_daily_fields': True,
    'network_connect_forbidden': True, 'head_unchanged': True,
    'mixed_price_daily_finite_coordinates': int(np.isfinite(mixed).sum()),
    'scope': 'Actual full-history candidate read at nine boundary/middle sessions; full source coverage is separately qualified.',
}
args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
print('Offline daily candidate reads passed', len(instruments), 'instruments', flush=True)
