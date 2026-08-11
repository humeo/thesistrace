from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

import pytest

from thesistrace.adapters.tushare_provider import TushareSourceError
from thesistrace.data import DataOperatorError, DataSourceError
from thesistrace.entrypoints import data_operator


def test_bootstrap_cli_exposes_an_explicit_start_date(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exit_status:
        data_operator.main(["bootstrap", "--help"])

    assert exit_status.value.code == 0
    assert "--start-date START_DATE" in capsys.readouterr().out


def test_bootstrap_cli_passes_the_explicit_start_date_to_the_operator(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    received: dict[str, object] = {}

    class FakeDatabase:
        def __init__(self, _url: str) -> None:
            pass

        def open(self) -> None:
            pass

        def close(self) -> None:
            pass

    class FakeOperator:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def bootstrap(self, **arguments: object) -> dict[str, str]:
            received.update(arguments)
            return {"status": "succeeded"}

    monkeypatch.setenv("THESISTRACE_DATABASE_URL", "postgresql://unused")
    monkeypatch.setenv("THESISTRACE_DATA_MOUNT", str(tmp_path))
    monkeypatch.setattr(data_operator, "PostgresDatabase", FakeDatabase)
    monkeypatch.setattr(data_operator, "verify_core_migrations", lambda _database: None)
    monkeypatch.setattr(data_operator, "ReplayTushareProvider", lambda _path: object())
    monkeypatch.setattr(data_operator, "TushareDataSource", lambda *, provider: provider)
    monkeypatch.setattr(data_operator, "DataOperator", FakeOperator)

    data_operator.main(
        [
            "bootstrap",
            "--idempotency-key",
            "one-month",
            "--start-date",
            "2026-07-03",
            "--as-of",
            "2026-08-03T18:00:00+08:00",
            "--replay",
            str(tmp_path / "unused-replay.json"),
        ]
    )

    assert json.loads(capsys.readouterr().out) == {"status": "succeeded"}
    assert received == {
        "idempotency_key": "one-month",
        "start_date": date(2026, 7, 3),
        "as_of": datetime.fromisoformat("2026-08-03T18:00:00+08:00"),
    }


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
