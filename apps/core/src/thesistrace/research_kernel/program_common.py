"""Python reads share the formula engine's point-in-time market aggregation."""

import numpy as np

from thesistrace.research_history import HistoryWindow
from thesistrace.research_kernel.common_inputs import COMMON_INPUTS, validate_common_reference
from thesistrace.research_kernel.common_market import compute_common_market_series


def common_identity(field_id):
    parts = field_id.removeprefix("common.").split(":")
    if len(parts) > 2:
        raise ValueError("Invalid common input")
    return validate_common_reference(
        {
            "kind": "common",
            "identifier": parts[0],
            "industry_code": parts[1] if len(parts) == 2 else None,
        }
    )


def common_window(data, *, session, days, reference, max_cells):
    end = data.sessions.index(session) + 1
    sessions = data.sessions[max(0, end - days - 1) : end]
    instruments = tuple(
        sorted(set().union(*(set(data.historical_universe_members[day]) for day in sessions)))
    )
    cells = len(instruments) * len(sessions)
    if cells > max_cells:
        raise ValueError("Common history cell budget exceeded")
    if hasattr(data, "numeric_field_matrices"):
        from thesistrace.research_series import slice_research_sessions

        scoped = slice_research_sessions(data, sessions)
        closes = scoped.numeric_field_matrices(("price.close.adjusted",), instruments)[
            "price.close.adjusted"
        ]
    else:
        field = data.fields["price.close.adjusted"]
        closes = np.asarray(
            [[field.get((day, stock)) for day in sessions] for stock in instruments],
            dtype=np.float64,
        ).reshape(len(instruments), len(sessions))
    common = compute_common_market_series(
        sessions=tuple(sessions),
        instruments=instruments,
        adjusted_close=closes,
        universe_members=data.historical_universe_members,
        industries=data.industries,
        industry_code=reference["industry_code"],
    )
    dates = tuple(sessions[-days:])
    values = getattr(common, COMMON_INPUTS[reference["identifier"]][0])[-len(dates) :]
    return HistoryWindow(dates, (reference["identifier"],), values.reshape(1, -1)), cells
