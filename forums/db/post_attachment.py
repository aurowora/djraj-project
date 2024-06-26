from datetime import datetime
from typing import Tuple, Optional, Any

from pydantic import BaseModel, Field


class PostAttachment(BaseModel):
    id: Optional[int] = Field(default=None)
    post: int
    filename: str = Field(max_length=128, min_length=0)
    author: int
    createdAt: Optional[datetime]


def _maybe_row_to_post_attachment(row: Any) -> Optional[PostAttachment]:
    if row is None:
        return None

    return PostAttachment(id=row[0], post=row[1], filename=row[2], author=row[3], createdAt=row[4])


class PostAttachmentRepository:
    def __init__(self, db):
        self.__db = db

    async def get_attachments_of_post(self, post_id: int) -> Tuple[PostAttachment, ...]:
        query = 'SELECT * FROM postsAttachments WHERE post = %s;'

        async with self.__db.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, (post_id,))
                return tuple(_maybe_row_to_post_attachment(atch) for atch in await cur.fetchall())

    async def get_attachment(self, attachment_id: int):
        async with self.__db.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute('SELECT * FROM postsAttachments WHERE id = %s;', (attachment_id, ))
                return _maybe_row_to_post_attachment(await cur.fetchone())

    async def delete_attachment(self, attachment_id: int):
        async with self.__db.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute('DELETE FROM postsAttachments WHERE id = %s;', (attachment_id, ))

    async def put_attachment(self, attachment: PostAttachment) -> int:
        async with self.__db.acquire() as conn:
            async with conn.cursor() as cur:
                if attachment.id is None:
                    # createdAt set by default func
                    await cur.execute(
                        'INSERT INTO postsAttachments (post, filename, author) VALUES (%s, %s, %s);',
                        (attachment.post, attachment.filename, attachment.author)
                    )
                    attachment.id = cur.lastrowid
                    return attachment.id
                else:
                    # createdAt deliberately excluded
                    num_rows = await cur.execute(
                        'UPDATE postsAttachments SET post = %s, filename = %s, author = %s WHERE id = %s;',
                        (attachment.post, attachment.filename, attachment.author, attachment.id)
                    )
                    if num_rows < 1:
                        raise KeyError(f'failed updating post attachment {attachment.id}: no such attachment')
                    return attachment.id
