"""Authenticated pagination of the current Agent catalog and folder projection."""

from __future__ import annotations

import hashlib
import json
from base64 import urlsafe_b64encode
from collections.abc import Callable

from cryptography.fernet import Fernet, InvalidToken
from pydantic import BaseModel

from thesistrace._paging import fit_page
from thesistrace._postgres import PostgresDatabase


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

        return fit_page(items[offset : offset + limit], render)
