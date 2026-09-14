"""Normalize TuShare indicator requests at the external source boundary."""

from collections.abc import Mapping, Sequence

from thesistrace.adapters.tushare_financial import RawTushareProvider
from thesistrace.adapters.tushare_provider import TushareSourceError, tushare_source_error_category
from thesistrace.data.source import DataSourceError, RawSourceResponse


class TushareFinancialIndicatorProvider:
    def __init__(self, provider: RawTushareProvider) -> None:
        self._provider = provider

    def query_raw(
        self, api_name: str, *, params: Mapping[str, object], fields: Sequence[str],
    ) -> RawSourceResponse:
        try:
            return self._provider.query_raw(api_name, params=params, fields=fields)
        except TushareSourceError as error:
            raise DataSourceError(
                tushare_source_error_category(error.reason_code), detail_code=error.reason_code,
            ) from error
