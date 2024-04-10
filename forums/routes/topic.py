from urllib.parse import urlencode

from fastapi import Form, APIRouter, Depends, HTTPException, Request
from typing import Annotated, Optional

from pydantic import BaseModel, Field
from pymysql import IntegrityError
from starlette import status
from starlette.responses import RedirectResponse, Response
from starlette.templating import Jinja2Templates

from forums.db.categories import CategoryRepository
from forums.db.posts import PostRepository, Post, POST_IS_HIDDEN
from forums.db.topics import TOPIC_ALL_FLAGS, Topic, TopicRepository, TOPIC_IS_HIDDEN, TOPIC_IS_PINNED, TOPIC_IS_LOCKED
from forums.db.users import User, IS_USER_RESTRICTED, IS_USER_MODERATOR, UserRepository, get_user_repo
from forums.models import UserAPI
from forums.routes.auth import current_user, csrf_verify, generate_csrf_token
import regex  # use instead of re for more advanced regex support

from forums.utils import get_topic_repo, get_post_repo, get_category_repo, get_templates

topic_router = APIRouter()

__TOPIC_ALLOW_MOST_CHARS = regex.compile(r"$[\P{Cc}\P{Cn}\P{Cs}]+^")
# This can be up to 2^16 since its a TEXT field, but realistically something much lower is going to be
# appropriate
MAX_TOPIC_CONTENT_LEN = 4000
# This can be no more than 100 characters
MAX_TOPIC_TITLE_LEN = 100
REPLIES_PER_PAGE = 20


@topic_router.post('/')
async def create_topic(req: Request,
                       title: Annotated[str, Form()], content: Annotated[str, Form()],
                       category: Annotated[int, Form()], create_flags: Annotated[int, Form()],
                       csrf_token: Annotated[str, Form()],
                       user: User = Depends(current_user),
                       topic_repo: TopicRepository = Depends(get_topic_repo)):
    eparams = {'child_of': str(category)}

    if user.flags & IS_USER_RESTRICTED == IS_USER_RESTRICTED:
        return RedirectResponse(status_code=status.HTTP_303_SEE_OTHER,
                                url=f'/new_topic?%s' % urlencode({
                                    'error': 'you do not have permission to post topics',
                                    **eparams
                                }))

    if not (0 < len(title) <= MAX_TOPIC_TITLE_LEN):
        return RedirectResponse(status_code=status.HTTP_303_SEE_OTHER,
                                url=f'/new_topic?%s' % urlencode({
                                    'error': f'title must be between 1 and {MAX_TOPIC_TITLE_LEN} characters',
                                    **eparams
                                }))

    if not (0 < len(content) <= MAX_TOPIC_CONTENT_LEN):
        return RedirectResponse(status_code=status.HTTP_303_SEE_OTHER,
                                url=f'/new_topic?%s' % urlencode({
                                    'error': f'post content must be between 1 and {MAX_TOPIC_CONTENT_LEN} characters',
                                    **eparams
                                }))

    if category < 0 and create_flags < 0:
        return RedirectResponse(status_code=status.HTTP_303_SEE_OTHER,
                                url=f'/new_topic?%s' % urlencode({
                                    'error': f'category and create_flags must be positive integers',
                                    **eparams
                                }))

    csrf_verify(req, csrf_token)

    # only moderators may set create flags
    create_flags = 0
    if user.is_moderator():
        create_flags = create_flags & TOPIC_ALL_FLAGS

    # Validate title and content fields
    if __TOPIC_ALLOW_MOST_CHARS.match(title) is not None or __TOPIC_ALLOW_MOST_CHARS.match(content) is not None:
        return RedirectResponse(status_code=status.HTTP_303_SEE_OTHER,
                                url=f'/new_topic?%s' % urlencode({
                                    'error': f'title or content contains illegal characters',
                                    **eparams
                                }))

    topic = Topic(topic_id=None, parent_cat=category, title=title.strip(),
                  content=content.strip(), flags=create_flags, author_id=user.user_id)

    try:
        await topic_repo.put_topic(topic)
    except IntegrityError:
        return RedirectResponse(status_code=status.HTTP_303_SEE_OTHER,
                                url=f'/new_topic?%s' % urlencode({
                                    'error': f'target category is not valid',
                                    **eparams
                                }))

    # Send the user to the topic they just created
    return RedirectResponse(status_code=status.HTTP_303_SEE_OTHER, url=f'/topic/{topic.topic_id}',
                            headers={'Cache-Control': 'no-store'})


