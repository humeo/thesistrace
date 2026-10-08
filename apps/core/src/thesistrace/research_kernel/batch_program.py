"""One numerical block shared by direct and composed Python strategy Adapters."""

import numpy as np

from thesistrace.research_kernel.direct_strategy import program_history
from thesistrace.research_kernel.program_wire import array_from_wire, array_to_wire


def current_values(context, values, instruments, column):
    visible = {row["instrument_id"] for row in context["candidates"]} | {
        row["instrument_id"] for row in context["account"]["positions"]
    }
    selected = [index for index, stock in enumerate(instruments) if stock in visible]
    context["value_instruments"] = [instruments[index] for index in selected]
    context["values"] = {
        name: array_to_wire(
            value[selected, column] if value.ndim == 2 else value[column],
        )
        for name, value in values.items()
    }


class PreparedProgramBlock:
    def __init__(self, data, program, runtime, sessions, first_session_index):
        self._data, self._program, self._runtime = data, program, runtime
        self._sessions, self._first_index = tuple(sessions), first_session_index
        self._block = None
        self.entrypoints = runtime.validate(program.source)

    def compute(self, session, state, account):
        block = self._evaluate(session, state, account, 128)
        dates, instruments, output, _ = block
        # These checks detect sampled lookahead; they are not a proof for arbitrary Python.
        for count in sorted({1, len(dates) // 2} - {0, len(dates)}):
            _, prefix_ids, prefix, _ = self._evaluate(session, state, account, count)
            rows = [instruments.index(stock) for stock in prefix_ids]
            if output["kind"] == "targets":
                consistent = (
                    output["equal"] == prefix["equal"]
                    and output["reason"] == prefix["reason"]
                    and np.array_equal(output["update"][:count], prefix["update"])
                    and np.array_equal(output["weights"][rows, :count], prefix["weights"])
                )
                if (output["priority"] is None) != (prefix["priority"] is None):
                    consistent = False
                elif output["priority"] is not None:
                    consistent &= np.array_equal(
                        output["priority"][rows, :count], prefix["priority"], equal_nan=True
                    )
            else:
                consistent = output["values"].keys() == prefix["values"].keys()
                for name, value in prefix["values"].items():
                    original = output["values"].get(name)
                    if original is None or original.ndim != value.ndim:
                        consistent = False
                        break
                    observed = original[rows, :count] if value.ndim == 2 else original[:count]
                    consistent &= np.array_equal(observed, value, equal_nan=True)
            if not consistent:
                raise ValueError(
                    f"compute prefix check differs through {dates[count - 1]}; "
                    "avoid future observations and block-relative business rules"
                )
        return block

    def _evaluate(self, session, state, account, count):
        start = self._sessions.index(session)
        sessions = self._sessions[start : start + count]
        instruments = tuple(
            sorted(
                set().union(
                    *(set(self._data.universe_members[day]) for day in sessions),
                    {row["instrument_id"] for row in account["positions"]},
                )
            )
        )
        context = {
            "session": sessions[-1],
            "random_seed": self._program.source_sha256,
            "block": {
                "sessions": list(sessions),
                "instruments": list(instruments),
                "session_index": list(
                    range(self._first_index + start, self._first_index + start + len(sessions))
                ),
                "eligible": array_to_wire(
                    np.array(
                        [
                            [stock in self._data.universe_members[day] for day in sessions]
                            for stock in instruments
                        ],
                        dtype=bool,
                    ).reshape(len(instruments), len(sessions))
                ),
            },
        }
        read_context = {
            "session": sessions[-1],
            "candidates": [{"instrument_id": stock} for stock in instruments],
            "account": {"positions": []},
        }
        result = self._runtime.invoke(
            self._program.source,
            context=context,
            state=state,
            operation="compute",
            read_history=program_history(
                self._data,
                read_context,
                max_sessions=380,
                max_cells=2_097_152,
                total_cells=4_194_304,
            ),
        )
        output = result.output
        if not isinstance(output, dict):
            raise ValueError("compute must return Targets or Values")
        expected_kind = "values" if self.entrypoints["decide"] else "targets"
        if output.get("kind") != expected_kind:
            raise ValueError(f"compute must return {expected_kind}")
        if output.get("kind") == "targets":
            if set(output) != {"kind", "weights", "update", "priority", "equal", "reason"}:
                raise ValueError("Invalid Targets envelope")
            weights, update = array_from_wire(output["weights"]), array_from_wire(output["update"])
            if (
                weights.shape != (len(instruments), len(sessions))
                or update.shape != (len(sessions),)
                or update.dtype != np.dtype(bool)
                or type(output["equal"]) is not bool
                or type(output["reason"]) is not str
                or not np.isfinite(weights).all()
                or (weights < 0).any()
                or (output["equal"] and weights.dtype != np.dtype(bool))
            ):
                raise ValueError(
                    "Targets require finite nonnegative weights and aligned boolean updates"
                )
            priority = None
            if output["priority"] is not None:
                encoded = output["priority"]
                if type(encoded) is not dict or set(encoded) != {"indices", "values"}:
                    raise ValueError("Invalid Targets priority envelope")
                indices = array_from_wire(encoded["indices"])
                values = array_from_wire(encoded["values"])
                if (
                    indices.dtype != np.dtype("uint32")
                    or indices.ndim != 1
                    or values.shape != indices.shape
                    or values.dtype.kind not in "fiu"
                    or not np.isfinite(values).all()
                    or not np.array_equal(indices, np.flatnonzero(weights > 0))
                ):
                    raise ValueError(
                        "Targets priority must align with weights and be finite for selections"
                    )
                priority = np.zeros(weights.shape, dtype=values.dtype)
                priority.ravel()[indices] = values
            output = {**output, "weights": weights, "update": update, "priority": priority}
        elif output.get("kind") == "values":
            if set(output) != {"kind", "values"} or type(output["values"]) is not dict:
                raise ValueError("Invalid Values envelope")
            values = {name: array_from_wire(value) for name, value in output["values"].items()}
            if any(
                type(name) is not str
                or not name
                or len(name) > 200
                or value.shape not in {(len(sessions),), (len(instruments), len(sessions))}
                or np.isinf(value).any()
                for name, value in values.items()
            ):
                raise ValueError("Values must align with the output dates and contain no infinity")
            output = {"kind": "values", "values": values}
        else:
            raise ValueError("Unknown batch output")
        self._block = (sessions, instruments, output, result)

        return self._block
