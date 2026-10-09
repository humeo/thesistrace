"""Discoverable authoring instructions built from the current domain contracts."""

import json

from thesistrace.alpha_language.syntax import (
    ARITHMETIC_OPERATORS,
    BOOLEAN_OPERATORS,
    COMPARISON_OPERATORS,
    UNARY_OPERATORS,
)
from thesistrace.research_authoring.models import ResearchAuthoringConstraints
from thesistrace.research_authoring.reference_models import (
    AuthoringExample,
    AuthoringGuide,
    AuthoringReference,
    AuthoringReferenceEntry,
    AuthoringReferenceQuery,
    AuthoringSymbolSummary,
    AuthoringTopicSummary,
)
from thesistrace.research_authoring.sdk_reference import SDK_OVERVIEW, sdk_reference_entries
from thesistrace.research_kernel.strategy_program_runtime import (
    FUEL,
    HISTORY_CELLS,
    HISTORY_RESPONSE_BYTES,
    HISTORY_TOTAL_CELLS,
    MAX_JSON_DEPTH,
)

EXECUTION_RECOMMENDATIONS = (
    "Prefer catalog Formulae and builtin Strategy rules when they express the intended logic. "
    "Use Python when the Researcher requests code or needs custom computation or account "
    "decisions beyond those rules.",
    "For research sharing the same start/end dates, universe and compatible neutralization, "
    "consider a supported Batch: factor_evaluation prepares common Data, Universe and Labels "
    "once per chunk for multiple Formula Alphas; strategy_sweep computes one shared Formula "
    "Alpha for multiple Strategy configurations. Each Strategy account still runs independently "
    "and reads its required execution Data in bounded chunks.",
    "Submit separate ResearchRuns for complete Strategy Backtests with different Formula "
    "Alphas. Equal dates alone do not make a supported Batch. Preserve the requested research "
    "kind and logic; do not rewrite Formulae as Python merely to place them in a Batch.",
    "For Python numerical work, use compute(data, state) and NumPy over the provided multi-date "
    "arrays. Load each required history window once per compute invocation and reuse it. "
    "Use decide(data, account, state) for decisions needing actual account state. Keep "
    "computation causal and invariant to chunk boundaries; let the platform choose bounded "
    "chunk sizes and own persistence and recovery.",
)

AUTHORING_GUIDE = AuthoringGuide(
    steps=(
        "Read get_research_context for current data coverage, readiness and research folders.",
        "Read get_authoring_reference for the relevant workflow, formula syntax or Python SDK. "
        "Browse get_alpha_catalog(kind='fields' or 'functions', query=...) for available inputs.",
        *EXECUTION_RECOMMENDATIONS,
        "Write the complete ResearchSpec using current schemas. Diagnose formulas with "
        "diagnose_alpha_formula and the complete configuration with diagnose_research_spec; "
        "correct the reported field paths or source locations before submission.",
        "Submit with a caller-stable request_id. An uncertain response must be retried with "
        "the exact same arguments and ID; changed commands need a new ID. Only an accepted "
        "receipt proves that a ResearchRun or Research Batch exists.",
        "Poll the returned durable ID using retry_after_seconds. Read required Result sections "
        "and follow opaque cursors with unchanged filters. Research continues after disconnect.",
    ),
    topics=(
        AuthoringTopicSummary(
            topic="workflow",
            title="Research workflow",
            summary="Choose research, submit, recover and read results.",
        ),
        AuthoringTopicSummary(
            topic="formula",
            title="Alpha Formula language",
            summary="Allowed syntax, operators, types and context restrictions.",
        ),
        AuthoringTopicSummary(
            topic="python_sdk",
            title="Python strategy SDK",
            summary="Public classes, methods, observations and current limits.",
        ),
        AuthoringTopicSummary(
            topic="examples",
            title="Executable examples",
            summary="Formula and Direct/Framework source templates.",
        ),
    ),
)


