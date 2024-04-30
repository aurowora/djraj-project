from fastapi import APIRouter, Depends, HTTPException, Form, Request
from pydantic import Field, BaseModel
from pymysql import IntegrityError
from starlette import status
from starlette.responses import RedirectResponse
from starlette.templating import Jinja2Templates

from forums.db.categories import CategoryRepository, Category
from forums.db.topics import TopicRepository
from forums.db.users import User
from forums.routes.auth import current_user, generate_csrf_token
from forums.routes.auth import csrf_verify
from asyncio import gather
from typing import Annotated, Optional
import regex
from urllib.parse import urlencode
import logging

from forums.utils import get_category_repo, get_topic_repo, async_collect, get_templates

cat_router = APIRouter()
TOPICS_PER_PAGE = 20

_CAT_BAD_CHARS = regex.compile(r"$[\P{Cc}\P{Cn}\P{Cs}]+^")
CATEGORY_NAME_MAX_SIZE = 64
CATEGORY_DESC_MAX_SIZE = 128


def _name_is_valid(name: str):
    return (0 < len(name) <= CATEGORY_NAME_MAX_SIZE) and _CAT_BAD_CHARS.match(name) is None


def _desc_is_valid(desc: str):
    """
    Raises an exception if the provided string is not a valid category description
    """
    return (0 < len(desc) <= CATEGORY_DESC_MAX_SIZE) and _CAT_BAD_CHARS.match(desc) is None


@cat_router.get('/{cat_id}')
async def category_index(req: Request, cat_id: int, page: int = 1, user: User = Depends(current_user),
                         cat_repo: CategoryRepository = Depends(get_category_repo),
                         topic_repo: TopicRepository = Depends(get_topic_repo),
                         tpl: Jinja2Templates = Depends(get_templates),
                         csrf_token: str = Depends(generate_csrf_token)):
    if page < 1:
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER,
                            detail='page number must be greater than 0', headers={'Location': '/'})

    offset = (page - 1) * TOPICS_PER_PAGE

    cat, (total_results, topics), subcat, pins = await gather(cat_repo.get_category_by_id(cat_id),
                                                              topic_repo.generate_category_list_data(cat_id,
                                                                                                     include_hidden=user.is_moderator(),
                                                                                                     limit=TOPICS_PER_PAGE,
                                                                                                     skip=offset),
                                                              async_collect(
                                                                  cat_repo.get_subcategories_of_category(cat_id,
                                                                                                         include_hidden_in_cnt=user.is_moderator())),
                                                              topic_repo.get_pinned_topics(cat_id,
                                                                                           include_hidden=user.is_moderator()))

    if cat is None:
        raise HTTPException(status_code=404, detail='No such category')

    # generate the breadcrumb
    bread = [(cat.id, cat.cat_name)]
    j = cat
    while (j := j.parent_cat) is not None:
        j = await cat_repo.get_category_by_id(j)
        bread.append((j.id, j.cat_name))
    bread.reverse()

    ctx = {
        'category': cat,
        'topics': topics,
        'children': subcat,
        'current_page': page,
        'total_pages': (total_results // TOPICS_PER_PAGE) + 1,
        'total_results': total_results,
        'user': user,
        'bread': bread,
        'pins': pins,
        'csrf_token': csrf_token
    }

    return tpl.TemplateResponse(req, name='cat_index.html', context=ctx)


@cat_router.get('/{cat_id}/edit')
async def edit_category_page(req: Request, cat_id: int, error: Optional[str] = None, user: User = Depends(current_user),
                             cat_repo: CategoryRepository = Depends(get_category_repo),
                             tpl: Jinja2Templates = Depends(get_templates),
                             csrf_token: str = Depends(generate_csrf_token)):
    if not user.is_moderator():
        raise HTTPException(status_code=403, detail='You do not have permission to do this.')

    category = await cat_repo.get_category_by_id(cat_id)
    if not category:
        raise HTTPException(status_code=404, detail='No such category exists.')

    all_categories = [c for c in await cat_repo.get_all_categories() if c.id != cat_id]

    ctx = {
        'csrf_token': csrf_token,
        'user': user,
        'category': category,
        'all_categories': all_categories
    }

    if error:
        ctx['error'] = error

    return tpl.TemplateResponse(req, name='new_category.html', context=ctx)


@cat_router.post('/create')
async def create_category(
        req: Request,
        name: Annotated[str, Form()], desc: Annotated[str, Form()], csrf_token: Annotated[str, Form()],
        parent: Annotated[int | None, Form()] = None, user: User = Depends(current_user),
        cat_repo: CategoryRepository = Depends(get_category_repo)):
    eparams = {'child_of': str(parent)} if parent is not None else {}

    # check privs
    if not user.is_moderator():
        return RedirectResponse(status_code=status.HTTP_303_SEE_OTHER,
                                url=f'/new_category?%s' % urlencode({
                                    'error': 'you do not have permission to do this',
                                    **eparams
                                }))

    csrf_verify(req, csrf_token)

    # check that the name / desc has valid chars and isn't too long
    if not _name_is_valid(name):
        return RedirectResponse(status_code=status.HTTP_303_SEE_OTHER,
                                url=f'/new_category?%s' % urlencode({
                                    'error': 'the provided category name is not valid. The category name must be less than 64 characters and contain printable characters',
                                    **eparams
                                }))
    if not _desc_is_valid(name):
        return RedirectResponse(status_code=status.HTTP_303_SEE_OTHER,
                                url=f'/new_category?%s' % urlencode({
                                    'error': 'the provided category description is not valid. The category description must be less than 128 characters and contain printable characters',
                                    **eparams
                                }))

    # insert
    new_cat = Category(cat_name=name, cat_desc=desc, parent_cat=parent, id=None)

    try:
        await cat_repo.put_category(new_cat)
    except IntegrityError:
        return RedirectResponse(status_code=status.HTTP_303_SEE_OTHER,
                                url=f'/new_category?%s' % urlencode({
                                    'error': 'the parent category is not valid',
                                    **eparams
                                }))
    except Exception as e:
        logging.error('failed to create category', exc_info=e)
        return RedirectResponse(status_code=status.HTTP_303_SEE_OTHER,
                                url=f'/new_category?%s' % urlencode({
                                    'error': 'internal server error',
                                    **eparams
                                }))

    return RedirectResponse(status_code=status.HTTP_303_SEE_OTHER, url=f'/categories/{new_cat.id}')


@cat_router.get('/{cat_id}/delete')
async def delete_category(
        req: Request,
        cat_id: int,
        csrf_token: str,
        user: User = Depends(current_user),
        cat_repo: CategoryRepository = Depends(get_category_repo)):
    # check priv
    if not user.is_moderator():
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Only moderators can delete categories.')

    csrf_verify(req, csrf_token)

    # load category from db
    if (cat := await cat_repo.get_category_by_id(cat_id)) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='No such category exists.')

    try:
        await cat_repo.delete_category(cat_id)
    except IntegrityError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='The category must have no subcategories '
                                                                            'and no topics before it can be deleted.')

    # returns to the parent, if one
    if cat.parent_cat is not None:
        return RedirectResponse(status_code=status.HTTP_303_SEE_OTHER, url=f'/categories/{cat.parent_cat}')
    else:
        return RedirectResponse(status_code=status.HTTP_303_SEE_OTHER, url='/')


