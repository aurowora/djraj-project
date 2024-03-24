from fastapi import APIRouter
from forums.routes.auth import router as auth_router
from .pages import pages_router


def router() -> APIRouter:
    app_router = APIRouter()

    app_router.include_router(pages_router)
    app_router.include_router(auth_router, prefix='/auth')

    return app_router
