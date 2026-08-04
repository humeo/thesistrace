import ast
import json
import subprocess
import sys
from pathlib import Path

from thesistrace.entrypoints.runtime import CoreRuntime, CoreSettings
from thesistrace.research_kernel import kernel_advance, kernel_run, strategy

ROOT = Path(__file__).resolve().parents[2]
CORE_PACKAGES = (
    "_postgres",
    "data",
    "daily_track",
    "definition",
    "entrypoints",
    "publication",
    "research_run",
)
FORBIDDEN_IMPORTS = (
    "thesistrace.hosted",
    "thesistrace.auth",
    "thesistrace.runtime",
    "temporalio",
)


def test_new_core_packages_do_not_import_old_or_hosted_runtime() -> None:
    for package in CORE_PACKAGES:
        for path in (ROOT / "src" / "thesistrace" / package).rglob("*.py"):
            tree = ast.parse(path.read_text())
            imports = [
                node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
            ]
            imports.extend(
                alias.name
                for node in ast.walk(tree)
                if isinstance(node, ast.Import)
                for alias in node.names
            )
            assert not any(
                imported.startswith(forbidden)
                for imported in imports
                for forbidden in FORBIDDEN_IMPORTS
            ), f"{path} imports a forbidden runtime dependency"


def test_runtime_configuration_has_no_deployment_mode() -> None:
    assert "mode" not in CoreSettings.__dataclass_fields__


def test_postgres_support_contains_mechanics_but_no_product_sql() -> None:
    postgres_source = "\n".join(
        path.read_text() for path in (ROOT / "src" / "thesistrace" / "_postgres").rglob("*.py")
    )
    assert "ConnectionPool" in postgres_source
    assert "MigrationPlan" in postgres_source
    for product_schema in (
        "data.",
        "definitions.",
        "research_runs.",
        "daily_tracks.",
        "publication.",
    ):
        assert product_schema not in postgres_source

    data_migrations = (ROOT / "src" / "thesistrace" / "data" / "migrations.py").read_text()
    assert "CREATE TABLE data.state" in data_migrations
    assert "CREATE TABLE data.releases" in data_migrations


def test_isolated_runtime_pins_only_postgres_and_rustfs() -> None:
    compose = (ROOT / "deploy" / "core" / "compose.test.yaml").read_text()
    assert "postgres:16.10-alpine" in compose
    assert "rustfs/rustfs:1.0.0-beta.12" in compose
    assert ":latest" not in compose
    for forbidden in ("sqlite", "temporal", "object-store", "auth"):
        assert forbidden not in compose.lower()


def test_web_shell_declares_only_the_four_product_resources() -> None:
    source = (ROOT / "web" / "src" / "shell" / "AppShell.tsx").read_text()
    assert source.count("path:") == 4
    assert 'path: "/data"' in source
    assert 'path: "/definitions"' in source
    assert 'path: "/research-runs"' in source
    assert 'path: "/daily-tracks"' in source
    for forbidden in ("hosted", "login", "workspace", "manifest", "download"):
        assert forbidden not in source.lower()


def test_alpha_tree_has_one_legacy_parser_and_no_dynamic_execution() -> None:
    facade_source = (ROOT / "src" / "thesistrace" / "alpha.py").read_text()
    alpha_source = (ROOT / "src" / "thesistrace" / "research_kernel" / "alpha.py").read_text()
    normalized_source = (
        ROOT / "src" / "thesistrace" / "research_kernel" / "alpha_expression.py"
    ).read_text()
    assert alpha_source.count("ast.parse(") == 1
    assert "def validate_legacy_alpha(" in alpha_source
    assert "ast.parse(" not in facade_source
    for forbidden in ("eval(", "exec(", "importlib", "sql"):
        assert forbidden not in normalized_source.lower()


def test_data_owns_the_single_authorable_field_binding_catalog() -> None:
    data_fields = (ROOT / "src" / "thesistrace" / "data" / "fields.py").read_text()
    alpha_source = (ROOT / "src" / "thesistrace" / "alpha.py").read_text()
    fixture_source = (ROOT / "src" / "thesistrace" / "fixture.py").read_text()

    for field_id in (
        "price.open.adjusted",
        "price.high.adjusted",
        "price.low.adjusted",
        "price.close.adjusted",
        "market.volume.shares",
        "market.turnover.cny",
    ):
        assert data_fields.count(field_id) == 1
        assert field_id not in alpha_source
        assert field_id not in fixture_source


