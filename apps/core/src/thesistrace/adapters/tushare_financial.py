from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol

from thesistrace.adapters.tushare_provider import TushareSourceError
from thesistrace.data.source import RawSourceResponse

_FINANCIAL_PAGE_SIZE = 100
_MAX_FINANCIAL_PAGES = 100


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

    Tushare financial endpoints can cap a response at 100 rows even when one
    instrument has more history. The source adapter owns provider pagination
    so the Data collection checkpoint remains one ``endpoint x instrument``
    logical shard.
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
        if "limit" in params or "offset" in params:
            raise TushareSourceError(
                "INVALID_FINANCIAL_PAGINATION_REQUEST",
                source_code=0,
                api_name=api_name,
            )
        if api_name == "balancesheet":
            return self._complete_response(
                api_name,
                params=params,
                fields=fields,
            )
        initial = self._provider.query_raw(api_name, params=params, fields=fields)
        if len(initial.items) != _FINANCIAL_PAGE_SIZE:
            return initial
        return self._complete_response(
            api_name,
            params=params,
            fields=fields,
            initial=initial,
        )

    def _complete_response(
        self,
        api_name: str,
        *,
        params: Mapping[str, object],
        fields: Sequence[str],
        initial: RawSourceResponse | None = None,
    ) -> RawSourceResponse:
        response_fields = initial.fields if initial is not None else None
        items = list(initial.items) if initial is not None else []
        full_pages = [initial.items] if initial is not None else []
        first_page = 1 if initial is not None else 0
        for page_number in range(first_page, _MAX_FINANCIAL_PAGES):
            offset = page_number * _FINANCIAL_PAGE_SIZE
            page = self._provider.query_raw(
                api_name,
                params={
                    **params,
                    "limit": _FINANCIAL_PAGE_SIZE,
                    "offset": offset,
                },
                fields=fields,
            )
            if len(page.items) > _FINANCIAL_PAGE_SIZE:
                raise self._pagination_error(api_name, "INVALID_RESPONSE")
            if response_fields is None:
                response_fields = page.fields
            elif page.fields != response_fields:
                raise self._pagination_error(api_name, "INVALID_RESPONSE")
            if len(page.items) == _FINANCIAL_PAGE_SIZE:
                if page.items in full_pages:
                    raise self._pagination_error(api_name, "PAGINATION_STALLED")
                full_pages.append(page.items)
            items.extend(page.items)
            if len(page.items) < _FINANCIAL_PAGE_SIZE:
                assert response_fields is not None
                return RawSourceResponse(response_fields, tuple(items))
        raise self._pagination_error(api_name, "PAGINATION_LIMIT_EXCEEDED")

    @staticmethod
    def _pagination_error(api_name: str, code: str) -> TushareSourceError:
        return TushareSourceError(code, source_code=0, api_name=api_name)


__all__ = ("TushareFinancialSource",)