def _workflow_entries(constraints: ResearchAuthoringConstraints):
    return (
        AuthoringReferenceEntry(
            symbol="research_kinds",
            description="Choose the research that answers the question.",
            notes=(
                "Factor Evaluation evaluates a Formula's predictive scores. Strategy Backtest "
                "simulates a long-only account, costs and execution. Framework can use builtin "
                "rules and/or Python stages; Direct supplies one Strategy program.",
                *EXECUTION_RECOMMENDATIONS,
                "Dates and universe must fit current Data Overview. initial_cash_cny and costs "
                "are decimal strings. Use the current tool schema for required configuration.",
            ),
            constraints=constraints.model_dump(mode="json"),
        ),
        AuthoringReferenceEntry(
            symbol="submission",
            description="Validate and admit a complete research question.",
            notes=(
                "Use diagnose_research_spec(spec) before a new or edited submission. It checks "
                "current data, Formula dependencies, execution budgets and Python "
                "function loading. "
                "It does not reserve capacity, create a Run or prove every Python branch works. "
                "Submission independently revalidates against current conditions.",
                "Diagnostics identify field, code, message and source range or Python line when "
                "available. Formula details include expected and actual values. Correct these "
                "using the formula reference, field catalog or Python SDK entry.",
                "submit_research_run uses the complete config plus request_id and folder_id. "
                "Use folders.items[].id, not its display name. An owned rerun uses rerun_source "
                "branch of the tool schema. outcome='rejected' creates no Run.",
                "Reuse exactly the same command and request_id after a lost response. When "
                "changing configuration after rejection, use a new request_id. Do not turn a "
                "successful diagnostic into a claimed accepted Run.",
            ),
        ),
        AuthoringReferenceEntry(
            symbol="batches",
            description="Submit ordered child ResearchRuns with compatible shared inputs.",
            notes=(
                *EXECUTION_RECOMMENDATIONS[1:3],
                "A Python strategy_sweep accepts independent programs per item, all in the same "
                "Framework or Direct mode. It shares the frozen scope and common input artifact, "
                "not program signal computation. Each account still performs its own bounded "
                "Data reads; a Batch does not guarantee that Python history is loaded only once.",
                "submit_research_batch admits ordered item_keys atomically under a common "
                "period, universe, neutralization and data generation. The platform owns the "
                "Batch Research Folder; do not supply folder_id. Keep item_keys and request_id "
                "stable on retries. Use the current constraints for batch size and kinds.",
                "get_research_batch returns ordered child run IDs and lifecycle. Read each "
                "child's get_research_run_result sections; a Batch has no synthetic aggregate "
                "Result. Describe partial failures without inventing metrics.",
            ),
        ),
        AuthoringReferenceEntry(
            symbol="results",
            description="Read bounded authoritative results and resume safely.",
            notes=(
                "get_research_run returns status, normalized inputs and available sections. "
                "After success, get_research_run_result reads a chosen section. Follow "
                "retry_after_seconds while work is pending. Listing or polling never reruns it.",
                "Result reads use the current section-specific schema. Follow next_cursor "
                "without changing query filters; an empty page with a cursor is not the end. "
                "A partial page is not the entire Result or necessarily the newest observation.",
                "Large sections return section='result_page'. Continue the same Result tool "
                "with section='result_page', the original section arguments in query, and "
                "result_cursor=next_result_cursor. Concatenate json_fragment values in offset "
                "order and verify total_bytes/checksum_sha256 before parsing JSON. A decoded "
                "collection page may have its own next_cursor. Invalid cursors require a fresh "
                "original query; do not combine fragments from different reads.",
                "Holdings detail availability is explicit. Expired or unrecorded detail is not "
                "an empty portfolio. Reading retained detail renews that unit's retention; "
                "checking its status does not. Never rerun automatically to replace "
                "missing detail.",
            ),
        ),
        AuthoringReferenceEntry(
            symbol="daily_tracks",
            description="Continue a succeeded Strategy Backtest.",
            notes=(
                "start_daily_track requires a succeeded Strategy Run; reuse its existing Track. "
                "get_daily_track returns lifecycle and current action eligibility. View reloads "
                "are reads. refresh_daily_track explicitly queues an advance for an active, "
                "lagging, idle Track. retry_daily_track retries a blocked Track.",
                "A Track freezes its origin program and continues independently of the Agent "
                "Chat. Read get_daily_track_result sections and immutable paged publications. "
                "Disconnect or Chat deletion does not stop it. Cancel and Stop require their "
                "dedicated scopes and explicit user intent; discovery is authority-filtered.",
            ),
        ),
    )


