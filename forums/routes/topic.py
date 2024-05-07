import asyncio
import os
from urllib.parse import urlencode

from fastapi import Form, APIRouter, Depends, HTTPException, Request, UploadFile, File
from typing import Annotated, Optional, List

from pydantic import BaseModel, Field
from pymysql import IntegrityError
from starlette import status
from starlette.responses import RedirectResponse, Response, FileResponse
from starlette.templating import Jinja2Templates

from forums.blocking import spawn_blocking
from forums.db.categories import CategoryRepository
from forums.db.post_attachment import PostAttachment, PostAttachmentRepository
from forums.db.posts import PostRepository, Post, POST_IS_HIDDEN
from forums.db.topic_attachment import TopicAttachment, TopicAttachmentRepository
from forums.db.topics import TOPIC_ALL_FLAGS, Topic, TopicRepository, TOPIC_IS_HIDDEN, TOPIC_IS_PINNED, TOPIC_IS_LOCKED
from forums.db.users import User, IS_USER_RESTRICTED, IS_USER_MODERATOR, UserRepository, get_user_repo
from forums.ioutil import escape_filename, create_next_file, is_allowed_type
from forums.models import UserAPI
from forums.routes.auth import current_user, csrf_verify, generate_csrf_token
import regex  # use instead of re for more advanced regex support
import logging
from aiofiles.os import unlink as async_unlink

from forums.utils import get_topic_repo, get_post_repo, get_category_repo, get_templates, get_topic_attach_repo, \
    get_post_attach_repo

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
                       files: Annotated[List[UploadFile], File()],
                       csrf_token: Annotated[str, Form()],
                       user: User = Depends(current_user),
                       topic_repo: TopicRepository = Depends(get_topic_repo),
                       topic_attach_repo: TopicAttachmentRepository = Depends(get_topic_attach_repo)):
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
        topic_id = await topic_repo.put_topic(topic)
    except IntegrityError:
        return RedirectResponse(status_code=status.HTTP_303_SEE_OTHER,
                                url=f'/new_topic?%s' % urlencode({
                                    'error': f'target category is not valid',
                                    **eparams
                                }))

    # add the attachments
    try:
        for uploadf in files:
            if uploadf.filename != "":
                attach = await create_attachment(req, topic_id, uploadf.filename, uploadf, user.user_id)
                await topic_attach_repo.put_attachment(attach)
    except Exception as e:
        logging.error('file upload error', exc_info=e)
        return RedirectResponse(status_code=status.HTTP_303_SEE_OTHER,
                                url=f'/new_topic?%s' % urlencode({
                                    'error': f'attachment has a bad file name or bad file type',
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
                    csrf_token: str = Depends(generate_csrf_token),
                    topic_attach_repo: TopicAttachmentRepository = Depends(get_topic_attach_repo),
                    post_attach_repo: PostAttachmentRepository = Depends(get_post_attach_repo)):
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

    # load post attachments
    post_attachments = {}
    for atchs in await asyncio.gather(*[post_attach_repo.get_attachments_of_post(post.post_id) for post in posts]):
        if len(atchs) > 0:
            post_attachments[atchs[0].post] = atchs

    # generate the breadcrumb
    bread = [(category.id, category.cat_name)]
    j = category
    while (j := j.parent_cat) is not None:
        j = await cat_repo.get_category_by_id(j)
        bread.append((j.id, j.cat_name))
    bread.reverse()

    # load topic attachments
    attachments = await topic_attach_repo.get_attachments_of_topic(topic.topic_id)

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
        't_attachments': attachments,
        'p_attachments': post_attachments
    }

    return tpl.TemplateResponse(request=req, name='topic.html', context=ctx)


@topic_router.get('/{topic_id}/attachments/{attachment_id}')
async def download_attachment_of_topic(req: Request, topic_id: int, attachment_id: int, user: User = Depends(current_user),
                              topic_attach_repo: TopicAttachmentRepository = Depends(get_topic_attach_repo),
                              topic_repo: TopicRepository = Depends(get_topic_repo)):
    topic = await topic_repo.get_topic_by_id(topic_id)
    if topic is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='There is no such topic.')
    if topic.is_hidden() and not user.is_moderator():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='There is no such topic.')

    topic_attachment = await topic_attach_repo.get_attachment(attachment_id)
    if topic_attachment is None or topic_attachment.thread != topic_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='There is no such attachment.')

    fpath = os.path.join(req.app.state.cfg.storage.path, 'attachments', str(topic.topic_id), topic_attachment.filename)
    return FileResponse(path=fpath, filename=topic_attachment.filename, content_disposition_type='attachment')


