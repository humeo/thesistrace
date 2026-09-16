"""Durable execution opportunity history, owned by Researcher rather than work."""

from typing import Literal
from uuid import UUID

from thesistrace._postgres import PostgresTransaction


def record_execution_opportunity(
    transaction: PostgresTransaction,
    *,
    pool: Literal["research", "batch-research"],
    researcher_id: UUID,
) -> int:
    row = transaction.execute(
        """
        INSERT INTO researchers.execution_opportunities (pool, researcher_id, last_sequence)
        VALUES (%s, %s, nextval('researchers.execution_opportunity_sequence'))
        ON CONFLICT (pool, researcher_id) DO UPDATE
        SET last_sequence = EXCLUDED.last_sequence
        RETURNING last_sequence
        """,
        (pool, researcher_id),
    ).fetchone()
    assert row is not None
    return int(row["last_sequence"])
