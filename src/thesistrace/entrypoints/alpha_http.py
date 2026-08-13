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
    financial_authoring_ready: Callable[[Request], bool] | None = None,
) -> None:
    @app.get("/api/alpha/catalog", response_model=AlphaAuthoringCatalog)
    def get_alpha_catalog(request: Request) -> AlphaAuthoringCatalog:
        return alpha_language.catalog(
            financial_authoring_ready=(
                financial_authoring_ready(request)
                if financial_authoring_ready is not None
                else False
            )
        )

    @app.post("/api/alpha/diagnostics", response_model=FormulaDiagnostics)
    def diagnose_alpha_formula(formula: FormulaSource) -> FormulaDiagnostics:
        return alpha_language.diagnose(formula.source)
