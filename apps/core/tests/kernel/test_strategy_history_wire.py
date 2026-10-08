import io
import json

import numpy as np
import pytest

from thesistrace.research_history import (
    MAX_BYTES,
    HistoryWindow,
    decode_history,
    encode_history,
)


def test_history_array_round_trip_preserves_exact_numbers_missing_cells_and_axes():
    array = np.array([[10.29, -0.0, np.nan], [12.29, 1 / 3, 2**53 - 1]], dtype="<f8")
    window = HistoryWindow(("2026-08-03", "2026-08-04", "2026-08-05"), ("B", "A"), array)
    decoded = decode_history(encode_history(window))
    assert decoded.sessions == window.sessions
    assert decoded.instruments == ("B", "A")
    assert decoded.array.tobytes() == array.tobytes()
    with pytest.raises(ValueError):
        decoded.array[0, 0] = 99
    with pytest.raises(ValueError):
        decoded.array.setflags(write=True)
    copy = decoded.array.copy()
    copy[0, 0] = 99
    assert decoded.array[0, 0] == 10.29


def test_history_transfers_only_selected_cells_even_when_backing_array_has_future_rows():
    underlying = np.array([[1., 2., 987654321.], [3., 4., 876543210.]])
    selected = HistoryWindow(("2026-08-03", "2026-08-04"), ("A",), underlying[:1, :2])
    wire = encode_history(selected)
    decoded = decode_history(wire)
    assert decoded.array.tolist() == [[1, 2]]
    assert len(decoded.array.base) < underlying.nbytes + 1024
    assert np.float64(987654321.).tobytes() not in wire
    assert np.float64(876543210.).tobytes() not in wire


def test_empty_instrument_axis_retains_calendar():
    decoded = decode_history(encode_history(HistoryWindow(
        ("2026-08-03", "2026-08-04"), (), np.empty((0, 2)),
    )))
    assert decoded.sessions == ("2026-08-03", "2026-08-04")
    assert decoded.instruments == ()
    assert decoded.array.shape == (0, 2)


@pytest.mark.parametrize("array", [
    np.array([[float("inf")]]), np.array([[float("-inf")]]),
    np.array([[float(2**53)]]), np.array([["1"]], dtype=object),
    np.zeros((2, 2)),
])
def test_invalid_numeric_history_is_rejected_before_transfer(array):
    with pytest.raises(ValueError):
        encode_history(HistoryWindow(("2026-08-03",), ("A",), array))


def test_decoder_rejects_pickle_and_mismatched_axes_without_loading_objects():
    metadata = json.dumps({"sessions": ["2026-08-03"], "instruments": ["A"]}).encode() + b"\n"
    for matrix in (np.array([[{}]], dtype=object), np.ones((1, 2))):
        stream = io.BytesIO()
        np.save(stream, matrix)
        with pytest.raises(ValueError):
            decode_history(metadata + stream.getvalue())


def test_decoder_rejects_trailing_bytes_and_oversized_frames():
    wire = encode_history(HistoryWindow(("2026-08-03",), ("A",), np.ones((1, 1))))
    for invalid in (wire + b"extra", wire[:-1], b"x" * (MAX_BYTES + 1)):
        with pytest.raises(ValueError):
            decode_history(invalid)
