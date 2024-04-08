from typing import Optional, AsyncGenerator, Tuple

from pydantic import BaseModel
from aiomysql import Pool


class Category(BaseModel):
    id: Optional[int]
    cat_name: str
    cat_desc: str
    parent_cat: Optional[int]


_ROW_SPEC = 'id, cat_name, cat_desc, parent_cat'
_ROW = Tuple[int, str, str, int]


def _maybe_row_to_category(row: Optional[_ROW]) -> Optional[Category]:
    return Category(id=row[0], cat_name=row[1], cat_desc=row[2], parent_cat=row[3]) if row is not None else None


class CategoryRepository:
    def __init__(self, db: Pool):
        self.__db = db

    async def get_category_by_id(self, cat_id: int) -> Optional[Category]:
        """
        Get the category associated with the given `cat_id` if such a category exists.
        """
        async with self.__db.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(f"SELECT {_ROW_SPEC} FROM categories WHERE id = %s;", (cat_id, ))
                return _maybe_row_to_category(await cur.fetchone())

    async def get_subcategories_of_category(self, cat_id: Optional[int]) -> AsyncGenerator[Tuple[Category, int], None]:
        """
        Returns a stream of (category, num_topics) objects that are children of the category given in `cat_id`.
        If the `cat_id` is None, then all root level categories are returned.
        """

        where_clause = 'WHERE C.parent_cat = %s' if cat_id is not None else 'WHERE C.parent_cat IS NULL'
        qargs = (cat_id, ) if cat_id is not None else None

        q = f'''
            SELECT C.id, C.cat_name, C.cat_desc, C.parent_cat, COUNT(T.threadID) AS topic_count FROM categories AS C
            LEFT OUTER JOIN threadsTable AS T ON T.parent_cat = C.id
            {where_clause}
            GROUP BY C.id
            ORDER BY topic_count DESC, C.id ASC;
        '''

        async with self.__db.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(q, qargs)
                while row := await cur.fetchone():
                    yield _maybe_row_to_category(row[:4]), row[4]

    async def delete_category(self, cat_id: int) -> None:
        """
        Deletes the target category.

        Note that if the DB enforces FK constraints, this will fail if the category has any children.

        cat_id must not be None as it doesn't make any sense to delete the root.
        """
        assert cat_id is not None

        async with self.__db.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute('DELETE FROM categories WHERE id = %s LIMIT 1;', (cat_id, ))
                return await cur.fetchone()[0]

    async def put_category(self, cat: Category) -> int:
        """
        Saves the category into the database. If the category already exists, it is updated.

        Returns the cat_id.
        """
        async with self.__db.acquire() as conn:
            async with conn.cursor() as cur:
                if cat.id is None:
                    await cur.execute("INSERT INTO categories (cat_name, cat_desc, parent_cat) VALUES (%s, %s, %s)", (cat.cat_name, cat.cat_desc, cat.parent_cat))
                    cat.id = cur.lastrowid
                    return cat.id
                else:
                    num_rows = await cur.execute("UPDATE categories SET cat_name = %s, cat_desc = %s, parent_cat = %s WHERE id = %s LIMIT 1;", (cat.cat_name, cat.cat_desc, cat.parent_cat, cat.id))
                    if num_rows < 1:
                        raise KeyError(f'failed to update category {cat.cat_name} (id = {cat.id}): no such category')
                    return cat.id
