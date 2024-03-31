from fastapi import APIRouter, Depends, HTTPException
from starlette import status

from forums.db.categories import CategoryRepository
from forums.db.topics import TopicRepository
from forums.db.users import User
from forums.routes.auth import current_user
from forums.routes.auth import csrf_verify
from asyncio import gather

from forums.utils import get_category_repo, get_topic_repo, async_collect

cat_router = APIRouter()
TOPICS_PER_PAGE = 20


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
async def create_category():
    raise NotImplemented


@cat_router.delete('/{cat_id}')
async def delete_category(cat_id: int, user: User = Depends(current_user)):
    raise NotImplemented


@cat_router.patch('/{cat_id}')
async def patch_category(cat_id: int, user: User = Depends(current_user)):
    raise NotImplemented
