from fastapi import APIRouter
from forums.routes.auth import router as auth_router


def router() -> APIRouter:
    api_router = APIRouter()

    api_router.include_router(auth_router, prefix='/auth')

    return api_router
