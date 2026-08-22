from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from thesistrace.adapters.tushare_provider import TushareSourceError
from thesistrace.data import (
    DataOperatorError,
    DataSourceError,
    FinancialCollectionError,
)
from thesistrace.entrypoints import data_operator


def test_bootstrap_cli_exposes_an_explicit_start_date(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exit_status:
        data_operator.main(["bootstrap", "--help"])

    assert exit_status.value.code == 0
    assert "--start-date START_DATE" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        (
            "probe-financial",
            ("--reference-instrument", "--comparison-shard"),
        ),
        (
            "collect-financial",
            ("--generation-manifest-sha256", "--capability-report"),
        ),
        (
            "bootstrap-financial",
            (
                "--generation-manifest-sha256",
                "--capability-report",
                "--observation-through-session",
            ),
        ),
    ],
)
def test_private_financial_operator_exposes_explicit_contract_inputs(
    capsys: pytest.CaptureFixture[str],
    command: str,
    expected: tuple[str, ...],
) -> None:
    with pytest.raises(SystemExit) as exit_status:
        data_operator.main([command, "--help"])

    assert exit_status.value.code == 0
    output = capsys.readouterr().out
    assert all(item in output for item in expected)
    if command in {"collect-financial", "bootstrap-financial"}:
        assert "--date-shard" not in output


