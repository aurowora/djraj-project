from fastapi import APIRouter, Depends, HTTPException, Form, Request
from pydantic import Field, BaseModel
from pymysql import IntegrityError
from starlette import status
from starlette.responses import RedirectResponse
from starlette.templating import Jinja2Templates

from forums.db.categories import CategoryRepository, Category
from forums.db.topics import TopicRepository
from forums.db.users import User
from forums.routes.auth import current_user
from forums.routes.auth import csrf_verify
from asyncio import gather
from typing import Annotated
import regex

from forums.utils import get_category_repo, get_topic_repo, async_collect, get_templates

cat_router = APIRouter()
TOPICS_PER_PAGE = 20

_CATEGORY_ALLOWED_CHARS = regex.compile(r"$[\P{Cc}\P{Cn}\P{Cs}]+^")
CATEGORY_NAME_MAX_SIZE = 64
CATEGORY_DESC_MAX_SIZE = 128


def _assert_name_is_valid(name: str):
    """
    Raises an exception if the provided string is not a valid category name
    """
    if not (0 < len(name) <= CATEGORY_NAME_MAX_SIZE) and _CATEGORY_ALLOWED_CHARS.match(name) is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f'Category name must be between 0 and {CATEGORY_NAME_MAX_SIZE} characters.')


def _assert_desc_is_valid(desc: str):
    """
    Raises an exception if the provided string is not a valid category description
    """
    if not (0 < len(desc) <= CATEGORY_DESC_MAX_SIZE) and _CATEGORY_ALLOWED_CHARS.match(desc) is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f'Category description must be between 0 '
                                                                            f'and {CATEGORY_DESC_MAX_SIZE} characters')


@cat_router.get('/{cat_id}')
async def category_index(req: Request, cat_id: int, page: int = 1, user: User = Depends(current_user),
                         cat_repo: CategoryRepository = Depends(get_category_repo),
                         topic_repo: TopicRepository = Depends(get_topic_repo),
                         tpl: Jinja2Templates = Depends(get_templates)):
    if page < 1:
        raise HTTPException(status_code=400, detail='page number must be greater than 0')

    offset = (page - 1) * TOPICS_PER_PAGE

    cat, (total_results, topics), subcat = await gather(cat_repo.get_category_by_id(cat_id),
                                                        topic_repo.generate_category_list_data(cat_id,
                                                                                               include_hidden=user.is_moderator(),
                                                                                               limit=TOPICS_PER_PAGE,
                                                                                               skip=offset),
                                                        async_collect(cat_repo.get_subcategories_of_category(cat_id)))

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
    }

    return tpl.TemplateResponse(req, name='cat_index.html', context=ctx)


@cat_router.post('/create')
async def create_category(
        req: Request,
        name: Annotated[str, Form()], desc: Annotated[str, Form()], parent: Annotated[int | None, Form()],
        csrf_token: Annotated[str, Form()], user: User = Depends(current_user),
        cat_repo: CategoryRepository = Depends(get_category_repo)):
    # check privs
    if not user.is_moderator():
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='You do not have permission to do this.')

    csrf_verify(req, csrf_token)

    # check that the name / desc has valid chars and isnt too long
    _assert_name_is_valid(name)
    _assert_desc_is_valid(desc)

    # insert
    new_cat = Category(cat_name=name, cat_desc=desc, parent_cat=parent, id=None)

    try:
        await cat_repo.put_category(new_cat)
    except IntegrityError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='The parent category is not valid.')

    # Take them to the new category page
    if new_cat.id is None:
        raise TypeError
    return RedirectResponse(status_code=status.HTTP_303_SEE_OTHER, url=f'/categories/{new_cat.id}')


@cat_router.delete('/{cat_id}')
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


@cat_router.patch('/{cat_id}')
async def patch_category(req: Request,
                         cat_id: int, patch: CategoryPatchDesc, user: User = Depends(current_user),
                         cat_repo: CategoryRepository = Depends(get_category_repo)):
    # check priv
    if not user.is_moderator():
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Only moderators can edit categories.')

    csrf_verify(req, patch.csrf_token)

    # load category and update it according to patch
    if (cat := await cat_repo.get_category_by_id(cat_id)) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='No such category exists.')

    if patch.set_name is not None:
        _assert_name_is_valid(patch.set_name)
        cat.cat_name = patch.set_name

    if patch.set_desc is not None:
        _assert_desc_is_valid(patch.set_desc)
        cat.cat_desc = patch.set_desc

    if patch.set_parent is not None:
        if patch.set_parent < 0:
            cat.parent_cat = None
        else:
            cat.parent_cat = patch.set_parent

    # try commit
    try:
        await cat_repo.put_category(cat)
    except IntegrityError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='The parent category is not valid.')

    # todo: better integrate with the front end
    return RedirectResponse(status_code=status.HTTP_303_SEE_OTHER, url=f'/categories/{cat.id}')
