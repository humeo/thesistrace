"""Read-only live diagnostic; never imports the DB or submits a Refresh.

Run the installed AKShare function with its original parameters and transport.
The only experimental variable is bounded retries of the same failing request.
JSON is inspected for diagnostics before AKShare reads the same response again.
No response bodies, cookies, auth headers, or environment values are logged.
"""

from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import math
import re
import time
from datetime import UTC, date, datetime
from threading import Event
from urllib.parse import urlsplit

import akshare
import requests
from akshare.stock_feature import stock_disclosure_cninfo as cninfo

RETRYABLE = (
    requests.exceptions.Timeout,
    requests.exceptions.ConnectionError,
    requests.exceptions.JSONDecodeError,
)


def emit(event: str, **fields: object) -> None:
    print(
        json.dumps(
            {
                "probe": "cninfo-discovery",
                "at": datetime.now(UTC).isoformat(),
                "event": event,
                **fields,
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
        flush=True,
    )


def safe_error(error: Exception) -> dict[str, str]:
    message = re.sub(r"(?i)(https?://)[^/@\s]+@", r"\1<REDACTED>@", str(error))
    message = re.sub(
        r"(?i)(token|password|authorization|cookie|api_key)([=:]\s*)[^\s,;]+",
        r"\1\2<REDACTED>",
        message,
    )
    return {
        "exception_type": f"{type(error).__module__}.{type(error).__name__}",
        "exception_message": message[:600],
    }


class ProbeLimitError(RuntimeError):
    pass


class ObservedRequests:
    def __init__(self, original: object, args: argparse.Namespace) -> None:
        self.original = original
        self.args = args
        self.started = time.monotonic()
        self.requests = 0
        self.failures = 0
        self.recovered_requests = 0
        self.query_calls = 0
        self.pages: set[int] = set()
        self.expected_rows: int | None = None

    def get(self, url: str, **kwargs: object) -> requests.Response:
        return self.call("get", url, kwargs)

    def post(self, url: str, **kwargs: object) -> requests.Response:
        return self.call("post", url, kwargs)

    def call(self, method: str, url: str, kwargs: dict[str, object]) -> requests.Response:
        parsed = urlsplit(url)
        if parsed.hostname != "www.cninfo.com.cn" or parsed.path not in {
            "/new/data/szse_stock.json",
            "/new/hisAnnouncement/query",
        }:
            raise ValueError("PROBE_ENDPOINT_NOT_ALLOWED")
        is_query = parsed.path.endswith("/query")
        if is_query:
            self.query_calls += 1
        phase = (
            "count"
            if is_query and self.query_calls == 1
            else ("page" if is_query else "stock_metadata")
        )
        payload = kwargs.get("data", {})
        page = int(payload["pageNum"]) if is_query else None
        kwargs.setdefault("timeout", 30)
        context = {
            "method": method.upper(),
            "path": parsed.path,
            "phase": phase,
            "page": page,
            "logical_query": self.query_calls if is_query else None,
        }
        for attempt in range(1, self.args.max_attempts + 1):
            if (
                self.requests >= self.args.max_requests
                or time.monotonic() - self.started >= self.args.max_seconds
            ):
                raise ProbeLimitError("PROBE_REQUEST_OR_TIME_BUDGET_EXHAUSTED")
            self.requests += 1
            started = time.monotonic()
            details: dict[str, object] = {}
            response = None
            try:
                response = getattr(self.original, method)(url, **kwargs)
                details = {
                    "http_status": response.status_code,
                    "content_type": response.headers.get("Content-Type"),
                    "body_bytes": len(response.content),
                    "body_sha256": hashlib.sha256(response.content).hexdigest(),
                    "retry_after": response.headers.get("Retry-After"),
                }
                body = response.json()
                if is_query:
                    total = int(body["totalAnnouncement"])
                    rows = body.get("announcements") or []
                    details.update(total_announcements=total, page_rows=len(rows))
                    if self.expected_rows is None:
                        self.expected_rows = total
                    elif total != self.expected_rows:
                        raise ValueError("CNINFO_TOTAL_CHANGED_DURING_PAGINATION")
                    if phase == "page":
                        self.pages.add(page)
            except Exception as error:
                self.failures += 1
                will_retry = isinstance(error, RETRYABLE) and attempt < self.args.max_attempts
                delay = float(2 ** (attempt - 1))
                if response is not None:
                    retry_after = response.headers.get("Retry-After", "")
                    if retry_after:
                        if retry_after.isdigit() and int(retry_after) <= 30:
                            delay = max(delay, float(retry_after))
                        else:
                            will_retry = False
                    response.close()
                emit(
                    "request_failed",
                    **context,
                    **details,
                    **safe_error(error),
                    attempt=attempt,
                    request_number=self.requests,
                    elapsed_ms=round((time.monotonic() - started) * 1000),
                    will_retry=will_retry,
                    retry_delay_seconds=delay if will_retry else None,
                )
                if not will_retry:
                    raise
                # Bounded retry backoff, not a test synchronization sleep.
                Event().wait(delay)
                continue
            emit(
                "request_succeeded",
                **context,
                **details,
                attempt=attempt,
                request_number=self.requests,
                elapsed_ms=round((time.monotonic() - started) * 1000),
            )
            if attempt > 1:
                self.recovered_requests += 1
            return response
        raise AssertionError("unreachable")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default="2026-08-08")
    parser.add_argument("--end", default="2026-08-17")
    parser.add_argument("--max-attempts", type=int, choices=(1, 3), default=1)
    parser.add_argument("--max-requests", type=int, default=100)
    parser.add_argument("--max-seconds", type=int, default=240)
    args = parser.parse_args()
    if date.fromisoformat(args.start) > date.fromisoformat(args.end):
        parser.error("start must not exceed end")
    query = {
        "symbol": "",
        "market": "沪深京",
        "category": "半年报",
        "start_date": args.start.replace("-", ""),
        "end_date": args.end.replace("-", ""),
    }
    original = cninfo.requests
    probe = ObservedRequests(original, args)
    emit(
        "probe_started",
        query=query,
        max_attempts=args.max_attempts,
        max_requests=args.max_requests,
        max_seconds=args.max_seconds,
        akshare_version=akshare.__version__,
        requests_version=requests.__version__,
        source_sha256=hashlib.sha256(
            inspect.getsource(cninfo.stock_zh_a_disclosure_report_cninfo).encode()
        ).hexdigest(),
    )
    cninfo.requests = probe
    try:
        frame = cninfo.stock_zh_a_disclosure_report_cninfo(**query)
        expected_pages = math.ceil(probe.expected_rows / 30)
        if probe.pages != set(range(1, expected_pages + 1)) or len(frame) != probe.expected_rows:
            raise ValueError("CNINFO_INCOMPLETE_PAGINATION")
        records = frame.to_dict(orient="records")
        ordered = sorted(
            json.dumps(row, ensure_ascii=False, sort_keys=True, default=str) for row in records
        )
        emit(
            "probe_succeeded",
            **summary(probe),
            announcements=len(frame),
            companies=int(frame["代码"].nunique()),
            result_sha256=hashlib.sha256("\n".join(ordered).encode()).hexdigest(),
        )
        return 0
    except Exception as error:
        emit("probe_failed", **summary(probe), **safe_error(error))
        return 1
    finally:
        cninfo.requests = original


def summary(probe: ObservedRequests) -> dict[str, object]:
    return {
        "max_attempts": probe.args.max_attempts,
        "requests": probe.requests,
        "failed_requests": probe.failures,
        "recovered_requests": probe.recovered_requests,
        "pages_completed": len(probe.pages),
        "expected_announcements": probe.expected_rows,
        "elapsed_seconds": round(time.monotonic() - probe.started, 3),
    }


if __name__ == "__main__":
    raise SystemExit(main())