@topic_router.get('/{topic_id}/{post_id}/attachments/{attachment_id}')
async def download_attachment_of_post(req: Request, topic_id: int, post_id: int, attachment_id: int, user: User = Depends(current_user), post_attach_repo: PostAttachmentRepository = Depends(get_post_attach_repo), post_repo: PostRepository = Depends(get_post_repo)):
    post = await post_repo.get_post_by_id(post_id, include_hidden=user.is_moderator())
    if post is None or post.topic_id != topic_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='There is no such post.')

    post_attachment = await post_attach_repo.get_attachment(attachment_id)
    if post_attachment is None or post_attachment.post != post_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='There is no such attachment.')

    fpath = os.path.join(req.app.state.cfg.storage.path, 'attachments', str(post.topic_id), '.posts', str(post.post_id), post_attachment.filename)
    return FileResponse(path=fpath, filename=post_attachment.filename, content_disposition_type='attachment')


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


@topic_router.post('/{topic_id}/edit')
async def update_topic(req: Request, topic_id: int, title: Annotated[str, Form()],
                       content: Annotated[str, Form()], csrf_token: Annotated[str, Form()],
                       hide: Annotated[bool, Form()] = None, pin: Annotated[bool, Form()] = None,
                       lock: Annotated[bool, Form()] = None, parent: Annotated[int, Form()] = None,
                       topic_repo: TopicRepository = Depends(get_topic_repo),
                       user: User = Depends(current_user)):
    csrf_verify(req, csrf_token)

    # load topic
    topic = await topic_repo.get_topic_by_id(topic_id, include_hidden=user.is_moderator())
    if topic is None:
        raise HTTPException(status_code=404, detail='No such topic.')

    # quit early if !moderator, user != author, or user.is_restricted
    if (not user.is_moderator() and user.user_id != topic.author_id) or user.is_restricted():
        raise HTTPException(status_code=403, detail='You do not have permission to do this.')

    # prohibit edits made to a locked or hidden topic by non-moderators
    if not user.is_moderator() and (topic.flags & (TOPIC_IS_HIDDEN | TOPIC_IS_LOCKED) != 0):
        raise HTTPException(status_code=403, detail='You do not have permission to do this.')

    if not (0 < len(content) <= MAX_TOPIC_CONTENT_LEN) and __TOPIC_ALLOW_MOST_CHARS.match(content):
        raise HTTPException(status_code=400, detail='Invalid content.')
    if not (0 < len(title) <= MAX_TOPIC_TITLE_LEN) and __TOPIC_ALLOW_MOST_CHARS.match(title):
        raise HTTPException(status_code=400, detail='Invalid title.')

    # Apply visibility change
    if user.is_moderator():
        if hide:
            topic.flags |= TOPIC_IS_HIDDEN
        else:
            topic.flags &= ~TOPIC_IS_HIDDEN
        if pin:
            topic.flags |= TOPIC_IS_PINNED
        else:
            topic.flags &= ~TOPIC_IS_PINNED
        if lock:
            topic.flags |= TOPIC_IS_LOCKED
        else:
            topic.flags &= ~TOPIC_IS_LOCKED
        topic.parent_cat = parent

    topic.title = title
    topic.content = content

    # Commit if anything change
    try:
        await topic_repo.put_topic(topic)
    except IntegrityError:
        raise HTTPException(status_code=400,
                            detail='Cannot set category of topic because the target category is not valid.')

    return RedirectResponse(status_code=status.HTTP_303_SEE_OTHER, url=f'/topic/{topic_id}')