@topic_router.get('/{topic_id}')
async def get_topic(req: Request,
                    topic_id: int,
                    page: int = 1,
                    topic_repo: TopicRepository = Depends(get_topic_repo),
                    user_repo: UserRepository = Depends(get_user_repo),
                    cat_repo: CategoryRepository = Depends(get_category_repo),
                    posts_repo: PostRepository = Depends(get_post_repo),
                    user: User = Depends(current_user),
                    tpl: Jinja2Templates = Depends(get_templates),
                    csrf_token: str = Depends(generate_csrf_token)):
    if page < 1:
        raise HTTPException(status_code=400, detail='page must be greater than 0')

    # load the topic
    if topic_id < 0:
        raise HTTPException(status_code=403, detail='Invalid topic id')
    topic = await topic_repo.get_topic_by_id(topic_id,
                                             include_hidden=user.is_moderator())

    if not topic:
        raise HTTPException(status_code=404, detail='No such topic')

    offset = (page - 1) * REPLIES_PER_PAGE

    # load user obj for author
    author = await user_repo.get_user_by_id(topic.author_id)
    if not author:
        # fake it
        author = UserAPI(user_id=None, username="deleted", display_name="Deleted User", flags=0)
    else:
        author = UserAPI.from_user(author)

    # load category obj
    category = await cat_repo.get_category_by_id(topic.parent_cat)
    if not category:
        raise HTTPException(status_code=404, detail='Category referenced by topic does not exist')

    # load posts
    (count, posts) = await posts_repo.get_posts_of_topic(topic_id, limit=REPLIES_PER_PAGE, skip=offset, include_hidden=user.is_moderator())

    # generate the breadcrumb
    bread = [(category.id, category.cat_name)]
    j = category
    while (j := j.parent_cat) is not None:
        j = await cat_repo.get_category_by_id(j)
        bread.append((j.id, j.cat_name))
    bread.reverse()

    ctx = {
        'user': user,
        'author': author,
        'topic': topic,
        'category': category,
        'posts': posts,
        'current_page': page,
        'total_pages': (count // REPLIES_PER_PAGE) + 1,
        'total_results': count,
        'base_url': f'/topic/{topic.topic_id}/',
        'csrf_token': csrf_token,
        'bread': bread,
    }

    return tpl.TemplateResponse(request=req, name='topic.html', context=ctx)


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
    set_hide: Optional[bool] = Field(default=None)

    # Moderators can set pin
    set_pin: Optional[bool] = Field(default=None)

    # topic author and moderators can set content
    set_content: Optional[str] = Field(default=None, le=2048, gt=0)

    # topic author and moderators can set title
    set_title: Optional[str] = Field(default=None, le=100, gt=0)

    # moderators can lock and unlock topics
    set_locked: Optional[bool] = Field(default=None)

    # moderators can set category
    set_category: Optional[int]


@topic_router.patch('/{topic_id}')
async def update_topic(req: Request, patch_spec: TopicPatchSpec, topic_id: int,
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

    # prohibit edits made to a locked or hidden topic by non-moderators
    if not user.is_moderator() and (topic.flags & (TOPIC_IS_HIDDEN | TOPIC_IS_LOCKED) != 0):
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
        if __TOPIC_ALLOW_MOST_CHARS.match(patch_spec.set_content):
            raise HTTPException(status_code=400, detail='Invalid content.')
        topic.content = patch_spec.set_content
        dirty = True

    # change the title
    if patch_spec.set_title is not None:
        if not (0 < len(patch_spec.set_title) <= MAX_TOPIC_TITLE_LEN):
            raise HTTPException(status_code=400, detail=f'Title must be between 0 and {MAX_TOPIC_TITLE_LEN}.')

        if __TOPIC_ALLOW_MOST_CHARS.match(patch_spec.set_title):
            raise HTTPException(status_code=400, detail='Invalid title.')
        topic.title = patch_spec.set_title
        dirty = True

    # change the category
    if patch_spec.set_category and user.is_moderator():
        topic.parent_cat = patch_spec.set_category
        dirty = True

    # lock or unlock
    if patch_spec.set_locked is not None and user.is_moderator():
        if patch_spec.set_locked:
            topic.flags |= TOPIC_IS_LOCKED
        else:
            topic.flags &= ~TOPIC_IS_LOCKED
        dirty = True

    # Commit if anything change
    if dirty:
        try:
            await topic_repo.put_topic(topic)
        except IntegrityError:
            raise HTTPException(status_code=400,
                                detail='Cannot set category of topic because the target category is not valid.')

    # TODO: figure out how to integrate this with the front end
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@topic_router.post('/{topic_id}/reply')
async def reply_to_topic(req: Request, topic_id: int, content: Annotated[str, Form()],
                         csrf_token: Annotated[str, Form()], user: User = Depends(current_user),
                         topic_repo: TopicRepository = Depends(get_topic_repo),
                         post_repo: PostRepository = Depends(get_post_repo)):
    if user.is_restricted():
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='You do not have permission to do this.')

    # csrf chk
    csrf_verify(req, csrf_token)

    # get topic
    topic = await topic_repo.get_topic_by_id(topic_id)
    if not topic:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='There is no such topic.')

    # only mods can reply to hidden / locked topics
    if (topic.flags & (TOPIC_IS_HIDDEN | TOPIC_IS_LOCKED) != 0) and not user.is_moderator():
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='You do not have permission to do this.')

    # check topic contents
    if __TOPIC_ALLOW_MOST_CHARS.match(content) is not None or not (0 < len(content) <= MAX_TOPIC_CONTENT_LEN):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail='Post content is too long or contains illegal characters.')

    # commit
    post = Post(post_id=None,
                topic_id=topic_id,
                author_id=user.user_id,
                content=content.strip(),
                created_at=None,
                flags=0)

    await post_repo.put_post(post)

    return RedirectResponse(status_code=status.HTTP_303_SEE_OTHER, url=f'/topic/{topic_id}/')


