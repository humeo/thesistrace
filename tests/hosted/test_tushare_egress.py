import pytest

from thesistrace.hosted.tushare_egress import (
    ALLOWED_HOST,
    ALLOWED_PORT,
    connect_authority,
)


def test_tushare_egress_accepts_only_the_pinned_connect_target() -> None:
    assert connect_authority(
        b"CONNECT api.tushare.pro:443 HTTP/1.1\r\n"
        b"Host: api.tushare.pro:443\r\n\r\n"
    ) == (ALLOWED_HOST, ALLOWED_PORT)


@pytest.mark.parametrize(
    "payload",
    [
        b"CONNECT example.com:443 HTTP/1.1\r\n\r\n",
        b"CONNECT api.tushare.pro:80 HTTP/1.1\r\n\r\n",
        b"POST https://api.tushare.pro HTTP/1.1\r\n\r\n",
        b"CONNECT api.tushare.pro:443 HTTP/2\r\n\r\n",
        b"not-http",
    ],
)
def test_tushare_egress_rejects_every_other_target(
    payload: bytes,
) -> None:
    assert connect_authority(payload) != (
        ALLOWED_HOST,
        ALLOWED_PORT,
    )
