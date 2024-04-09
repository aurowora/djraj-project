from typing import Optional
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Request, HTTPException
from starlette import status
from starlette.responses import RedirectResponse
from starlette.templating import Jinja2Templates

from .auth import current_user, _assert_no_user, generate_csrf_token
from .categories import TOPICS_PER_PAGE
from ..db.categories import CategoryRepository
from ..db.topics import TopicRepository
from ..db.users import User
from forums.utils import get_templates, get_category_repo, async_collect, get_topic_repo
import re

pages_router = APIRouter()


@pages_router.get('/')
async def index(req: Request, user: User = Depends(current_user),
                         cat_repo: CategoryRepository = Depends(get_category_repo),
                         tpl: Jinja2Templates = Depends(get_templates)):
    subcat = await async_collect(cat_repo.get_subcategories_of_category(None, include_hidden_in_cnt=user.is_moderator()))

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
        'user': user,
    }

    if parent_cat:
        ctx['parent_cat'] = parent_cat

    if error:
        ctx["error"] = format_error(error)

    return tpl.TemplateResponse(request=req, name='new_category.html', context=ctx)


@pages_router.get('/new_topic')
async def new_topic_form(
        req: Request,
        child_of: int,
        error: Optional[str] = None,
        csrf_token: str = Depends(generate_csrf_token),
        tpl: Jinja2Templates = Depends(get_templates),
        cat_repo: CategoryRepository = Depends(get_category_repo),
        user: User = Depends(current_user)
):
    if (parent_cat := await cat_repo.get_category_by_id(child_of)) is None:
        return RedirectResponse(status_code=status.HTTP_303_SEE_OTHER, url='/')

    ctx = {
        'csrf_token': csrf_token,
        'parent_cat': parent_cat,
        'user': user,
    }

    if error:
        ctx["error"] = format_error(error)

    return tpl.TemplateResponse(request=req, name='new_topic.html', context=ctx)


@pages_router.get('/search')
async def search(
        req: Request,
        q: str,
        page: int = 1,
        tpl: Jinja2Templates = Depends(get_templates),
        topic_repo: TopicRepository = Depends(get_topic_repo),
        user: User = Depends(current_user)
):
    if page < 1:
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, detail='page number must be greater than 0',
                            headers={'Location': '/'})

    offset = (page - 1) * TOPICS_PER_PAGE

    (count, results) = await topic_repo.generate_search_result_data(q, limit=TOPICS_PER_PAGE, skip=offset, include_hidden=user.is_moderator())

    ctx = {
        'user': user,
        'current_page': page,
        'total_pages': (count // TOPICS_PER_PAGE) + 1,
        'total_results': count,
        'query': q,
        'base_url': '/search?%s' % urlencode({'q': q}),
        'results': results
    }

    return tpl.TemplateResponse(req, name='search.html', context=ctx)


def format_error(err: str):
    """
    Add a period and capitalizes the error.
    """
    err = err.capitalize()
    if __ENDSWITH_PUNCT.match(err) is None:
        err = err + '.'

    return err