class PostPatchSpec(BaseModel):
    set_content: Optional[str]
    set_hidden: Optional[bool]

    csrf_token: str


@topic_router.patch('/{topic_id}/{post_id}')
async def edit_post(req: Request, topic_id: int, post_id: int, patch_spec: PostPatchSpec,
                    user: User = Depends(current_user), topic_repo: TopicRepository = Depends(get_topic_repo),
                    post_repo: PostRepository = Depends(get_post_repo)):
    # restricted users cannot edit posts
    if user.is_restricted():
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='You do not have permission to do this.')

    csrf_verify(req, patch_spec.csrf_token)

    # load the topic and post
    topic = await topic_repo.get_topic_by_id(topic_id)
    post = await post_repo.get_post_by_id(post_id)
    if not topic or not post:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Could not locate topic/post.')

    # only the author and moderators may edit this
    if post.author_id != user.user_id and not user.is_moderator():
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='You do not have permission to do this.')
    # if the topic or post is hidden, only a moderator can change it
    if (
            topic.flags & (TOPIC_IS_HIDDEN | TOPIC_IS_LOCKED) != 0 or post.flags & POST_IS_HIDDEN == POST_IS_HIDDEN) and not user.is_moderator():
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='You do not have permission to do this.')

    dirty = False

    if patch_spec.set_content is not None:
        if __TOPIC_ALLOW_MOST_CHARS.match(patch_spec.set_content) is not None or not (
                0 < len(patch_spec.set_content) <= MAX_TOPIC_CONTENT_LEN):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                                detail='Post content is too long or contains illegal characters.')

        post.content = patch_spec.set_content
        dirty = True

    if patch_spec.set_hidden is not None:
        if patch_spec.set_hidden:
            post.flags |= POST_IS_HIDDEN
        elif user.is_moderator():
            post.flags &= ~POST_IS_HIDDEN
        else:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='You do not have permission to do this.')
        dirty = True

    if dirty:
        await post_repo.put_post(post)

    return RedirectResponse(status_code=status.HTTP_303_SEE_OTHER, url=f'/topic/{topic_id}/')