@topic_router.post('/{topic_id}/reply')
async def reply_to_topic(req: Request, topic_id: int, content: Annotated[str, Form()],
                         files: Annotated[List[UploadFile], File()],
                         csrf_token: Annotated[str, Form()], user: User = Depends(current_user),
                         topic_repo: TopicRepository = Depends(get_topic_repo),
                         post_repo: PostRepository = Depends(get_post_repo),
                         post_attach_repo: PostAttachmentRepository = Depends(get_post_attach_repo)):
    if user.is_restricted():
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='You do not have permission to do this.')

    # csrf chk
    csrf_verify(req, csrf_token)

    # get topic
    topic = await topic_repo.get_topic_by_id(topic_id, include_hidden=user.is_moderator())
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

    # add the attachments
    try:
        for uploadf in files:
            if uploadf.filename != "":
                attach = await create_attachment(req, topic_id, uploadf.filename, uploadf, user.user_id,
                                                 post=post.post_id)
                await post_attach_repo.put_attachment(attach)
    except Exception as e:
        logging.error('file upload error', exc_info=e)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail='bad attachment.')

    return RedirectResponse(status_code=status.HTTP_303_SEE_OTHER, url=f'/topic/{topic_id}/')


class PostPatchSpec(BaseModel):
    set_content: Optional[str]
    set_hidden: Optional[bool]

    csrf_token: str


@topic_router.get('/{topic_id}/edit')
async def edit_topic_page(req: Request, topic_id: int,
                          user: User = Depends(current_user),
                          topic_repo: TopicRepository = Depends(get_topic_repo),
                          csrf_token: str = Depends(generate_csrf_token),
                          error: Optional[str] = None,
                          tpl: Jinja2Templates = Depends(get_templates),
                          cat_repo: CategoryRepository = Depends(get_category_repo)):
    if user.is_restricted() and not user.is_moderator():
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='You do not have permission to do this.')

    topic = await topic_repo.get_topic_by_id(topic_id, include_hidden=user.is_moderator())
    if not topic:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='There is no such topic.')

    if not user.is_moderator() and user.user_id != topic.author_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='You do not have permission to do this.')

    all_categories = await cat_repo.get_all_categories()

    ctx = {
        'user': user,
        'topic': topic,
        'csrf_token': csrf_token,
        'all_categories': all_categories,
    }

    if error:
        ctx['error'] = error

    return tpl.TemplateResponse(request=req, name='edit_topic.html', context=ctx)


@topic_router.get('/{topic_id}/{post_id}/edit')
async def edit_post_page(req: Request, topic_id: int, post_id: int, error: Optional[str] = None,
                         prev_page: int = 1,
                         csrf_token: str = Depends(generate_csrf_token),
                         user: User = Depends(current_user),
                         topic_repo: TopicRepository = Depends(get_topic_repo),
                         post_repo: PostRepository = Depends(get_post_repo),
                         tpl: Jinja2Templates = Depends(get_templates)):
    if user.is_restricted() and not user.is_moderator():
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='You do not have permission to do this.')

    topic = await topic_repo.get_topic_by_id(topic_id, include_hidden=user.is_restricted())
    if not topic:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='There is no such topic.')

    post = await post_repo.get_post_by_id(post_id, include_hidden=user.is_moderator())
    if not post or post.topic_id != topic_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='There is no such post.')

    if not user.is_moderator() and user.user_id != post.author_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='You do not have permission to do this.')

    ctx = {
        'user': user,
        'topic': topic,
        'post': post,
        'csrf_token': csrf_token,
        'prev_page': prev_page
    }

    if error is not None:
        ctx["error"] = error

    return tpl.TemplateResponse(request=req, name='edit_post.html', context=ctx)


