"""Handlers package."""

from aiogram import Router

from handlers.booking import router as booking_router
from handlers.fallback import router as fallback_router
from handlers.menu import router as menu_router
from handlers.portfolio import router as portfolio_router
from handlers.start import router as start_router


def setup_routers() -> Router:
    """Register all handler routers."""
    root = Router(name="root")
    root.include_router(start_router)
    root.include_router(menu_router)
    root.include_router(booking_router)
    root.include_router(portfolio_router)
    root.include_router(fallback_router)
    return root