def test_publication_hides_physical_s3_keys_and_uses_the_standard_client() -> None:
    source = (ROOT / "src" / "thesistrace" / "publication" / "service.py").read_text()
    exported = (ROOT / "src" / "thesistrace" / "publication" / "__init__.py").read_text()

    assert "put_object(" in source
    assert "get_object(" in source
    assert "httpx" not in source
    assert "_object_key" in source
    assert "object_key" not in exported
    assert "s3" not in CoreRuntime.__dataclass_fields__
    assert "thesistrace.objects" not in source
    assert (ROOT / "src" / "thesistrace" / "publication" / "serialization.py").is_file()
    for forbidden in ("token", "proxy", "fastapi", "filesystem"):
        assert forbidden not in source.lower()


def test_publication_owns_its_sql_and_never_commits_a_caller_transaction() -> None:
    service = (ROOT / "src" / "thesistrace" / "publication" / "service.py").read_text()
    migrations = (ROOT / "src" / "thesistrace" / "publication" / "migrations.py").read_text()

    assert "CREATE TABLE publication.objects" in migrations
    assert "CREATE TABLE publication.manifests" in migrations
    assert "CREATE TABLE publication.manifest_objects" in migrations
    assert "def record(" in service
    assert "def read_in_transaction(" in service
    assert ".commit(" not in service
    for product_schema in ("data.", "definitions.", "research_runs.", "daily_tracks."):
        assert product_schema not in service
        assert product_schema not in migrations


def test_definition_and_research_run_keep_sql_behind_atomic_admission_seam() -> None:
    definition_source = (ROOT / "src" / "thesistrace" / "definition" / "service.py").read_text()
    definition_migrations = (
        ROOT / "src" / "thesistrace" / "definition" / "migrations.py"
    ).read_text()
    run_source = (ROOT / "src" / "thesistrace" / "research_run" / "service.py").read_text()
    run_migrations = (ROOT / "src" / "thesistrace" / "research_run" / "migrations.py").read_text()

    assert "def admit(" in run_source
    assert ".commit(" not in run_source
    assert "CREATE TABLE research_runs.runs" in run_migrations
    assert "research_runs." not in definition_source
    assert "research_runs." not in definition_migrations
    assert "definitions." not in run_source
    assert "definitions." not in run_migrations


def test_research_run_processor_owns_claims_and_uses_module_seams() -> None:
    run_source = (ROOT / "src" / "thesistrace" / "research_run" / "service.py").read_text()
    run_migrations = (ROOT / "src" / "thesistrace" / "research_run" / "migrations.py").read_text()
    worker_source = (ROOT / "src" / "thesistrace" / "entrypoints" / "worker.py").read_text()

    assert "def process_next(" in run_source
    assert "FOR UPDATE OF run SKIP LOCKED" in run_source
    assert "CREATE TABLE research_runs.attempts" in run_migrations
    assert "execution_fence" in run_migrations
    assert "lease_expires_at <= now()" in run_source
    assert "def _maintain_claim(" in run_source
    assert "def _heartbeat_claim(" in run_source
    assert "MAX_RESEARCH_RUN_ATTEMPTS = 3" in run_source
    assert "MAX_RESOURCE_EXHAUSTED_ATTEMPTS = 2" in run_source
    assert "def _failure_policy(" in run_source
    assert "PublicationUnavailableError" in run_source
    failure_policy_source = run_source[
        run_source.index("def _failure_policy(") : run_source.index("def _cancel_fingerprint(")
    ]
    assert "PublicationPreparationError" not in failure_policy_source
    assert "PublicationVerificationError" not in failure_policy_source
    assert "ADD COLUMN failure_reason text" in run_migrations
    assert "def cancel(" in run_source
    assert "CREATE TABLE research_runs.cancel_receipts" in run_migrations
    assert "execution_fence = execution_fence + 1" in run_source
    assert "def rerun(" in run_source
    assert "CREATE TABLE research_runs.rerun_receipts" in run_migrations
    assert "immutable_input, rerun_of_id" in run_source
    assert "load_canonical" in run_source
    assert "self._publication.prepare(" in run_source
    assert "self._publication.record(" in run_source
    assert "runtime.research_runs.process_next()" in worker_source
    for removed in ("outbox", "dispatch", "global job", "temporal"):
        assert removed not in run_source.lower()
        assert removed not in run_migrations.lower()
    for foreign_schema in ("data", "definitions", "publication", "daily_tracks"):
        for sql_verb in ("FROM", "JOIN", "INSERT INTO", "UPDATE", "DELETE FROM"):
            assert f"{sql_verb} {foreign_schema}." not in run_source


