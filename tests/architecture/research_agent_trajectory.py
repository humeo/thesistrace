from __future__ import annotations

import json
from collections import Counter, deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from hashlib import sha256
from uuid import UUID

from jsonschema import ValidationError, validate
from mcp.types import CallToolResult, TextContent, Tool

EFFECTFUL_TOOLS = frozenset(
    {
        "cancel_research_batch",
        "cancel_research_run",
        "retry_daily_track",
        "start_daily_track",
        "stop_daily_track",
        "submit_research_batch",
        "submit_research_run",
    }
)

POLL_TARGET = {
    "cancel_research_batch": "get_research_batch",
    "cancel_research_run": "get_research_run",
    "get_daily_track": "get_daily_track",
    "get_research_batch": "get_research_batch",
    "get_research_run": "get_research_run",
    "retry_daily_track": "get_daily_track",
    "start_daily_track": "get_daily_track",
    "stop_daily_track": "get_daily_track",
    "submit_research_batch": "get_research_batch",
    "submit_research_run": "get_research_run",
}
KNOWN_TOOL_NAMES = frozenset(POLL_TARGET) | frozenset(POLL_TARGET.values()) | frozenset(
    {
        "diagnose_alpha_formula",
        "get_alpha_catalog",
        "get_daily_track_result",
        "get_research_context",
        "get_research_run_result",
        "list_daily_tracks",
        "list_research_batches",
        "list_research_runs",
    }
)


PUBLIC_PRODUCT_STATES = frozenset(
    {
        "authoring_input_rejected",
        "batch_cancelled",
        "batch_succeeded",
        "daily_track_stopped",
        "daily_track_up_to_date",
        "research_results_ready",
    }
)
MAX_FAILURE_DIAGNOSTIC_BYTES = 32 * 1024


def public_tools(tools: Iterable[Tool]) -> dict[str, Tool]:
    return {tool.name: tool for tool in tools}


def tool_result(outcome: Mapping[str, object]) -> CallToolResult:
    structured = dict(outcome)
    return CallToolResult(
        content=[
            TextContent(
                type="text",
                text=json.dumps(
                    structured,
                    ensure_ascii=True,
                    separators=(",", ":"),
                    sort_keys=True,
                ),
            )
        ],
        structured_content=structured,
        is_error="code" in structured,
        meta={
            "thesistrace/tool-outcome": (
                "failed" if "code" in structured else "succeeded"
            )
        },
    )


@dataclass(frozen=True)
class CallTool:
    name: str
    arguments: Mapping[str, object]


@dataclass(frozen=True)
class WaitForRetry:
    seconds: int


@dataclass(frozen=True)
class RefreshAuthorization:
    pass


@dataclass(frozen=True)
class RediscoverTools:
    pass


@dataclass(frozen=True)
class Finish:
    artifacts: Mapping[str, object]
    product_state: str


type ModelAction = CallTool | WaitForRetry | RefreshAuthorization | RediscoverTools | Finish


class ScriptedFakeModel:
    """A fixed response sequence, not a probabilistic model or text assertion surface."""

    def __init__(self, actions: Iterable[ModelAction]) -> None:
        self._actions = deque(actions)

    def next_action(self, _last_public_observation: Mapping[str, object] | None) -> ModelAction:
        if not self._actions:
            raise AssertionError("scripted model exhausted before Finish")
        return self._actions.popleft()


class TransportFailure(RuntimeError):
    pass


class ConnectionDropped(TransportFailure):
    pass


class AuthorizationExpired(TransportFailure):
    pass


@dataclass(frozen=True)
class ScriptedExchange:
    tool_name: str
    arguments: Mapping[str, object]
    outcome: CallToolResult | Mapping[str, object] | TransportFailure

    def __post_init__(self) -> None:
        if isinstance(self.outcome, Mapping):
            object.__setattr__(self, "outcome", tool_result(self.outcome))


