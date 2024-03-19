from datetime import datetime
from typing import Optional, AsyncGenerator
from aiomysql import Pool
from forums.db import mysql_date_to_python

from pydantic import BaseModel


class Post(BaseModel):
    post_id: Optional[int]
    topic_id: int
    author_id: int
    content: str
    created_at: datetime


def _maybe_row_to_post(row: dict) -> Optional[Post]:
    return Post(post_id=row["postID"], thread_id=row["threadID"], author_id=row["userID"], content=row["content"],
                created_at=mysql_date_to_python(row["createdAt"]))


class PostRepository:
    def __init__(self, db: Pool):
        self.__db = db

    async def get_post_by_id(self, post_id: int) -> Optional[Post]:
        async with self.__db.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT postID, threadID, userID, content, createdAt FROM postsTable WHERE postID = %s;",
                    (post_id,))
                return _maybe_row_to_post(await cur.fetchone())

    async def get_posts_of_topic(self, topic_id: int, limit: int = 20, skip: int = 0) -> AsyncGenerator[Post, None]:
        async with self.__db.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT postID, threadID, userID, content, createdAt FROM postsTable WHERE threadID = %s ORDER BY createdAt ASC LIMIT %s OFFSET %s;",
                    (topic_id, limit, skip))
                while row := cur.fetchone():
                    yield _maybe_row_to_post(row)

    async def put_post(self, post: Post) -> int:
        async with self.__db.acquire() as conn:
            async with conn.cursor() as cur:
                if post.post_id is None:
                    # createdAt set by default func
                    await cur.execute('INSERT INTO postsTable (threadID, userID, content) VALUES (%s, %s, %s);',
                                      (post.topic_id, post.author_id, post.content))
                    post.post_id = cur.lastrowid
                    return post.post_id
                else:
                    # createdAt deliberately excluded
                    num_rows = await cur.execute(
                        'UPDATE threadsTable SET userID = %s, threadID = %s, content = %s WHERE threadID = %s;',
                        (post.author_id, post.topic_id, post.content, post.post_id))
                    if num_rows < 1:
                        raise KeyError(f'failed updating topic {post.post_id}: no such topic')
                    return post.post_id
