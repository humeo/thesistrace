from __future__ import annotations

from collections.abc import Mapping

_INITIAL = (
    0x6A09E667,
    0xBB67AE85,
    0x3C6EF372,
    0xA54FF53A,
    0x510E527F,
    0x9B05688C,
    0x1F83D9AB,
    0x5BE0CD19,
)
_K = (
    0x428A2F98,
    0x71374491,
    0xB5C0FBCF,
    0xE9B5DBA5,
    0x3956C25B,
    0x59F111F1,
    0x923F82A4,
    0xAB1C5ED5,
    0xD807AA98,
    0x12835B01,
    0x243185BE,
    0x550C7DC3,
    0x72BE5D74,
    0x80DEB1FE,
    0x9BDC06A7,
    0xC19BF174,
    0xE49B69C1,
    0xEFBE4786,
    0x0FC19DC6,
    0x240CA1CC,
    0x2DE92C6F,
    0x4A7484AA,
    0x5CB0A9DC,
    0x76F988DA,
    0x983E5152,
    0xA831C66D,
    0xB00327C8,
    0xBF597FC7,
    0xC6E00BF3,
    0xD5A79147,
    0x06CA6351,
    0x14292967,
    0x27B70A85,
    0x2E1B2138,
    0x4D2C6DFC,
    0x53380D13,
    0x650A7354,
    0x766A0ABB,
    0x81C2C92E,
    0x92722C85,
    0xA2BFE8A1,
    0xA81A664B,
    0xC24B8B70,
    0xC76C51A3,
    0xD192E819,
    0xD6990624,
    0xF40E3585,
    0x106AA070,
    0x19A4C116,
    0x1E376C08,
    0x2748774C,
    0x34B0BCB5,
    0x391C0CB3,
    0x4ED8AA4A,
    0x5B9CCA4F,
    0x682E6FF3,
    0x748F82EE,
    0x78A5636F,
    0x84C87814,
    0x8CC70208,
    0x90BEFFFA,
    0xA4506CEB,
    0xBEF9A3F7,
    0xC67178F2,
)
_MASK = 0xFFFFFFFF


def empty_sha256_state() -> dict[str, object]:
    return {"words": list(_INITIAL), "buffer": "", "byte_count": 0}


def update_sha256_state(state: Mapping[str, object], payload: bytes) -> dict[str, object]:
    words = [int(value) for value in state["words"]]
    buffer = bytes.fromhex(str(state["buffer"])) + payload
    byte_count = int(state["byte_count"]) + len(payload)
    while len(buffer) >= 64:
        words = _compress(words, buffer[:64])
        buffer = buffer[64:]
    return {"words": words, "buffer": buffer.hex(), "byte_count": byte_count}


def sha256_state_hexdigest(state: Mapping[str, object]) -> str:
    byte_count = int(state["byte_count"])
    padding_length = (55 - byte_count) % 64
    finalized = update_sha256_state(
        state,
        b"\x80" + b"\x00" * padding_length + (byte_count * 8).to_bytes(8, "big"),
    )
    if finalized["buffer"] != "":
        raise ValueError("SHA-256 finalization left an incomplete block")
    return "".join(f"{int(word):08x}" for word in finalized["words"])


def _rotate_right(value: int, count: int) -> int:
    return ((value >> count) | (value << (32 - count))) & _MASK


def _compress(words: list[int], block: bytes) -> list[int]:
    schedule = [int.from_bytes(block[index : index + 4], "big") for index in range(0, 64, 4)]
    for index in range(16, 64):
        prior = schedule[index - 15]
        recent = schedule[index - 2]
        s0 = _rotate_right(prior, 7) ^ _rotate_right(prior, 18) ^ (prior >> 3)
        s1 = _rotate_right(recent, 17) ^ _rotate_right(recent, 19) ^ (recent >> 10)
        schedule.append((schedule[index - 16] + s0 + schedule[index - 7] + s1) & _MASK)
    a, b, c, d, e, f, g, h = words
    for index, constant in enumerate(_K):
        sum1 = _rotate_right(e, 6) ^ _rotate_right(e, 11) ^ _rotate_right(e, 25)
        choice = (e & f) ^ ((~e) & g)
        temporary1 = (h + sum1 + choice + constant + schedule[index]) & _MASK
        sum0 = _rotate_right(a, 2) ^ _rotate_right(a, 13) ^ _rotate_right(a, 22)
        majority = (a & b) ^ (a & c) ^ (b & c)
        temporary2 = (sum0 + majority) & _MASK
        h, g, f, e, d, c, b, a = (
            g,
            f,
            e,
            (d + temporary1) & _MASK,
            c,
            b,
            a,
            (temporary1 + temporary2) & _MASK,
        )
    return [
        (words[0] + a) & _MASK,
        (words[1] + b) & _MASK,
        (words[2] + c) & _MASK,
        (words[3] + d) & _MASK,
        (words[4] + e) & _MASK,
        (words[5] + f) & _MASK,
        (words[6] + g) & _MASK,
        (words[7] + h) & _MASK,
    ]
