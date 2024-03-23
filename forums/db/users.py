from typing import Optional

from aiomysql import Pool
from pydantic import BaseModel
from fastapi import Request


class User(BaseModel):
    """
    Represents a User in the database. This item is meant to be returned by a UserRepository.
    When constructing a new User, generally user_id must be None as the database must assign the id.
    """
    user_id: Optional[int]
    display_name: str
    username: str
    pw_hash: str
    flags: int


def _maybe_row_to_user(row: Optional[dict]) -> Optional[User]:
    return User(user_id=row["id"], username=row["MYUSER"], pw_hash=row["PASSWORD"], flags=row["flags"], display_name=row["display_name"]) if row is not None else None


class UserRepository:
    def __init__(self, db: Pool):
        self.__db = db

    async def get_user_by_id(self, user_id: int) -> Optional[User]:
        """
        Returns a User object for the user with the given user_id if such a user exists. Otherwise, returns None.
        """
        async with self.__db.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute('SELECT * FROM `loginTable` WHERE `id` = %s;', (user_id,))
                return _maybe_row_to_user(await cur.fetchone())

    async def get_user_by_name(self, username: str) -> Optional[User]:
        """
        Returns a User object for the user with the given username if such a user exists. Otherwise, returns None.
        """
        async with self.__db.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute('SELECT * FROM `loginTable` WHERE `MYUSER` = %s;', (username,))
                return _maybe_row_to_user(await cur.fetchone())

    async def put_user(self, user: User) -> int:
        """
        Persists a User into the database. If the user already exists (per user.user_id), the existing user object
        is updated. If the user does not exist (user.user_id is None), a new user object is inserted into the db

        Returns the id of the user. The given user object's user_id field is updated on insert.
        """
        async with self.__db.acquire() as conn:
            async with conn.cursor() as cur:
                if user.user_id is None:
                    # insert
                    await cur.execute('INSERT INTO `loginTable` (`MYUSER`, `PASSWORD`, `flags`, `display_name`) VALUES (%s, %s, %s, %s);', (user.username, user.pw_hash, user.flags, user.display_name))
                    user.user_id = cur.lastrowid
                    return user.user_id
                else:
                    # update
                    num_rows = await cur.execute('UPDATE `loginTable` SET `MYUSER` = %s, `PASSWORD` = %s, `flags` = %s, `display_name` = %s WHERE `id` = %s LIMIT 1;', (user.username, user.pw_hash, user.flags, user.display_name, user.user_id))
                    if num_rows < 1:
                        raise KeyError(f'failed updating user {user.username}: there is no such user with user_id {user.user_id}')
                    return user.user_id


def get_user_repo(req: Request) -> UserRepository:
    return UserRepository(req.app.state.db)