def test_private_daily_financial_operator_has_only_current_head_inputs(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as refresh_exit:
        data_operator.main(["refresh-financial", "--help"])

    assert refresh_exit.value.code == 0
    refresh_help = capsys.readouterr().out
    assert "--idempotency-key" in refresh_help
    assert "--observation-through-session" in refresh_help
    assert "--generation-manifest-sha256" not in refresh_help
    assert "--capability-report" not in refresh_help
    assert "--prior-candidate-manifest-sha256" not in refresh_help
    assert "--replay" not in refresh_help

    with pytest.raises(SystemExit) as inspect_exit:
        data_operator.main(["inspect-financial-refresh", "--help"])

    assert inspect_exit.value.code == 0
    inspect_help = capsys.readouterr().out
    assert "--idempotency-key" in inspect_help
    assert "--observation-through-session" not in inspect_help


def test_daily_financial_operator_wires_live_discovery_and_current_head_service(
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

    class FakeTransport:
        def close(self) -> None:
            pass

    class FakeService:
        def __init__(
            self,
            database: object,
            mount_root: Path,
            announcement_source: object,
            financial_source: object,
            *,
            progress: object,
        ) -> None:
            received.update(
                database=database,
                mount_root=mount_root,
                announcement_source=announcement_source,
                financial_source=financial_source,
                progress=progress,
            )

        def publish(self, **arguments: object) -> object:
            received.update(arguments)
            return SimpleNamespace(
                idempotency_key="daily-live",
                status="succeeded_with_pending",
                candidate=SimpleNamespace(manifest_sha256="c" * 64),
                generation_manifest_sha256="g" * 64,
                attempted_through_session="2026-08-14",
                complete_through_session="2026-08-14",
                accepted_instrument_count=1,
                failed_instrument_count=1,
                pending_instrument_count=1,
                discovery_gap_count=0,
            )

    provider = object()
    announcement_source = object()
    financial_source = object()
    monkeypatch.setenv("THESISTRACE_DATABASE_URL", "postgresql://unused")
    monkeypatch.setenv("THESISTRACE_DATA_MOUNT", str(tmp_path))
    monkeypatch.setattr(data_operator, "PostgresDatabase", FakeDatabase)
    monkeypatch.setattr(data_operator, "verify_core_schema", lambda _database: None)
    monkeypatch.setattr(
        data_operator,
        "_create_live_tushare_provider",
        lambda **_kwargs: (FakeTransport(), provider),
    )
    monkeypatch.setattr(
        data_operator,
        "AkshareCninfoFinancialAnnouncementSource",
        lambda: announcement_source,
    )
    monkeypatch.setattr(
        data_operator,
        "TushareFinancialSource",
        lambda selected: financial_source if selected is provider else None,
    )
    monkeypatch.setattr(data_operator, "DailyFinancialRefreshService", FakeService)

    data_operator.main(
        [
            "refresh-financial",
            "--idempotency-key",
            "daily-live",
            "--observation-through-session",
            "2026-08-14",
        ]
    )

    assert received["mount_root"] == tmp_path
    assert received["announcement_source"] is announcement_source
    assert received["financial_source"] is financial_source
    assert received["idempotency_key"] == "daily-live"
    assert received["observation_through_session"] == "2026-08-14"
    assert json.loads(capsys.readouterr().out) == {
        "accepted_instrument_count": 1,
        "attempted_through_session": "2026-08-14",
        "candidate_manifest_sha256": "c" * 64,
        "complete_through_session": "2026-08-14",
        "discovery_gap_count": 0,
        "failed_instrument_count": 1,
        "generation_manifest_sha256": "g" * 64,
        "idempotency_key": "daily-live",
        "pending_instrument_count": 1,
        "status": "succeeded_with_pending",
    }


def test_private_industry_operator_exposes_refresh_and_inspection_contracts(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as refresh_exit:
        data_operator.main(["refresh-industry", "--help"])

    assert refresh_exit.value.code == 0
    refresh_help = capsys.readouterr().out
    assert "--idempotency-key" in refresh_help
    assert "--observation-through-session" in refresh_help
    assert "--replay" in refresh_help

    with pytest.raises(SystemExit) as inspect_exit:
        data_operator.main(["inspect-industry-refresh", "--help"])

    assert inspect_exit.value.code == 0
    inspect_help = capsys.readouterr().out
    assert "--idempotency-key" in inspect_help
    assert "--observation-through-session" not in inspect_help


def test_financial_probe_does_not_require_database_or_data_mount(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class FakeTransport:
        def close(self) -> None:
            pass

    class FakeReport:
        @staticmethod
        def descriptor() -> dict[str, str]:
            return {"status": "probed"}

    def reject_database(_url: str) -> object:
        raise AssertionError("financial probe opened the database")

    monkeypatch.delenv("THESISTRACE_DATABASE_URL", raising=False)
    monkeypatch.delenv("THESISTRACE_DATA_MOUNT", raising=False)
    monkeypatch.setenv("THESISTRACE_TUSHARE_TOKEN", "test-token")
    monkeypatch.setattr(data_operator, "PostgresDatabase", reject_database)
    monkeypatch.setattr(data_operator, "HttpTushareTransport", lambda **_kwargs: FakeTransport())
    monkeypatch.setattr(data_operator, "TushareAdapter", lambda **_kwargs: object())
    monkeypatch.setattr(data_operator, "TushareFinancialSource", lambda provider: provider)
    monkeypatch.setattr(
        data_operator,
        "probe_financial_capability",
        lambda *_args, **_kwargs: FakeReport(),
    )

    data_operator.main(
        [
            "probe-financial",
            "--reference-instrument",
            "000001.SZ",
            "--comparison-shard",
            "2026:20260101:20261231",
        ]
    )

    assert json.loads(capsys.readouterr().out) == {"status": "probed"}


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
    monkeypatch.setattr(data_operator, "verify_core_schema", lambda _database: None)
    monkeypatch.setattr(data_operator, "ReplayTushareProvider", lambda _path: object())
    monkeypatch.setattr(
        data_operator,
        "TushareDataSource",
        lambda *, provider, progress: provider,
    )
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


def test_financial_operator_failure_identifies_only_the_failed_shard(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail(_arguments: list[str] | None = None) -> None:
        raise FinancialCollectionError(
            "UPSTREAM_RATE_LIMITED",
            endpoint="cashflow",
            instrument="000001.SZ",
            shard="complete-history",
        )

    monkeypatch.setattr(data_operator, "_run", fail)

    with pytest.raises(SystemExit) as failure:
        data_operator.main(["collect-financial"])

    assert failure.value.code == 2
    assert json.loads(capsys.readouterr().err) == {
        "status": "failed",
        "code": "UPSTREAM_RATE_LIMITED",
        "error": {
            "endpoint": "cashflow",
            "instrument": "000001.SZ",
            "shard": "complete-history",
        },
    }