class ScriptedPublicMCP:
    """Schema-validating public MCP transport with deterministic faults and grants."""

    def __init__(
        self,
        *,
        tools_by_grant: Iterable[Mapping[str, Tool]],
        exchanges: Iterable[ScriptedExchange],
        mode: str = "stdio",
    ) -> None:
        self._grants = tuple(dict(tools) for tools in tools_by_grant)
        if not self._grants:
            raise ValueError("at least one authorization grant is required")
        self._grant_index = 0
        self._exchanges = deque(exchanges)
        self.mode = mode
        self.discovery_count = 0
        self.refresh_count = 0
        self.public_call_count = 0

    def discover(self) -> dict[str, Tool]:
        self.discovery_count += 1
        return dict(self._grants[self._grant_index])

    def refresh_authorization(self) -> None:
        if self.mode != "streamable_http":
            raise AssertionError("authorization refresh only applies to streamable HTTP")
        if self._grant_index + 1 >= len(self._grants):
            raise AssertionError("no scripted refreshed authorization grant")
        self._grant_index += 1
        self.refresh_count += 1

    def call(self, name: str, arguments: Mapping[str, object]) -> CallToolResult:
        self.public_call_count += 1
        if not self._exchanges:
            raise AssertionError(f"unexpected public Tool call: {name}")
        exchange = self._exchanges.popleft()
        if exchange.tool_name != name or dict(exchange.arguments) != dict(arguments):
            raise AssertionError(
                "public Tool call did not match scripted exchange: "
                f"expected {exchange.tool_name} fields={sorted(exchange.arguments)}, "
                f"got {name} fields={sorted(arguments)}"
            )
        if isinstance(exchange.outcome, TransportFailure):
            raise exchange.outcome
        result = exchange.outcome
        if not isinstance(result, CallToolResult):
            raise AssertionError("scripted exchange did not produce a CallToolResult")
        if result.structured_content is None:
            raise AssertionError("public CallToolResult omitted structuredContent")
        if result.is_error != ("code" in result.structured_content):
            raise AssertionError("public CallToolResult isError disagrees with structuredContent")
        text_blocks = [block for block in result.content if isinstance(block, TextContent)]
        if len(text_blocks) != 1:
            raise AssertionError("public CallToolResult must contain one text envelope")
        if json.loads(text_blocks[0].text) != result.structured_content:
            raise AssertionError("public CallToolResult text and structuredContent disagree")
        return result

    def assert_exhausted(self) -> None:
        if self._exchanges:
            raise AssertionError(f"{len(self._exchanges)} scripted public exchanges were unused")


@dataclass(frozen=True)
class TrajectoryResult:
    artifacts: Mapping[str, object]
    product_state: str
    virtual_time_seconds: int
    step_count: int
    public_call_count: int
    estimated_cost_units: float
    poll_counts: Mapping[str, int]
    trajectory: tuple[Mapping[str, object], ...]


class TrajectoryFailure(AssertionError):
    pass


