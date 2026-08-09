from pathlib import Path


def test_versioned_data_operator_is_not_registered_in_product_surfaces() -> None:
    root = Path(__file__).resolve().parents[2]
    project = (root / "pyproject.toml").read_text()
    http = (root / "src/thesistrace/entrypoints/http.py").read_text()
    worker = (root / "src/thesistrace/entrypoints/worker.py").read_text()
    runtime = (root / "src/thesistrace/entrypoints/runtime.py").read_text()
    web = "\n".join(path.read_text() for path in sorted((root / "web/src").rglob("*.tsx")))

    assert 'thesistrace-data-operator-v1 = "thesistrace.entrypoints.data_operator:main"' in project
    assert "data_operator" not in http
    assert "data_operator" not in worker
    assert "TushareDataSource" not in runtime
    assert "TushareAdapter" not in runtime
    assert "data operator" not in web.lower()
