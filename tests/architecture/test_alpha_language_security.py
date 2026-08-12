import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_formula_language_never_executes_python() -> None:
    calls: list[str] = []
    for path in (ROOT / "src" / "thesistrace" / "alpha_language").glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                calls.append(node.func.id)

    assert not {"eval", "exec", "compile"}.intersection(calls)


def test_formula_language_does_not_publish_python_ast() -> None:
    public = (ROOT / "src" / "thesistrace" / "alpha_language" / "__init__.py").read_text()

    assert "ast" not in public


def test_research_kernel_owns_builtin_definitions() -> None:
    assert not (ROOT / "src" / "thesistrace" / "alpha_language" / "builtins.py").exists()
    kernel_builtins = (
        ROOT / "src" / "thesistrace" / "research_kernel" / "alpha_builtins.py"
    ).read_text()

    assert "class BuiltinDefinition" in kernel_builtins
    assert "evaluator=" in kernel_builtins
    assert "decimal" not in kernel_builtins.lower()
    assert "Decimal" not in kernel_builtins


def test_alpha_matrix_has_no_recursive_evaluator_or_physical_field_map() -> None:
    alpha_source = (ROOT / "src" / "thesistrace" / "research_kernel" / "alpha.py").read_text()
    plan_source = (ROOT / "src" / "thesistrace" / "research_kernel" / "series_plan.py").read_text()

    assert "def evaluate_node" not in alpha_source
    assert "canonical_keys" not in alpha_source
    assert "read_field_series" in alpha_source
    assert "alpha_field_catalog" not in alpha_source
    assert "import ast" not in plan_source
    assert "ParsedAlpha" not in plan_source
    assert "for node in plan.nodes" in plan_source
