from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol

from thesistrace.adapters.tushare_provider import TushareSourceError
from thesistrace.data.source import RawSourceResponse

_BALANCESHEET_PAGE_SIZE = 100
_MAX_BALANCESHEET_PAGES = 100


class RawTushareProvider(Protocol):
    def query_raw(
        self,
        api_name: str,
        *,
        params: Mapping[str, object],
        fields: Sequence[str],
    ) -> RawSourceResponse: ...


class TushareFinancialSource:
    """Ordinary financial statements as complete logical responses.

    Tushare's ordinary balance-sheet endpoint caps a response at 100 rows even
    when one instrument has more history. The source adapter owns the provider
    pagination so the Data collection checkpoint remains one
    ``endpoint x instrument`` logical shard.
    """

    def __init__(self, provider: RawTushareProvider) -> None:
        self._provider = provider

    def query_raw(
        self,
        api_name: str,
        *,
        params: Mapping[str, object],
        fields: Sequence[str],
    ) -> RawSourceResponse:
        if api_name != "balancesheet":
            return self._provider.query_raw(api_name, params=params, fields=fields)
        if "limit" in params or "offset" in params:
            raise TushareSourceError(
                "INVALID_FINANCIAL_PAGINATION_REQUEST",
                source_code=0,
                api_name=api_name,
            )
        return self._complete_balancesheet(params=params, fields=fields)

    def _complete_balancesheet(
        self,
        *,
        params: Mapping[str, object],
        fields: Sequence[str],
    ) -> RawSourceResponse:
        response_fields: tuple[str, ...] | None = None
        items: list[tuple[object, ...]] = []
        full_pages: list[tuple[tuple[object, ...], ...]] = []
        for page_number in range(_MAX_BALANCESHEET_PAGES):
            offset = page_number * _BALANCESHEET_PAGE_SIZE
            page = self._provider.query_raw(
                "balancesheet",
                params={
                    **params,
                    "limit": _BALANCESHEET_PAGE_SIZE,
                    "offset": offset,
                },
                fields=fields,
            )
            if len(page.items) > _BALANCESHEET_PAGE_SIZE:
                raise self._pagination_error("INVALID_RESPONSE")
            if response_fields is None:
                response_fields = page.fields
            elif page.fields != response_fields:
                raise self._pagination_error("INVALID_RESPONSE")
            if len(page.items) == _BALANCESHEET_PAGE_SIZE:
                if page.items in full_pages:
                    raise self._pagination_error("PAGINATION_STALLED")
                full_pages.append(page.items)
            items.extend(page.items)
            if len(page.items) < _BALANCESHEET_PAGE_SIZE:
                assert response_fields is not None
                return RawSourceResponse(response_fields, tuple(items))
        raise self._pagination_error("PAGINATION_LIMIT_EXCEEDED")

    @staticmethod
    def _pagination_error(code: str) -> TushareSourceError:
        return TushareSourceError(code, source_code=0, api_name="balancesheet")


__all__ = ("TushareFinancialSource",)
