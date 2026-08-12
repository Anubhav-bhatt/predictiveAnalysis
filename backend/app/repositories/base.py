"""Repository foundations.

Repositories are the only place that builds SQL. Services orchestrate them;
API routes never touch a session directly.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

__all__ = ["Page", "PageRequest", "Repository", "paginate"]


@dataclass(frozen=True, slots=True)
class PageRequest:
    page: int = 1
    page_size: int = 50

    def normalised(self, *, max_page_size: int) -> PageRequest:
        return PageRequest(
            page=max(1, self.page),
            page_size=max(1, min(self.page_size, max_page_size)),
        )

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


@dataclass(frozen=True, slots=True)
class Page[T]:
    items: Sequence[T]
    total: int
    page: int
    page_size: int

    @property
    def total_pages(self) -> int:
        if self.page_size <= 0:
            return 0
        return (self.total + self.page_size - 1) // self.page_size

    def meta(self) -> dict[str, int]:
        return {
            "page": self.page,
            "page_size": self.page_size,
            "total": self.total,
            "total_pages": self.total_pages,
        }


async def paginate(
    session: AsyncSession,
    statement: sa.Select[Any],
    request: PageRequest,
) -> Page[Any]:
    """Run a count and a windowed fetch for one statement."""
    count_stmt = sa.select(sa.func.count()).select_from(statement.subquery())
    total = int((await session.execute(count_stmt)).scalar_one())
    rows = await session.execute(statement.limit(request.page_size).offset(request.offset))
    return Page(
        items=list(rows.scalars().unique().all()),
        total=total,
        page=request.page,
        page_size=request.page_size,
    )


class Repository:
    """Base class holding the session."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
