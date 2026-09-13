"""Bounded current-catalog projection measurement, not a production capacity claim."""
import json
import time
import tracemalloc
from datetime import date, timedelta
from pathlib import Path

import pyarrow as pa

from thesistrace.data.fields import FINANCIAL_INDICATOR_FIELDS
from thesistrace.data.financial_indicator_series import FinancialIndicatorSeriesResolver

root = Path(__file__).resolve().parent
instruments = tuple(f'stock-{i:03d}' for i in range(50))
sessions = tuple((date(2020, 1, 1)+timedelta(days=i)).isoformat() for i in range(100))
metadata = {'instrument_id', 'source_report_period', 'source_published_date',
            'state_effective_session', 'availability_status', 'observation_event_at'}
rows = [{
    'instrument_id': instrument, 'source_report_period': '20191231',
    'source_published_date': '20191231', 'state_effective_session': sessions[0],
    'availability_status': 'available', 'observation_event_at': sessions[0]+'T00:00:00+00:00',
    **{field.source_column: '15' for field in FINANCIAL_INDICATOR_FIELDS},
} for instrument in instruments]
source = pa.Table.from_pylist(rows)
results = []
for count in (1, 16, len(FINANCIAL_INDICATOR_FIELDS)):
    selected = FINANCIAL_INDICATOR_FIELDS[:count]
    observed = []
    def read(columns, selected_instruments, through):
        assert columns == metadata | {f.source_column for f in selected}
        assert selected_instruments == frozenset(instruments)
        assert through == sessions[-1]
        observed.append(sorted(columns))
        return source.select(sorted(columns))
    tracemalloc.start()
    started = time.perf_counter()
    result = FinancialIndicatorSeriesResolver('a'*64, read).resolve_table(
        manifest_sha256='a'*64, field_ids=tuple(f.field_id for f in selected),
        sessions=sessions, instrument_ids=instruments,
    )
    seconds = time.perf_counter()-started
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert result.num_rows == 5000 and result.num_columns == count+2
    for field in selected:
        expected = .15 if field.source_unit == 'percent' else 15
        assert result[field.field_id][0].as_py() == expected
        assert result[field.field_id][-1].as_py() == expected
    results.append({'requested_fields': count, 'requested_source_columns': observed,
                    'rows': result.num_rows, 'arrow_bytes': result.nbytes,
                    'python_peak_bytes': peak, 'seconds_under_tracing': seconds})
report = {'scope': '50 securities x100 daily coordinates; one sparse fact/security; current implemented fields only.',
          'limitations': 'Synthetic fixture. tracemalloc is Python allocations, not RSS; no production capacity or full-history qualification claim.',
          'indicator_catalog_count': len(FINANCIAL_INDICATOR_FIELDS), 'measurements': results}
(root/'indicator-projection-resource-evidence.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps([{k:v for k,v in x.items() if k!='requested_source_columns'} for x in results]))
