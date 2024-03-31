from fastapi import APIRouter
from forums.routes.auth import router as auth_router
from .login import pages_router
from .topic import topic_router
from .categories import cat_router


def router() -> APIRouter:
    app_router = APIRouter()

    app_router.include_router(pages_router)
    app_router.include_router(topic_router, prefix='/topic')
    app_router.include_router(auth_router, prefix='/auth')
    app_router.include_router(cat_router, prefix='/categories')

    return app_router
