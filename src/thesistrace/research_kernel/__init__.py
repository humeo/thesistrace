from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from thesistrace.research_kernel.alpha_expression import operator_catalog
    from thesistrace.research_kernel.kernel_advance import AdvanceInput, advance
    from thesistrace.research_kernel.kernel_run import KernelRunError, RunInput, run

__all__ = [
    "AdvanceInput",
    "KernelRunError",
    "RunInput",
    "advance",
    "operator_catalog",
    "run",
]


def __getattr__(name: str) -> object:
    if name == "operator_catalog":
        from thesistrace.research_kernel.alpha_expression import operator_catalog

        return operator_catalog
    if name in {"AdvanceInput", "advance"}:
        from thesistrace.research_kernel.kernel_advance import AdvanceInput, advance

        return {"AdvanceInput": AdvanceInput, "advance": advance}[name]
    if name in {"KernelRunError", "RunInput", "run"}:
        from thesistrace.research_kernel.kernel_run import KernelRunError, RunInput, run

        return {
            "KernelRunError": KernelRunError,
            "RunInput": RunInput,
            "run": run,
        }[name]
    raise AttributeError(name)
