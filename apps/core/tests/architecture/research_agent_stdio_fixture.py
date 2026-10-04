"""Real Core MCP transport with deterministic readers for the Agent contract test."""

import runpy
from pathlib import Path

import anyio

from thesistrace.entrypoints.research_agent_mcp import _serve_stdio
from thesistrace.research_run.models import (
    ResearchRunAdmissionIssue,
    ResearchRunAdmissionRejectedOutcome,
)

fixture = runpy.run_path(str(Path(__file__).with_name("test_research_agent_mcp_contract.py")))
runs = fixture["_ResearchRunReader"]()
runs.admission_outcome = ResearchRunAdmissionRejectedOutcome(
    issues=[ResearchRunAdmissionIssue(
        field="formula", code="UNKNOWN_IDENTIFIER", message="Unknown Alpha identifier",
    )],
    replayed=False,
)
tracks = fixture["_DailyTrackReader"]()
tracks.result_section = fixture["_large_origin_result"]()
registry = fixture["_registry"](research_runs=runs, daily_tracks=tracks)
anyio.run(_serve_stdio, fixture["_server"](registry, events=[]))
