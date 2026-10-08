"""Public numerical-program behavior, independent of the execution mechanism."""

import numpy as np
import pytest

from thesistrace.research_history import HistoryWindow
from thesistrace.research_kernel.strategy_program_assets import NUMPY_VERSION, PYTHON_VERSION
from thesistrace.research_kernel.strategy_program_runtime import (
    PythonStrategyRuntime,
    StrategyProgramError,
)

pytestmark = pytest.mark.bounded_process


@pytest.fixture(scope="module")
def runtime():
    return PythonStrategyRuntime()


def test_packaged_library_versions_match_the_admitted_environment(runtime):
    source = """import sys
import numpy as np

def decide(data, account, state):
    state.update(python='.'.join(map(str, sys.version_info[:3])), numpy=np.__version__)
"""
    assert runtime.invoke(source, context={}, state={}).state == {
        "python": PYTHON_VERSION,
        "numpy": NUMPY_VERSION,
    }


def test_strategy_uses_numpy_arrays_with_the_same_history_axes(runtime):
    source = """from quantgrove import target_weights
import numpy as np


def decide(data, account, state):
    history = data.close_prices(3, instruments=["B", "A", "C"])
    prices = history.array
    scores = prices[:, -1] / prices[:, 0] - 1
    winner = history.instruments[int(np.nanargmax(scores))]
    state.update(
        sessions=list(history.sessions),
        instruments=list(history.instruments),
        scores=scores.tolist(),
        shape=list(prices.shape),
        legacy=list(history["A"]),
        keyed_order=list(history.values),
    )
    return target_weights({winner: 1})
"""
    result = runtime.invoke(
        source,
        context={"session": "2026-08-05"},
        state={},
        read_history=lambda _: HistoryWindow(
            ("2026-08-03", "2026-08-04", "2026-08-05"),
            ("B", "A", "C"),
            np.array([[10, 11, 15], [10, 15, 20], [20, 15, 10]], dtype="<f8"),
        ),
    )
    assert result.state == {
        "sessions": ["2026-08-03", "2026-08-04", "2026-08-05"],
        "instruments": ["B", "A", "C"],
        "scores": [0.5, 1.0, -0.5],
        "shape": [3, 3],
        "legacy": [10, 15, 20],
        "keyed_order": ["A", "B", "C"],
    }
    assert result.output["allocation"]["instrument_ids"] == ["A"]
    assert result.output["allocation"]["exposure"] == 1


def test_numpy_module_mutations_and_arrays_do_not_survive_invocations(runtime):
    source = """import numpy as np
counter = np.array([0])

def decide(data, account, state):
    counter[0] += 1
    state['counter'] = int(counter[0])
    state['sum'] = float(np.sum([1.0, 2.0, 3.0]))
    state['days'] = state.get('days', 0) + 1
    np.sum = lambda *args, **kwargs: -999
    np.seterr(all='raise')
"""
    first = runtime.invoke(source, context={}, state={})
    second = runtime.invoke(source, context={}, state=first.state)
    assert second.state == {"counter": 1, "sum": 6.0, "days": 2}


def test_history_arrays_are_read_only_and_missing_values_have_both_public_views(runtime):
    source = """import numpy as np


def decide(data, account, state):
    history = data.close_prices(3)
    state["missing"] = np.isnan(history.array).tolist()
    state["values"] = list(history["A"])
    for operation in (
        lambda: history.array.__setitem__((0, 0), 99),
        lambda: history.array.setflags(write=True),
    ):
        try:
            operation()
        except ValueError:
            state["denied"] = state.get("denied", 0) + 1
    writable = history.array.copy()
    writable[0, 0] = 99
    state["original"] = float(history.array[0, 0])
"""
    result = runtime.invoke(
        source,
        context={},
        state={},
        read_history=lambda _: HistoryWindow(
            ("2026-08-03", "2026-08-04", "2026-08-05"),
            ("A",),
            np.array([[1.0, np.nan, 3.0]]),
        ),
    )
    assert result.state == {
        "missing": [[False, True, False]],
        "values": [1, None, 3],
        "denied": 2,
        "original": 1,
    }


def test_numpy_clock_and_unseeded_generators_receive_deterministic_inputs(runtime):
    source = """import numpy as np


def decide(data, account, state):
    state.update(
        now=str(np.datetime64("now")),
        today=str(np.datetime64("today")),
        default=np.random.default_rng().integers(0, 1000000, size=5).tolist(),
        legacy=np.random.randint(0, 1000000, size=5).tolist(),
        explicit=np.random.default_rng(42).integers(0, 1000000, size=5).tolist(),
    )
"""
    first = runtime.invoke(source, context={"session": "2026-08-03"}, state={})
    with_other_runtime = PythonStrategyRuntime().invoke(
        source,
        context={"session": "2026-08-03"},
        state={},
    )
    assert first == with_other_runtime
    assert first.state["now"] == "2026-08-03T07:00:00"
    assert first.state["today"] == "2026-08-03"
    changed = runtime.invoke(source, context={"session": "2026-08-04"}, state={})
    assert changed.state["default"] != first.state["default"]
    assert changed.state["explicit"] == first.state["explicit"]


def test_frozen_interpreter_preserves_the_zero_hash_seed(runtime):
    source = """import sys

def decide(data, account, state):
    state['hash_randomization'] = sys.flags.hash_randomization
    state['hashes'] = [hash(x) for x in ('A', 'equity:A.SH', 'price.close.adjusted')]
"""
    first = runtime.invoke(source, context={}, state={})
    assert first.state["hash_randomization"] == 0
    # Recorded from the previous pinned WASI interpreter with PYTHONHASHSEED=0.
    assert first.state["hashes"] == [-269909568, 1063239369, -1041973765]
    assert runtime.invoke(source, context={}, state={}) == first


def test_numpy_allocation_is_bounded_and_the_next_invocation_is_healthy(runtime):
    source = """import numpy as np

def decide(data, account, state):
    state['sum'] = float(np.ones(128 * 1024 * 1024, dtype=np.float64).sum())
"""
    with pytest.raises(StrategyProgramError):
        runtime.invoke(source, context={}, state={})
    source = source.replace("128 * 1024 * 1024", "3")
    assert runtime.invoke(source, context={}, state={}).state == {"sum": 3.0}
