import re
from datetime import datetime
from typing import Any

__MYSQL_TS_FORMAT = '%Y-%m-%d %H:%M:%S'


def mysql_date_to_python(d: Any) -> datetime:
    # todo: remove this function, it's a noop
    return d


__MYSQL_ESCAPE_LIKE_REGEX = re.compile(r'(?P<tok>[%\\_])', flags=re.RegexFlag.UNICODE)


def mysql_escape_like(s: str) -> str:
    return __MYSQL_ESCAPE_LIKE_REGEX.sub('\\$tok', s, count=0)