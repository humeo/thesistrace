from __future__ import annotations

import json

import pytest

from thesistrace.adapters.tushare_provider import TushareSourceError
from thesistrace.data import DataOperatorError, DataSourceError
from thesistrace.entrypoints import data_operator


def test_data_operator_cli_preserves_tushare_failure_diagnostic(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source_failure = TushareSourceError(
        "UPSTREAM_RATE_LIMITED",
        source_code=40203,
        api_name="adj_factor",
    )
    data_failure = DataSourceError("unavailable", detail_code="UPSTREAM_RATE_LIMITED")
    data_failure.__cause__ = source_failure
    operator_failure = DataOperatorError("SOURCE_UNAVAILABLE")
    operator_failure.__cause__ = data_failure

    def fail(_arguments: list[str] | None = None) -> None:
        raise operator_failure

    monkeypatch.setattr(data_operator, "_run", fail)

    with pytest.raises(SystemExit) as failure:
        data_operator.main(["bootstrap"])

    assert failure.value.code == 2
    assert json.loads(capsys.readouterr().err) == {
        "status": "failed",
        "code": "SOURCE_UNAVAILABLE",
        "error": {
            "category": "unavailable",
            "reason_code": "UPSTREAM_RATE_LIMITED",
            "source_code": 40203,
            "api_name": "adj_factor",
        },
    }