def test_daily_track_owns_activation_sql_and_copied_origin() -> None:
    track_source = (ROOT / "src" / "thesistrace" / "daily_track" / "service.py").read_text()
    track_migrations = (ROOT / "src" / "thesistrace" / "daily_track" / "migrations.py").read_text()
    run_source = (ROOT / "src" / "thesistrace" / "research_run" / "service.py").read_text()
    http_source = (ROOT / "src" / "thesistrace" / "entrypoints" / "http.py").read_text()
    data_source = (ROOT / "src" / "thesistrace" / "data" / "service.py").read_text()
    worker_source = (ROOT / "src" / "thesistrace" / "entrypoints" / "worker.py").read_text()

    assert "CREATE TABLE daily_tracks.tracks" in track_migrations
    assert "CREATE TABLE daily_tracks.activation_receipts" in track_migrations
    assert "CREATE TABLE daily_tracks.progressions" in track_migrations
    assert "CREATE TABLE daily_tracks.checkpoints" in track_migrations
    assert "def activate(" in track_source
    assert "def resolve_activation(" in track_source
    assert "origin" in track_source
    assert "activate_track" in run_source
    assert "resolve_track_activation" in run_source
    assert "read_in_transaction" in run_source
    assert "TrackingOrigin(" in run_source
    assert "daily_tracks." not in run_source
    assert "research_runs." not in track_source
    assert "research_runs." not in track_migrations
    assert "def next_release(" in data_source
    assert "daily_tracks" not in data_source
    for sql_verb in ("FROM", "JOIN", "INSERT INTO", "UPDATE", "DELETE FROM"):
        assert f"{sql_verb} data." not in track_source
    assert "AdvanceInput(" in track_source
    assert 'kind="daily-track.checkpoint"' in track_source
    assert "while runtime.daily_tracks.process_next()" in worker_source
    assert '"/api/research-runs/{run_id}/daily-tracks"' in http_source
    assert '@app.post("/api/daily-tracks"' not in http_source
    assert '@app.delete("/api/daily-tracks' not in http_source


def test_daily_track_working_cache_is_private_concrete_and_worker_local() -> None:
    package = ROOT / "src" / "thesistrace" / "daily_track"
    source = "\n".join(path.read_text() for path in package.rglob("*.py"))
    exported = (package / "__init__.py").read_text()
    runtime_source = (ROOT / "src" / "thesistrace" / "entrypoints" / "runtime.py").read_text()
    http_source = (ROOT / "src" / "thesistrace" / "entrypoints" / "http.py").read_text()

    assert "thesistrace.working_cache" not in source
    assert "WorkingCachePort" not in source
    assert "_DailyTrackWorkingCache" not in exported
    assert "working_cache_root" not in CoreSettings.__dataclass_fields__
    assert "TemporaryDirectory" in runtime_source
    assert "working_cache_root=Path(working_cache.name)" in runtime_source
    assert "/api/working-cache" not in http_source


def test_daily_track_cache_rebuild_has_a_fixed_checkpoint_tail() -> None:
    service = (ROOT / "src" / "thesistrace" / "daily_track" / "service.py").read_text()
    checkpoint = (ROOT / "src" / "thesistrace" / "daily_track" / "checkpoint.py").read_text()
    kernel = (ROOT / "src" / "thesistrace" / "research_kernel" / "__init__.py").read_text()

    assert "REBUILD_CHECKPOINT_LIMIT = 525" in service
    assert "LIMIT %s" in service
    assert "_rebuild_prior_state" not in service
    assert "advance_continuation(" in service
    assert "daily-track-checkpoint-v1" in checkpoint
    assert "project_tracking_checkpoint" not in kernel