class CategoryPatchDesc(BaseModel):
    set_name: str | None = Field(gt=0, le=CATEGORY_NAME_MAX_SIZE)
    set_desc: str | None = Field(gt=0, le=CATEGORY_DESC_MAX_SIZE)
    # note: the meaning of this is ambiguous because in some places None indicates the root
    # but here it will indicate "do not change." As such, for this call, the root is specified using
    # any values less than 0
    set_parent: int | None

    csrf_token: str


@cat_router.post('/{cat_id}/edit')
async def patch_category(req: Request,
                         cat_id: int, name: Annotated[str, Form()], desc: Annotated[str, Form()],
                         parent: Annotated[int, Form()], csrf_token: Annotated[str, Form()],
                         user: User = Depends(current_user),
                         cat_repo: CategoryRepository = Depends(get_category_repo)):
    # check priv
    if not user.is_moderator():
        return RedirectResponse(status_code=status.HTTP_303_SEE_OTHER,
                                url=f'/categories/{cat_id}/edit?%s' % urlencode({
                                    'error': 'only moderators can edit categories'
                                }))

    csrf_verify(req, csrf_token)

    # load category and update it accordingly
    if (cat := await cat_repo.get_category_by_id(cat_id)) is None:
        return RedirectResponse(status_code=status.HTTP_303_SEE_OTHER,
                                url=f'/categories/{cat_id}/edit?%s' % urlencode({
                                    'error': 'no such category exists'
                                }))

    if not _name_is_valid(name):
        return RedirectResponse(status_code=status.HTTP_303_SEE_OTHER,
                                url=f'/categories/{cat_id}/edit?%s' % urlencode({
                                    'error': 'name is not valid'
                                }))
    if not _desc_is_valid(name):
        return RedirectResponse(status_code=status.HTTP_303_SEE_OTHER,
                                url=f'/categories/{cat_id}/edit?%s' % urlencode({
                                    'error': 'description is not valid'
                                }))

    cat.cat_name = name
    cat.cat_desc = desc
    cat.parent_cat = parent

    # try commit
    try:
        await cat_repo.put_category(cat)
    except IntegrityError:
        return RedirectResponse(status_code=status.HTTP_303_SEE_OTHER,
                                url=f'/categories/{cat_id}/edit?%s' % urlencode({
                                    'error': 'the parent category is not valid'
                                }))

    return RedirectResponse(status_code=status.HTTP_303_SEE_OTHER, url=f'/categories/{cat.id}')