def _formula_entries(constraints: ResearchAuthoringConstraints):
    return (
        AuthoringReferenceEntry(
            symbol="syntax", description="One expression in the strict Alpha Language.",
            notes=(
                "Use finite numeric literals, catalog field identifiers, parentheses and "
                "direct calls to catalog functions with positional arguments. Window arguments "
                "must be positive integer literals within the function's published bounds.",
                "Allowed operators are listed in constraints.operators. Use parentheses to "
                "make precedence explicit.",
                "No power (**), modulo (%), floor division (//), unary +, chained comparisons, "
                "boolean/string literals, keyword arguments, attribute access, subscripts, "
                "assignment, imports, comprehensions, lambdas or Python conditional expressions. "
                "Use if_else(condition, when_true, when_false) for conditional values.",
            ),
            examples=(AuthoringExample(
                title="Conditional score", language="formula", context="signal",
                source="if_else(close > open, close, open)",
            ),),
            constraints={
                **constraints.formula.model_dump(mode="json"),
                "operators": {
                    name: [spelling for spelling, _operator in operators.values()]
                    for name, operators in (
                        ("arithmetic", ARITHMETIC_OPERATORS),
                        ("comparison", COMPARISON_OPERATORS),
                        ("unary", UNARY_OPERATORS), ("boolean", BOOLEAN_OPERATORS),
                    )
                },
            },
        ),
        AuthoringReferenceEntry(
            symbol="contexts", description="signal and exposure have different result contracts.",
            notes=(
                "signal must produce a numeric series per instrument; a bare number or boolean "
                "condition is not an Alpha score. Higher scores mean stronger expected return.",
                "exposure permits a number or common daily numeric series evaluated at Close "
                "for the next Open, with values from 0 to 1. Stock fields, cross-sectional "
                "rank and account state are unavailable. Diagnose with context='exposure'.",
                "Numeric and boolean types are distinct. Arithmetic and comparisons require "
                "numeric operands; and/or/not require boolean operands. Scalars and common "
                "series can broadcast into instrument series; exposure cannot use that result.",
                "Missing or non-finite inputs can produce missing values, not implicit zero. "
                "Read each function's missing_value_behavior and numeric_behavior from "
                "get_alpha_catalog. Rolling windows require their declared observations.",
            ),
            examples=(AuthoringExample(title="Common daily exposure", language="formula",
                                       context="exposure",
                                       source="if_else(universe_return() > 0, 1, 0.3)"),),
        ),
        AuthoringReferenceEntry(
            symbol="fields_and_functions",
            description="Discover data and functions from the live catalog.",
            notes=(
                "get_alpha_catalog(kind='fields', query=...) searches currently available fields. "
                "Each entry includes identifier, canonical field_id, unit, provenance, temporal "
                "availability and missingness. Formulae use identifier, not field_id.",
                "get_alpha_catalog(kind='functions') browses mathematical functions separately "
                "from fields. Each entry has parameters, types, bounds, result semantics and "
                "examples. Use identifiers for exact lookup; combine query/kind as filters.",
                "The catalog is pinned to its reported generation manifest. Follow next_cursor "
                "with unchanged filters. Available financial fields depend on current published "
                "data; language support alone does not prove data readiness.",
            ),
        ),
    )


