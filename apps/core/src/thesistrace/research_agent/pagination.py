"""Authenticated, stateless pagination of Agent discovery and semantic Results."""

from __future__ import annotations

import hashlib
import json
from base64 import urlsafe_b64encode
from collections.abc import Callable

from cryptography.fernet import Fernet, InvalidToken
from pydantic import BaseModel

from thesistrace._paging import BUSINESS_PAGE_BYTES, fit_page
from thesistrace._postgres import PostgresDatabase
from thesistrace.research_agent.result_pages import (
    INLINE_RESULT_BYTES,
    RESULT_FRAGMENT_BYTES,
    ResearchResultPage,
)

# These fields describe the read, not the immutable data. Preserve their first-read
# values inside the authenticated cursor; never freeze arbitrary user state fields.
_RESULT_READ_METADATA = (
    ("next_cursor",), ("expires_at",), ("unit", "last_read_at"), ("unit", "expires_at"),
)


class InvalidPageCursor(ValueError):
    pass


class ResearchAgentPagination:
    def __init__(self, secret: bytes) -> None:
        self._cipher = Fernet(urlsafe_b64encode(secret))

    @classmethod
    def from_database(cls, database: PostgresDatabase) -> ResearchAgentPagination:
        with database.transaction() as transaction:
            row = transaction.execute(
                "SELECT secret FROM research_agent.cursor_secrets WHERE singleton = 1"
            ).fetchone()
        if row is None or not isinstance(row["secret"], str):
            raise RuntimeError("Research Agent cursor secret is unavailable")
        return cls(bytes.fromhex(row["secret"]))

    def page[Item: BaseModel, Page: BaseModel](
        self,
        items: list[Item],
        *,
        identity: str,
        query: dict[str, object],
        cursor: str | None,
        limit: int,
        build: Callable[[list[Item], str | None], Page],
        byte_budget: int = BUSINESS_PAGE_BYTES,
    ) -> Page:
        if isinstance(limit, bool) or not 1 <= limit <= 50:
            raise ValueError("Page limit must be between 1 and 50")
        # A changed record/order invalidates the cursor instead of silently skipping data.
        scope = hashlib.sha256(
            json.dumps(
                {
                    "identity": identity,
                    "query": query,
                    "records": [item.model_dump(mode="json") for item in items],
                },
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        offset = 0
        if cursor is not None:
            try:
                payload = json.loads(self._cipher.decrypt(cursor.encode("ascii")))
                if not isinstance(payload, dict) or set(payload) != {"scope", "after"}:
                    raise ValueError
                offset = payload["after"]
                if (
                    payload["scope"] != scope
                    or type(offset) is not int
                    or not 0 < offset < len(items)
                ):
                    raise ValueError
            except (InvalidToken, ValueError, UnicodeError, TypeError) as error:
                raise InvalidPageCursor("Page cursor is invalid for this query") from error

        def render(kept: list[Item]) -> Page:
            after = offset + len(kept)
            next_cursor = None
            if after < len(items):
                next_cursor = self._cipher.encrypt(
                    json.dumps({"scope": scope, "after": after}, separators=(",", ":")).encode(
                        "utf-8"
                    )
                ).decode("ascii")
            return build(kept, next_cursor)

        return fit_page(items[offset : offset + limit], render, byte_budget=byte_budget)

    def result_page(
        self, result: BaseModel, *, query: BaseModel, identity: str, cursor: str | None,
    ) -> BaseModel:
        values = result.model_dump(mode="json")
        metadata = {}
        for path in _RESULT_READ_METADATA:
            parent = values if len(path) == 1 else values.get(path[0])
            if isinstance(parent, dict) and path[-1] in parent:
                metadata[".".join(path)] = parent[path[-1]]
        has_next = values.get("next_cursor") is not None
        offset = 0
        payload = None
        if cursor is not None:
            try:
                payload = json.loads(self._cipher.decrypt(cursor.encode("ascii")))
                if not isinstance(payload, dict) or set(payload) != {"scope", "after", "read"}:
                    raise ValueError
                if (not isinstance(payload["read"], dict)
                        or payload["read"].keys() != metadata.keys()):
                    raise ValueError
                offset = payload["after"]
                if type(offset) is not int or offset <= 0 or offset % RESULT_FRAGMENT_BYTES:
                    raise ValueError
                metadata = payload["read"]
            except (InvalidToken, ValueError, UnicodeError, TypeError) as error:
                raise InvalidPageCursor("Result cursor is invalid for this query") from error
            for path in _RESULT_READ_METADATA:
                key = ".".join(path)
                if key in metadata:
                    parent = values if len(path) == 1 else values[path[0]]
                    parent[path[-1]] = metadata[key]
        # ASCII makes offsets byte-exact even across Unicode escapes. Domain reads
        # still reauthorize every request; no result is cached or held by a session.
        encoded = json.dumps(values, ensure_ascii=True, allow_nan=False,
                             sort_keys=True, separators=(",", ":"))
        if len(encoded) <= INLINE_RESULT_BYTES:
            if cursor is not None:
                raise InvalidPageCursor("Result changed; restart the original section query")
            return result
        checksum = hashlib.sha256(encoded.encode("ascii")).hexdigest()
        scope = hashlib.sha256(json.dumps({
            "identity": identity, "query": query.model_dump(mode="json"),
            "checksum": checksum, "has_next": has_next,
        }, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        if payload is not None and (payload["scope"] != scope or offset >= len(encoded)):
            raise InvalidPageCursor("Result changed; restart the original section query")
        after = offset + RESULT_FRAGMENT_BYTES
        next_cursor = None
        if after < len(encoded):
            next_cursor = self._cipher.encrypt(json.dumps({
                "scope": scope, "after": after, "read": metadata,
            }, sort_keys=True, separators=(",", ":")).encode()).decode("ascii")
        return ResearchResultPage(
            result_section=query.section, json_fragment=encoded[offset:after], offset=offset,
            total_bytes=len(encoded), checksum_sha256=checksum, next_result_cursor=next_cursor,
        )
