from typing import Optional

from fastapi import APIRouter, Depends, Request
from starlette.templating import Jinja2Templates

from .auth import current_user, _assert_no_user, generate_csrf_token
from ..db.users import User
from forums.utils import get_templates

pages_router = APIRouter()


@pages_router.get('/')
async def index(user: User = Depends(current_user)) -> str:
    return f'Hello, {user.username}!'


@pages_router.get('/login', dependencies=[Depends(_assert_no_user)])
def login(req: Request, error: Optional[str] = None, tpl: Jinja2Templates = Depends(get_templates), csrf_token: str = Depends(generate_csrf_token)):
    ctx = {'csrf_token': csrf_token}

    if error:
        ctx["error"] = error

    return tpl.TemplateResponse(request=req, name='login.html', context=ctx)


@pages_router.get('/register', dependencies=[Depends(_assert_no_user)])
def register(req: Request, error: Optional[str] = None, tpl: Jinja2Templates = Depends(get_templates), csrf_token: str = Depends(generate_csrf_token)):
    ctx = {'csrf_token': csrf_token}

    if error:
        ctx["error"] = error

    print(ctx)

    return tpl.TemplateResponse(request=req, name='register.html', context=ctx)
