from typing import Optional

from fastapi import APIRouter, Depends, Request
from starlette import status
from starlette.responses import RedirectResponse
from starlette.templating import Jinja2Templates

from .auth import current_user, _assert_no_user, generate_csrf_token
from ..db.categories import CategoryRepository
from ..db.users import User
from forums.utils import get_templates, get_category_repo, async_collect
import re

pages_router = APIRouter()


@pages_router.get('/')
async def index(req: Request, user: User = Depends(current_user),
                         cat_repo: CategoryRepository = Depends(get_category_repo),
                         tpl: Jinja2Templates = Depends(get_templates)):
    subcat = await async_collect(cat_repo.get_subcategories_of_category(None))

    ctx = {
        'children': subcat,
        'user': user,
    }

    return tpl.TemplateResponse(req, name='index.html', context=ctx)


__ENDSWITH_PUNCT = re.compile('.*[.?!]$')


@pages_router.get('/login', dependencies=[Depends(_assert_no_user)])
def login(req: Request, error: Optional[str] = None, tpl: Jinja2Templates = Depends(get_templates), csrf_token: str = Depends(generate_csrf_token)):
    ctx = {'csrf_token': csrf_token}

    if error:
        ctx["error"] = format_error(error)

    return tpl.TemplateResponse(request=req, name='login.html', context=ctx)


@pages_router.get('/register', dependencies=[Depends(_assert_no_user)])
def register(req: Request, error: Optional[str] = None, tpl: Jinja2Templates = Depends(get_templates), csrf_token: str = Depends(generate_csrf_token)):
    ctx = {'csrf_token': csrf_token}

    if error:
        ctx["error"] = format_error(error)

    return tpl.TemplateResponse(request=req, name='register.html', context=ctx)


@pages_router.get('/new_category')
async def new_category_form(
        req: Request,
        error: Optional[str] = None,
        child_of: Optional[int] = None,
        csrf_token: str = Depends(generate_csrf_token),
        tpl: Jinja2Templates = Depends(get_templates),
        user: User = Depends(current_user),
        cat_repo: CategoryRepository = Depends(get_category_repo)
):
    if not user.is_moderator():
        return RedirectResponse(status_code=status.HTTP_303_SEE_OTHER, url='/')

    parent_cat = await cat_repo.get_category_by_id(child_of) if child_of else None

    ctx = {
        'csrf_token': csrf_token,
    }

    if parent_cat:
        ctx['parent_cat'] = parent_cat

    if error:
        ctx["error"] = format_error(error)

    return tpl.TemplateResponse(request=req, name='new_category.html', context=ctx)


def format_error(err: str):
    """
    Add a period and capitalizes the error.
    """
    err = err.capitalize()
    if __ENDSWITH_PUNCT.match(err) is None:
        err = err + '.'

    return err