@topic_router.post('/{topic_id}/{post_id}/edit')
async def edit_post(req: Request, topic_id: int, post_id: int,
                    content: Annotated[str, Form()], prev_page: Annotated[int, Form()],
                    csrf_token: Annotated[str, Form()], hide: Annotated[bool, Form()] = None,
                    user: User = Depends(current_user),
                    topic_repo: TopicRepository = Depends(get_topic_repo),
                    post_repo: PostRepository = Depends(get_post_repo)):
    csrf_verify(req, csrf_token)

    if user.is_restricted() and not user.is_moderator():
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='You do not have permission to do this.')

    topic = await topic_repo.get_topic_by_id(topic_id, include_hidden=user.is_moderator())
    if not topic:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='There is no such topic.')

    post = await post_repo.get_post_by_id(post_id, include_hidden=user.is_moderator())
    if not post or post.topic_id != topic_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='There is no such post.')

    if not user.is_moderator() and user.user_id != post.author_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='You do not have permission to do this.')

    if __TOPIC_ALLOW_MOST_CHARS.match(content) is not None or not (0 < len(content) <= MAX_TOPIC_CONTENT_LEN):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail='Post content is too long or contains illegal characters.')

    post.content = content

    if hide:
        post.flags |= POST_IS_HIDDEN
    elif user.is_moderator():
        post.flags &= ~POST_IS_HIDDEN

    await post_repo.put_post(post)

    return RedirectResponse(status_code=status.HTTP_303_SEE_OTHER, url=f'/topic/{topic_id}?page={prev_page}')


@topic_router.post('/delete_attachment')
async def detach_file(req: Request, topic_id: Annotated[int, Form()], csrf_token: Annotated[str, Form()], attachment_id: Annotated[int, Form()],
                      post_id: Annotated[Optional[int], Form()] = None, user: User = Depends(current_user),
                      topic_repo: TopicRepository = Depends(get_topic_repo), post_repo: PostRepository = Depends(get_post_repo),
                      topic_atch_repo: TopicAttachmentRepository = Depends(get_topic_attach_repo), post_atch_repo: PostAttachmentRepository = Depends(get_post_attach_repo)):
    csrf_verify(req, csrf_token)

    # load the item
    if post_id is not None:
        ent = await post_repo.get_post_by_id(post_id, include_hidden=user.is_moderator())
        # verify post is of topic
        if ent.topic_id != topic_id:
            # use the post's topic instead
            topic_id = ent.topic_id
    else:
        ent = await topic_repo.get_topic_by_id(topic_id, include_hidden=user.is_moderator())
    if ent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='There is no such entity.')

    # only moderators and the author of the item may remove attachments
    if not (ent.author_id == user.user_id or user.is_moderator()):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='You do not have permission to do this.')

    # load the attachment spec
    if post_id is not None:
        atch = await post_atch_repo.get_attachment(attachment_id)
        # verify atch is of post
        if atch.post != post_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Attachment does not belong to the specified post.')
        # delete the attachment from the listing
        await post_atch_repo.delete_attachment(attachment_id)
    else:
        atch = await topic_atch_repo.get_attachment(attachment_id)
        # verify atch is of topic
        if atch.thread != topic_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Attachment does not belong to the specified topic.')
        # delete the attachment from the listing
        await topic_atch_repo.delete_attachment(attachment_id)

    # delete the attachment from the filesystem
    path = os.path.join(req.app.state.cfg.storage.path, 'attachments', str(topic_id))
    if post_id is not None:
        path = os.path.join(path, '.posts', str(post_id))
    path = os.path.join(path, atch.filename)
    await async_unlink(path)

    return RedirectResponse(status_code=status.HTTP_303_SEE_OTHER, url=f'/topic/{topic_id}')