def test_research_run_owns_its_embedded_result_product_projection() -> None:
    run_source = (ROOT / "src" / "thesistrace" / "research_run" / "service.py").read_text()
    http_source = (ROOT / "src" / "thesistrace" / "entrypoints" / "http.py").read_text()

    assert "def get_detail(" in run_source
    assert "self._publication.read(" in run_source
    assert '"factor": {"horizons": horizons}' in run_source
    assert '"observations": observations' in run_source
    assert "publication." not in http_source
    assert '"/api/research-runs/{run_id}/result"' not in http_source
    for private_field in (
        '"terminal_strategy_state"',
        '"result_manifest_sha256"',
        '"result_provenance"',
    ):
        assert private_field not in run_source[run_source.index("def _public_result(") :]


def test_research_kernel_run_has_no_product_or_infrastructure_dependency() -> None:
    package = ROOT / "src" / "thesistrace" / "research_kernel"
    source = "\n".join(path.read_text() for path in package.rglob("*.py"))

    for forbidden in (
        "thesistrace._postgres",
        "thesistrace.bounded_research",
        "thesistrace.hosted",
        "thesistrace.ports",
        "thesistrace.quota",
        "thesistrace.research_runs",
        "thesistrace.storage",
        "boto3",
        "fastapi",
        "httpx",
        "psycopg",
        "temporalio",
    ):
        assert forbidden not in source
    assert "mode:" not in source
    assert "mode =" not in source


def test_importing_research_kernel_does_not_load_infrastructure() -> None:
    script = """
import json
import sys
from thesistrace.research_kernel import RunInput
del RunInput
forbidden = {
    name for name in sys.modules
    if name == "psycopg"
    or name.startswith("psycopg.")
    or name in {"boto3", "fastapi", "httpx", "temporalio"}
    or name.startswith("thesistrace.publication")
    or name in {"thesistrace.objects", "thesistrace.ports"}
}
print(json.dumps(sorted(forbidden)))
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(completed.stdout) == []


def test_partition_loader_has_no_second_calculation_engine() -> None:
    loader = (ROOT / "src" / "thesistrace" / "bounded_research.py").read_text()
    adapter = (ROOT / "src" / "thesistrace" / "research_runs.py").read_text()

    for removed in (
        "AlphaValueStore",
        "PriceLookup",
        "StateLookup",
        "LimitLookup",
        "UniverseLookup",
        "_calculate_alpha",
        "_calculate_labels_and_factor",
        "strategy_canonical",
        "discard_alpha_only_fields",
    ):
        assert removed not in loader
    assert "RunInput(" not in loader
    assert adapter.count("RunInput(") == 1


def test_kernel_run_and_advance_share_the_same_calculation_path() -> None:
    run_source = (ROOT / "src" / "thesistrace" / "research_kernel" / "kernel_run.py").read_text()
    advance_source = (
        ROOT / "src" / "thesistrace" / "research_kernel" / "kernel_advance.py"
    ).read_text()

    assert "evaluate_alpha_matrix(" in run_source
    assert "build_forward_labels(" in run_source
    assert "evaluate_factor(" in run_source
    assert kernel_run.transition_strategy is strategy.transition_strategy
    assert "transition_strategy(" in run_source
    assert "run_strategy(" not in run_source
    assert "class RunOutput(dict" not in run_source
    assert "def artifacts_snapshot(" in run_source
    assert "evaluate_alpha_matrix(" in advance_source
    assert "build_forward_labels(" in advance_source
    assert "evaluate_factor(" in advance_source
    assert kernel_advance.transition_strategy is strategy.transition_strategy
    assert "transition_strategy(" in advance_source
    assert "run_strategy(" not in advance_source
    assert "initial_state(" not in advance_source
    assert "affected_label_sessions(" in advance_source
    assert "- horizon - 1" not in advance_source
    for forbidden in ("mode:", "mode =", "thesistrace.tracking", "thesistrace.research_runs"):
        assert forbidden not in advance_source
