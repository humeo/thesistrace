from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from thesistrace.research_kernel.alpha_expression import operator_catalog
    from thesistrace.research_kernel.kernel_advance import AdvanceInput, advance
    from thesistrace.research_kernel.kernel_run import (
        KernelRunError,
        KernelState,
        RunInput,
        RunOutput,
        run,
    )

__all__ = [
    "AdvanceInput",
    "KernelRunError",
    "KernelState",
    "RunInput",
    "RunOutput",
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
    if name in {"KernelRunError", "KernelState", "RunInput", "RunOutput", "run"}:
        from thesistrace.research_kernel.kernel_run import (
            KernelRunError,
            KernelState,
            RunInput,
            RunOutput,
            run,
        )

        return {
            "KernelRunError": KernelRunError,
            "KernelState": KernelState,
            "RunInput": RunInput,
            "RunOutput": RunOutput,
            "run": run,
        }[name]
    raise AttributeError(name)