class DeterministicTrajectoryHarness:
    def __init__(
        self,
        *,
        model: ScriptedFakeModel,
        transport: ScriptedPublicMCP,
        seed: int,
        fixed_uuid: str,
        max_steps: int = 80,
        max_public_calls: int = 50,
        max_poll_calls: int = 12,
        max_virtual_time_seconds: int = 300,
    ) -> None:
        self.model = model
        self.transport = transport
        self.seed = seed
        self.fixed_uuid = str(UUID(fixed_uuid))
        self.max_steps = max_steps
        self.max_public_calls = max_public_calls
        self.max_poll_calls = max_poll_calls
        self.max_virtual_time_seconds = max_virtual_time_seconds
        self.virtual_time_seconds = 0
        self.trajectory: list[dict[str, object]] = []
        self.tool_envelopes: list[dict[str, object]] = []
        self.trace_ids: list[str] = []
        self.poll_counts: Counter[str] = Counter()
        self._contracts: dict[str, Tool] = {}
        self._authorization_expired = False
        self._rediscovery_required = False
        self._required_replay: tuple[str, dict[str, object]] | None = None
        self._required_wait: tuple[str, int] | None = None
        self._permanent_failures: set[tuple[str, str]] = set()
        self._last_public_observation: dict[str, object] | None = None
        self._run_statuses: dict[str, str] = {}
        self._batch_statuses: dict[str, str] = {}
        self._track_statuses: dict[str, str] = {}
        self._track_phases: dict[str, str] = {}
        self._track_retry_eligibility: dict[str, bool] = {}
        self._available_sections: dict[str, tuple[str, ...]] = {}
        self._observed_result_sections: set[tuple[str, str]] = set()
        self._next_cursors: dict[tuple[str, str, str], str | None] = {}
        self._page_counts: Counter[str] = Counter()
        self._batch_child_order: dict[str, tuple[str, ...]] = {}
        self._context_loaded = False
        self._formula_invalid_seen = False
        self._formula_valid_seen = False
        self._research_submitted = False
        self._permanent_error_codes: set[str] = set()

    def run(self) -> TrajectoryResult:
        try:
            self._contracts = self.transport.discover()
            self.trajectory.append(
                {"action": "discover", "tool_count": len(self._contracts)}
            )
            for step in range(1, self.max_steps + 1):
                action = self.model.next_action(self._last_public_observation)
                finished = self._apply(action)
                if finished is not None:
                    self.transport.assert_exhausted()
                    if self._required_replay is not None:
                        raise AssertionError(
                            "trajectory finished before required idempotent replay"
                        )
                    if self._authorization_expired or self._rediscovery_required:
                        raise AssertionError("trajectory finished with expired Tool discovery")
                    return TrajectoryResult(
                        artifacts=finished.artifacts,
                        product_state=finished.product_state,
                        virtual_time_seconds=self.virtual_time_seconds,
                        step_count=step,
                        public_call_count=self.transport.public_call_count,
                        estimated_cost_units=self._estimated_cost_units(),
                        poll_counts=dict(self.poll_counts),
                        trajectory=tuple(self.trajectory),
                    )
            raise AssertionError(f"trajectory exceeded max_steps={self.max_steps}")
        except Exception as error:
            if isinstance(error, TrajectoryFailure):
                raise
            raise TrajectoryFailure(self._failure_diagnostic(error)) from error

    def _apply(self, action: ModelAction) -> Finish | None:
        if isinstance(action, Finish):
            self._validate_finish(action)
            self.trajectory.append(
                {
                    "action": "finish",
                    "artifact_keys": sorted(action.artifacts),
                    "product_state": action.product_state,
                }
            )
            return action
        if isinstance(action, WaitForRetry):
            if action.seconds < 0:
                raise AssertionError("virtual wait cannot be negative")
            self.virtual_time_seconds += action.seconds
            if self.virtual_time_seconds > self.max_virtual_time_seconds:
                raise AssertionError(
                    "trajectory exceeded "
                    f"max_virtual_time_seconds={self.max_virtual_time_seconds}"
                )
            if self._required_wait is not None:
                tool_name, remaining = self._required_wait
                self._required_wait = (tool_name, max(0, remaining - action.seconds))
            self.trajectory.append({"action": "wait", "seconds": action.seconds})
            return None
        if isinstance(action, RefreshAuthorization):
            if not self._authorization_expired:
                raise AssertionError("authorization refresh was selected without token expiry")
            self.transport.refresh_authorization()
            self._authorization_expired = False
            self._rediscovery_required = True
            self.trajectory.append({"action": "refresh_authorization"})
            return None
        if isinstance(action, RediscoverTools):
            if not self._rediscovery_required:
                raise AssertionError("Tool rediscovery was selected without a changed grant")
            self._contracts = self.transport.discover()
            self._rediscovery_required = False
            self.trajectory.append(
                {"action": "rediscover", "tool_count": len(self._contracts)}
            )
            return None
        self._call_tool(action)
        return None

    def _call_tool(self, action: CallTool) -> None:
        if self._authorization_expired:
            raise AssertionError("Agent must refresh authorization after token expiry")
        if self._rediscovery_required:
            raise AssertionError("Agent must rediscover Tools after authorization refresh")
        arguments = dict(action.arguments)
        self._validate_outcome_driven_selection(action.name, arguments)
        if self._required_replay is not None:
            required_name, required_arguments = self._required_replay
            if action.name != required_name or arguments != required_arguments:
                raise AssertionError(
                    "effectful transport failure requires the exact same Tool, arguments, "
                    "and request_id"
                )
        fingerprint = (action.name, _canonical(arguments))
        if fingerprint in self._permanent_failures:
            raise AssertionError("Agent retried a permanent Tool error")
        if self._required_wait is not None:
            wait_tool, remaining = self._required_wait
            if action.name == wait_tool and remaining > 0:
                raise AssertionError(
                    f"Agent polled {action.name} before retry_after_seconds elapsed"
                )
            if action.name == wait_tool:
                self._required_wait = None

        contract = self._contracts.get(action.name)
        if contract is None:
            safe_name = _safe_tool_name(action.name)
            self._last_public_observation = {
                "code": "FORBIDDEN",
                "retryable": False,
                "tool_name": safe_name,
            }
            self.trajectory.append(
                {"action": "local_rejection", "tool": safe_name, "code": "FORBIDDEN"}
            )
            return
        _validate_public_envelope(arguments, contract.input_schema, envelope="input")
        if action.name.startswith("get_") and action.name in POLL_TARGET:
            self.poll_counts[action.name] += 1
            if self.poll_counts[action.name] > self.max_poll_calls:
                raise AssertionError(
                    f"trajectory exceeded max_poll_calls={self.max_poll_calls} for {action.name}"
                )
        if self.transport.public_call_count >= self.max_public_calls:
            raise AssertionError(f"trajectory exceeded max_public_calls={self.max_public_calls}")

        try:
            result = self.transport.call(action.name, arguments)
        except AuthorizationExpired:
            self._authorization_expired = True
            self._last_public_observation = {"transport_error": "token_expired"}
            self.trajectory.append(
                {"action": "tool", "tool": action.name, "outcome": "token_expired"}
            )
            self.tool_envelopes.append(
                {"tool": action.name, "input_fields": sorted(arguments), "fault": "token_expired"}
            )
            return
        except ConnectionDropped as error:
            if action.name not in EFFECTFUL_TOOLS:
                raise AssertionError(
                    "connection replay contract is only asserted for effectful Tools"
                ) from error
            self._required_replay = (action.name, arguments)
            self._last_public_observation = {"transport_error": "connection_dropped"}
            self.trajectory.append(
                {"action": "tool", "tool": action.name, "outcome": "connection_dropped"}
            )
            self.tool_envelopes.append(
                {
                    "tool": action.name,
                    "input_fields": sorted(arguments),
                    "fault": "connection_dropped",
                }
            )
            return

        outcome = dict(result.structured_content or {})
        if contract.output_schema is None:
            raise AssertionError("public Tool omitted outputSchema")
        _validate_public_envelope(outcome, contract.output_schema, envelope="output")
        self._last_public_observation = outcome
        if self._required_replay is not None:
            self._required_replay = None
        retry_after = outcome.get("retry_after_seconds")
        if isinstance(retry_after, int):
            wait_target = (
                action.name
                if outcome.get("code") == "TEMPORARILY_UNAVAILABLE"
                else POLL_TARGET.get(action.name)
            )
            if wait_target is not None:
                self._required_wait = (wait_target, retry_after)
        if outcome.get("code") not in {None, "TEMPORARILY_UNAVAILABLE"}:
            self._permanent_failures.add(fingerprint)
            self._permanent_error_codes.add(str(outcome["code"]))
        trace_id = outcome.get("trace_id")
        if isinstance(trace_id, str):
            self.trace_ids.append(trace_id)
        self._observe_outcome(action.name, arguments, outcome)
        sanitized = _sanitize_outcome(outcome)
        self.trajectory.append({"action": "tool", "tool": action.name, **sanitized})
        self.tool_envelopes.append(
            {
                "tool": action.name,
                "input_fields": sorted(arguments),
                "output_fields": sorted(outcome),
                **sanitized,
            }
        )

    def _validate_outcome_driven_selection(
        self,
        tool_name: str,
        arguments: Mapping[str, object],
    ) -> None:
        if tool_name in {"submit_research_run", "submit_research_batch"}:
            if self._formula_invalid_seen and not self._formula_valid_seen:
                raise AssertionError("Agent submitted research before Formula correction")
        if tool_name == "retry_daily_track":
            track_id = arguments.get("track_id")
            if not isinstance(track_id, str):
                return
            if self._track_statuses.get(track_id) != "blocked":
                raise AssertionError("Agent selected DailyTrack Retry outside blocked state")
            if self._track_retry_eligibility.get(track_id) is not True:
                raise AssertionError("Agent ignored DailyTrack Retry action eligibility")
        if tool_name not in {"get_research_run_result", "get_daily_track_result"}:
            return
        resource_key = "run_id" if tool_name == "get_research_run_result" else "track_id"
        resource_id = arguments.get(resource_key)
        section = arguments.get("section")
        if not isinstance(resource_id, str) or not isinstance(section, str):
            return
        page_key = (tool_name, resource_id, section)
        provided_cursor = arguments.get("cursor")
        if page_key not in self._next_cursors:
            if provided_cursor is not None:
                raise AssertionError("Agent started Result paging from an unobserved cursor")
            return
        expected_cursor = self._next_cursors[page_key]
        if expected_cursor is None:
            raise AssertionError("Agent requested a Result page after the terminal page")
        if provided_cursor != expected_cursor:
            raise AssertionError("Agent did not follow the returned Result cursor")

    def _observe_outcome(
        self,
        tool_name: str,
        arguments: Mapping[str, object],
        outcome: Mapping[str, object],
    ) -> None:
        if tool_name == "get_research_context" and "code" not in outcome:
            self._context_loaded = True
        if tool_name == "diagnose_alpha_formula" and "valid" in outcome:
            if outcome["valid"] is True:
                self._formula_valid_seen = True
            else:
                self._formula_invalid_seen = True
        if (
            tool_name in {"submit_research_run", "submit_research_batch"}
            and outcome.get("outcome") == "accepted"
        ):
            self._research_submitted = True

        direct_status = outcome.get("status")
        if isinstance(outcome.get("run_id"), str) and isinstance(direct_status, str):
            self._run_statuses[str(outcome["run_id"])] = direct_status
        if isinstance(outcome.get("batch_id"), str) and isinstance(direct_status, str):
            self._batch_statuses[str(outcome["batch_id"])] = direct_status
        if isinstance(outcome.get("track_id"), str) and isinstance(direct_status, str):
            self._track_statuses[str(outcome["track_id"])] = direct_status

        resource_id = outcome.get("id")
        if tool_name == "get_research_run" and isinstance(resource_id, str):
            status = outcome.get("status")
            if isinstance(status, str):
                self._run_statuses[resource_id] = status
            sections = outcome.get("available_result_sections")
            if isinstance(sections, list) and all(isinstance(item, str) for item in sections):
                self._available_sections[resource_id] = tuple(sections)
        if tool_name == "get_research_batch" and isinstance(resource_id, str):
            status = outcome.get("status")
            if isinstance(status, str):
                self._batch_statuses[resource_id] = status
            self._observe_batch_items(resource_id, outcome)
        if tool_name == "get_daily_track" and isinstance(resource_id, str):
            status = outcome.get("status")
            if isinstance(status, str):
                self._track_statuses[resource_id] = status
            progress = outcome.get("progress")
            if isinstance(progress, Mapping) and isinstance(progress.get("phase"), str):
                self._track_phases[resource_id] = str(progress["phase"])
            eligibility = outcome.get("action_eligibility")
            if isinstance(eligibility, Mapping) and isinstance(eligibility.get("retry"), bool):
                self._track_retry_eligibility[resource_id] = bool(eligibility["retry"])
        batch = outcome.get("batch")
        if isinstance(batch, Mapping) and isinstance(batch.get("id"), str):
            batch_id = str(batch["id"])
            if isinstance(batch.get("status"), str):
                self._batch_statuses[batch_id] = str(batch["status"])
            self._observe_batch_items(batch_id, batch)

        if tool_name not in {"get_research_run_result", "get_daily_track_result"}:
            return
        resource_key = "run_id" if tool_name == "get_research_run_result" else "track_id"
        resource_id = outcome.get(resource_key)
        section = outcome.get("section")
        if not isinstance(resource_id, str) or not isinstance(section, str):
            return
        self._observed_result_sections.add((resource_id, section))
        if "next_cursor" in outcome:
            page_key = (tool_name, resource_id, section)
            next_cursor = outcome["next_cursor"]
            self._next_cursors[page_key] = next_cursor if isinstance(next_cursor, str) else None
            self._page_counts[tool_name] += 1

    def _observe_batch_items(
        self,
        batch_id: str,
        outcome: Mapping[str, object],
    ) -> None:
        items = outcome.get("items")
        if not isinstance(items, list):
            return
        ordered: list[tuple[int, str]] = []
        for item in items:
            if not isinstance(item, Mapping):
                continue
            ordinal = item.get("ordinal")
            run_id = item.get("research_run_id")
            if isinstance(ordinal, int) and isinstance(run_id, str):
                ordered.append((ordinal, run_id))
        if ordered:
            ordinals = [ordinal for ordinal, _ in ordered]
            if ordinals != sorted(ordinals):
                raise AssertionError("Research Batch items were not ordered by ordinal")
            self._batch_child_order[batch_id] = tuple(run_id for _, run_id in ordered)

    def _validate_finish(self, action: Finish) -> None:
        if action.product_state not in PUBLIC_PRODUCT_STATES:
            raise AssertionError("Scripted model returned an unknown Product State")
        allowed_artifacts = {
            "batch_id",
            "child_result_sections",
            "context_loaded",
            "formula_submitted",
            "ordered_child_run_ids",
            "result_pages",
            "result_sections",
            "run_ids",
            "track_id",
        }
        if not set(action.artifacts) <= allowed_artifacts:
            raise AssertionError("Scripted model returned unknown artifact fields")
        if action.product_state == "research_results_ready":
            run_ids = tuple(action.artifacts.get("run_ids", ()))
            runs_are_terminal = all(
                self._run_statuses.get(str(run_id)) == "succeeded" for run_id in run_ids
            )
            if not run_ids or not runs_are_terminal:
                raise AssertionError("Finish did not match observed succeeded ResearchRuns")
            sections = tuple(action.artifacts.get("result_sections", ()))
            if not sections or any(
                not any(
                    observed_run == run_id and observed_section == section
                    for observed_run, observed_section in self._observed_result_sections
                )
                for run_id, section in zip(run_ids, sections, strict=True)
            ):
                raise AssertionError("Finish did not match observed ResearchRun Result sections")
            if any(
                section not in self._available_sections.get(str(run_id), ())
                for run_id, section in zip(run_ids, sections, strict=True)
            ):
                raise AssertionError("Finish claimed a Result section not advertised at terminal")
            if any(cursor is not None for cursor in self._next_cursors.values()):
                raise AssertionError("Finish left a ResearchRun Result cursor unread")
        elif action.product_state == "batch_succeeded":
            batch_id = str(action.artifacts.get("batch_id", ""))
            if self._batch_statuses.get(batch_id) != "succeeded":
                raise AssertionError("Finish did not match observed succeeded Research Batch")
            expected_order = tuple(action.artifacts.get("ordered_child_run_ids", ()))
            if self._batch_child_order.get(batch_id) != expected_order:
                raise AssertionError("Finish did not preserve observed Research Batch item order")
            child_sections = tuple(action.artifacts.get("child_result_sections", ()))
            if not all(
                (run_id, section) in self._observed_result_sections
                for run_id, section in zip(expected_order, child_sections, strict=False)
            ):
                raise AssertionError("Finish claimed an unread child ResearchRun Result")
        elif action.product_state == "batch_cancelled":
            batch_id = str(action.artifacts.get("batch_id", ""))
            if self._batch_statuses.get(batch_id) != "cancelled":
                raise AssertionError("Finish did not match observed cancelled Research Batch")
        elif action.product_state == "daily_track_up_to_date":
            track_id = str(action.artifacts.get("track_id", ""))
            if self._track_phases.get(track_id) != "up_to_date":
                raise AssertionError("Finish did not match observed DailyTrack Product State")
            expected_pages = action.artifacts.get("result_pages")
            if expected_pages != self._page_counts["get_daily_track_result"]:
                raise AssertionError("Finish did not match observed DailyTrack Result pages")
            if any(cursor is not None for cursor in self._next_cursors.values()):
                raise AssertionError("Finish left a DailyTrack Result cursor unread")
        elif action.product_state == "daily_track_stopped":
            track_id = str(action.artifacts.get("track_id", ""))
            if self._track_statuses.get(track_id) != "stopped":
                raise AssertionError("Finish did not match observed stopped DailyTrack")
        elif action.product_state == "authoring_input_rejected":
            if not self._context_loaded or "INVALID_INPUT" not in self._permanent_error_codes:
                raise AssertionError("Finish did not match observed permanent authoring rejection")
            if action.artifacts.get("context_loaded") is not self._context_loaded:
                raise AssertionError("Finish did not match observed Research Context state")
            if action.artifacts.get("formula_submitted") is not self._research_submitted:
                raise AssertionError("Finish did not match observed research submission state")

    def _estimated_cost_units(self) -> float:
        return (
            float(self.transport.public_call_count)
            + self.transport.discovery_count * 0.25
            + self.transport.refresh_count * 0.25
        )

    def _failure_diagnostic(self, error: Exception) -> str:
        diagnostic = {
            "error_type": type(error).__name__,
            "error_digest": sha256(str(error).encode()).hexdigest()[:16],
            "seed": self.seed,
            "fixed_uuid": self.fixed_uuid,
            "max_steps": self.max_steps,
            "max_public_calls": self.max_public_calls,
            "max_poll_calls": self.max_poll_calls,
            "max_virtual_time_seconds": self.max_virtual_time_seconds,
            "virtual_time_seconds": self.virtual_time_seconds,
            "trajectory": self.trajectory,
            "tool_envelopes": self.tool_envelopes,
            "trace_ids": self.trace_ids,
            "sanitized_state": {
                "authorization_expired": self._authorization_expired,
                "rediscovery_required": self._rediscovery_required,
                "replay_required": self._required_replay is not None,
                "wait_required": self._required_wait,
                "remaining_exchange_count": len(self.transport._exchanges),
            },
        }
        encoded = json.dumps(diagnostic, ensure_ascii=True, sort_keys=True)
        if len(encoded.encode()) <= MAX_FAILURE_DIAGNOSTIC_BYTES:
            return encoded
        bounded = {
            **{
                key: value
                for key, value in diagnostic.items()
                if key not in {"trajectory", "tool_envelopes"}
            },
            "trajectory": self.trajectory[-8:],
            "tool_envelopes": self.tool_envelopes[-8:],
            "diagnostic_truncated": True,
        }
        encoded = json.dumps(bounded, ensure_ascii=True, sort_keys=True)
        if len(encoded.encode()) <= MAX_FAILURE_DIAGNOSTIC_BYTES:
            return encoded
        minimal = {
            "error_type": type(error).__name__,
            "error_digest": sha256(str(error).encode()).hexdigest()[:16],
            "seed": self.seed,
            "fixed_uuid": self.fixed_uuid,
            "diagnostic_truncated": True,
        }
        return json.dumps(minimal, ensure_ascii=True, sort_keys=True)


