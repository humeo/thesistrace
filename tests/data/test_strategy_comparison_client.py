from __future__ import annotations

import json
from urllib.error import URLError
from urllib.request import Request

import pytest

import thesistrace.benchmark.client as client_module
from thesistrace.benchmark import (
    INTERNAL_STRATEGY_METRIC_PATH,
    RemoteAnnualizedExcessCalculator,
    StrategyComparisonFacts,
)


class _Response:
    def __init__(self, content: bytes) -> None:
        self._content = content

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, limit: int) -> bytes:
        assert limit == 4097
        return self._content


def test_remote_calculator_posts_only_strategy_facts_and_reads_the_scalar(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: tuple[Request, float] | None = None

    def open_request(request: Request, *, timeout: float) -> _Response:
        nonlocal captured
        captured = (request, timeout)
        return _Response(b'{"annualized_excess_return":0.125}')

    monkeypatch.setattr(client_module, "urlopen", open_request)
    facts = StrategyComparisonFacts(
        entry_session="2026-08-03",
        terminal_session="2026-08-05",
        session_interval_count=2,
        initial_cash_cny="10000000",
        terminal_net_nav="10100000",
    )

    result = RemoteAnnualizedExcessCalculator(
        "http://api:8100",
        timeout_seconds=3,
    ).annualized_excess_return(facts)

    assert result == 0.125
    assert captured is not None
    request, timeout = captured
    assert request.full_url == f"http://api:8100{INTERNAL_STRATEGY_METRIC_PATH}"
    assert request.method == "POST"
    assert json.loads(request.data or b"") == {
        "entry_session": facts.entry_session,
        "terminal_session": facts.terminal_session,
        "session_interval_count": facts.session_interval_count,
        "initial_cash_cny": facts.initial_cash_cny,
        "terminal_net_nav": facts.terminal_net_nav,
    }
    assert timeout == 3


@pytest.mark.parametrize(
    "content",
    (
        b'{"annualized_excess_return":NaN}',
        b'{"annualized_excess_return":true}',
        b'{"annualized_excess_return":0,"levels":[]}',
        b"not-json",
        b"x" * 4097,
    ),
)
def test_remote_calculator_rejects_unbounded_or_non_scalar_responses(
    monkeypatch: pytest.MonkeyPatch,
    content: bytes,
) -> None:
    monkeypatch.setattr(
        client_module,
        "urlopen",
        lambda _request, *, timeout: _Response(content),
    )

    with pytest.raises(ConnectionError, match="response is invalid"):
        RemoteAnnualizedExcessCalculator("http://api:8100").annualized_excess_return(
            StrategyComparisonFacts(
                entry_session="2026-08-03",
                terminal_session="2026-08-05",
                session_interval_count=2,
                initial_cash_cny="10000000",
                terminal_net_nav="10100000",
            )
        )


@pytest.mark.parametrize(
    "origin",
    (
        "",
        "file:///tmp/api",
        "http://api:8100/prefix",
        "http://api:8100?query=1",
    ),
)
def test_remote_calculator_requires_one_plain_http_origin(origin: str) -> None:
    with pytest.raises(ValueError, match="origin is invalid"):
        RemoteAnnualizedExcessCalculator(origin)


def test_remote_calculator_reports_transport_failure_as_connection_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unavailable(_request: Request, *, timeout: float) -> _Response:
        del timeout
        raise URLError("unavailable")

    monkeypatch.setattr(client_module, "urlopen", unavailable)

    with pytest.raises(ConnectionError, match="API is unavailable"):
        RemoteAnnualizedExcessCalculator("http://api:8100").annualized_excess_return(
            StrategyComparisonFacts(
                entry_session="2026-08-03",
                terminal_session="2026-08-05",
                session_interval_count=2,
                initial_cash_cny="10000000",
                terminal_net_nav="10100000",
            )
        )
