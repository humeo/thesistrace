from fastapi import FastAPI

from thesistrace.alpha_language import (
    AlphaAuthoringCatalog,
    FormulaDiagnostics,
    FormulaSource,
    alpha_language,
)


def install_alpha_http(app: FastAPI) -> None:
    @app.get("/api/alpha/catalog", response_model=AlphaAuthoringCatalog)
    def get_alpha_catalog() -> AlphaAuthoringCatalog:
        return alpha_language.catalog()

    @app.post("/api/alpha/diagnostics", response_model=FormulaDiagnostics)
    def diagnose_alpha_formula(formula: FormulaSource) -> FormulaDiagnostics:
        return alpha_language.diagnose(formula.source)
