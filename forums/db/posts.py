from datetime import datetime
from typing import Optional, AsyncGenerator, Tuple

from aiomysql import Pool, Connection
from pydantic import BaseModel

from forums.db.utils import mysql_date_to_python
from forums.models import UserAPI

# Post flags
POST_IS_HIDDEN = 1 << 0


class Post(BaseModel):
    post_id: Optional[int]
    topic_id: int
    author_id: int
    content: str
    created_at: Optional[datetime]
    flags: int

    def is_hidden(self):
        return self.flags & POST_IS_HIDDEN == POST_IS_HIDDEN


_ROW_SPEC = 'postID, threadID, userID, content, createdAt, flags'
_ROW = Tuple[int, int, int, str, str, str, int]


def _maybe_row_to_post(row: Optional[_ROW]) -> Optional[Post]:
    return Post(post_id=row[0], topic_id=row[1], author_id=row[2], content=row[3],
                created_at=mysql_date_to_python(row[4]), flags=row[5]) if row is not None else None


class PostWithAuthor(BaseModel):
    post_id: Optional[int]
    topic_id: int
    author: UserAPI
    content: str
    created_at: Optional[datetime]
    flags: int

    def is_hidden(self):
        return self.flags & POST_IS_HIDDEN == POST_IS_HIDDEN


def _maybe_row_to_post_author(row: Optional[tuple]) -> Optional[PostWithAuthor]:
    author = UserAPI(user_id=row[6], username=row[8], display_name=row[7], flags=row[9])

    return PostWithAuthor(post_id=row[0], topic_id=row[1], author=author, content=row[3],
                created_at=mysql_date_to_python(row[4]), flags=row[5]) if row is not None else None


class PostRepository:
    def __init__(self, db: Pool):
        self.__db = db

    async def get_post_by_id(self, post_id: int, include_hidden=False) -> Optional[Post]:
        async with self.__db.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    f"SELECT * FROM postsTable WHERE postID = %s;" if include_hidden else f"SELECT {_ROW_SPEC} FROM postsTable WHERE postID = %s AND (flags & {POST_IS_HIDDEN}) = 0;",
                    (post_id,))
                return _maybe_row_to_post(await cur.fetchone())

    async def get_posts_of_topic(self, topic_id: int, limit: int = 20, skip: int = 0, include_hidden=False) -> \
    Tuple[int, Tuple[PostWithAuthor, ...]]:

        where_clause = 'WHERE threadID = %s' if include_hidden else f'WHERE threadID = %s AND (P.flags & {POST_IS_HIDDEN}) = 0'
        result_query = f'''
        SELECT P.postID, P.threadID, P.userID, P.content, P.createdAt, P.flags, A.id, A.display_name, A.MYUSER, A.flags
        FROM postsTable AS P JOIN loginTable AS A ON P.userID = A.id
        {where_clause}
        ORDER BY createdAt ASC, postID ASC
        LIMIT %s OFFSET %s;
        '''

        count_query = f'SELECT COUNT(P.postID) FROM postsTable AS P JOIN loginTable AS A ON P.userID = A.id {where_clause};'

        async with self.__db.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(count_query, (topic_id, ))
                total_results = (await cur.fetchone())[0]

                await cur.execute(
                    result_query,
                    (topic_id, limit, skip))

                return total_results, tuple(_maybe_row_to_post_author(post) for post in await cur.fetchall())

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
                        (post.topic_id, post.author_id, post.content, 0))
                    post.post_id = cur.lastrowid
                    return post.post_id
                else:
                    # createdAt deliberately excluded
                    num_rows = await cur.execute(
                        'UPDATE postsTable SET userID = %s, threadID = %s, content = %s, flags = %s WHERE postID = %s;',
                        (post.author_id, post.topic_id, post.content, post.flags, post.post_id))
                    if num_rows < 1:
                        raise KeyError(f'failed updating topic {post.post_id}: no such topic')
                    return post.post_id
