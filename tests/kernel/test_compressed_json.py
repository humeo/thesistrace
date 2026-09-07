import gzip

import pytest

from thesistrace.publication.serialization import (
    compressed_json_bytes,
    read_compressed_json_bytes,
)


def test_compressed_json_is_deterministic_and_round_trips_canonical_values():
    value = {"z": ["量化", "123.4500"], "a": 1}
    encoded = compressed_json_bytes(value)
    assert encoded == compressed_json_bytes({"a": 1, "z": ["量化", "123.4500"]})
    raw = b'{"a":1,"z":["\xe9\x87\x8f\xe5\x8c\x96","123.4500"]}'
    assert gzip.decompress(encoded) == raw
    assert read_compressed_json_bytes(encoded, len(raw)) == value


@pytest.mark.parametrize("mutation", ["truncated", "trailing", "member", "corrupt"])
def test_compressed_json_rejects_invalid_stream(mutation):
    encoded = compressed_json_bytes({"a": 1})
    changed = {
        "truncated": encoded[:-1],
        "trailing": encoded + b"extra",
        "member": encoded + encoded,
        "corrupt": encoded[:-8] + b"\0" * 8,
    }[mutation]
    with pytest.raises(ValueError):
        read_compressed_json_bytes(changed, 7)


@pytest.mark.parametrize("length", [0, 6, 8, True, 64 * 1024**2 + 1])
def test_compressed_json_rejects_invalid_decoded_size(length):
    with pytest.raises(ValueError):
        read_compressed_json_bytes(compressed_json_bytes({"a": 1}), length)


def test_compressed_json_rejects_noncanonical_content_and_expansion():
    for raw, size in [(b'{ "a":1}', 8), (b"x" * 100_000, 10)]:
        with pytest.raises(ValueError):
            read_compressed_json_bytes(gzip.compress(raw, mtime=0), size)


@pytest.mark.parametrize("media,descriptor", [
    ("application/json", {"format": "canonical-json-gzip", "version": 1, "uncompressed_bytes": 7}),
    ("application/gzip", {"format": "canonical-json", "version": 1, "uncompressed_bytes": 7}),
    ("application/gzip", {"format": "canonical-json-gzip", "version": 2, "uncompressed_bytes": 7}),
    ("application/gzip",
     {"format": "canonical-json-gzip", "version": True, "uncompressed_bytes": 7}),
    ("application/gzip", {"format": "canonical-json-gzip", "version": 1}),
])
def test_public_decoder_rejects_unknown_encoding(media, descriptor):
    from thesistrace.publication import (
        PublicationVerificationError,
        VerifiedPayload,
        decode_compressed_json,
    )

    payload = VerifiedPayload(media, compressed_json_bytes({"a": 1}), descriptor)
    with pytest.raises(PublicationVerificationError):
        decode_compressed_json(payload)
