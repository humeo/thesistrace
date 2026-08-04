from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from thesistrace.research_kernel.alpha_expression import operator_catalog
    from thesistrace.research_kernel.equivalence import equivalence_bytes, first_divergence
    from thesistrace.research_kernel.kernel_advance import (
        AdvanceInput,
        advance,
        advance_continuation,
        continuation_snapshot,
        empty_continuation,
    )
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
    "advance_continuation",
    "continuation_snapshot",
    "empty_continuation",
    "equivalence_bytes",
    "first_divergence",
    "operator_catalog",
    "run",
]


def __getattr__(name: str) -> object:
    if name == "operator_catalog":
        from thesistrace.research_kernel.alpha_expression import operator_catalog

        return operator_catalog
    if name in {
        "AdvanceInput",
        "advance",
        "advance_continuation",
        "continuation_snapshot",
        "empty_continuation",
    }:
        from thesistrace.research_kernel.kernel_advance import (
            AdvanceInput,
            advance,
            advance_continuation,
            continuation_snapshot,
            empty_continuation,
        )

        return {
            "AdvanceInput": AdvanceInput,
            "advance": advance,
            "advance_continuation": advance_continuation,
            "continuation_snapshot": continuation_snapshot,
            "empty_continuation": empty_continuation,
        }[name]
    if name in {"equivalence_bytes", "first_divergence"}:
        from thesistrace.research_kernel.equivalence import (
            equivalence_bytes,
            first_divergence,
        )

        return {
            "equivalence_bytes": equivalence_bytes,
            "first_divergence": first_divergence,
        }[name]
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
