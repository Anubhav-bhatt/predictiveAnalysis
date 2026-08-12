"""Shared API response envelope and pagination types.

One envelope shape across every endpoint (``data`` / ``meta`` / ``error``) so the
frontend has a single contract to code against rather than a different shape per
route.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

__all__ = ["ApiError", "Envelope", "PageMeta", "PaginatedEnvelope", "ok", "paginated"]


class ApiError(BaseModel):
    code: str
    message: str
    details: dict[str, Any] | None = None


class PageMeta(BaseModel):
    page: int
    page_size: int
    total: int
    total_pages: int


class Envelope[T](BaseModel):
    model_config = ConfigDict(from_attributes=True)

    data: T | None = None
    meta: dict[str, Any] = Field(default_factory=dict)
    error: ApiError | None = None


class PaginatedEnvelope[T](BaseModel):
    model_config = ConfigDict(from_attributes=True)

    data: list[T]
    meta: PageMeta
    error: ApiError | None = None


def ok[T](data: T, **meta: Any) -> Envelope[T]:
    return Envelope[T](data=data, meta=dict(meta))


def paginated[T](items: list[T], meta: dict[str, int]) -> PaginatedEnvelope[T]:
    return PaginatedEnvelope[T](data=items, meta=PageMeta(**meta))
