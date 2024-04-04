from datetime import datetime
from typing import Optional, AsyncGenerator, Tuple

from aiomysql import Pool, Connection
from pydantic import BaseModel

from forums.db.utils import mysql_date_to_python

# Post flags
POST_IS_HIDDEN = 1 << 0


class Post(BaseModel):
    post_id: Optional[int]
    topic_id: int
    author_id: int
    content: str
    created_at: Optional[datetime]
    flags: int


_ROW_SPEC = 'postID, threadID, userID, content, createdAt, flags'
_ROW = Tuple[int, int, int, str, str, str, int]


def _maybe_row_to_post(row: Optional[_ROW]) -> Optional[Post]:
    return Post(post_id=row[0], thread_id=row[1], author_id=row[2], content=row[3],
                created_at=mysql_date_to_python(row[4]), flags=row[5]) if row is not None else None


class PostRepository:
    def __init__(self, db: Pool):
        self.__db = db

    async def get_post_by_id(self, post_id: int, include_hidden=False) -> Optional[Post]:
        async with self.__db.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    f"SELECT {_ROW_SPEC} FROM postsTable WHERE postID = %s;" if include_hidden else f"SELECT {_ROW_SPEC} FROM postsTable WHERE postID = %s AND (flags & {POST_IS_HIDDEN}) = 0;",
                    (post_id,))
                return _maybe_row_to_post(await cur.fetchone())

    async def get_posts_of_topic(self, topic_id: int, limit: int = 20, skip: int = 0, include_hidden=False) -> \
    AsyncGenerator[Post, None]:
        async with self.__db.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    f"SELECT {_ROW_SPEC} FROM postsTable WHERE threadID = %s ORDER BY createdAt ASC LIMIT %s OFFSET %s;" if include_hidden else f"SELECT {_ROW_SPEC} FROM postsTable WHERE threadID = %s AND (flags & {POST_IS_HIDDEN}) = 0 ORDER BY createdAt ASC LIMIT %s OFFSET %s;",
                    (topic_id, limit, skip))
                while row := cur.fetchone():
                    yield _maybe_row_to_post(row)

    @classmethod
    async def _delete_all_posts_of_topic(cls, conn: Connection, topic_id: int) -> int:
        """
        Internal "friend" function of TopicRepository used to delete all posts of a certain topic
        """
        async with conn.cursor() as cur:
            return await cur.execute('DELETE FROM postsTable WHERE threadID = %s;', topic_id)

    async def put_post(self, post: Post) -> int:
        async with self.__db.acquire() as conn:
            async with conn.cursor() as cur:
                if post.post_id is None:
                    # createdAt set by default func
                    await cur.execute(
                        'INSERT INTO postsTable (threadID, userID, content, flags) VALUES (%s, %s, %s, %s);',
                        (post.topic_id, post.author_id, post.content))
                    post.post_id = cur.lastrowid
                    return post.post_id
                else:
                    # createdAt deliberately excluded
                    num_rows = await cur.execute(
                        'UPDATE threadsTable SET userID = %s, threadID = %s, content = %s, flags = %s WHERE threadID = %s;',
                        (post.author_id, post.topic_id, post.content, post.flags, post.post_id))
                    if num_rows < 1:
                        raise KeyError(f'failed updating topic {post.post_id}: no such topic')
                    return post.post_id