def _canonical(value: Mapping[str, object]) -> str:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


def _safe_tool_name(value: str) -> str:
    if value in KNOWN_TOOL_NAMES:
        return value
    digest = sha256(value.encode()).hexdigest()[:16]
    return f"unknown_tool_{digest}"


def _validate_public_envelope(
    value: Mapping[str, object],
    schema: Mapping[str, object],
    *,
    envelope: str,
) -> None:
    try:
        validate(value, schema)
    except ValidationError as error:
        path = ".".join(str(part) for part in error.absolute_path) or "<root>"
        raise AssertionError(
            f"public Tool {envelope} failed JSON Schema at {path} "
            f"({error.validator})"
        ) from None


def _sanitize_outcome(outcome: Mapping[str, object]) -> dict[str, object]:
    sanitized: dict[str, object] = {}
    for key in (
        "outcome",
        "code",
        "status",
        "section",
        "run_id",
        "batch_id",
        "track_id",
        "replayed",
        "retry_after_seconds",
        "trace_id",
    ):
        if key in outcome:
            sanitized[key] = outcome[key]
    if "next_cursor" in outcome:
        sanitized["next_cursor_present"] = outcome["next_cursor"] is not None
    if "available_result_sections" in outcome:
        sanitized["available_result_sections"] = outcome["available_result_sections"]
    if "items" in outcome and isinstance(outcome["items"], list):
        sanitized["item_count"] = len(outcome["items"])
    return sanitized
