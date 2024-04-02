from fastapi import APIRouter, Depends, HTTPException, Form, Request
from starlette import status
from starlette.responses import RedirectResponse

from forums.db.categories import CategoryRepository, Category
from forums.db.topics import TopicRepository
from forums.db.users import User
from forums.routes.auth import current_user
from forums.routes.auth import csrf_verify
from asyncio import gather
from typing import Annotated
import regex

from forums.utils import get_category_repo, get_topic_repo, async_collect

cat_router = APIRouter()
TOPICS_PER_PAGE = 20

_CATEGORY_ALLOWED_CHARS = regex.compile(r"$[\P{Cc}\P{Cn}\P{Cs}]+^")
CATEGORY_NAME_MAX_SIZE = 64
CATEGORY_DESC_MAX_SIZE = 128


@cat_router.get('/{cat_id}')
async def category_index(cat_id: int, page: int, user: User = Depends(current_user),
                         cat_repo: CategoryRepository = Depends(get_category_repo),
                         topic_repo: TopicRepository = Depends(get_topic_repo)):
    if page < 1:
        raise HTTPException(status_code=400, detail='page number must be greater than 0')

    offset = (page - 1) * TOPICS_PER_PAGE

    cat, (total_results, topics), subcat = await gather(cat_repo.get_category_by_id(cat_id),
                                                        topic_repo.get_topics_of_category(cat_id,
                                                                                          include_hidden=user.is_moderator(),
                                                                                          limit=TOPICS_PER_PAGE,
                                                                                          skip=offset),
                                                        async_collect(cat_repo.get_subcategories_of_category(cat_id)))

    if cat is None:
        raise HTTPException(status_code=404, detail='No such category')

    # TODO: Render template once one exists
    raise NotImplemented


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
    if not (0 < len(name) <= CATEGORY_NAME_MAX_SIZE) and _CATEGORY_ALLOWED_CHARS.match(name) is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f'Category name must be between 0 and {CATEGORY_NAME_MAX_SIZE} characters.')
    if not (0 < len(desc) <= CATEGORY_DESC_MAX_SIZE) and _CATEGORY_ALLOWED_CHARS.match(desc) is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f'Category description must be between 0 '
                                                                            f'and {CATEGORY_DESC_MAX_SIZE} characters')

    # insert
    new_cat = Category(cat_name=name, cat_desc=desc, parent_cat=parent, id=None)

    # todo catch fk vio
    await cat_repo.put_category(new_cat)

    # Take them to the new category page
    if new_cat.id is None:
        raise TypeError
    return RedirectResponse(status_code=status.HTTP_303_SEE_OTHER, url=f'/categories/{new_cat.id}')


@cat_router.delete('/{cat_id}')
async def delete_category(cat_id: int, csrf_token: str, user: User = Depends(current_user)):
    raise NotImplemented


@cat_router.patch('/{cat_id}')
async def patch_category(cat_id: int, user: User = Depends(current_user)):
    raise NotImplemented
