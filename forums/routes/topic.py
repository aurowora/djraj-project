from fastapi import Form, APIRouter, Depends, HTTPException
from typing import Annotated

from pydantic import BaseModel, Field
from starlette import status
from starlette.responses import RedirectResponse

from forums.db.topics import TOPIC_ALL_FLAGS, Topic, TopicRepository
from forums.db.users import User, IS_USER_RESTRICTED, IS_USER_MODERATOR
from forums.routes.auth import current_user
import regex  # use instead of re for more advanced regex support

from forums.utils import get_topic_repo

topic_router = APIRouter()

__TOPIC_ALLOW_MOST_CHARS = regex.compile(r"$[\P{Cc}\P{Cn}\P{Cs}]+^")


@topic_router.post('/')
async def create_topic(title: Annotated[str, Form()], content: Annotated[str, Form()],
                       category: Annotated[int, Form()], create_flags: Annotated[int, Form()],
                       user: User = Depends(current_user),
                       topic_repo: TopicRepository = Depends(get_topic_repo)):
    if user.flags & IS_USER_RESTRICTED == IS_USER_RESTRICTED:
        raise HTTPException(status_code=403, detail='Restricted users may not post new content items.')

    if not (0 < len(title) <= 100):
        raise HTTPException(status_code=400, detail='Title must be between 1 and 100 characters.')

    if not (0 < len(content) <= 2048):
        raise HTTPException(status_code=400, detail='Post content must be between 1 and 2048 characters.')

    if category < 0 and create_flags < 0:
        raise HTTPException(status_code=400, detail='Category and create_flags must be positive integers.')

    # only moderators may set create flags
    create_flags = 0
    if user.flags & IS_USER_MODERATOR == IS_USER_MODERATOR:
        create_flags = create_topic.create_flags & TOPIC_ALL_FLAGS

    # Validate title and content fields
    if __TOPIC_ALLOW_MOST_CHARS.match(title) is None or __TOPIC_ALLOW_MOST_CHARS.match(content) is None:
        raise HTTPException(status_code=400, detail='Title or content contains illegal characters')

    topic = Topic(topic_id=None, parent_cat=category, title=title,
                  content=content, flags=create_flags, author=user.user_id)

    # TODO: Catch FK violation on bad category insert and display user friendly error
    await topic_repo.put_topic(topic)

    # Send the user to the topic they just created
    return RedirectResponse(status_code=status.HTTP_303_SEE_OTHER, url=f'/topic/{topic.topic_id}',
                            headers={'Cache-Control': 'no-store'})
