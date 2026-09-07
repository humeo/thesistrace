from __future__ import annotations

import json
import math
from dataclasses import asdict
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen

from thesistrace.benchmark.comparison import (
    StrategyComparisonError,
    StrategyComparisonFacts,
)

INTERNAL_STRATEGY_METRIC_PATH = "/internal/strategy-comparison/annualized-excess"


class AnnualizedExcessCalculator(Protocol):
    def annualized_excess_return(
        self,
        facts: StrategyComparisonFacts,
    ) -> float | None: ...


class RemoteAnnualizedExcessCalculator:
    def __init__(self, api_origin: str, *, timeout_seconds: float = 10) -> None:
        parsed = urlsplit(api_origin)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
            or timeout_seconds <= 0
        ):
            raise ValueError("Internal API origin is invalid")
        self._url = urlunsplit(
            (
                parsed.scheme,
                parsed.netloc,
                INTERNAL_STRATEGY_METRIC_PATH,
                "",
                "",
            )
        )
        self._timeout_seconds = timeout_seconds

    def annualized_excess_return(
        self,
        facts: StrategyComparisonFacts,
    ) -> float | None:
        request = Request(
            self._url,
            data=json.dumps(asdict(facts), separators=(",", ":")).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                content = response.read(4097)
        except HTTPError as error:
            if error.code == 422:
                raise StrategyComparisonError(
                    "Strategy comparison facts were rejected"
                ) from error
            raise ConnectionError("Strategy comparison API is unavailable") from error
        except (OSError, URLError) as error:
            raise ConnectionError("Strategy comparison API is unavailable") from error
        if len(content) > 4096:
            raise ConnectionError("Strategy comparison API response is invalid")
        try:
            value = json.loads(content)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ConnectionError("Strategy comparison API response is invalid") from error
        if not isinstance(value, dict) or set(value) != {"annualized_excess_return"}:
            raise ConnectionError("Strategy comparison API response is invalid")
        metric = value["annualized_excess_return"]
        if metric is None:
            return None
        if isinstance(metric, bool) or not isinstance(metric, (int, float)):
            raise ConnectionError("Strategy comparison API response is invalid")
        result = float(metric)
        if not math.isfinite(result):
            raise ConnectionError("Strategy comparison API response is invalid")
        return result


__all__ = (
    "AnnualizedExcessCalculator",
    "INTERNAL_STRATEGY_METRIC_PATH",
    "RemoteAnnualizedExcessCalculator",
)
