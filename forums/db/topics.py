from typing import Optional, AsyncGenerator

from forums.db import mysql_date_to_python, mysql_escape_like

from aiomysql import Pool
from pydantic import BaseModel
from datetime import datetime


class Topic(BaseModel):
    topic_id: Optional[int]
    author_id: int
    title: str
    content: str
    created_at: Optional[datetime]


def _maybe_row_to_topic(row: Optional[dict]) -> Optional[Topic]:
    return Topic(topic_id=row["threadID"], author_id=row["userID"], title=row["title"], content=row["content"],
                 created_at=mysql_date_to_python(row["createdAt"])) if row is not None else None


class TopicRepository:
    def __init__(self, db: Pool):
        self.__db = db

    async def get_topic_by_id(self, topic_id: int) -> Optional[Topic]:
        async with self.__db.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT threadID, userID, title, content, createdAt FROM threadsTable WHERE threadId = %s;",
                    (topic_id,))
                return _maybe_row_to_topic(await cur.fetchone())

    async def get_topics_of_author(self, author_id: int, limit: int = 20, skip: int = 0) -> AsyncGenerator[Topic, None]:
        async with self.__db.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT threadID, userID, title, content, createdAt FROM threadsTable WHERE authorID = %s ORDER BY title ASC LIMIT %s OFFSET %s;",
                    (author_id, limit, skip))
                while row := await cur.fetchone():
                    yield _maybe_row_to_topic(row)  # is never None

    async def search_topics(self, query: str, limit: int = 20, skip: int = 0) -> AsyncGenerator[Topic, None]:
        query = f'%{mysql_escape_like(query)}%'

        async with self.__db.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT threadID, userID, title, content, createdAt FROM threadsTable WHERE title LIKE %s ESCAPE '\\\\' OR content LIKE %s ESCAPE '\\\\' ORDER BY title ASC LIMIT %s OFFSET %s;",
                    (query, query, limit, skip)
                )
                while row := await cur.fetchone():
                    yield _maybe_row_to_topic(row)  # is never None

    async def put_topic(self, topic: Topic) -> int:
        async with self.__db.acquire() as conn:
            async with conn.cursor() as cur:
                if topic.topic_id is None:
                    # createdAt set by default func
                    await cur.execute('INSERT INTO threadsTable (userID, title, content) VALUES (%s, %s, %s);',
                                      (topic.author_id, topic.title, topic.content))
                    topic.topic_id = cur.lastrowid
                    return topic.topic_id
                else:
                    # createdAt deliberately excluded
                    num_rows = await cur.execute(
                        'UPDATE threadsTable SET userID = %s, title = %s, content = %s WHERE threadID = %s;',
                        (topic.author_id, topic.title, topic.content, topic.topic_id))
                    if num_rows < 1:
                        raise KeyError(f'failed updating topic {topic.topic_id}: no such topic')
                    return topic.topic_id
