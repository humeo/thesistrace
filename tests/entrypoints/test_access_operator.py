from __future__ import annotations

import json
from uuid import UUID

import pytest

from thesistrace.entrypoints import access_operator

RESEARCHER_ID = UUID("00000000-0000-4000-8000-000000000001")


def test_access_operator_reports_active_daily_tracks_read_only(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    events: list[object] = []

    class FakeDatabase:
        def __init__(self, database_url: str) -> None:
            assert database_url == "postgresql://core-runtime"

        def open(self) -> None:
            events.append("open")

        def close(self) -> None:
            events.append("close")

    class FakeInspector:
        def __init__(self, database: FakeDatabase) -> None:
            events.append(database)

        def count_active(self, researcher_id: UUID) -> int:
            assert researcher_id == RESEARCHER_ID
            return 3

    monkeypatch.setenv("THESISTRACE_DATABASE_URL", "postgresql://core-runtime")
    monkeypatch.setattr(access_operator, "PostgresDatabase", FakeDatabase)
    monkeypatch.setattr(
        access_operator,
        "verify_core_schema",
        lambda database: events.append(database),
    )
    monkeypatch.setattr(access_operator, "DailyTrackAccessInspector", FakeInspector)

    access_operator.main(
        ["active-daily-tracks", "--researcher-id", str(RESEARCHER_ID)]
    )

    streams = capsys.readouterr()
    assert json.loads(streams.out) == {
        "active_daily_track_count": 3,
        "researcher_id": str(RESEARCHER_ID),
        "status": "inspected",
    }
    assert json.loads(streams.err) == {
        "event": "core_access_inspection_completed",
        "status": "inspected",
    }
    assert events[0] == "open"
    assert events[-1] == "close"


def test_access_operator_fails_closed_without_database_configuration(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("THESISTRACE_DATABASE_URL", raising=False)

    with pytest.raises(SystemExit, match="4"):
        access_operator.main(
            ["active-daily-tracks", "--researcher-id", str(RESEARCHER_ID)]
        )

    assert capsys.readouterr().err == (
        '{"code":"POSTGRESQL_UNAVAILABLE",'
        '"event":"core_access_inspection_failed"}\n'
    )
