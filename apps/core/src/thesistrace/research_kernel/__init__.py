from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from thesistrace.research_kernel.equivalence import equivalence_bytes, first_divergence
    from thesistrace.research_kernel.kernel_advance import (
        AdvanceInput,
        advance,
        advance_continuation,
        continuation_snapshot,
        empty_continuation,
    )
    from thesistrace.research_kernel.kernel_run import (
        InsufficientCalculationWarmupError,
        KernelRunError,
        KernelState,
        RunInput,
        RunOutput,
        StrategyRunInput,
        run,
    )

__all__ = [
    "AdvanceInput",
    "InsufficientCalculationWarmupError",
    "KernelRunError",
    "KernelState",
    "RunInput",
    "RunOutput",
    "StrategyRunInput",
    "advance",
    "advance_continuation",
    "continuation_snapshot",
    "empty_continuation",
    "equivalence_bytes",
    "first_divergence",
    "run",
]


def __getattr__(name: str) -> object:
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
    if name in {
        "InsufficientCalculationWarmupError",
        "KernelRunError",
        "KernelState",
        "RunInput",
        "RunOutput",
        "StrategyRunInput",
        "run",
    }:
        from thesistrace.research_kernel.kernel_run import (
            InsufficientCalculationWarmupError,
            KernelRunError,
            KernelState,
            RunInput,
            RunOutput,
            StrategyRunInput,
            run,
        )

        return {
            "InsufficientCalculationWarmupError": InsufficientCalculationWarmupError,
            "KernelRunError": KernelRunError,
            "KernelState": KernelState,
            "RunInput": RunInput,
            "RunOutput": RunOutput,
            "StrategyRunInput": StrategyRunInput,
            "run": run,
        }[name]
    raise AttributeError(name)
