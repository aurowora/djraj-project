from datetime import datetime
from typing import Tuple, Optional, Any

from pydantic import BaseModel, Field


class PostAttachment(BaseModel):
    id: Optional[int] = Field(default=None)
    post: int
    filename: str = Field(lte=128, gt=0)
    author: int
    createdAt: datetime


def _maybe_row_to_post_attachment(row: Any) -> Optional[PostAttachment]:
    if row is None:
        return None

    return PostAttachment()


class PostAttachmentRepository:
    def __init__(self, db):
        self.__db = db

    async def get_attachments_of_topic(self, post_id: int) -> Tuple[PostAttachment, ...]:
        query = 'SELECT * FROM postAttachments WHERE post = %s;'

        async with self.__db.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, (post_id,))
                return tuple(_maybe_row_to_post_attachment(atch) for atch in await cur.fetchall())

    async def put_topic_attachment(self, attachment: PostAttachment) -> int:
        async with self.__db.acquire() as conn:
            async with conn.cursor() as cur:
                if attachment.id is None:
                    # createdAt set by default func
                    await cur.execute(
                        'INSERT INTO postAttachments (post, filename, author) VALUES (%s, %s, %s);',
                        (attachment.post, attachment.filename, attachment.author)
                    )
                    attachment.id = cur.lastrowid
                    return attachment.id
                else:
                    # createdAt deliberately excluded
                    num_rows = await cur.execute(
                        'UPDATE postAttachments SET post = %s, filename = %s, author = %s WHERE id = %s;',
                        (attachment.post, attachment.filename, attachment.author, attachment.id)
                    )
                    if num_rows < 1:
                        raise KeyError(f'failed updating post attachment {attachment.id}: no such attachment')
                    return attachment.id
