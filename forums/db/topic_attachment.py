from datetime import datetime
from typing import Tuple, Optional, Any

from pydantic import BaseModel, Field


class TopicAttachment(BaseModel):
    id: Optional[int] = Field(default=None)
    thread: int
    filename: str = Field(lte=128, gt=0)
    author: int
    createdAt: datetime


def _maybe_row_to_topic_attachment(row: Any) -> Optional[TopicAttachment]:
    if row is None:
        return None

    return TopicAttachment(id=row[0], thread=row[1], filename=row[2], author=row[3], createdAt=row[4])


class TopicAttachmentRepository:
    def __init__(self, db):
        self.__db = db

    async def get_attachments_of_topic(self, topic_id: int) -> Tuple[TopicAttachment, ...]:
        query = 'SELECT * FROM threadAttachments WHERE thread = %s;'

        async with self.__db.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, (topic_id,))
                return tuple(_maybe_row_to_topic_attachment(atch) for atch in await cur.fetchall())

    async def get_attachment(self, attachment_id: int):
        async with self.__db.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute('SELECT * FROM threadAttachments WHERE id = %s;', (attachment_id, ))
                return _maybe_row_to_topic_attachment(await cur.fetchone())

    async def delete_attachment(self, attachment_id: int):
        async with self.__db.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute('DELETE FROM threadAttachments WHERE id = %s;', (attachment_id, ))

    async def put_topic_attachment(self, attachment: TopicAttachment) -> int:
        async with self.__db.acquire() as conn:
            async with conn.cursor() as cur:
                if attachment.id is None:
                    # createdAt set by default func
                    await cur.execute(
                        'INSERT INTO threadAttachments (thread, filename, author) VALUES (%s, %s, %s);',
                        (attachment.thread, attachment.filename, attachment.author)
                    )
                    attachment.id = cur.lastrowid
                    return attachment.id
                else:
                    # createdAt deliberately excluded
                    num_rows = await cur.execute(
                        'UPDATE threadAttachments SET thread = %s, filename = %s, author = %s WHERE id = %s;',
                        (attachment.thread, attachment.filename, attachment.author, attachment.id)
                    )
                    if num_rows < 1:
                        raise KeyError(f'failed updating topic {attachment.id}: no such topic')
                    return attachment.id
