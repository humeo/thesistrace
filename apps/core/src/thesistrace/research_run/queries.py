"""Owned collection predicates and ordering shared by Web and MCP queries."""

import hashlib
import json
import math
from collections.abc import Mapping
from datetime import datetime
from uuid import UUID

from cryptography.fernet import Fernet, InvalidToken

from thesistrace.research_run.models import ResearchRunQuery


def query_fingerprint(query: ResearchRunQuery) -> str:
    values = query.model_dump(mode="json")
    # AND is order-independent; equivalent condition order can continue a query.
    values["metric_filters"] = sorted(
        values["metric_filters"],
        key=lambda item: (item["metric"], item["operator"], item["value"]),
    )
    return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()


def query_predicates(researcher_id: UUID, query: ResearchRunQuery) -> tuple[str, list[object]]:
    clauses = ["researcher_id = %s"]
    values: list[object] = [researcher_id]
    for expression, value in (
        ("folder_id", query.folder_id),
        ("immutable_input->>'research_kind'", query.research_kind),
        ("status", query.status),
        ("immutable_input->>'universe'", query.universe),
    ):
        if value is not None:
            clauses.append(f"{expression} = %s")
            values.append(value)
    if query.research_period is not None:
        clauses.extend(["requested_start_date = %s", "requested_end_date = %s"])
        values.extend([query.research_period.start_date, query.research_period.end_date])
    if query.search is not None:
        pattern = "%" + query.search.replace("!", "!!").replace("%", "!%").replace("_", "!_") + "%"
        clauses.append("(lower(name) LIKE lower(%s) ESCAPE '!' "
                       "OR search_notes LIKE lower(%s) ESCAPE '!' "
                       "OR search_formula LIKE lower(%s) ESCAPE '!')")
        values.extend([pattern] * 3)
    operators = {"gt": ">", "gte": ">=", "lt": "<", "lte": "<="}
    for condition in query.metric_filters:
        clauses.append(f"(key_metrics->>'{condition.metric}')::double precision "
                       f"{operators[condition.operator]} %s")
        values.append(condition.value)
    return " AND ".join(clauses), values


def sort_expression(query: ResearchRunQuery) -> str:
    return ("created_at" if query.sort_by == "created_at"
            else f"(key_metrics->>'{query.sort_by}')::double precision")


def query_order(query: ResearchRunQuery, prefix: str = "") -> str:
    direction = "ASC" if query.sort_direction == "ascending" else "DESC"
    primary = f"{prefix}sort_value {direction} NULLS LAST"
    secondary = "" if query.sort_by == "created_at" else f", {prefix}created_at DESC"
    return f"{primary}{secondary}, {prefix}id ASC"


def encode_cursor(row: Mapping[str, object], cipher: Fernet,
                  researcher_id: UUID, query: ResearchRunQuery) -> str:
    value = row["sort_value"]
    payload = {"version": 1, "researcher": str(researcher_id),
               "query": query_fingerprint(query), "id": row["id"],
               "created_at": row["created_at"].isoformat(),
               "value": value.isoformat() if isinstance(value, datetime) else value}
    return cipher.encrypt(json.dumps(payload, separators=(",", ":")).encode()).decode("ascii")


def cursor_predicate(cursor: str | None, cipher: Fernet, researcher_id: UUID,
                     query: ResearchRunQuery) -> tuple[str, list[object]]:
    if cursor is None:
        return "true", []
    try:
        payload = json.loads(cipher.decrypt(cursor.encode("ascii")))
        if (not isinstance(payload, dict)
                or set(payload) != {"version", "researcher", "query", "id", "created_at", "value"}
                or payload["version"] != 1 or payload["researcher"] != str(researcher_id)
                or payload["query"] != query_fingerprint(query)
                or not isinstance(payload["id"], str) or not payload["id"]):
            raise ValueError
        created_at = datetime.fromisoformat(payload["created_at"])
        if created_at.tzinfo is None:
            raise ValueError
        value = payload["value"]
        if query.sort_by == "created_at":
            value = datetime.fromisoformat(value)
            if value != created_at:
                raise ValueError
        elif value is not None and (type(value) not in (int, float) or not math.isfinite(value)):
            raise ValueError
    except (InvalidToken, ValueError, TypeError, KeyError, UnicodeError) as error:
        raise ValueError("ResearchRun cursor is invalid") from error
    comparison = ">" if query.sort_direction == "ascending" else "<"
    if query.sort_by == "created_at":
        return (f"(sort_value {comparison} %s OR (sort_value = %s AND id > %s))",
                [value, value, payload["id"]])
    tie = "(created_at < %s OR (created_at = %s AND id > %s))"
    ties = [created_at, created_at, payload["id"]]
    if value is None:
        return f"(sort_value IS NULL AND {tie})", ties
    return (f"(sort_value IS NULL OR sort_value {comparison} %s "
            f"OR (sort_value = %s AND {tie}))", [value, value, *ties])