def _examples(constraints: ResearchAuthoringConstraints):
    examples = [("direct", AuthoringExample(
        title="Direct strategy", language="python",
        source=constraints.python_program.source_template,
        entrypoint="compute",
    ))]
    for stage in constraints.framework.stages:
        examples.append((stage.stage, AuthoringExample(
            title=stage.stage, language="python", source=stage.source_template,
            entrypoint="compute" if stage.stage == "alpha" else "decide",
        )))
    examples.extend((
        ("signal", AuthoringExample(title="Momentum Alpha", language="formula", context="signal",
                                   source="rank(pct_change(close, 20))")),
        ("exposure", AuthoringExample(
            title="Common daily exposure", language="formula", context="exposure",
            source="if_else(universe_return() > 0, 1, 0.3)",
        )),
    ))
    return tuple(AuthoringReferenceEntry(
        symbol=symbol, description=example.title,
        examples=(example,),
        notes=("An executable authoring example, not a claim about profitability. "
               "Check current data readiness and diagnose your complete configuration.",),
    ) for symbol, example in examples)


def authoring_reference(
    query: AuthoringReferenceQuery,
    constraints: ResearchAuthoringConstraints,
) -> AuthoringReference:
    overview = AUTHORING_GUIDE.steps
    if query.topic == "workflow":
        entries = _workflow_entries(constraints)
    elif query.topic == "formula":
        entries = _formula_entries(constraints)
        overview = (
            "Read syntax and contexts, then query the current field/function catalog. "
            "Alpha Formulae are compiled expressions; Python strategies use "
            "a separate SDK.",
        )
    elif query.topic == "examples":
        entries = _examples(constraints)
        overview = (
            "Select an example symbol for complete source. Python examples declare the "
            "required entrypoint; Formula examples declare signal/exposure context.",
        )
    else:
        limits = constraints.python_program.model_dump(mode="json", exclude={"source_template"})
        limits.update(
            {
                "fuel": FUEL,
                "maximum_json_depth": MAX_JSON_DEPTH,
                "maximum_history_cells_per_request": HISTORY_CELLS,
                "maximum_history_cells_per_invocation": HISTORY_TOTAL_CELLS,
                "maximum_history_response_bytes_per_request": (HISTORY_RESPONSE_BYTES),
                "maximum_history_response_bytes_per_invocation": HISTORY_RESPONSE_BYTES,
                "maximum_active_signals": constraints.framework.maximum_active_signals,
                "signal_validity_sessions": (
                    constraints.framework.signal_validity_sessions.model_dump()
                ),
            }
        )
        entries = (
            *sdk_reference_entries(),
            AuthoringReferenceEntry(
                symbol="limits",
                description="Current Python environment and bounded execution limits.",
                constraints=limits,
                notes=(
                    "Only the listed installed modules are available; there is no package "
                    "installation, filesystem or network access. State accepts JSON "
                    "containers and bounded numeric arrays, with "
                    "string object keys; integers must fit ±(2**53 - 1). "
                    "Date/time is fixed to this Session's 15:00 UTC+08:00, monotonic clocks are "
                    "zero. Use data.rng addressed by date and purpose for "
                    "partition-independent randomness. No sleeping.",
                ),
            ),
        )
        overview = SDK_OVERVIEW
    entry = next((entry for entry in entries if entry.symbol == query.symbol), None)
    result = AuthoringReference(
        topic=query.topic,
        title=next(item.title for item in AUTHORING_GUIDE.topics if item.topic == query.topic),
        overview=overview,
        found=query.symbol is None or entry is not None,
        symbols=(
            tuple(
                AuthoringSymbolSummary(symbol=item.symbol, description=item.description)
                for item in entries
            )
            if entry is None
            else ()
        ),
        entry=entry,
    )
    # Fixed topics and individual symbols keep every read bounded; never silently truncate docs.
    if len(json.dumps(result.model_dump(mode="json"), ensure_ascii=False).encode()) > 64 * 1024:
        raise ValueError("Authoring reference exceeds its complete-document byte budget")
    return result
