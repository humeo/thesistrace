from decimal import Decimal

import pytest
from pydantic import BaseModel

from thesistrace._paging import PageCapacityError, fit_page


class Record(BaseModel):
    id: int
    text: str
    metric: Decimal


class Page(BaseModel):
    items: list[Record]
    next_cursor: str | None


def test_utf8_budget_keeps_complete_records_and_cursor_after_actual_last_item() -> None:
    records = [
        Record(id=i, text="研究" * 1500, metric=Decimal("0.123456789123456789")) for i in range(8)
    ]
    page = fit_page(
        records,
        lambda kept: Page(
            items=kept,
            next_cursor=str(kept[-1].id) if len(kept) < len(records) else None,
        ),
    )
    assert 0 < len(page.items) < len(records)
    assert len(page.model_dump_json().encode("utf-8")) <= 32 * 1024
    assert page.items == records[: len(page.items)]
    assert page.next_cursor == str(page.items[-1].id)
    assert page.items[0].metric == Decimal("0.123456789123456789")
    assert records[0].text == "研究" * 1500


def test_metadata_is_included_and_oversize_record_never_returns_empty_continuation() -> None:
    oversized = [Record(id=0, text="中" * 12000, metric=Decimal("1"))]
    with pytest.raises(PageCapacityError):
        fit_page(oversized, lambda kept: Page(items=kept, next_cursor="resume"))
    with pytest.raises(PageCapacityError):
        fit_page([], lambda kept: Page(items=kept, next_cursor="x" * (32 * 1024)))
    assert fit_page([], lambda kept: Page(items=kept, next_cursor=None)).items == []
