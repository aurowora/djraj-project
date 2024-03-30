from fastapi import Form, APIRouter, Depends, HTTPException, Request
from typing import Annotated, Optional

from pydantic import BaseModel, Field
from starlette import status
from starlette.responses import RedirectResponse, Response

from forums.db.topics import TOPIC_ALL_FLAGS, Topic, TopicRepository, TOPIC_IS_HIDDEN, TOPIC_IS_PINNED
from forums.db.users import User, IS_USER_RESTRICTED, IS_USER_MODERATOR, UserRepository, get_user_repo
from forums.routes.auth import current_user, csrf_verify
import regex  # use instead of re for more advanced regex support

from forums.utils import get_topic_repo, UserAPI

topic_router = APIRouter()

__TOPIC_ALLOW_MOST_CHARS = regex.compile(r"$[\P{Cc}\P{Cn}\P{Cs}]+^")
# This can be up to 2^16 since its a TEXT field, but realistically something much lower is going to be
# appropriate
MAX_TOPIC_CONTENT_LEN = 4000
# This can be no more than 100 characters
MAX_TOPIC_TITLE_LEN = 100


@topic_router.post('/')
async def create_topic(req: Request,
                       title: Annotated[str, Form()], content: Annotated[str, Form()],
                       category: Annotated[int, Form()], create_flags: Annotated[int, Form()],
                       csrf_token: Annotated[str, Form()],
                       user: User = Depends(current_user),
                       topic_repo: TopicRepository = Depends(get_topic_repo)):
    if user.flags & IS_USER_RESTRICTED == IS_USER_RESTRICTED:
        raise HTTPException(status_code=403, detail='Restricted users may not post new content items.')

    if not (0 < len(title) <= MAX_TOPIC_TITLE_LEN):
        raise HTTPException(status_code=400, detail=f'Title must be between 1 and {MAX_TOPIC_TITLE_LEN} characters.')

    if not (0 < len(content) <= MAX_TOPIC_CONTENT_LEN):
        raise HTTPException(status_code=400, detail=f'Post content must be between 1 and {MAX_TOPIC_CONTENT_LEN} characters.')

    if category < 0 and create_flags < 0:
        raise HTTPException(status_code=400, detail='Category and create_flags must be positive integers.')

    csrf_verify(req, csrf_token)

    # only moderators may set create flags
    create_flags = 0
    if user.is_moderator():
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


@topic_router.get('/{topic_id}')
async def get_topic(topic_id: int,
                    topic_repo: TopicRepository = Depends(get_topic_repo),
                    user_repo: UserRepository = Depends(get_user_repo),
                    user: User = Depends(current_user)):
    # load the topic
    if topic_id < 0:
        raise HTTPException(status_code=403, detail='Invalid topic id')
    topic = await topic_repo.get_topic_by_id(topic_id,
                                             include_hidden=user.is_moderator())

    if not topic:
        raise HTTPException(status_code=404, detail='No such topic')

    # load user obj for author
    author = await user_repo.get_user_by_id(topic.author_id)
    if not author:
        # fake it
        author = UserAPI(user_id=None, username="deleted", display_name="Deleted User", flags=0)
    else:
        author = UserAPI.from_user(author)

    # placeholder until template
    return f'Title: {topic.title}\nAuthor: {author.display_name}\nDate: {topic.created_at}\nContent: {topic.content}'


@topic_router.delete('/{topic_id}')
async def delete_topic(req: Request, topic_id: int, csrf_token: str, user: User = Depends(current_user),
                       topic_repo: TopicRepository = Depends(get_topic_repo)):
    # check csrf
    csrf_verify(req, csrf_token)

    # load topic
    topic = await topic_repo.get_topic_by_id(topic_id)
    if not topic:
        raise HTTPException(status_code=404, detail='No such topic')

    # check user perms
    # we only allow admins to delete topics (users can only hide their own topics)
    if user.flags & IS_USER_MODERATOR != IS_USER_MODERATOR:
        raise HTTPException(status_code=403, detail='You do not have permission to do that.')

    await topic_repo.delete_topic_by_id(topic_id)

    # TODO: When the category view is done, redirect the user to the category that the topic belonged to.
    return Response(status_code=204)