@topic_router.get('/{topic_id}/add_attachment')
async def attach_file_page(req: Request, topic_id: int, post_id: Optional[int] = None, error: str = None,
                           prev_page: int = 1,
                           user: User = Depends(current_user), csrf_token: str = Depends(generate_csrf_token),
                           topic_repo: TopicRepository = Depends(get_topic_repo), post_repo: PostRepository = Depends(get_post_repo),
                           tpl: Jinja2Templates = Depends(get_templates)):
    ctx = {
        'csrf_token': csrf_token,
        'prev_page': prev_page,
    }

    if post_id is not None:
        post = await post_repo.get_post_by_id(post_id, include_hidden=user.is_moderator())
        if not post:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='No such post exists.')
        ctx["post"] = post
        topic_id = post.topic_id

    topic = await topic_repo.get_topic_by_id(topic_id, include_hidden=user.is_moderator())
    if not topic:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='No such topic exists.')
    ctx["topic"] = topic

    if error is not None:
        ctx["error"] = error

    return tpl.TemplateResponse(request=req, name='add_attachment.html', context=ctx)


@topic_router.post('/{topic_id}/add_attachment')
async def attach_file(req: Request, topic_id: int, csrf_token: Annotated[str, Form()],
                      files: Annotated[List[UploadFile], File()], prev_page: Annotated[int, Form()],
                      post_id: Annotated[int, Form()] = None, user: User = Depends(current_user),
                      topic_repo: TopicRepository = Depends(get_topic_repo), post_repo: PostRepository = Depends(get_post_repo),
                      topic_atch_repo: TopicAttachmentRepository = Depends(get_topic_attach_repo),
                      post_atch_repo: PostAttachmentRepository = Depends(get_post_attach_repo)):
    if user.is_restricted() and not user.is_moderator():
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='You do not have permission to do this.')

    csrf_verify(req, csrf_token)

    topic = await topic_repo.get_topic_by_id(topic_id, include_hidden=user.is_moderator())
    if not topic:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='No such topic exists.')

    if post_id is not None:
        post = await post_repo.get_post_by_id(post_id, include_hidden=user.is_moderator())
        if not post:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='No such post exists.')

        if not user.is_moderator() and user.user_id != post.author_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='You do not have permission to do this.')
    elif not user.is_moderator() and user.user_id != topic.author_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='You do not have permission to do this.')

    # add the attachments
    try:
        for uploadf in files:
            if uploadf.filename != "":
                attach = await create_attachment(req, topic_id, uploadf.filename, uploadf, user.user_id, post=post_id)
                if post_id is not None:
                    await post_atch_repo.put_attachment(attach)
                else:
                    await topic_atch_repo.put_attachment(attach)
    except Exception as e:
        logging.error('file upload error', exc_info=e)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail='Error uploading file.')

    return RedirectResponse(url=f'/topic/{topic_id}?page={prev_page}', status_code=status.HTTP_303_SEE_OTHER)


async def create_attachment(req: Request, topic_id: int, filename: str, data: UploadFile, author: int,
                                  post: Optional[int] = None):
    """
    May raise the following exceptions:
      ValueError - Bad filename or file type
      Exception - MAX_OPEN_ATTEMPTS exceeded
      OSError - Problem opening the file for writing
    """
    sconf = req.app.state.cfg.storage

    # check that the file type is allowed
    if not is_allowed_type(sconf.allow_attach_types, data):
        raise ValueError('content type not allowed')
    await data.seek(0)

    fname = escape_filename(filename)

    (fd, fname, fpath) = await create_next_file(sconf.path, topic_id, fname, post=post)

    try:
        while (b := await data.read(512)) != b'':
            await fd.write(b)
        await fd.close()
    except Exception as e:
        await fd.close()
        await async_unlink(fpath)
        raise e

    logging.info("file upload: author = %s, topic = %s, fpath = %s, size = %s, post = %s" % (
        author, topic_id, fpath, data.size, post
    ))

    if post is None:
        return TopicAttachment(id=None, thread=topic_id, filename=fname, author=author, createdAt=None)
    else:
        return PostAttachment(id=None, post=post, filename=fname, author=author, createdAt=None)
