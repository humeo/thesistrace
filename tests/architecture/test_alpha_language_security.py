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
