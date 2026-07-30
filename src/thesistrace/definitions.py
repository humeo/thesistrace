import hashlib
import json
from decimal import Decimal, InvalidOperation

from thesistrace.alpha import AlphaValidationError, ParsedAlpha, validate_alpha
from thesistrace.datasets import DatasetPublisher
from thesistrace.numeric import NUMERIC_CONTRACT_ID
from thesistrace.objects import canonical_json_bytes
from thesistrace.ports import ControlMetadataPort

FIXED_COSTS = {
    "commission_rate_all_in": Decimal("0.0003"),
    "commission_min_cny": Decimal("5"),
    "stamp_duty_sell_rate": Decimal("0.0005"),
    "transfer_fee_rate": Decimal("0.00001"),
}
SEMANTIC_VERSIONS = {
    "alpha": "alpha-v1",
    "factor": "factor-v1",
    "strategy": "strategy-v1",
    "kernel": "kernel-v1",
}


class DefinitionValidationError(ValueError):
    def __init__(self, errors: list[dict[str, str]]) -> None:
        super().__init__("research definition is invalid")
        self.errors = errors


class ResearchDefinitionService:
    def __init__(
        self,
        metadata: ControlMetadataPort,
        datasets: DatasetPublisher,
    ) -> None:
        self.metadata = metadata
        self.datasets = datasets

    def create_draft(self, content: dict[str, object]) -> dict[str, object]:
        return self.metadata.create_research_draft(json_copy(content))

    def update_draft(self, draft_id: str, content: dict[str, object]) -> dict[str, object] | None:
        return self.metadata.update_research_draft(draft_id, json_copy(content))

    def request_run(
        self, draft_id: str, idempotency_key: str
    ) -> tuple[dict[str, object], dict[str, object], bool]:
        draft = self.metadata.research_draft(draft_id)
        if draft is None:
            raise KeyError(draft_id)
        content = draft["content"]
        if not isinstance(content, dict):
            raise DefinitionValidationError(
                [error("definition", "INVALID_STRUCTURE", "definition must be an object")]
            )
        frozen_content, release_id = self.validate_and_resolve(content)
        content_hash = hashlib.sha256(canonical_json_bytes(frozen_content)).hexdigest()
        return self.metadata.freeze_definition_and_create_run(
            draft_id=draft_id,
            frozen_content=frozen_content,
            content_hash=content_hash,
            dataset_release_id=release_id,
            idempotency_key=idempotency_key,
        )

    def validate_and_resolve(self, content: dict[str, object]) -> tuple[dict[str, object], str]:
        errors: list[dict[str, str]] = []
        for field in ("title", "hypothesis"):
            if not isinstance(content.get(field), str) or not str(content[field]).strip():
                errors.append(error(field, "REQUIRED", f"{field} is required"))

        release_selector = content.get("dataset_release")
        release = (
            self.metadata.latest_dataset_release()
            if release_selector == "latest"
            else self.metadata.dataset_release(str(release_selector))
            if isinstance(release_selector, str)
            else None
        )
        if release is None:
            errors.append(
                error(
                    "dataset_release",
                    "DATASET_RELEASE_NOT_FOUND",
                    "selected Dataset Release does not exist",
                )
            )

        if content.get("universe") not in {"top300", "top1000", "top2000", "top3000"}:
            errors.append(
                error("universe", "UNIVERSE_NOT_SUPPORTED", "unsupported Liquidity Universe")
            )
        if content.get("neutralization") not in {"none", "industry"}:
            errors.append(
                error(
                    "neutralization",
                    "NEUTRALIZATION_NOT_SUPPORTED",
                    "neutralization must be none or industry",
                )
            )

        parsed: ParsedAlpha | None = None
        alpha = content.get("alpha")
        expression = alpha.get("expression") if isinstance(alpha, dict) else None
        if not isinstance(expression, str):
            errors.append(error("alpha.expression", "REQUIRED", "Alpha expression is required"))
        else:
            try:
                parsed = validate_alpha(expression)
            except AlphaValidationError as validation:
                errors.extend(
                    {
                        "location": item.location,
                        "reason_code": item.reason_code,
                        "message": item.message,
                    }
                    for item in validation.issues
                )

        strategy = content.get("strategy")
        if not isinstance(strategy, dict):
            errors.append(error("strategy", "INVALID_STRUCTURE", "strategy must be an object"))
            strategy = {}
        holdings_count = strategy.get("holdings_count")
        if (
            isinstance(holdings_count, bool)
            or not isinstance(holdings_count, int)
            or not 1 <= holdings_count <= 100
        ):
            errors.append(
                error(
                    "strategy.holdings_count",
                    "HOLDINGS_COUNT_OUT_OF_RANGE",
                    "Holdings Count must be between 1 and 100",
                )
            )
        rebalance_interval = strategy.get("rebalance_interval")
        if (
            isinstance(rebalance_interval, bool)
            or not isinstance(rebalance_interval, int)
            or not 1 <= rebalance_interval <= 20
        ):
            errors.append(
                error(
                    "strategy.rebalance_interval",
                    "REBALANCE_INTERVAL_OUT_OF_RANGE",
                    "Rebalance Interval must be between 1 and 20",
                )
            )
        if str(strategy.get("initial_cash_cny")) != "10000000":
            errors.append(
                error(
                    "strategy.initial_cash_cny",
                    "INITIAL_CASH_FIXED",
                    "V1 Initial Cash must be CNY 10,000,000",
                )
            )
        if strategy.get("execution") != "next_open_full_fill":
            errors.append(
                error(
                    "strategy.execution",
                    "EXECUTION_NOT_SUPPORTED",
                    "V1 execution must be next_open_full_fill",
                )
            )

        costs = content.get("costs")
        if not isinstance(costs, dict):
            errors.append(error("costs", "INVALID_STRUCTURE", "costs must be an object"))
            costs = {}
        for name, expected in FIXED_COSTS.items():
            try:
                actual = Decimal(str(costs.get(name)))
            except (InvalidOperation, ValueError):
                actual = None
            if actual != expected:
                errors.append(
                    error(
                        f"costs.{name}",
                        "COST_CONTRACT_MISMATCH",
                        f"{name} must equal {expected}",
                    )
                )
        try:
            risk_free = Decimal(str(content.get("risk_free_rate")))
        except (InvalidOperation, ValueError):
            risk_free = None
        if risk_free != 0:
            errors.append(
                error(
                    "risk_free_rate",
                    "RISK_FREE_RATE_FIXED",
                    "V1 risk-free rate must be zero",
                )
            )

        field_bindings: list[dict[str, str]] = []
        if release is not None and parsed is not None:
            contract = self.datasets.data_contract(release)
            catalog = {
                str(item["name"]): item for item in contract["fields"] if isinstance(item, dict)
            }
            for name in parsed.field_names:
                item = catalog.get(name)
                if item is None or item.get("alpha_authorable") is not True:
                    errors.append(
                        error(
                            "alpha.expression",
                            "FIELD_UNAVAILABLE_IN_RELEASE",
                            f"{name} is unavailable in the selected Release",
                        )
                    )
                else:
                    field_bindings.append({"name": name, "field_id": str(item["field_id"])})

        if errors:
            raise DefinitionValidationError(errors)
        assert release is not None
        frozen = json_copy(content)
        frozen["dataset_release"] = str(release["id"])
        frozen["field_bindings"] = field_bindings
        frozen["numeric_execution_contract"] = NUMERIC_CONTRACT_ID
        frozen["semantic_versions"] = SEMANTIC_VERSIONS
        return frozen, str(release["id"])


def error(location: str, reason_code: str, message: str) -> dict[str, str]:
    return {"location": location, "reason_code": reason_code, "message": message}


def json_copy(value: dict[str, object]) -> dict[str, object]:
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))
