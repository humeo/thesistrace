from collections.abc import Callable

from fastapi import FastAPI, Request

from thesistrace.alpha_language import (
    AlphaAuthoringCatalog,
    FormulaDiagnostics,
    FormulaSource,
    alpha_language,
)


def install_alpha_http(
    app: FastAPI,
    *,
    catalog_snapshot: Callable[[Request], AlphaAuthoringCatalog],
) -> None:
    @app.get("/api/alpha/catalog", response_model=AlphaAuthoringCatalog)
    def get_alpha_catalog(request: Request) -> AlphaAuthoringCatalog:
        return catalog_snapshot(request)

    @app.post("/api/alpha/diagnostics", response_model=FormulaDiagnostics)
    def diagnose_alpha_formula(formula: FormulaSource) -> FormulaDiagnostics:
        return alpha_language.diagnose(formula.source)
