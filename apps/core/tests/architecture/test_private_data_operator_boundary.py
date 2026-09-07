from pathlib import Path


def test_data_refresh_exposes_only_queue_control_not_live_provider_access() -> None:
    root = Path(__file__).resolve().parents[4]
    project = (root / "apps/core/pyproject.toml").read_text()
    http = (root / "apps/core/src/thesistrace/entrypoints/http.py").read_text()
    worker = (root / "apps/core/src/thesistrace/entrypoints/worker.py").read_text()
    runtime = (root / "apps/core/src/thesistrace/entrypoints/runtime.py").read_text()

    assert 'thesistrace-data-operator = "thesistrace.entrypoints.data_operator:main"' in project
    assert "thesistrace-data-operator-v" not in project
    assert "data_operator" not in http
    assert "data_operator" not in worker
    assert '"/api/operator/data/refreshes/market"' in http
    assert '"/api/operator/data/refreshes/financial"' in http
    assert "TushareDataSource" not in runtime
    assert "TushareAdapter" not in runtime
    assert "TushareDataSource" not in http
    assert "TushareAdapter" not in http


def test_live_bootstrap_uses_one_current_checkpoint_manifest() -> None:
    root = Path(__file__).resolve().parents[4]
    operator = (root / "apps/core/src/thesistrace/entrypoints/data_operator.py").read_text()

    assert "tushare-bootstrap-checkpoint.json" in operator
    assert "tushare-bootstrap-checkpoint-v" not in operator


def test_generation_collection_is_only_wired_to_the_private_operator() -> None:
    root = Path(__file__).resolve().parents[4]
    operator = (root / "apps/core/src/thesistrace/entrypoints/data_operator.py").read_text()
    ordinary_paths = (
        "apps/core/src/thesistrace/entrypoints/http.py",
        "apps/core/src/thesistrace/entrypoints/runtime.py",
        "apps/core/src/thesistrace/entrypoints/worker.py",
        "apps/core/src/thesistrace/data/refresh.py",
    )

    assert "DataGarbageCollector" in operator
    assert 'add_parser("collect")' in operator
    for path in ordinary_paths:
        assert "DataGarbageCollector" not in (root / path).read_text()
