from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol

from thesistrace.adapters.tushare_provider import (
    TushareSourceError,
    tushare_source_error_category,
)
from thesistrace.benchmark import (
    BENCHMARK_SOURCE_API_NAME,
    BENCHMARK_SOURCE_FIELDS,
    BENCHMARK_TS_CODE,
    BenchmarkLevel,
)
from thesistrace.data.source import DataSourceError, RawSourceResponse

_PAGE_SIZE = 5_000


class RawTushareBenchmarkProvider(Protocol):
    def query_raw(
        self,
        api_name: str,
        *,
        params: Mapping[str, object],
        fields: Sequence[str],
    ) -> RawSourceResponse: ...


class TushareBenchmarkSource:
    def __init__(self, provider: RawTushareBenchmarkProvider) -> None:
        self._provider = provider

    def collect_open_levels(
        self,
        *,
        start_session: str,
        end_session: str,
    ) -> tuple[BenchmarkLevel, ...]:
        rows: list[dict[str, object]] = []
        offset = 0
        try:
            while True:
                response = self._provider.query_raw(
                    BENCHMARK_SOURCE_API_NAME,
                    params={
                        "ts_code": BENCHMARK_TS_CODE,
                        "start_date": start_session.replace("-", ""),
                        "end_date": end_session.replace("-", ""),
                        "limit": _PAGE_SIZE,
                        "offset": offset,
                    },
                    fields=BENCHMARK_SOURCE_FIELDS,
                )
                page = [dict(zip(response.fields, item, strict=True)) for item in response.items]
                rows.extend(page)
                if len(page) < _PAGE_SIZE:
                    break
                offset += _PAGE_SIZE
        except TushareSourceError as error:
            raise DataSourceError(
                tushare_source_error_category(error.reason_code),
                detail_code=error.reason_code,
            ) from error
        except (KeyError, TypeError, ValueError) as error:
            raise DataSourceError(
                "invalid_source_data",
                detail_code="MALFORMED_BENCHMARK_PROVIDER_PAYLOAD",
            ) from error
        levels: list[BenchmarkLevel] = []
        seen: set[str] = set()
        try:
            for row in rows:
                if row.get("ts_code") != BENCHMARK_TS_CODE:
                    raise ValueError("unexpected benchmark identity")
                raw_session = str(row["trade_date"])
                if len(raw_session) != 8 or not raw_session.isdigit():
                    raise ValueError("invalid benchmark session")
                session = f"{raw_session[:4]}-{raw_session[4:6]}-{raw_session[6:]}"
                if session in seen:
                    raise DataSourceError(
                        "invalid_source_data",
                        detail_code="DUPLICATE_BENCHMARK_LEVEL",
                    )
                seen.add(session)
                levels.append(BenchmarkLevel(session=session, open_level=str(row["open"])))
        except DataSourceError:
            raise
        except (KeyError, TypeError, ValueError) as error:
            raise DataSourceError(
                "invalid_source_data",
                detail_code="MALFORMED_BENCHMARK_PROVIDER_PAYLOAD",
            ) from error
        return tuple(sorted(levels, key=lambda level: level.session))


__all__ = ("TushareBenchmarkSource",)
