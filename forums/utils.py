from typing import Optional, AsyncGenerator, Any, Tuple, Callable, Coroutine, Awaitable, AsyncIterable

from fastapi import Request
from pydantic import BaseModel, Field

from forums.db.categories import CategoryRepository
from forums.db.topics import TopicRepository
from forums.db.users import User


def get_templates(req: Request):
    return req.app.state.tpl


def get_topic_repo(req: Request) -> TopicRepository:
    return TopicRepository(req.app.state.db)


def get_category_repo(req: Request) -> CategoryRepository:
    return CategoryRepository(req.app.state.db)


async def async_collect[T](gen: AsyncGenerator[T, None]) -> Tuple[T, ...]:
    return tuple(x async for x in gen)
