"""Version 1 API router aggregation."""

from __future__ import annotations

from fastapi import APIRouter

from backend.app.api.v1 import chargers, data_operations, frames, uploads

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(data_operations.router)
api_router.include_router(chargers.router)
api_router.include_router(frames.router)
api_router.include_router(uploads.router)

__all__ = ["api_router"]
