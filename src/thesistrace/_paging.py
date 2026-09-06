"""Complete-record business pages; callers own ordering and authenticated cursors."""

from collections.abc import Callable

from pydantic import BaseModel

BUSINESS_PAGE_BYTES = 32 * 1024


class PageCapacityError(ValueError):
    """A record or fixed metadata violates the domain's bounded-page contract."""


def fit_page[Record, Page: BaseModel](
    records: list[Record], build: Callable[[list[Record]], Page]
) -> Page:
    """Return the largest fitting prefix, with metadata rebuilt for that prefix.

    The caller must derive its continuation from the actual last retained record.
    Neither numeric values nor record fields are transformed. Oversize single
    records are contract errors, never an empty page with a non-advancing cursor.
    """
    minimum = 1 if records else 0
    for count in range(len(records), minimum - 1, -1):
        page = build(records[:count])
        if len(page.model_dump_json().encode("utf-8")) <= BUSINESS_PAGE_BYTES:
            return page
    raise PageCapacityError("Business page exceeds its declared record or metadata limit")
