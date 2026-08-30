from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from thesistrace.adapters.tushare_provider import TushareSourceError
from thesistrace.data import (
    DataOperatorError,
    DataRefreshError,
    DataSourceError,
    FinancialCollectionError,
    validate_financial_refresh_request,
    validate_industry_refresh_request,
    validate_market_refresh_request,
)
from thesistrace.entrypoints import data_operator


def test_market_worker_hard_cuts_the_manual_worker_command(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as help_exit:
        data_operator.main(["worker", "--help"])

    assert help_exit.value.code == 0
    worker_help = capsys.readouterr().out
    assert "--once" in worker_help
    assert "--replay" in worker_help

    with pytest.raises(SystemExit) as obsolete_exit:
        data_operator.main(["work-refresh", "--help"])

    assert obsolete_exit.value.code == 2
    assert "invalid choice" in capsys.readouterr().err


def test_one_shot_market_worker_is_replay_only(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        data_operator,
        "PostgresDatabase",
        lambda _url: (_ for _ in ()).throw(AssertionError("database opened")),
    )

    with pytest.raises(SystemExit) as failure:
        data_operator.main(["worker", "--once"])

    assert failure.value.code == 2
    assert json.loads(capsys.readouterr().out) == {
        "code": "WORKER_REPLAY_REQUIRED",
        "status": "failed",
    }


@pytest.mark.parametrize(
    "value",
    [
        "2026-08-11",
        "not-a-time",
        "2026-08-11T18:00:00",
        "2026-08-11T18:00:00." + "1" * 110 + "+08:00",
    ],
)
def test_market_refresh_rejects_non_timezone_aware_as_of_before_opening_storage(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    value: str,
) -> None:
    monkeypatch.setattr(
        data_operator,
        "PostgresDatabase",
        lambda _url: (_ for _ in ()).throw(AssertionError("database opened")),
    )
    monkeypatch.setenv("THESISTRACE_DATABASE_URL", "postgresql://unused")
    monkeypatch.setenv("THESISTRACE_DATA_MOUNT", "/unused")
    monkeypatch.setenv("THESISTRACE_BENCHMARK_MOUNT", "/unused-benchmark")

    with pytest.raises(SystemExit) as failure:
        data_operator.main(
            [
                "refresh",
                "--idempotency-key",
                "market-20260811T180000+0800",
                "--as-of",
                value,
            ]
        )

    assert failure.value.code == 2
    assert json.loads(capsys.readouterr().err) == {
        "code": "INVALID_AS_OF",
        "status": "failed",
    }


@pytest.mark.parametrize(
    "key",
    ("k" * 513, "刷" * 513, "market-\0-key", f"market-{chr(0xD800)}-key"),
)
def test_market_refresh_rejects_a_key_over_the_shared_character_limit(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    key: str,
) -> None:
    monkeypatch.setattr(
        data_operator,
        "PostgresDatabase",
        lambda _url: (_ for _ in ()).throw(AssertionError("database opened")),
    )
    monkeypatch.setenv("THESISTRACE_DATABASE_URL", "postgresql://unused")
    monkeypatch.setenv("THESISTRACE_DATA_MOUNT", "/unused")
    monkeypatch.setenv("THESISTRACE_BENCHMARK_MOUNT", "/unused-benchmark")

    with pytest.raises(SystemExit) as failure:
        data_operator.main(
            [
                "refresh",
                "--idempotency-key",
                key,
                "--as-of",
                "2026-08-11T18:00:00+08:00",
            ]
        )

    assert failure.value.code == 2
    assert json.loads(capsys.readouterr().err) == {
        "code": "INVALID_IDEMPOTENCY_KEY",
        "status": "failed",
    }


@pytest.mark.parametrize(
    "value",
    (
        "2026-08-14T00:00:00Z",
        "20260814",
        "2026-8-14",
        "2026-08-14 ",
        "0000-01-01",
        "not-a-session",
    ),
)
def test_financial_refresh_rejects_non_iso_research_session_before_opening_storage(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    value: str,
) -> None:
    monkeypatch.setattr(
        data_operator,
        "PostgresDatabase",
        lambda _url: (_ for _ in ()).throw(AssertionError("database opened")),
    )
    monkeypatch.setenv("THESISTRACE_DATABASE_URL", "postgresql://unused")
    monkeypatch.setenv("THESISTRACE_DATA_MOUNT", "/unused")
    monkeypatch.setenv("THESISTRACE_BENCHMARK_MOUNT", "/unused-benchmark")

    with pytest.raises(SystemExit) as failure:
        data_operator.main(
            [
                "refresh-financial",
                "--idempotency-key",
                "financial-20260814",
                "--observation-through-session",
                value,
            ]
        )

    assert failure.value.code == 2
    assert json.loads(capsys.readouterr().err) == {
        "code": "INVALID_OBSERVATION_THROUGH_SESSION",
        "status": "failed",
    }


def test_financial_refresh_request_preserves_the_exact_key_and_canonical_session() -> None:
    key, target = validate_financial_refresh_request(
        idempotency_key="financial-20260814-custom",
        observation_through_session="2026-08-14",
    )

    assert key == "financial-20260814-custom"
    assert target == "2026-08-14"


def test_industry_refresh_request_preserves_the_exact_key_and_canonical_session() -> None:
    key, target = validate_industry_refresh_request(
        idempotency_key="industry-20260814-custom",
        observation_through_session="2026-08-14",
    )

    assert key == "industry-20260814-custom"
    assert target == "2026-08-14"


def test_market_key_uses_the_explicit_python_boundary_whitespace_contract() -> None:
    as_of = "2026-08-11T18:00:00+08:00"

    key, _target = validate_market_refresh_request(
        idempotency_key="\ufeffmarket-key",
        as_of=as_of,
    )
    assert key == "\ufeffmarket-key"
    with pytest.raises(DataRefreshError, match="INVALID_IDEMPOTENCY_KEY"):
        validate_market_refresh_request(
            idempotency_key="\x85market-key",
            as_of=as_of,
        )


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


def test_daily_financial_operator_submits_and_returns_without_opening_sources(
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

    class FakeService:
        def __init__(
            self,
            database: object,
            mount_root: Path,
            *,
            benchmark_mount_root: Path,
        ) -> None:
            received.update(
                database=database,
                mount_root=mount_root,
                benchmark_mount_root=benchmark_mount_root,
            )

        def submit_financial(self, **arguments: object) -> object:
            received.update(arguments)
            return SimpleNamespace(
                idempotency_key="daily-live",
                kind="financial",
                as_of=None,
                observation_through_session="2026-08-14",
                status="accepted",
                outcome=None,
                data_through_session=None,
                last_refresh_at=None,
                failure_code=None,
                last_failure_code=None,
                attempt_count=0,
                financial_complete_through_session=None,
                matched_trigger_count=None,
                checked_no_structured_change_count=None,
                accepted_instrument_count=None,
                failed_instrument_count=None,
                pending_instrument_count=None,
                discovery_gap_count=None,
            )

    monkeypatch.setenv("THESISTRACE_DATABASE_URL", "postgresql://unused")
    monkeypatch.setenv("THESISTRACE_DATA_MOUNT", str(tmp_path))
    monkeypatch.setenv(
        "THESISTRACE_BENCHMARK_MOUNT",
        str(tmp_path.parent / f"{tmp_path.name}-benchmark-data"),
    )
    monkeypatch.setattr(data_operator, "PostgresDatabase", FakeDatabase)
    monkeypatch.setattr(data_operator, "verify_core_schema", lambda _database: None)
    monkeypatch.setattr(
        data_operator,
        "_create_live_tushare_provider",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("source opened")),
    )
    monkeypatch.setattr(data_operator, "DataRefreshService", FakeService)

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
    assert received["idempotency_key"] == "daily-live"
    assert received["observation_through_session"] == "2026-08-14"
    assert json.loads(capsys.readouterr().out) == {
        "accepted_instrument_count": None,
        "as_of": None,
        "attempt_count": 0,
        "checked_no_structured_change_count": None,
        "data_through_session": None,
        "discovery_gap_count": None,
        "failed_instrument_count": None,
        "failure_code": None,
        "financial_complete_through_session": None,
        "idempotency_key": "daily-live",
        "kind": "financial",
        "last_failure_code": None,
        "last_refresh_at": None,
        "matched_trigger_count": None,
        "observation_through_session": "2026-08-14",
        "outcome": None,
        "pending_instrument_count": None,
        "status": "accepted",
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
    assert "--replay" not in refresh_help

    with pytest.raises(SystemExit) as inspect_exit:
        data_operator.main(["inspect-industry-refresh", "--help"])

    assert inspect_exit.value.code == 0
    inspect_help = capsys.readouterr().out
    assert "--idempotency-key" in inspect_help
    assert "--observation-through-session" not in inspect_help


def test_industry_operator_submits_and_returns_without_opening_sources(
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

    class FakeService:
        def __init__(
            self,
            database: object,
            mount_root: Path,
            *,
            benchmark_mount_root: Path,
        ) -> None:
            received.update(
                database=database,
                mount_root=mount_root,
                benchmark_mount_root=benchmark_mount_root,
            )

        def submit_industry(self, **arguments: object) -> object:
            received.update(arguments)
            return SimpleNamespace(
                idempotency_key="industry-live",
                kind="industry",
                as_of=None,
                observation_through_session="2026-08-14",
                status="accepted",
                outcome=None,
                data_through_session=None,
                last_refresh_at=None,
                failure_code=None,
                last_failure_code=None,
                attempt_count=0,
                financial_complete_through_session=None,
                matched_trigger_count=None,
                checked_no_structured_change_count=None,
                accepted_instrument_count=None,
                failed_instrument_count=None,
                pending_instrument_count=None,
                discovery_gap_count=None,
            )

    monkeypatch.setenv("THESISTRACE_DATABASE_URL", "postgresql://unused")
    monkeypatch.setenv("THESISTRACE_DATA_MOUNT", str(tmp_path))
    monkeypatch.setenv(
        "THESISTRACE_BENCHMARK_MOUNT",
        str(tmp_path.parent / f"{tmp_path.name}-benchmark-data"),
    )
    monkeypatch.setattr(data_operator, "PostgresDatabase", FakeDatabase)
    monkeypatch.setattr(data_operator, "verify_core_schema", lambda _database: None)
    monkeypatch.setattr(
        data_operator,
        "_create_live_tushare_provider",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("source opened")),
    )
    monkeypatch.setattr(data_operator, "DataRefreshService", FakeService)

    data_operator.main(
        [
            "refresh-industry",
            "--idempotency-key",
            "industry-live",
            "--observation-through-session",
            "2026-08-14",
        ]
    )

    assert received["mount_root"] == tmp_path
    assert received["idempotency_key"] == "industry-live"
    assert received["observation_through_session"] == "2026-08-14"
    assert json.loads(capsys.readouterr().out) == {
        "accepted_instrument_count": None,
        "as_of": None,
        "attempt_count": 0,
        "checked_no_structured_change_count": None,
        "data_through_session": None,
        "discovery_gap_count": None,
        "failed_instrument_count": None,
        "failure_code": None,
        "financial_complete_through_session": None,
        "idempotency_key": "industry-live",
        "kind": "industry",
        "last_failure_code": None,
        "last_refresh_at": None,
        "matched_trigger_count": None,
        "observation_through_session": "2026-08-14",
        "outcome": None,
        "pending_instrument_count": None,
        "status": "accepted",
    }


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
    monkeypatch.setenv(
        "THESISTRACE_BENCHMARK_MOUNT",
        str(tmp_path.parent / f"{tmp_path.name}-benchmark-data"),
    )
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