class TopicPatchSpec(BaseModel):
    csrf_token: str

    # topic author can set hide to True (apparently deleting the topic).
    # Moderators can set hide.
    set_hide: Optional[bool]

    # Moderators can set pin
    set_pin: Optional[bool]

    # topic author and moderators can set content
    set_content: Optional[str] = Field(default=None, le=2048, gt=0)

    # topic author and moderators can set title
    set_title: Optional[str] = Field(default=None, le=100, gt=0)

    # moderators can set category
    set_category: Optional[int]


@topic_router.patch('/{topic_id}')
async def update_topic(req: Request, patch_spec: TopicPatchSpec, topic_id: int = Field(ge=0),
                       topic_repo: TopicRepository = Depends(get_topic_repo),
                       user_repo: UserRepository = Depends(get_user_repo),
                       user: User = Depends(current_user)):
    csrf_verify(req, patch_spec.csrf_token)

    # load topic
    topic = await topic_repo.get_topic_by_id(topic_id)
    if topic is None:
        raise HTTPException(status_code=404, detail='No such topic.')

    # quit early if !moderator, user != author, or user.is_restricted
    if (not user.is_moderator() and user.user_id != topic.author_id) or user.is_restricted():
        raise HTTPException(status_code=403, detail='You do not have permission to do this.')

    dirty = False

    # Apply visibility change
    if patch_spec.set_hide is not None:
        if patch_spec.set_hide:
            topic.flags |= TOPIC_IS_HIDDEN
        elif user.is_moderator():
            topic.flags &= ~TOPIC_IS_HIDDEN
        else:  # the user is trying to un-hide a topic, but they are not a moderator
            raise HTTPException(status_code=403, detail='You may not un-hide this topic.')
        dirty = True

    # Pin or unpin
    if patch_spec.set_pin is not None:
        # Only a moderator may alter the pin status of a topic.
        if not user.is_moderator():
            raise HTTPException(status_code=403, detail='You may not pin or unpin this topic.')

        if patch_spec.set_pin:
            topic.flags |= TOPIC_IS_PINNED
        else:
            topic.flags &= ~TOPIC_IS_PINNED
        dirty = True

    # change the content
    # both the author and moderators are permitted to set the content
    if patch_spec.set_content:
        # validate topic length
        if not (0 < len(patch_spec.set_content) <= MAX_TOPIC_CONTENT_LEN):
            raise HTTPException(status_code=400, detail=f'Content must be between 0 and {MAX_TOPIC_CONTENT_LEN}.')

        # validate that it only contains legal characters
        if not __TOPIC_ALLOW_MOST_CHARS.match(patch_spec.set_content):
            raise HTTPException(status_code=400, detail='Invalid content.')
        topic.content = patch_spec.set_content
        dirty = True

    # change the title
    if patch_spec.set_title is not None:
        if not (0 < len(patch_spec.set_title) <= MAX_TOPIC_TITLE_LEN):
            raise HTTPException(status_code=400, detail=f'Title must be between 0 and {MAX_TOPIC_TITLE_LEN}.')

        if not __TOPIC_ALLOW_MOST_CHARS.match(patch_spec.set_title):
            raise HTTPException(status_code=400, detail='Invalid title.')
        topic.title = patch_spec.set_title
        dirty = True

    # change the category
    if patch_spec.set_category and user.is_moderator():
        topic.parent_cat = patch_spec.set_category
        dirty = True

    # Commit if anything change
    if dirty:
        await topic_repo.put_topic(topic)

    # TODO: figure out how to integrate this with the front end
    return Response(status_code=status.HTTP_204_NO_CONTENT)


