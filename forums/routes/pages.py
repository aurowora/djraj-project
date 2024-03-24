from fastapi import APIRouter, Depends
from .auth import current_user
from ..db.users import User

pages_router = APIRouter()


@pages_router.get('/')
async def index(user: User = Depends(current_user)) -> str:
    return f'Hello, {user.username}!'
