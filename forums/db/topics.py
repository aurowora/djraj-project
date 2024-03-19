from datetime import datetime
from typing import Optional, AsyncGenerator

from aiomysql import Pool
from pydantic import BaseModel

from forums.db.utils import mysql_date_to_python, mysql_escape_like

# Bitflags for Topic
TOPIC_IS_HIDDEN = 1 << 0
TOPIC_IS_PINNED = 1 << 1


class Topic(BaseModel):
    """
    Topic represents a Topic in the database, which is a top level post created by some User (the author).

    This is generally returned by the get_* methods of the TopicRepository. When constructing a Topic, the topic_id
    and created_at fields are expected to be None so that the database may populate them. To persist a Topic to the db,
    use the TopicRepository's put_topic() method.
    """
    topic_id: Optional[int]
    author_id: int
    title: str
    content: str
    created_at: Optional[datetime]
    flags: int = 0


def _maybe_row_to_topic(row: Optional[dict]) -> Optional[Topic]:
    return Topic(topic_id=row["threadID"], author_id=row["userID"], title=row["title"], content=row["content"],
                 created_at=mysql_date_to_python(row["createdAt"]), flags=row["flags"]) if row is not None else None


class TopicRepository:
    """
    TopicRepository implements CRUD operations for Topics.
    """

    def __init__(self, db: Pool):
        self.__db = db

    async def get_topic_by_id(self, topic_id: int, include_hidden=False) -> Optional[Topic]:
        """
        Returns the topic with the given topic_id, or none if there is no such topic.
        """
        async with self.__db.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT * FROM threadsTable WHERE threadId = %s;" if include_hidden else f"SELECT * FROM threadsTable WHERE threadId = %s AND (flags & {TOPIC_IS_HIDDEN}) = 0;",
                    (topic_id,))
                return _maybe_row_to_topic(await cur.fetchone())

    async def get_topics_of_author(self, author_id: int, limit: int = 20, skip: int = 0, include_hidden=False) -> \
    AsyncGenerator[Topic, None]:
        """
        Returns a generator over all topics from the given author, sorted by the creation time. This will return
        up to `limit` topics with an offset of `skip` from the beginning of the sorted topic set.
        """
        async with self.__db.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT * FROM threadsTable WHERE authorID = %s ORDER BY createdAt DESC LIMIT %s OFFSET %s;" if include_hidden else f"SELECT * FROM threadsTable WHERE authorID = %s AND (flags & {TOPIC_IS_HIDDEN}) = 0 ORDER BY createdAt DESC LIMIT %s OFFSET %s;",
                    (author_id, limit, skip))
                while row := await cur.fetchone():
                    yield _maybe_row_to_topic(row)  # is never None

    async def search_topics(self, query: str, limit: int = 20, skip: int = 0, include_hidden=False) -> AsyncGenerator[
        Topic, None]:
        """
        Returns a generator over all topics that contain the phrase in the query, sorted by the creation time.
        This will return up to `limit` topics with an offset of `skip` from the beginning of the sorted topic set.
        """
        query = f'%{mysql_escape_like(query)}%'

        async with self.__db.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT * FROM threadsTable WHERE title LIKE %s ESCAPE '\\\\' OR content LIKE %s ESCAPE '\\\\' ORDER BY createdAt DESC LIMIT %s OFFSET %s;" if include_hidden else f"SELECT * FROM threadsTable WHERE (title LIKE %s ESCAPE '\\\\' OR content LIKE %s ESCAPE '\\\\') AND (flags & {TOPIC_IS_HIDDEN}) = 0 ORDER BY createdAt DESC LIMIT %s OFFSET %s;",
                    (query, query, limit, skip))
                while row := await cur.fetchone():
                    yield _maybe_row_to_topic(row)  # is never None

    async def put_topic(self, topic: Topic) -> int:
        """
        If the topic_id is None, this will insert the Topic into the database.

        If the topic_id is not None, this will update the existing topic.

        Returns the topic_id of the affected item.
        """
        async with self.__db.acquire() as conn:
            async with conn.cursor() as cur:
                if topic.topic_id is None:
                    # createdAt set by default func
                    await cur.execute(
                        'INSERT INTO threadsTable (userID, title, content, flags) VALUES (%s, %s, %s, %s);',
                        (topic.author_id, topic.title, topic.content, topic.flags))
                    topic.topic_id = cur.lastrowid
                    return topic.topic_id
                else:
                    # createdAt deliberately excluded
                    num_rows = await cur.execute(
                        'UPDATE threadsTable SET userID = %s, title = %s, content = %s, flags = %s WHERE threadID = %s;',
                        (topic.author_id, topic.title, topic.content, topic.flags, topic.topic_id))
                    if num_rows < 1:
                        raise KeyError(f'failed updating topic {topic.topic_id}: no such topic')
                    return topic.topic_id
